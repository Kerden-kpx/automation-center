# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SellerSprite historical trends export flow."""

from __future__ import annotations

import argparse
import os
import random
import re
import time
import traceback
from datetime import datetime
from pathlib import Path

from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from core import config as web_config
from core.data.client import execute, fetch_all
from core.settings import load_env_files
from . import sellersprite_ccp as ccp
from ...amazon.flows.amazon_product_details import (
    _parse_fact_rows_from_export,
    _upsert_fact_daily_rows,
)

HISTORICAL_TREND_STATUS_TABLE = "auto_scheduler.fact_bi_amazon_product_detail_status"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_step(message: str) -> None:
    print(f"[{_now_str()}] [SellerSpriteHistoricalTrends] {message}")


# Reuse CCP helpers but keep log prefix distinct in this process.
ccp._log_step = _log_step


def _safe_site_dir(site: str) -> str:
    return ccp._safe_dir_name((site or "US").strip().upper() or "US", "US")


def _resolve_historical_trends_dir(site: str) -> Path:
    site_dir_root = ccp._uc_resolve_download_dir() / _safe_site_dir(site)
    category_dir = ccp._resolve_category_dir_name(site)
    download_dir = site_dir_root / category_dir / "historical trends"
    download_dir.mkdir(parents=True, exist_ok=True)
    return download_dir


def _load_runtime_env() -> None:
    project_root = Path(__file__).resolve().parents[3]
    root_env = project_root / ".env"
    cwd_env = Path.cwd() / ".env"
    # Keep existing DB_NAME untouched because this flow reads from multiple schemas.
    load_env_files([root_env], override=False)
    if cwd_env != root_env:
        load_env_files([cwd_env], override=False)


def _load_success_asins_from_status(site: str) -> set[str]:
    run_date = time.strftime("%Y-%m-%d")
    site_code = (site or "US").strip().upper() or "US"
    rows = fetch_all(
        f"""
        SELECT asin
        FROM {HISTORICAL_TREND_STATUS_TABLE}
        WHERE run_date = %s
          AND site = %s
          AND status = 'success'
        """,
        (run_date, site_code),
    )
    return {
        str(row.get("asin") or "").strip().upper()
        for row in rows
        if str(row.get("asin") or "").strip()
    }


def _upsert_historical_trend_status(
    site: str,
    asin: str,
    status: str,
    *,
    category: str = "",
    message: str = "",
    artifact_path: str = "",
    started_at: str = "",
    ended_at: str = "",
) -> None:
    run_date = time.strftime("%Y-%m-%d")
    site_code = (site or "US").strip().upper() or "US"
    sql = f"""
    INSERT INTO {HISTORICAL_TREND_STATUS_TABLE} (
      run_date,
      site,
      category,
      asin,
      status,
      message,
      artifact_path,
      started_at,
      ended_at
    ) VALUES (
      %s, %s, %s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, '')
    )
    ON DUPLICATE KEY UPDATE
      category = VALUES(category),
      status = VALUES(status),
      message = VALUES(message),
      artifact_path = VALUES(artifact_path),
      started_at = COALESCE(VALUES(started_at), started_at),
      ended_at = COALESCE(VALUES(ended_at), ended_at)
    """
    execute(
        sql,
        (
            run_date,
            site_code,
            str(category or "").strip(),
            str(asin or "").strip().upper(),
            str(status or "").strip().lower(),
            message,
            artifact_path,
            started_at,
            ended_at,
        ),
    )


def _wait_new_xlsx(download_dir: Path, before: set[Path], timeout_sec: int = 120) -> Path | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for path in download_dir.glob("*.xlsx"):
            if path in before:
                continue
            if path.name.endswith(".crdownload"):
                continue
            return path
        time.sleep(1.0)
    return None


def _wait_new_xlsx_for_asin(
    download_dir: Path,
    before: set[Path],
    asin: str,
    timeout_sec: int = 120,
) -> Path | None:
    asin_upper = str(asin or "").strip().upper()
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for path in download_dir.glob("*.xlsx"):
            if path in before:
                continue
            if path.name.endswith(".crdownload"):
                continue
            if asin_upper and asin_upper not in path.name.upper():
                continue
            return path
        time.sleep(1.0)
    return None


def _history_export_button_is_busy(driver) -> bool:
    try:
        button = ccp._uc_wait_present(driver, "history_trend_export_button", timeout=3)
    except Exception:
        return False

    try:
        class_name = str(button.get_attribute("class") or "").lower()
        aria_disabled = str(button.get_attribute("aria-disabled") or "").lower()
        inner_html = str(button.get_attribute("innerHTML") or "").lower()
    except Exception:
        return False

    busy_tokens = (
        "is-loading",
        "loading",
        "icon-loading",
        "fa-spinner",
        "fa-spin",
    )
    if any(token in class_name for token in busy_tokens):
        return True
    if any(token in inner_html for token in busy_tokens):
        return True
    if aria_disabled == "true" and "导出" in (button.text or ""):
        return True
    return False


def _wait_historical_export_result(
    driver,
    download_dir: Path,
    before: set[Path],
    *,
    asin: str,
    timeout_sec: int = 180,
    stable_after_idle_sec: int = 30,
) -> Path | None:
    deadline = time.time() + max(30, int(timeout_sec))
    idle_since: float | None = None
    last_busy: bool | None = None
    saw_busy = False

    while time.time() < deadline:
        saved = _wait_new_xlsx_for_asin(download_dir, before=before, asin=asin, timeout_sec=1)
        if saved is not None:
            return saved

        busy = _history_export_button_is_busy(driver)
        if busy != last_busy:
            _log_step(f"[{asin}] 历史趋势导出状态: {'loading' if busy else 'idle'}")
            last_busy = busy

        if busy:
            saw_busy = True
            idle_since = None
            time.sleep(1.0)
            continue

        if idle_since is None:
            idle_since = time.time()
            if not saw_busy:
                _log_step(f"[{asin}] 导出按钮未进入 loading，按已提交处理并延长等待文件")
        elif time.time() - idle_since >= max(5, int(stable_after_idle_sec)):
            return None
        time.sleep(1.0)

    return None


def _close_history_trend_dialog_if_idle(driver: WebDriver, *, asin: str) -> None:
    if _history_export_button_is_busy(driver):
        _log_step(f"[{asin}] 导出按钮仍在 loading，保持弹窗打开，不提前关闭")
        return
    try:
        ccp._uc_click(driver, "history_trend_close_button", timeout=5)
        ccp._uc_pause(0.3, 0.6)
    except Exception:
        try:
            # 改进④：如果普通点击失败，尝试使用 JS 强制关闭所有激活的弹窗关闭按钮
            driver.execute_script(
                "var closeBtns = document.querySelectorAll('.el-dialog__wrapper[style*=\"z-index\"] .el-dialog__headerbtn');"
                "for(var i=0; i<closeBtns.length; i++){ "
                "  if(closeBtns[i].offsetParent !== null) closeBtns[i].click(); "
                "}"
            )
            ccp._uc_pause(0.3, 0.6)
        except Exception:
            pass


def _pause_between_asins(
    *,
    idx: int,
    total: int,
    failed: bool,
    retries_used: int = 0,
) -> None:
    if failed:
        base_min, base_max = 8.0, 16.0
    else:
        base_min, base_max = 5.0, 11.0
    if retries_used > 0:
        base_min += 2.0 * retries_used
        base_max += 4.0 * retries_used
    if idx % 8 == 0:
        base_min += 6.0
        base_max += 12.0
    _log_step(f"[{idx}/{total}] 下一条前等待 {base_min:.0f}-{base_max:.0f}s")
    ccp._uc_pause(base_min, base_max)


def _simulate_human_browse(driver) -> None:
    try:
        driver.execute_script("window.scrollBy(0, arguments[0]);", random.randint(180, 420))
    except Exception:
        pass
    ccp._uc_pause(0.6, 1.4)
    try:
        driver.execute_script("window.scrollBy(0, arguments[0]);", -random.randint(60, 180))
    except Exception:
        pass
    ccp._uc_pause(0.8, 1.8)


def _human_hover_element(driver, element, *, min_pause: float = 0.25, max_pause: float = 0.9) -> None:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    except Exception:
        pass
    ccp._uc_pause(0.15, 0.35)
    try:
        ActionChains(driver).move_to_element(element).pause(random.uniform(min_pause, max_pause)).perform()
    except Exception:
        try:
            driver.execute_script(
                """
                const el = arguments[0];
                el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                el.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
                el.dispatchEvent(new MouseEvent('mousemove', {bubbles:true}));
                """,
                element,
            )
        except Exception:
            pass
        ccp._uc_pause(min_pause, max_pause)


def _humanize_before_export_click(driver) -> None:
    try:
        button = ccp._uc_wait_first_interactable(
            driver,
            ccp._uc_selector_xpaths("history_trend_export_button"),
            timeout=8,
        )
    except Exception:
        return

    _simulate_human_browse(driver)
    _human_hover_element(driver, button, min_pause=0.35, max_pause=1.1)

    try:
        rect = driver.execute_script(
            """
            const r = arguments[0].getBoundingClientRect();
            return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height};
            """,
            button,
        ) or {}
        center_x = float(rect.get("x") or 0)
        center_y = float(rect.get("y") or 0)
        width = max(8.0, float(rect.get("w") or 12))
        height = max(8.0, float(rect.get("h") or 12))
        offset_x = random.uniform(-width * 0.18, width * 0.18)
        offset_y = random.uniform(-height * 0.18, height * 0.18)
        ActionChains(driver).move_by_offset(center_x + offset_x, center_y + offset_y).pause(
            random.uniform(0.12, 0.45)
        ).perform()
    except Exception:
        pass
    ccp._uc_pause(0.2, 0.6)


def _click_export_button_with_retry(driver, *, asin: str, idx: int, total: int, retries: int = 2) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            button = ccp._uc_wait_first_interactable(
                driver,
                ccp._uc_selector_xpaths("history_trend_export_button"),
                timeout=12,
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
            _humanize_before_export_click(driver)
            _log_step(f"[{idx}/{total}][{asin}] 点击历史趋势导出按钮 (attempt {attempt}/{retries})")
            try:
                button.click()
            except Exception:
                driver.execute_script("arguments[0].click();", button)
            ccp._uc_pause(0.5, 1.2)
            return
        except Exception as exc:
            last_exc = exc
            _log_step(f"[{idx}/{total}][{asin}] 点击导出按钮失败 (attempt {attempt}/{retries}): {exc}")
            if attempt >= retries:
                break
            ccp._uc_pause(1.5, 3.0)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("点击导出按钮失败")


def _extract_asin_from_row(row) -> str:
    try:
        asin_blocks = row.find_elements(
            By.XPATH,
            ".//div[.//span[contains(normalize-space(.), 'ASIN:')]]",
        )
        for block in asin_blocks:
            text = " ".join(str(block.text or "").split())
            match = re.search(r"ASIN:\s*([A-Z0-9]{10})", text, re.IGNORECASE)
            if match:
                return match.group(1).upper()
    except Exception:
        pass
    try:
        inner_html = row.get_attribute("innerHTML") or ""
    except Exception:
        return ""
    match = re.search(r"amazon\.[a-z\.]+?/dp/([A-Z0-9]{10})", inner_html, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(B[\dA-Z]{9}|\d{9}[\dX])\b", inner_html)
    return match.group(1).upper() if match else ""


def _click_chart_button_in_row(driver, row) -> None:
    buttons = row.find_elements(
        By.XPATH,
        ".//a[contains(@class,'el-tooltip') and .//span[contains(@class,'icon-historical-trend')]]",
    )
    if not buttons:
        raise RuntimeError("未找到图表按钮")
    button = buttons[0]
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
    ccp._uc_pause(0.2, 0.5)
    try:
        button.click()
    except Exception:
        driver.execute_script("arguments[0].click();", button)


def _process_single_asin_export(
    driver: WebDriver,
    get_row_func,
    asin: str,
    download_dir: Path,
    idx: int,
    total: int,
) -> tuple[Path, int]:
    """处理单个 ASIN 的导出逻辑，返回 (下载文件路径, 使用的重试次数)"""
    retries_used = 0
    row = get_row_func()
    
    # 将 row 滚入视口，防止被浮动表头或滚动条遮挡导致点击失败
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", row)
        ccp._uc_pause(0.2, 0.4)
    except Exception:
        pass

    _click_chart_button_in_row(driver, row)
    ccp._uc_wait_present(driver, "history_trend_tab", timeout=20)
    ccp._uc_pause(0.6, 1.2)
    ccp._uc_click(driver, "history_trend_tab", timeout=20)
    ccp._uc_wait_first_interactable(
        driver,
        ccp._uc_selector_xpaths("history_trend_export_button"),
        timeout=20,
    )
    
    before = set(download_dir.glob("*.xlsx"))
    saved = None
    last_export_exc: Exception | None = None
    
    for export_attempt in range(1, 3):
        retries_used = export_attempt - 1
        try:
            _click_export_button_with_retry(
                driver,
                asin=asin,
                idx=idx,
                total=total,
                retries=2,
            )
            saved = _wait_historical_export_result(
                driver,
                download_dir,
                before=before,
                asin=asin,
                timeout_sec=240,
                stable_after_idle_sec=30,
            )
            if saved is not None:
                break
            raise RuntimeError("导出结束但未检测到当前 ASIN 文件")
        except Exception as export_exc:
            last_export_exc = export_exc
            _log_step(
                f"[{idx}/{total}][{asin}] 导出尝试失败 "
                f"(attempt {export_attempt}/2): {export_exc}"
            )
            if export_attempt >= 2:
                break
            
            _close_history_trend_dialog_if_idle(driver, asin=asin)
            ccp._uc_pause(3.0, 6.0)
            
            # 重试前重新点击打开图表
            row = get_row_func()
            _click_chart_button_in_row(driver, row)
            ccp._uc_wait_present(driver, "history_trend_tab", timeout=20)
            ccp._uc_pause(0.8, 1.6)
            ccp._uc_click(driver, "history_trend_tab", timeout=20)
            ccp._uc_wait_first_interactable(
                driver,
                ccp._uc_selector_xpaths("history_trend_export_button"),
                timeout=20,
            )
            before = set(download_dir.glob("*.xlsx"))
            
    if saved is None:
        raise last_export_exc or RuntimeError("导出结束但未检测到当前 ASIN 文件")
        
    return saved, retries_used


def _export_historical_trends_from_rows(
    driver: WebDriver, download_dir: Path, site: str = "US"
) -> tuple[int, int, list[Path]]:
    def _current_main_rows():
        return driver.find_elements(By.CSS_SELECTOR, "tr.el-table__row")

    rows = _current_main_rows()
    if not rows:
        _log_step("未找到结果表行，跳过历史趋势导出。")
        return 0, 0, []

    succeeded_asins = _load_success_asins_from_status(site)
    category_name = download_dir.parent.name
    success_count = 0
    fail_count = 0
    consecutive_fail = 0
    downloaded: list[Path] = []
    total = len(rows)
    _log_step(f"开始逐行导出历史趋势: 共 {total} 条")

    for idx in range(1, total + 1):
        # 改进：每 30 行检查一次登录状态，防止 Session 过期
        if idx % 30 == 0:
            if ccp._uc_is_not_logged_in(driver):
                _log_step(f"[{idx}/{total}] 检测到 Session 失效，尝试新开 Tab 恢复登录")
                original_window = driver.current_window_handle
                try:
                    driver.switch_to.new_window('tab')
                    ccp._uc_safe_get(driver, web_config.SELLERSPRITE_LOGIN_URL, title="登录页")
                    ccp._uc_wait_document_ready(driver)
                    ccp._uc_pause(2.0, 3.0)
                    
                    if ccp._uc_is_not_logged_in(driver):
                        account = os.getenv("SELLERSPRITE_ACCOUNT", "").strip()
                        password = os.getenv("SELLERSPRITE_PASSWORD", "").strip()
                        ccp._uc_click(driver, "account_login_tab", timeout=20)
                        ccp._uc_fill(driver, "account_input", account, timeout=20)
                        ccp._uc_fill(driver, "password_input", password, timeout=20)
                        ccp._uc_click(driver, "login_submit_button", timeout=20)
                        if not ccp._uc_wait_login_ready(driver, timeout_sec=45):
                            raise RuntimeError("新 Tab 登录后状态仍未恢复")
                    
                    # 恢复成功后关闭新 Tab，切回原 Tab
                    driver.close()
                    driver.switch_to.window(original_window)
                    _log_step("新 Tab 恢复登录检查完毕")
                except Exception as re_exc:
                    _log_step(f"恢复登录失败: {re_exc}，终止导出")
                    try:
                        driver.close()
                        driver.switch_to.window(original_window)
                    except Exception:
                        pass
                    raise RuntimeError(f"Session 恢复失败: {re_exc}") from re_exc

        rows = _current_main_rows()
        if len(rows) < idx:
            raise RuntimeError(f"[{idx}/{total}] 当前主行数量不足，结果表状态已丢失")
        row = rows[idx - 1]
        asin = _extract_asin_from_row(row) or f"row-{idx}"
        
        if asin.startswith("row-"):
            fail_count += 1
            _log_step(f"[{idx}/{total}] 无法识别 ASIN，跳过")
            continue
            
        if asin in succeeded_asins:
            _log_step(f"[{idx}/{total}][{asin}] 今日已成功，跳过")
            continue

        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        retries_used = 0
        
        try:
            def _get_row():
                _rs = _current_main_rows()
                if len(_rs) >= idx:
                    return _rs[idx - 1]
                raise RuntimeError("行元素已丢失")
                
            saved, retries_used = _process_single_asin_export(
                driver, _get_row, asin, download_dir, idx, total
            )
            
            _log_step(
                f"[{idx}/{total}][{asin}] 历史趋势下载成功: "
                f"{saved.name} ({saved.stat().st_size // 1024} KB)"
            )
            downloaded.append(saved)
            _upsert_historical_trend_status(
                site,
                asin,
                "success",
                category=category_name,
                artifact_path=str(saved),
                started_at=started_at,
                ended_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            success_count += 1
            consecutive_fail = 0
            _pause_between_asins(idx=idx, total=total, failed=False, retries_used=retries_used)
            
        except Exception as exc:
            fail_count += 1
            consecutive_fail += 1
            _log_step(f"[{idx}/{total}][{asin}] 历史趋势下载失败: {exc}")
            _upsert_historical_trend_status(
                site,
                asin,
                "error",
                category=category_name,
                message=str(exc),
                started_at=started_at,
                ended_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            _pause_between_asins(idx=idx, total=total, failed=True, retries_used=retries_used)

            # 改进：熔断机制
            if consecutive_fail >= 6:
                raise RuntimeError(f"连续失败 {consecutive_fail} 次，触发熔断，终止当前列表导出")
                
            if consecutive_fail >= 3:
                _log_step(f"连续失败 {consecutive_fail} 次，等待 60s 后继续...")
                time.sleep(60)
        finally:
            _close_history_trend_dialog_if_idle(driver, asin=asin)

    return success_count, fail_count, downloaded



def _run_uc(site: str = "US", keyword: str | None = None, driver=None) -> bool:
    completed_ok = False
    own_driver = driver is None
    account = os.getenv("SELLERSPRITE_ACCOUNT", "").strip()
    password = os.getenv("SELLERSPRITE_PASSWORD", "").strip()
    if not account or not password:
        raise RuntimeError("缺少环境变量：SELLERSPRITE_ACCOUNT / SELLERSPRITE_PASSWORD")

    queries = ccp._resolve_query_keywords(keyword=keyword, site=site)
    payload = ",".join(queries)
    download_dir = _resolve_historical_trends_dir(site)

    if own_driver:
        driver = ccp._uc_build_driver(download_dir)
    else:
        ccp._uc_set_download_dir(driver, download_dir)

    try:
        ccp._uc_prepare_visible_tab(driver)
        ccp._uc_safe_get(driver, web_config.SELLERSPRITE_COMPETITOR_LOOKUP_URL, title="竞品反查")
        ccp._uc_wait_document_ready(driver)
        ccp._uc_pause(0.6, 1.2)

        if ccp._uc_is_not_logged_in(driver):
            _log_step("检测到未登录，开始登录")
            ccp._uc_safe_get(driver, web_config.SELLERSPRITE_LOGIN_URL, title="登录页")
            ccp._uc_wait_document_ready(driver)
            ccp._uc_pause(0.8, 1.4)
            if ccp._uc_is_not_logged_in(driver):
                ccp._uc_click(driver, "account_login_tab", timeout=20)
                ccp._uc_fill(driver, "account_input", account, timeout=20)
                ccp._uc_fill(driver, "password_input", password, timeout=20)
                ccp._uc_click(driver, "login_submit_button", timeout=20)
                _log_step("已提交登录，等待登录状态生效")
                if not ccp._uc_wait_login_ready(driver, timeout_sec=45):
                    name_text = ccp._uc_read_user_name_text(driver)
                    raise RuntimeError(f"登录提交后仍未生效，user-name={name_text or '<empty>'}")
            else:
                _log_step("登录页自动跳转后已恢复登录，跳过手动登录")

        ccp._uc_safe_get(driver, web_config.SELLERSPRITE_COMPETITOR_LOOKUP_URL, title="竞品反查")
        ccp._uc_wait_document_ready(driver)
        ccp._uc_pause(0.8, 1.5)
        if ccp._uc_is_not_logged_in(driver):
            name_text = ccp._uc_read_user_name_text(driver)
            raise RuntimeError(f"登录后仍检测到未登录状态，user-name={name_text or '<empty>'}")

        ccp._uc_select_site(driver, site=site, timeout=20)
        _log_step(f"批量查询: 共 {len(queries)} 个 ASIN")
        ccp._uc_fill(driver, "competitor_query_input", payload, timeout=20)
        try:
            ccp._uc_click(driver, "competitor_query_button", timeout=20)
        except Exception:
            elem = ccp._uc_first_present(driver, ccp._uc_selector_xpaths("competitor_query_input"), timeout=10)
            elem.send_keys(Keys.ENTER)
        ccp._uc_pause(2.0, 3.5)

        _log_step("导出前切换 100 条/页")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        ccp._uc_pause(0.4, 0.8)
        ccp._uc_click(driver, "page_size_select", timeout=20)
        ccp._uc_click(driver, "page_size_option_100", timeout=20)
        ccp._uc_pause(1.2, 2.5)
        driver.execute_script("window.scrollTo(0, 0);")
        ccp._uc_pause(0.4, 0.8)

        ccp._uc_uncheck_include_variants_if_checked(driver)
        success_count, fail_count, downloaded_paths = _export_historical_trends_from_rows(driver, download_dir, site=site)
        _log_step(f"历史趋势导出完成: 成功 {success_count}, 失败 {fail_count}")

        # 入库：解析所有已下载文件，UPSERT 到 fact_bi_amazon_product_day
        if downloaded_paths:
            _log_step(f"开始入库: {len(downloaded_paths)} 个文件")
            all_rows: list = []
            failed_parse = 0
            for path in downloaded_paths:
                try:
                    rows_parsed = _parse_fact_rows_from_export(path, site)
                    all_rows.extend(rows_parsed)
                except Exception as parse_exc:
                    failed_parse += 1
                    _log_step(f"解析失败 [{path.name}]: {parse_exc}")
            upserted = _upsert_fact_daily_rows(all_rows)
            _log_step(
                f"入库完成: 解析行={len(all_rows)}, upserted={upserted}, 解析失败文件={failed_parse}"
            )
        else:
            _log_step("无成功下载的文件，跳过入库")

        completed_ok = fail_count == 0
        return completed_ok
    finally:
        keep_open = bool(ccp.ss_config.SELLERSPRITE_UC_KEEP_OPEN)
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
        if own_driver and driver is not None:
            driver.quit()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SellerSprite historical trends export flow")
    parser.add_argument("--sites", default="", help="Comma separated site codes or ALL, e.g. UK or US,UK or ALL")
    parser.add_argument("--keyword", default="", help="Optional manual ASIN keyword input")
    return parser.parse_args()


def main() -> None:
    _load_runtime_env()
    _log_step(
        "运行环境数据库: "
        f"DB_HOST={os.getenv('DB_HOST', '').strip()} "
        f"DB_PORT={os.getenv('DB_PORT', '').strip()} "
        f"DB_NAME={os.getenv('DB_NAME', '').strip()}"
    )
    args = _parse_args()
    keyword = (args.keyword or os.getenv("SELLERSPRITE_KEYWORD") or "").strip() or None
    sites = ccp._resolve_sites_to_run(args.sites)
    failures: list[str] = []
    shared_driver = None
    try:
        if sites:
            shared_root = _resolve_historical_trends_dir(sites[0])
            shared_driver = ccp._uc_build_driver(shared_root)
        for site in sites:
            ok = _run_uc(site=site, keyword=keyword, driver=shared_driver)
            if not ok:
                failures.append(site)
        if shared_driver is not None and not failures:
            _log_step("多站点执行完成，复用浏览器会话正常结束")
    except Exception as err:
        _log_step(f"ERROR: {err}")
        _log_step(traceback.format_exc().strip())
        raise
    finally:
        if shared_driver is not None:
            shared_driver.quit()
    if failures:
        raise RuntimeError("sellersprite_historical_trends run failed: " + ",".join(failures))


if __name__ == "__main__":
    main()
