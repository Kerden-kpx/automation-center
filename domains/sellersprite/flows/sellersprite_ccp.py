# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SellerSprite portal automation flow."""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
import traceback

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import yaml

from core import config as web_config
from core.settings import load_env_files
from .. import config as ss_config
from ..repositories.amazon_item_repo import fetch_asins_for_today, fetch_history_export_asins, fetch_top_category_for_today
from ..services import auth_service, query_service
from ..services.browser_client import SellerSpriteBrowserClient
from ..services.export_service import (
    check_include_variants_if_needed as export_check_include_variants_if_needed,
    click_next_page as export_click_next_page,
    dismiss_later_view_if_present as export_dismiss_later_view_if_present,
    download_exports_from_log as export_download_exports_from_log,
    find_existing_export_files as export_find_existing_export_files,
    infer_existing_export_bundle as export_infer_existing_export_bundle,
    load_completed_export_bundle as export_load_completed_export_bundle,
    save_completed_export_bundle as export_save_completed_export_bundle,
    set_select_all_checkbox as export_set_select_all_checkbox,
    uncheck_include_variants_if_checked as export_uncheck_include_variants_if_checked,
)
from ..services.history_monthly_service import (
    download_history_monthly_one as history_download_history_monthly_one,
    export_history_monthly_per_asin as history_export_history_monthly_per_asin,
)
from ..services.import_service import import_daily_sales, import_exports
from ..services.traffic_source_service import export_traffic_source_via_api
from ..support import BI_AMAZON_ITEM_TABLE, parse_float, parse_int, parse_rate, parse_date, safe_dir_name


def _load_selectors() -> dict:
    selectors_path = Path(__file__).resolve().parents[1] / "selectors" / "sellersprite_ccp_selectors.yaml"
    if not selectors_path.exists():
        raise RuntimeError(f"Missing selectors YAML: {selectors_path}")
    with selectors_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid selectors YAML format: {selectors_path}")
    return data


def _load_target_configs() -> dict[str, dict]:
    config_path = Path(__file__).resolve().parents[1] / "selectors" / "sellersprite_target_configs.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _load_flow_env() -> None:
    explicit = os.getenv("SELLERSPRITE_ENV_FILE", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(__file__).resolve().parents[3] / ".env")
    candidates.append(Path.cwd() / ".env")
    load_env_files(candidates, override=False)


_load_flow_env()


SELLERSPRITE_SELECTORS = _load_selectors()
os.environ["DB_NAME"] = ss_config.SELLERSPRITE_CCP_DB_NAME
SITE_TARGET_CONFIGS = _load_target_configs()
SITE_RUN_ORDER = ["US", "UK", "DE", "JP"]
PAGINATED_DETAIL_CATEGORY = "Kids' Paint With Water Kits"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_step(message: str) -> None:
    print(f"[{_now_str()}] [SellerSpriteCCP] {message}")


def _safe_dir_name(value: str, fallback: str) -> str:
    return safe_dir_name(value, fallback)


def _parse_float(value) -> float | None:
    return parse_float(value)


def _parse_int(value) -> int | None:
    return parse_int(value)


def _parse_rate(value) -> float | None:
    return parse_rate(value)


def _parse_date(value):
    return parse_date(value)


def _derive_type(brand: str | None) -> int | None:
    value = str(brand or "").strip().upper()
    if not value:
        return None
    return 1 if value in {"EZARC", "TOLESA"} else 0


def _find_column_name(columns, *patterns: str) -> str | None:
    normalized_map = {}
    for col in columns:
        col_text = str(col).strip()
        normalized = re.sub(r"\s+", "", col_text).lower()
        normalized_map[normalized] = col_text
    for pattern in patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        for normalized, original in normalized_map.items():
            if compiled.search(normalized):
                return original
    return None


def _import_competitor_export_update_dim(path: Path, site: str, category: str = "") -> int:
    from ..importers.competitor_importer import import_competitor_export

    return import_competitor_export(path, site=site, category=category)


def _normalize_month_col(col) -> str:
    raw = str(col).strip()
    m = re.match(r"(\d{4}-\d{2})", raw)
    return m.group(1) if m else raw


def _extract_month_columns(df):
    col_map = {c: _normalize_month_col(c) for c in df.columns}
    df = df.rename(columns=col_map)
    month_cols = [c for c in df.columns if re.fullmatch(r"\d{4}-\d{2}", str(c))]
    return df, month_cols


def _build_long_df(excel_path: Path, sheet_name: str, value_col: str):
    import pandas as pd

    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    if "ASIN" not in df.columns:
        raise RuntimeError(f"{sheet_name} 缺少 ASIN 列")
    df, month_cols = _extract_month_columns(df)
    if not month_cols:
        raise RuntimeError(f"{sheet_name} 未找到 YYYY-MM 日期列")
    df = df[["ASIN"] + month_cols].copy()
    df["ASIN"] = df["ASIN"].astype(str).str.strip().str.upper()
    df = df[df["ASIN"] != ""]
    return df.melt(id_vars=["ASIN"], value_vars=month_cols, var_name="month", value_name=value_col)


def _try_build_long_df(excel_path: Path, sheet_name: str, value_col: str):
    import pandas as pd

    try:
        return _build_long_df(excel_path, sheet_name, value_col)
    except Exception:
        return pd.DataFrame(columns=["ASIN", "month", value_col])


def _import_sales_export_to_fact_month(path: Path, site: str) -> int:
    from ..importers.sales_importer import import_sales_export

    return import_sales_export(path, site=site)


def _import_sellersprite_exports_to_db(export_files: dict[str, Path], site: str, category: str = "") -> dict[str, int]:
    return import_exports(export_files, site=site, category=category, log=_log_step)


def _upsert_traffic_source_items_to_dim(site: str, category: str, items: list[dict]) -> int:
    from ..repositories.amazon_item_repo import upsert_traffic_source_items

    return upsert_traffic_source_items(site=site, category=category, items=items)


class SellerSpritePortal:
    """Deprecated placeholder. This flow is UC+Selenium only."""

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError("SellerSpritePortal (Playwright) 已弃用，请使用 UC 入口函数。")


def login_sellersprite_from_env(page=None) -> bool:
    """UC-only login/query entry (without export)."""
    _ = page
    _log_step("入口: login_sellersprite_from_env (UC)")
    try:
        return _run_uc(site="US", keyword=None, do_query=False, do_export=False)
    except Exception as err:
        _log_step(f"ERROR: {err}")
        _log_step(traceback.format_exc().strip())
        return False


def _resolve_categories_for_site(site: str, id_filter: str = "") -> list[str]:
    site_code = (site or "US").strip().upper() or "US"
    id_filter_str = str(id_filter or "").strip()
    if not id_filter_str or id_filter_str.upper() == "ALL" or not SITE_TARGET_CONFIGS:
        return []

    allowed = {item.strip().lower() for item in id_filter_str.split(",") if item.strip()}
    categories: list[str] = []
    seen: set[str] = set()
    for cat_id, cat_val in SITE_TARGET_CONFIGS.items():
        if not isinstance(cat_val, dict):
            continue
        cat_site = str(cat_val.get("site", "")).strip().upper()
        cat_name = str(cat_val.get("name", "")).strip()
        if cat_site != site_code:
            continue
        if cat_id.strip().lower() not in allowed and cat_name.lower() not in allowed:
            continue
        if cat_name and cat_name not in seen:
            seen.add(cat_name)
            categories.append(cat_name)
    return categories


def _resolve_category_dir_from_id(site: str, id_filter: str = "") -> str:
    categories = _resolve_categories_for_site(site, id_filter)
    if not categories:
        raise RuntimeError(f"未找到站点 {site} 对应的类目配置，id={id_filter!r}")
    return _safe_dir_name(categories[0], "uncategorized")


def _resolve_primary_category(site: str, id_filter: str = "") -> str:
    categories = _resolve_categories_for_site(site, id_filter)
    return categories[0] if categories else ""


def _resolve_history_export_asins(site: str, category: str = "") -> list[str]:
    return fetch_history_export_asins(site=site, category=category)


def _resolve_query_keywords(keyword: str | None = None, site: str = "US", id_filter: str = "") -> list[str]:
    """
    Resolve query keywords.

    Priority:
    1) explicit `keyword` argument
    2) all ASINs from dim_bi_amazon_item where createtime=CURDATE() and site=<site>
    """
    value = (keyword or "").strip()
    if value:
        # Support comma/newline separated manual input.
        items = [x.strip().upper() for x in value.replace("\n", ",").split(",")]
        items = [x for x in items if x]
        if not items:
            raise RuntimeError("缺少查询参数：keyword 为空")
        return items

    site_code = (site or "US").strip().upper() or "US"
    allowed_categories = _resolve_categories_for_site(site_code, id_filter)
    asins = fetch_asins_for_today(site_code, categories=allowed_categories)
    if not asins:
        raise RuntimeError(
            f"缺少查询参数：keyword；且 {BI_AMAZON_ITEM_TABLE} 当天({site_code})无可用 ASIN"
        )
    if not asins:
        raise RuntimeError(
            f"缺少查询参数：keyword；且 {BI_AMAZON_ITEM_TABLE} 当天({site_code}) ASIN 全为空"
        )
    return asins


def _resolve_source_api_market(site: str) -> str:
    site_code = (site or "US").strip().upper() or "US"
    if site_code != "US":
        raise RuntimeError(f"流量来源接口仅支持特殊类目 US 站点，当前站点: {site_code}")
    return "COM"


def _uc_pause(min_s: float = 0.3, max_s: float = 0.9) -> None:
    SellerSpriteBrowserClient(None, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).pause(min_s, max_s)


def _uc_selector_xpaths(key: str) -> list[str]:
    return SellerSpriteBrowserClient(None, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).selector_xpaths(key)


def _uc_wait_first_interactable(driver, xpaths: list[str], timeout: int = 20):
    return SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).wait_first_interactable(
        xpaths, timeout=timeout
    )


def _uc_first_present(driver, xpaths: list[str], timeout: int = 20):
    return SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).first_present(
        xpaths, timeout=timeout
    )


def _uc_wait_present(driver, key: str, timeout: int = 20):
    return SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).wait_present(
        key, timeout=timeout
    )


def _uc_click(driver, key: str, timeout: int = 20) -> None:
    SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).click(key, timeout=timeout)


def _uc_fill(driver, key: str, value: str, timeout: int = 20) -> None:
    SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).fill(
        key, value, timeout=timeout
    )


def _uc_select_site(driver, site: str, timeout: int = 20) -> None:
    SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).select_site(
        site, timeout=timeout
    )


def _uc_has_any(driver, key: str) -> bool:
    return SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).has_any(key)


def _uc_has_interactable(driver, key: str, timeout: int = 6) -> bool:
    return SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).has_interactable(
        key, timeout=timeout
    )


def _uc_is_not_logged_in(driver) -> bool:
    return SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).is_not_logged_in()


def _uc_read_user_name_text(driver) -> str:
    return SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).read_user_name_text()


def _uc_wait_login_ready(driver, timeout_sec: int = 45) -> bool:
    return SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).wait_login_ready(
        timeout_sec=timeout_sec
    )


def _uc_wait_document_ready(driver, timeout: int = 30) -> None:
    SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).wait_document_ready(
        timeout=timeout
    )


def _uc_safe_get(driver, url: str, title: str = "", retries: int = 4, retry_delay: float = 3.0) -> None:
    SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step).safe_get(
        url, title=title, retries=retries, retry_delay=retry_delay
    )


def _uc_resolve_download_dir() -> Path:
    base_dir = Path(ss_config.SELLERSPRITE_DOWNLOAD_BASE_DIR).expanduser()
    download_dir = base_dir / datetime.now().strftime("%Y-%m-%d")
    download_dir.mkdir(parents=True, exist_ok=True)
    return download_dir


def _resolve_category_dir_name(site: str) -> str:
    category = fetch_top_category_for_today(site)
    if not category:
        return "uncategorized"
    return _safe_dir_name(category, "uncategorized")


def _move_path_to_dir(path: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    if not target.exists():
        return path.replace(target)
    stem = path.stem
    suffix = path.suffix
    idx = 1
    while True:
        candidate = target_dir / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return path.replace(candidate)
        idx += 1


def _relocate_download_dir_by_category(site_dir_root: Path, current_dir: Path, site: str) -> Path:
    actual_category_dir = _resolve_category_dir_name(site)
    current_name = current_dir.name
    if not actual_category_dir or actual_category_dir == current_name:
        return current_dir
    target_dir = site_dir_root / actual_category_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    _log_step(f"UC 检测到真实类目[{actual_category_dir}]，迁移目录: {current_dir} -> {target_dir}")
    for child in list(current_dir.iterdir()):
        try:
            _move_path_to_dir(child, target_dir)
        except Exception as exc:
            _log_step(f"UC 迁移文件失败[{child.name}]: {exc}")
    try:
        current_dir.rmdir()
    except Exception:
        pass
    return target_dir


def _uc_build_driver(download_dir: Path):
    import undetected_chromedriver as uc

    user_data_dir = Path(ss_config.SELLERSPRITE_UC_USER_DATA_DIR).expanduser()
    user_data_dir.mkdir(parents=True, exist_ok=True)

    headless = bool(ss_config.SELLERSPRITE_UC_HEADLESS)
    use_subprocess = bool(ss_config.SELLERSPRITE_UC_USE_SUBPROCESS)
    version_main = ss_config.SELLERSPRITE_UC_VERSION_MAIN
    driver_executable_path = str(ss_config.SELLERSPRITE_UC_DRIVER_PATH).strip()

    def _build_uc_kwargs() -> dict:
        options = uc.ChromeOptions()
        # 核心优化：Selenium 默认策略是 'normal'，会死等所有图片、第三方广告、追踪代码加载完毕才交出控制权，
        # 导致程序跑起来感觉比人肉看慢很多。改为 'eager' 后，只要 HTML DOM 加载完成就立刻继续执行！
        options.page_load_strategy = "eager"
        prefs = {
            "download.default_directory": str(download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        options.add_experimental_option("prefs", prefs)
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument("--lang=zh-CN")
        options.add_argument("--window-size=1440,900")
        # 不要添加 --disable-blink-features=AutomationControlled，因为 undetected-chromedriver 底层已经处理过了，
        # 重复添加或显式抹掉这个 flag 反而会被高级风控 (如 Cloudflare/极验) 判定为特征更可疑的爬虫，导致疯狂限速。
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")

        kwargs = {"options": options, "headless": headless, "use_subprocess": use_subprocess}
        if isinstance(version_main, int) and version_main > 0:
            kwargs["version_main"] = int(version_main)
        if driver_executable_path:
            kwargs["driver_executable_path"] = driver_executable_path
        return kwargs

    _log_step(
        "UC 启动浏览器: "
        f"headless={headless}, use_subprocess={use_subprocess}, "
        f"version_main={version_main if version_main else '<auto>'}, "
        f"driver={driver_executable_path or '<auto>'}, user_data_dir={user_data_dir}"
    )

    try:
        driver = uc.Chrome(**_build_uc_kwargs())
    except Exception as e:
        import shutil
        _log_step(f"UC 启动浏览器失败 (尝试清理残留状态后重试): {e}")
        # 清理异常崩溃导致的锁定文件
        try:
            lock_file = user_data_dir / "SingletonLock"
            if lock_file.exists():
                lock_file.unlink()
            
            # 常见情况：Preference/Local State 文件损坏导致不断崩溃
            pref_file = user_data_dir / "Default" / "Preferences"
            if pref_file.exists():
                pref_file.unlink()
                
            local_state = user_data_dir / "Local State"
            if local_state.exists():
                local_state.unlink()
        except Exception as clean_err:
            _log_step(f"UC 清理状态失败: {clean_err}")
            
        # 尝试杀掉可能卡住残留的进程 (不依赖 psutil)
        import subprocess
        try:
            if sys.platform == "win32":
                # 简单粗暴地杀掉 chrome.exe，因为这是个隔离环境
                # 我们尽量缩小范围，通过 wmic 查找带有我们 profile 的 Chrome 进程
                cmd = 'wmic process where "name=\'chrome.exe\' and commandline like \'%uc-sellersprite%\'" call terminate'
                subprocess.run(cmd, shell=True, capture_output=True)
            else:
                cmd = "pkill -f 'chrome.*uc-sellersprite'"
                subprocess.run(cmd, shell=True, capture_output=True)
        except Exception as kill_err:
            _log_step(f"UC 结束残留 Chrome 进程失败: {kill_err}")

        time.sleep(2.0)
        # 第二次重试启动
        driver = uc.Chrome(**_build_uc_kwargs())

    driver.set_page_load_timeout(120)

    try:
        driver.execute_cdp_cmd('Network.enable', {})
        # 初始启动时不加载拦截规则，保证登录页滑块等安全图片无损加载
        driver.execute_cdp_cmd('Network.setBlockedURLs', {"urls": []})
        _log_step("UC 已开启 CDP 网络监控 (暂未应用拦截规则，以保障登录页验证码加载)")
    except Exception as exc:
        _log_step(f"UC 开启 CDP网络监控失败: {exc}")

    try:
        driver.set_window_position(50, 50)
    except Exception:
        pass
    try:
        driver.maximize_window()
    except Exception:
        pass
    try:
        _log_step(
            "UC 浏览器已启动: "
            f"current_url={driver.current_url or '<empty>'}, title={driver.title or '<empty>'}"
        )
    except Exception:
        pass
    return driver


def _uc_set_download_dir(driver, download_dir: Path) -> None:
    download_dir.mkdir(parents=True, exist_ok=True)
    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(download_dir)},
        )
        _log_step(f"UC 切换下载目录: {download_dir}")
    except Exception as exc:
        _log_step(f"UC 切换下载目录失败，继续使用原目录: {exc}")

def _uc_enable_cdp_blocking(driver) -> None:
    """
    在确保账户已经完全登录后，再开启严厉的静态资源屏蔽，以最大化加速数据爬取页面的速度
    """
    try:
        driver.execute_cdp_cmd('Network.setBlockedURLs', {
            "urls": [
                "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg", "*.ico", # 此时可以放心屏蔽图片了
                "*.woff", "*.woff2", "*.ttf", "*.eot",
                "*.mp4", "*.webm", "*.audio", "*.mp3", "*.wav"
            ]
        })
        _log_step("UC 登录阶段已完成，主动开启 CDP 完全静态资源拦截(图片/字体/视频)以加速抓取")
    except Exception as exc:
        _log_step(f"UC 开启动态 CDP 资源拦截失败: {exc}")


def _uc_extract_row_text(row, css_list: list[str]) -> str:
    for css in css_list:
        elems = row.find_elements(By.CSS_SELECTOR, css)
        if elems:
            text = " ".join((elems[0].text or "").split())
            if text:
                return text
    return ""


def _uc_wait_downloaded_file(download_dir: Path, name_prefix: str, before: set[Path], timeout_sec: int = 50) -> Path | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for p in download_dir.glob("*.xlsx"):
            if p in before:
                continue
            if p.name.endswith(".crdownload"):
                continue
            if p.name.startswith(name_prefix) or name_prefix in p.name:
                return p
        time.sleep(1.0)
    return None


def _uc_prepare_visible_tab(driver) -> None:
    try:
        current_url = (driver.current_url or "").strip()
    except Exception:
        current_url = ""
    if not current_url.startswith("chrome://"):
        return
    _log_step(f"UC 检测到内部页，尝试新开可见标签页: {current_url}")
    try:
        driver.switch_to.new_window("tab")
        time.sleep(0.3)
        try:
            driver.set_window_position(50, 50)
        except Exception:
            pass
        try:
            driver.maximize_window()
        except Exception:
            pass
        _log_step(
            "UC 已切换到新标签页: "
            f"current_url={driver.current_url or '<empty>'}, title={driver.title or '<empty>'}"
        )
    except Exception as exc:
        _log_step(f"UC 新开标签页失败，继续使用当前页面: {exc}")


def _uc_download_exports_from_log(
    driver, download_dir: Path, site: str, wait_minutes: int = 3, expected_sales_exports: int = 1
) -> dict[str, Path]:
    return export_download_exports_from_log(
        driver,
        download_dir,
        site,
        wait_minutes=wait_minutes,
        expected_sales_exports=expected_sales_exports,
        safe_get=_uc_safe_get,
        wait_document_ready=_uc_wait_document_ready,
        extract_row_text=_uc_extract_row_text,
        log=_log_step,
    )


def _find_existing_export_files(download_dir: Path, site: str) -> dict[str, Path]:
    return export_find_existing_export_files(download_dir, site)


def _load_completed_export_bundle(download_dir: Path, site: str) -> dict[str, Path]:
    return export_load_completed_export_bundle(download_dir, site)


def _save_completed_export_bundle(download_dir: Path, site: str, export_files: dict[str, Path]) -> None:
    export_save_completed_export_bundle(download_dir, site, export_files)


def _infer_existing_export_bundle(download_dir: Path, site: str) -> dict[str, Path]:
    return export_infer_existing_export_bundle(download_dir, site)


def _uc_uncheck_include_variants_if_checked(driver) -> None:
    export_uncheck_include_variants_if_checked(driver, pause=_uc_pause, wait_present=_uc_wait_present, log=_log_step)


def _uc_check_include_variants_if_needed(driver) -> None:
    export_check_include_variants_if_needed(driver, pause=_uc_pause, wait_present=_uc_wait_present, log=_log_step)


def _uc_set_select_all_checkbox(driver, *, checked: bool) -> None:
    export_set_select_all_checkbox(
        driver,
        checked=checked,
        wait_first_interactable=_uc_wait_first_interactable,
        selector_xpaths=_uc_selector_xpaths,
        pause=_uc_pause,
    )


def _uc_has_clickable_next_page(driver) -> bool:
    for xp in _uc_selector_xpaths("next_page_button"):
        try:
            elems = driver.find_elements(By.XPATH, xp)
        except Exception:
            continue
        for elem in elems:
            try:
                cls = (elem.get_attribute("class") or "").lower()
                if elem.is_displayed() and elem.is_enabled() and "disabled" not in cls:
                    return True
            except Exception:
                continue
    return False


def _uc_click_next_page(driver) -> bool:
    return export_click_next_page(
        driver,
        selector_xpaths=_uc_selector_xpaths,
        click=_uc_click,
        pause=_uc_pause,
        wait_present=_uc_wait_present,
    )


def _uc_dismiss_later_view_if_present(driver, timeout: int = 4) -> bool:
    return export_dismiss_later_view_if_present(driver, click=_uc_click, pause=_uc_pause, log=_log_step, timeout=timeout)


def _download_history_monthly_one(
    driver,
    asin: str,
    site: str,
    cookies: dict[str, str],
    user_agent: str,
    save_dir: Path,
    min_valid_bytes: int = 10 * 1024,
) -> tuple[str, Path | None, str]:
    return history_download_history_monthly_one(
        driver, asin, site, cookies, user_agent, save_dir, log=_log_step, min_valid_bytes=min_valid_bytes
    )


def _uc_export_history_monthly_per_asin(
    driver,
    download_dir: Path,
    site: str,
    category: str = "",
    request_interval: tuple[float, float] = (2.0, 5.0),
    rate_limit_backoff_sec: int = 60,
    max_retries: int = 2,
    max_workers: int = 2,
) -> list[str]:
    return history_export_history_monthly_per_asin(
        driver,
        download_dir,
        site,
        category=category,
        request_interval=request_interval,
        rate_limit_backoff_sec=rate_limit_backoff_sec,
        max_retries=max_retries,
        max_workers=max_workers,
        resolve_history_export_asins=_resolve_history_export_asins,
        log=_log_step,
    )


def _import_daily_sales_volume_from_folder(download_dir: Path, site: str) -> dict[str, int]:
    return import_daily_sales(download_dir, site=site, log=_log_step)


def _export_traffic_source_via_api(
    driver,
    download_dir: Path,
    site: str,
    category: str,
    asins: list[str] | None = None,
    *,
    page_size: int = 100,
) -> tuple[int, int, list[Path], int]:
    return export_traffic_source_via_api(
        driver,
        download_dir,
        site=site,
        category=category,
        asins=asins,
        page_size=page_size,
        market_resolver=_resolve_source_api_market,
        log=_log_step,
    )


def run_site_pipeline(
    site: str = "US",
    keyword: str | None = None,
    id_filter: str = "",
    *,
    do_query: bool = True,
    do_export: bool = True,
    driver=None,
) -> bool:
    completed_ok = False
    own_driver = driver is None
    account = os.getenv("SELLERSPRITE_ACCOUNT", "").strip()
    password = os.getenv("SELLERSPRITE_PASSWORD", "").strip()
    if not account or not password:
        raise RuntimeError("缺少环境变量：SELLERSPRITE_ACCOUNT / SELLERSPRITE_PASSWORD")

    queries: list[str] = []
    payload = ""
    if do_query:
        queries = _resolve_query_keywords(keyword=keyword, site=site, id_filter=id_filter)
        payload = ",".join(queries)
    site_dir = _safe_dir_name((site or "US").strip().upper() or "US", "US")
    site_dir_root = _uc_resolve_download_dir() / site_dir
    initial_category_dir = _resolve_category_dir_from_id(site, id_filter)
    download_dir = site_dir_root / initial_category_dir
    download_dir.mkdir(parents=True, exist_ok=True)
    if own_driver:
        driver = _uc_build_driver(download_dir)
    else:
        _uc_set_download_dir(driver, download_dir)
    try:
        browser = SellerSpriteBrowserClient(driver, selectors=SELLERSPRITE_SELECTORS, logger=_log_step)
        _uc_prepare_visible_tab(driver)
        auth_service.ensure_logged_in(browser, account=account, password=password, log=_log_step)

        # 核心：确保登录完毕后，再重火力开启资源拦截提速，避免干扰前面的登录页和验证码
        _uc_enable_cdp_blocking(driver)

        if do_query:
            payload = query_service.run_competitor_query(browser, site=site, queries=queries, log=_log_step)

        if not do_query or not do_export:
            completed_ok = True
            return True

        _log_step("UC 导出前切换 100 条/页")
        # 增加弹性容错：解决网站高并发时下拉菜单点击超时或返回 50x 的问题
        page_size_ok = False
        for attempt in range(3):
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                _uc_pause(0.4, 0.8)
                browser.click("page_size_select", timeout=15)
                browser.click("page_size_option_100", timeout=15)
                browser.pause(1.2, 2.5)
                driver.execute_script("window.scrollTo(0, 0);")
                browser.pause(0.4, 0.8)
                page_size_ok = True
                break
            except Exception as e:
                _log_step(f"UC 切换 100 条/页失败，可能触发 502/加载超时 (第 {attempt+1}/3 次): {e}")
                _log_step("UC 主动刷新页面后重试...")
                try:
                    driver.refresh()
                    browser.wait_document_ready()
                    browser.pause(3.0, 5.0)
                except Exception:
                    pass
        
        if not page_size_ok:
             _log_step("UC 警告：多次尝试仍无法切换 100 条/页，将使用默认条数")

        category_name = _resolve_primary_category(site, id_filter)
        paginated_detail_mode = category_name == PAGINATED_DETAIL_CATEGORY
        db_result: dict[str, int] | None = None
        inferred_bundle_logged = False
        if paginated_detail_mode:
            _uc_check_include_variants_if_needed(driver)
        else:
            _uc_uncheck_include_variants_if_checked(driver)
        export_files = _load_completed_export_bundle(download_dir, site)
        if not export_files:
            inferred_bundle = _infer_existing_export_bundle(download_dir, site)
            if inferred_bundle:
                _save_completed_export_bundle(download_dir, site, inferred_bundle)
                export_files = inferred_bundle
                _log_step(
                    "UC 检测到当日 details 导出文件已齐全，已自动补写完成标记并跳过导出与入库: "
                    + ", ".join(path.name for path in export_files.values())
                )
                inferred_bundle_logged = True
        if export_files:
            if not inferred_bundle_logged:
                _log_step(
                    "UC 检测到当日导出完成标记，跳过导出与入库步骤: "
                    + ", ".join(path.name for path in export_files.values())
                )
            db_result = {"dim_rows": 0, "monthly_rows": 0}
        else:
            export_files = {} if paginated_detail_mode else _find_existing_export_files(download_dir, site)
        if export_files and not db_result:
            _log_step(
                "UC 检测到 details 已存在两份规范文件，跳过导出步骤: "
                + ", ".join(path.name for path in export_files.values())
            )
        elif not export_files:
            browser.click("export_button", timeout=25)
            _uc_dismiss_later_view_if_present(driver, timeout=6)
            detail_export_count = 0
            while True:
                _uc_set_select_all_checkbox(driver, checked=True)
                browser.click("export_detail_button", timeout=20)
                detail_export_count += 1
                _uc_dismiss_later_view_if_present(driver, timeout=6)
                if paginated_detail_mode:
                    _uc_dismiss_later_view_if_present(driver, timeout=3)
                    try:
                        _uc_set_select_all_checkbox(driver, checked=False)
                    except Exception:
                        pass
                    if _uc_click_next_page(driver):
                        _log_step(f"UC Kids 类目分页导出：继续导出下一页 (detail_page={detail_export_count + 1})")
                        continue
                break
            export_files = _uc_download_exports_from_log(
                driver,
                download_dir=download_dir,
                site=site,
                wait_minutes=int(ss_config.SELLERSPRITE_EXPORT_LOG_WAIT_MINUTES),
                expected_sales_exports=detail_export_count,
            )
        if export_files and not db_result:
            db_result = _import_sellersprite_exports_to_db(export_files, site=site, category=category_name)
            _save_completed_export_bundle(download_dir, site, export_files)
            _log_step(f"UC 入库完成: dim更新={db_result['dim_rows']} 行, fact_month导入={db_result['monthly_rows']} 行")
        _log_step("UC 开始逐 ASIN 导出历史月销量")
        history_asins = _uc_export_history_monthly_per_asin(driver, download_dir, site=site, category=category_name)
        day_result = _import_daily_sales_volume_from_folder(download_dir, site=site)
        _log_step(
            "UC 日销量入库完成: "
            f"files={day_result['files']}, parsed={day_result['parsed_rows']}, "
            f"upsert={day_result['upserted_rows']}, failed_files={day_result['failed_files']}"
        )
        if not id_filter:
            download_dir = _relocate_download_dir_by_category(site_dir_root, download_dir, site)
        
        # ===== 步骤 7: 提取 Keepa 历史趋势 (API极速版) =====
        try:
            from ..services.keepa_history_service import export_historical_trends_via_api
            _log_step("UC 开始附加步骤: 极速提取历史趋势 Keepa 数据 (API)")
            resolved_category = download_dir.name
            hist_dir = download_dir / "historical trends api"
            hist_dir.mkdir(parents=True, exist_ok=True)
            succ, fail, files = export_historical_trends_via_api(
                driver, hist_dir, site=site, category=resolved_category, asins=history_asins
            )
            _log_step(f"UC 历史趋势 Keepa 数据提取并入库完成 [{resolved_category}]: 成功 {succ}, 失败 {fail}")
        except Exception as e:
            _log_step(f"UC 附加步骤历史趋势提取失败: {e}")
        if paginated_detail_mode:
            try:
                source_asins = history_asins or _resolve_history_export_asins(site=site, category=category_name)
                if not source_asins:
                    raise RuntimeError("特殊类目流量来源接口缺少查询阶段 ASIN，跳过请求")
                _log_step("UC 开始附加步骤: 特殊类目请求流量来源数据 (API)")
                source_succ, source_fail, source_files, source_dim_rows = _export_traffic_source_via_api(
                    driver,
                    download_dir,
                    site=site,
                    category=category_name,
                    asins=source_asins,
                )
                _log_step(
                    f"UC 流量来源数据提取完成 [{download_dir.name}]: "
                    f"成功批次 {source_succ}, 失败批次 {source_fail}, 文件 {len(source_files)}, "
                    f"dim更新 {source_dim_rows}"
                )
            except Exception as e:
                _log_step(f"UC 附加步骤流量来源提取失败: {e}")

        completed_ok = True
        return True
    finally:
        keep_open = bool(ss_config.SELLERSPRITE_UC_KEEP_OPEN)
        keep_open_on_error = (os.getenv("SELLERSPRITE_UC_KEEP_OPEN_ON_ERROR", "0") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        should_keep_open = own_driver and (keep_open or (keep_open_on_error and not completed_ok))
        if should_keep_open:
            _log_step("SELLERSPRITE_UC_KEEP_OPEN=1，浏览器保持打开，按 Ctrl+C 结束脚本。")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        if own_driver:
            driver.quit()


def _run_uc(
    site: str = "US",
    keyword: str | None = None,
    id_filter: str = "",
    *,
    do_query: bool = True,
    do_export: bool = True,
    driver=None,
) -> bool:
    return run_site_pipeline(
        site=site,
        keyword=keyword,
        id_filter=id_filter,
        do_query=do_query,
        do_export=do_export,
        driver=driver,
    )


def login_and_query_sellersprite_from_env(
    page=None,
    keyword: str | None = None,
    site: str = "US",
    id_filter: str = "",
) -> bool:
    """
    Ensure SellerSprite login and run competitor query.

    Required env vars:
    - SELLERSPRITE_ACCOUNT
    - SELLERSPRITE_PASSWORD
    """
    _log_step("入口: login_and_query_sellersprite_from_env (UC)")
    try:
        _ = page  # compatibility: legacy callers may still pass a Playwright page
        return _run_uc(site=site, keyword=keyword, id_filter=id_filter, do_export=False)
    except Exception as err:
        _log_step(f"ERROR: {err}")
        _log_step(traceback.format_exc().strip())
        return False


def login_query_and_export_sellersprite_from_env(
    page=None,
    keyword: str | None = None,
    site: str = "US",
    id_filter: str = "",
) -> bool:
    """
    Ensure SellerSprite login, run competitor query, then click export.

    Required env vars:
    - SELLERSPRITE_ACCOUNT
    - SELLERSPRITE_PASSWORD
    """
    _log_step("入口: login_query_and_export_sellersprite_from_env (UC)")
    try:
        _ = page  # compatibility: legacy callers may still pass a Playwright page
        return _run_uc(site=site, keyword=keyword, id_filter=id_filter, do_export=True)
    except Exception as err:
        _log_step(f"ERROR: {err}")
        _log_step(traceback.format_exc().strip())
        return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SellerSprite CCP flow")
    parser.add_argument("--id", default="", help="Comma separated category IDs or ALL, e.g. '1,2' or 'ALL'")
    parser.add_argument("--keyword", default="", help="Optional manual ASIN keyword input")
    return parser.parse_args()


def _resolve_sites_to_run(id_filter: str = "") -> list[str]:
    id_filter_str = str(id_filter or "").strip()
    if id_filter_str and SITE_TARGET_CONFIGS:
        if id_filter_str.upper() == "ALL":
            inferred_sites = {
                str(val.get("site", "")).strip().upper()
                for val in SITE_TARGET_CONFIGS.values()
                if isinstance(val, dict) and val.get("site")
            }
            if inferred_sites:
                return sorted(list(inferred_sites))

        allowed = {item.strip().lower() for item in id_filter_str.split(",") if item.strip()}
        inferred_sites: set[str] = set()
        for cat_id, cat_val in SITE_TARGET_CONFIGS.items():
            if not isinstance(cat_val, dict):
                continue
            cat_name = str(cat_val.get("name", ""))
            if cat_id.strip().lower() in allowed or cat_name.strip().lower() in allowed:
                cat_site = str(cat_val.get("site", "")).strip().upper()
                if cat_site:
                    inferred_sites.add(cat_site)
        if inferred_sites:
            return sorted(list(inferred_sites))

    site = str(os.getenv("SELLERSPRITE_SITE") or "US").strip().upper() or "US"
    return [site]


def run_multi_site_pipeline(sites: list[str], *, keyword: str | None = None, id_filter: str = "") -> None:
    import random
    import traceback

    failures: list[str] = []
    shared_driver = None

    def _safe_quit_driver():
        nonlocal shared_driver
        if shared_driver is not None:
            try:
                shared_driver.quit()
            except Exception:
                pass
            shared_driver = None

    try:
        if sites:
            first_site_dir = _safe_dir_name(sites[0], "US")
            first_category_dir = _resolve_category_dir_from_id(sites[0], id_filter)
            shared_root = _uc_resolve_download_dir() / first_site_dir / first_category_dir
            shared_root.mkdir(parents=True, exist_ok=True)
            shared_driver = _uc_build_driver(shared_root)

        for idx, site in enumerate(sites):
            if idx > 0 and idx % 3 == 0:
                _log_step(f"UC 多站点内存防封：准备执行浏览器软重启 (已处理 {idx} 个站点)")
                _safe_quit_driver()
                time.sleep(5.0)
                site_dir = _safe_dir_name(site, "US")
                category_dir = _resolve_category_dir_from_id(site, id_filter)
                shared_root = _uc_resolve_download_dir() / site_dir / category_dir
                shared_root.mkdir(parents=True, exist_ok=True)
                shared_driver = _uc_build_driver(shared_root)

            if idx > 0:
                cooldown = random.uniform(30.0, 90.0)
                _log_step(f"UC 多站点防封：等待 {cooldown:.1f} 秒后开始处理站点: {site}")
                time.sleep(cooldown)

            try:
                ok = run_site_pipeline(site=site, keyword=keyword, id_filter=id_filter, do_export=True, driver=shared_driver)
                if not ok:
                    failures.append(site)
            except Exception as exc:
                _log_step(f"UC 站点 {site} 执行发生异常 (已隔离): {exc}")
                _log_step(traceback.format_exc().strip())
                failures.append(site)

        if shared_driver is not None and not failures:
            _log_step("UC 多站点执行完成，复用浏览器会话正常结束")
    finally:
        _safe_quit_driver()

    if failures:
        raise RuntimeError("sellersprite_ccp run failed for sites: " + ",".join(failures))


def _run_sites(sites: list[str], *, keyword: str | None = None, id_filter: str = "") -> None:
    run_multi_site_pipeline(sites, keyword=keyword, id_filter=id_filter)


def main() -> None:
    args = _parse_args()
    keyword = (args.keyword or os.getenv("SELLERSPRITE_KEYWORD") or "").strip() or None
    sites = _resolve_sites_to_run(args.id)
    run_multi_site_pipeline(sites, keyword=keyword, id_filter=args.id)


if __name__ == "__main__":
    main()
