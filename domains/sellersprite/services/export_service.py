# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SellerSprite export-related UI services."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import requests
from selenium.webdriver.common.by import By

from .. import config as ss_config


def load_completed_export_bundle(download_dir: Path, site: str) -> dict[str, Path]:
    details_dir = download_dir / "details"
    if not details_dir.exists():
        return {}
    site_code = (site or "US").strip().upper() or "US"
    manifest_path = details_dir / f"export_bundle_{site_code}_{datetime.now().strftime('%Y%m%d')}.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, dict) or not files:
        return {}
    resolved: dict[str, Path] = {}
    for key, rel_name in files.items():
        file_name = str(rel_name or "").strip()
        if not file_name:
            return {}
        path = details_dir / file_name
        if not path.exists():
            return {}
        resolved[str(key or file_name)] = path
    return resolved


def save_completed_export_bundle(download_dir: Path, site: str, export_files: dict[str, Path]) -> None:
    if not export_files:
        return
    details_dir = download_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    site_code = (site or "US").strip().upper() or "US"
    manifest_path = details_dir / f"export_bundle_{site_code}_{datetime.now().strftime('%Y%m%d')}.json"
    payload = {
        "site": site_code,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": {str(key): path.name for key, path in export_files.items()},
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def infer_existing_export_bundle(download_dir: Path, site: str) -> dict[str, Path]:
    details_dir = download_dir / "details"
    if not details_dir.exists():
        return {}
    site_code = (site or "US").strip().upper() or "US"
    date_token = datetime.now().strftime("%Y%m%d")
    sales_prefix = f"product-{site_code}-sales-{date_token}"
    competitor_prefix = f"Competitor-{site_code}-Last-30-days"

    competitor_candidates = sorted(
        [path for path in details_dir.glob("*.xlsx") if path.is_file() and path.name.startswith(competitor_prefix)],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    sales_candidates = sorted(
        [path for path in details_dir.glob("*.xlsx") if path.is_file() and path.name.startswith(sales_prefix)],
        key=lambda item: (item.stat().st_mtime, item.name),
    )
    if not competitor_candidates or not sales_candidates:
        return {}

    inferred: dict[str, Path] = {competitor_candidates[0].stem: competitor_candidates[0]}
    for path in sales_candidates:
        inferred[path.stem] = path
    return inferred


def download_exports_from_log(
    driver,
    download_dir: Path,
    site: str,
    *,
    wait_minutes: int = 3,
    expected_sales_exports: int = 1,
    safe_get,
    wait_document_ready,
    extract_row_text,
    log,
) -> dict[str, Path]:
    export_log_url = ss_config.SELLERSPRITE_EXPORT_LOG_URL
    details_dir = download_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    site_code = (site or "US").strip().upper() or "US"
    sales_prefix = f"product-{site_code}-sales-{datetime.now().strftime('%Y%m%d')}"
    competitor_prefix = f"Competitor-{site_code}-Last-30-days"
    pending: set[str] = set()
    downloaded: dict[str, Path] = {}
    task_ids: dict[str, str] = {}

    def _move_to_details(path: Path) -> Path:
        target = details_dir / path.name
        if target.exists():
            stem = path.stem
            suffix = path.suffix
            idx = 1
            while True:
                candidate = details_dir / f"{stem}_{idx}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
                idx += 1
        try:
            return path.replace(target)
        except Exception as exc:
            log(f"UC 文件移动到 details 失败，保留原路径[{path.name}]: {exc}")
            return path

    log("UC 导出任务已提交，先稍微等待 15 秒缓冲，随后即刻启动高速 API API 轮询...")
    time.sleep(15.0)

    log("UC 打开导出日志页，提取后台任务 ID")
    main_handle = driver.current_window_handle
    opened_new_tab = False
    handles_before = list(driver.window_handles)
    try:
        driver.execute_script("window.open(arguments[0], '_blank');", export_log_url)
        time.sleep(0.3)
        handles_after = list(driver.window_handles)
        if len(handles_after) > len(handles_before):
            driver.switch_to.window(handles_after[-1])
            opened_new_tab = True
    except Exception:
        pass
    if not opened_new_tab:
        try:
            driver.switch_to.new_window("tab")
            opened_new_tab = True
        except Exception:
            log("UC 新开标签页失败，改为当前标签页打开导出日志页")

    safe_get(driver, export_log_url, title="导出日志页")
    wait_document_ready(driver)

    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "tr[table-item-id], tr.bg-white, table tbody tr")
        for row in rows[:15]:
            name_text = extract_row_text(row, ["td:nth-child(2) span[data-id]", "td:nth-child(2) span", "td:nth-child(2) div"])
            if site_code not in name_text.upper():
                continue
            is_sales = name_text.startswith(sales_prefix)
            is_competitor = name_text.startswith(competitor_prefix)
            if not is_sales and not is_competitor:
                continue
            if is_competitor and any(name.startswith(competitor_prefix) for name in task_ids):
                continue
            if is_sales:
                current_sales = sum(1 for name in task_ids if name.startswith(sales_prefix))
                if current_sales >= max(1, int(expected_sales_exports)):
                    continue
            if name_text in task_ids:
                continue
            task_id_elem = row.find_elements(By.CSS_SELECTOR, "span[data-id]")
            if task_id_elem:
                tid = task_id_elem[0].get_attribute("data-id")
                if tid:
                    task_ids[name_text] = tid
                    pending.add(name_text)
                    log(f"UC 成功识别任务ID: {name_text} -> ID:{tid}")
    except Exception as e:
        log(f"UC 提取任务 ID 失败，尝试降级轮询: {e}")

    if not task_ids:
        log("UC 警告: 当前未从导出日志页提取到任务ID，后续仅能依赖降级轮询。")

    def _read_session_state() -> tuple[dict[str, str], str]:
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        user_agent = driver.execute_script("return navigator.userAgent")
        return cookies, user_agent

    cookies, user_agent = _read_session_state()
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Referer": ss_config.SELLERSPRITE_EXPORT_LOG_URL,
    }

    round_no = 0
    max_rounds = max(1, int(wait_minutes)) * 50
    while pending and round_no < max_rounds:
        round_no += 1
        log(f"UC API 导出状态查询第 {round_no}/{max_rounds} 轮, 待完成: {len(pending)} 个")
        for matched_name in list(pending):
            tid = task_ids.get(matched_name)
            if not tid:
                log(f"UC [{matched_name}] 没有任务ID，执行一次 UI 兜底降级...")
                try:
                    driver.refresh()
                    wait_document_ready(driver)
                    rows = driver.find_elements(By.CSS_SELECTOR, "tr[table-item-id], tr.bg-white, table tbody tr")
                    for row in rows[:10]:
                        n_str = extract_row_text(row, ["td:nth-child(2) span[data-id]", "td:nth-child(2) span"])
                        if n_str.startswith(matched_name):
                            links = row.find_elements(By.CSS_SELECTOR, "a.download-excel, a[href*='download']")
                            if not links:
                                links = row.find_elements(By.XPATH, ".//a[contains(normalize-space(.),'下载')]")
                            if links:
                                d_url = links[0].get_attribute("href")
                                if d_url:
                                    file_resp = requests.get(d_url, cookies=cookies, headers=headers, timeout=60)
                                    if file_resp.status_code == 200 and len(file_resp.content) > 1024:
                                        save_path = download_dir / f"{matched_name}.xlsx"
                                        save_path.write_bytes(file_resp.content)
                                        downloaded[matched_name] = _move_to_details(save_path)
                                        pending.discard(matched_name)
                except Exception as ex:
                    log(f"UC [{matched_name}] 降级轮询异常: {ex}")
                continue

            api_url = f"https://www.sellersprite.com/v2/export-log/flush?id={tid}"
            try:
                resp = requests.get(api_url, cookies=cookies, headers=headers, timeout=15)
                if resp.status_code == 200 and "application/json" in resp.headers.get("Content-Type", ""):
                    data = resp.json()
                    status = str(data.get("data", {}).get("status", "")).strip().upper()
                    file_path_url = data.get("data", {}).get("path", "")
                    if status in ("2", "3", "C", "S", "SUCCESS") or file_path_url:
                        if not file_path_url:
                            file_path_url = f"https://www.sellersprite.com/v2/export-log/{tid}/download"
                        file_resp = requests.get(file_path_url, cookies=cookies, headers=headers, timeout=60)
                        if file_resp.status_code == 200 and len(file_resp.content) > 1024:
                            save_path = download_dir / f"{matched_name}.xlsx"
                            save_path.write_bytes(file_resp.content)
                            downloaded[matched_name] = _move_to_details(save_path)
                            pending.discard(matched_name)
                            log(f"UC 后台静默下载完成: {matched_name}.xlsx (任务耗时约 {round_no*10} 秒)")
            except Exception as e:
                log(f"UC 刷新 ID:{tid} 时网络异常: {e}")

        if pending:
            time.sleep(10.0)

    if opened_new_tab:
        log("UC 任务导出执行完毕，关闭任务标签页")
        driver.close()
        handles_now = list(driver.window_handles)
        if main_handle in handles_now:
            driver.switch_to.window(main_handle)
        elif handles_now:
            driver.switch_to.window(handles_now[0])

    if pending:
        log(f"UC 警告: 导出日志彻底超时，未获取到以下任务: {pending}")
    return downloaded


def find_existing_export_files(download_dir: Path, site: str) -> dict[str, Path]:
    details_dir = download_dir / "details"
    if not details_dir.exists():
        return {}
    site_code = (site or "US").strip().upper() or "US"
    expected_prefixes = {
        f"product-{site_code}-sales-{datetime.now().strftime('%Y%m%d')}",
        f"Competitor-{site_code}-Last-30-days",
    }
    matched: dict[str, Path] = {}
    for prefix in expected_prefixes:
        candidates = sorted(
            [path for path in details_dir.glob("*.xlsx") if path.is_file() and path.name.startswith(prefix)],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            matched[prefix] = candidates[0]
    return matched if len(matched) == len(expected_prefixes) else {}


def uncheck_include_variants_if_checked(driver, *, pause, wait_present, log) -> None:
    candidates = driver.find_elements(
        By.XPATH,
        (
            "//label[contains(normalize-space(.),'包含变体') or contains(normalize-space(.),'变体')]"
            "//span[contains(@class,'el-checkbox__input')]"
        ),
    )
    if not candidates:
        return
    for box in candidates:
        cls = (box.get_attribute("class") or "").lower()
        if "is-checked" not in cls:
            continue
        log("UC 检测到“包含变体”已勾选，执行取消勾选")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", box)
        except Exception:
            pass
        pause(0.1, 0.3)
        try:
            box.click()
        except Exception:
            driver.execute_script("arguments[0].click();", box)
        pause(0.2, 0.5)
        log("UC 等待图表按钮出现，确认取消变体后的数据已加载")
        wait_present(driver, "chart_button", timeout=30)
        pause(0.5, 1.2)
        return


def check_include_variants_if_needed(driver, *, pause, wait_present, log) -> None:
    candidates = driver.find_elements(
        By.XPATH,
        (
            "//label[contains(normalize-space(.),'包含变体') or contains(normalize-space(.),'变体')]"
            "//span[contains(@class,'el-checkbox__input')]"
        ),
    )
    if not candidates:
        return
    for box in candidates:
        cls = (box.get_attribute("class") or "").lower()
        if "is-checked" in cls:
            log("UC 检测到“包含变体”已勾选，保留勾选状态")
            return
        log("UC 检测到“包含变体”未勾选，执行勾选")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", box)
        except Exception:
            pass
        pause(0.1, 0.3)
        try:
            box.click()
        except Exception:
            driver.execute_script("arguments[0].click();", box)
        pause(0.2, 0.5)
        wait_present(driver, "chart_button", timeout=30)
        pause(0.5, 1.2)
        return


def set_select_all_checkbox(driver, *, checked: bool, wait_first_interactable, selector_xpaths, pause) -> None:
    elem = wait_first_interactable(driver, selector_xpaths("select_all_checkbox"), timeout=20)
    cls = (elem.get_attribute("class") or "").lower()
    is_checked = "is-checked" in cls
    if is_checked == checked:
        return
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
    except Exception:
        pass
    pause(0.1, 0.3)
    try:
        elem.click()
    except Exception:
        driver.execute_script("arguments[0].click();", elem)
    pause(0.2, 0.5)


def click_next_page(driver, *, selector_xpaths, click, pause, wait_present) -> bool:
    clickable = False
    for xp in selector_xpaths("next_page_button"):
        try:
            elems = driver.find_elements(By.XPATH, xp)
        except Exception:
            continue
        for elem in elems:
            try:
                cls = (elem.get_attribute("class") or "").lower()
                if elem.is_displayed() and elem.is_enabled() and "disabled" not in cls:
                    clickable = True
                    break
            except Exception:
                continue
        if clickable:
            break
    if not clickable:
        return False
    click(driver, "next_page_button", timeout=10)
    pause(1.5, 2.8)
    wait_present(driver, "chart_button", timeout=30)
    pause(0.5, 1.2)
    return True


def dismiss_later_view_if_present(driver, *, click, pause, log, timeout: int = 4) -> bool:
    try:
        click(driver, "later_view_button", timeout=timeout)
        log("UC 已点击“等会儿看”关闭导出提示")
        pause(0.4, 0.8)
        return True
    except Exception:
        return False
