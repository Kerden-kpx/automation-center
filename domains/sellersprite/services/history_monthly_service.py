# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SellerSprite monthly history download service."""

from __future__ import annotations

import concurrent.futures
import random
import re
import threading
import time
from pathlib import Path


def _collect_existing_history_monthly_asins(save_dir: Path) -> set[str]:
    existing_asins: set[str] = set()
    if not save_dir.exists():
        return existing_asins
    for path in save_dir.glob("*.xlsx"):
        stem = path.stem
        asin = ""
        if stem.endswith("_history_monthly"):
            asin = stem[: -len("_history_monthly")].strip().upper()
        else:
            match = re.match(r"^Sales-([A-Za-z0-9]{10})-[A-Za-z]{2,3}-Monthly$", stem, re.IGNORECASE)
            if match:
                asin = str(match.group(1) or "").strip().upper()
        if asin:
            existing_asins.add(asin)
    return existing_asins


def download_history_monthly_one(
    driver,
    asin: str,
    site: str,
    cookies: dict[str, str],
    user_agent: str,
    save_dir: Path,
    *,
    log,
    min_valid_bytes: int = 10 * 1024,
) -> tuple[str, Path | None, str]:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.exceptions import TooManyRedirects
    from urllib.parse import unquote
    from urllib3.util.retry import Retry

    site_code = (site or "US").strip().upper() or "US"
    site_id_map = {"US": "1", "JP": "2", "UK": "3", "GB": "3", "DE": "4"}
    site_id = site_id_map.get(site_code)
    if not site_id:
        return asin, None, f"UNSUPPORTED_SITE:{site_code}"
    url = f"https://www.sellersprite.com/v2/competitor-lookup/{site_id}/{asin}/export-history-monthly"
    headers = {
        "User-Agent": user_agent,
        "Referer": "https://www.sellersprite.com/v3/competitor-lookup",
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.9",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    try:
        resp = session.get(url, cookies=cookies, headers=headers, timeout=(10, 30))
        resp.raise_for_status()
    except Exception as e:
        log(f"UC [ASIN: {asin}] requests 历史月下载被强行阻断 ({e})，尝试启动内核 fetch 级风控穿透...")
        js_code = f"""
            var cb = arguments[arguments.length - 1];
            fetch("{url}", {{
                method: "GET",
                headers: {{ "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.9" }}
            }}).then(response => {{
                if(!response.ok) throw new Error("HTTP " + response.status);
                return response.blob();
            }}).then(blob => {{
                var reader = new FileReader();
                reader.onloadend = function() {{
                    cb(reader.result);
                }};
                reader.readAsDataURL(blob);
            }}).catch(err => cb("ERROR: " + err.toString()));
        """
        try:
            res = driver.execute_async_script(js_code)
            if res and not res.startswith("ERROR:"):
                import base64

                b64_data = res.split(",")[-1] if "," in res else res
                raw_bytes = base64.b64decode(b64_data)
                if len(raw_bytes) < min_valid_bytes:
                    return asin, None, "RATE_LIMITED"
                raw_name = f"{asin}_history_monthly.xlsx"
                save_path = save_dir / raw_name
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(raw_bytes)
                log(f"UC [ASIN: {asin}] 内核级 fetch 成功穿透风控下载: {raw_name}")
                return asin, save_path, "OK"
            return asin, None, f"FETCH_FAILED: {res}"
        except Exception as sel_err:
            return asin, None, f"JS_EVAL_ERROR: {sel_err}"

    try:
        if len(resp.content) < min_valid_bytes:
            return asin, None, "RATE_LIMITED"
        disposition = resp.headers.get("Content-Disposition", "")
        raw_name = ""
        if disposition:
            fname_match = re.search(r"filename\*=utf-8''([^\r\n]+)", disposition, re.IGNORECASE)
            if fname_match:
                raw_name = unquote(fname_match.group(1))
            else:
                fname_match = re.search(r"filename\s*=\s*[\"']?([^\"';\r\n]+)", disposition, re.IGNORECASE)
                raw_name = fname_match.group(1).strip() if fname_match else ""
                if raw_name:
                    raw_name = unquote(raw_name)
        if not raw_name:
            raw_name = f"{asin}_history_monthly.xlsx"
        if not raw_name.lower().endswith(".xlsx"):
            raw_name += ".xlsx"
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", raw_name).strip().strip(".")
        if not safe_name:
            safe_name = f"{asin}_history_monthly.xlsx"
        stem = safe_name.rsplit(".", 1)[0]
        if not re.search(r"[A-Za-z0-9]", stem):
            safe_name = f"{asin}_history_monthly.xlsx"
        save_path = save_dir / safe_name
        save_path.write_bytes(resp.content)
        return asin, save_path, ""
    except TooManyRedirects:
        return asin, None, "SESSION_EXPIRED"
    except Exception as exc:
        return asin, None, str(exc)


def export_history_monthly_per_asin(
    driver,
    download_dir: Path,
    site: str,
    *,
    resolve_history_export_asins,
    log,
    category: str = "",
    request_interval: tuple[float, float] = (2.0, 5.0),
    rate_limit_backoff_sec: int = 60,
    max_retries: int = 2,
    max_workers: int = 2,
) -> list[str]:
    sales_volume_dir = download_dir / "sales volume"
    sales_volume_dir.mkdir(parents=True, exist_ok=True)
    log(f"UC 历史月销量文件将保存至: {sales_volume_dir}")
    asins = resolve_history_export_asins(site=site, category=category)
    if asins:
        log(f"UC 历史月销量从数据库获取到 {len(asins)} 个 ASIN (site={site}, category={category or '<empty>'})")
    if not asins:
        raise RuntimeError(
            f"历史月销量导出前未能从数据库获取 ASIN: site={site}, category={category or '<empty>'}, date=CURDATE()"
        )
    normalized_asins: list[str] = []
    seen_asins: set[str] = set()
    for asin in asins:
        value = str(asin or "").strip().upper()
        if not value or value in seen_asins:
            continue
        seen_asins.add(value)
        normalized_asins.append(value)
    asins = normalized_asins

    existing_asins = _collect_existing_history_monthly_asins(sales_volume_dir)
    missing_asins = [asin for asin in asins if asin not in existing_asins]
    if existing_asins:
        log(f"UC 历史月销量检测到已存在文件 {len(existing_asins)} 个，缺失 {len(missing_asins)} 个")
    if not missing_asins:
        log(f"UC 历史月销量并发拉取汇总: 成功 {len(asins)}/{len(asins)}, 失败 0 (已存在，跳过下载)")
        return asins

    log(
        f"UC 提取到 {len(asins)} 个 ASIN, 其中待下载 {len(missing_asins)} 个, "
        f"开始并发下载 (并发数={max_workers})..."
    )

    def _read_session_state() -> tuple[dict[str, str], str]:
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        user_agent = driver.execute_script("return navigator.userAgent")
        return cookies, user_agent

    shared_state = {"cookies": {}, "user_agent": "", "lock": threading.Lock(), "last_refresh_time": 0.0}
    try:
        shared_state["cookies"], shared_state["user_agent"] = _read_session_state()
        shared_state["last_refresh_time"] = time.time()
    except Exception as exc:
        log(f"UC 初始化 Session 失败, 跳过任务: {exc}")
        return []

    def _get_current_session() -> tuple[dict[str, str], str]:
        with shared_state["lock"]:
            return shared_state["cookies"], shared_state["user_agent"]

    def _refresh_session_if_needed(request_time: float) -> tuple[dict[str, str], str]:
        with shared_state["lock"]:
            if request_time >= shared_state["last_refresh_time"]:
                try:
                    log("UC [安全锁]触发浏览器 Cookie 同步刷新...")
                    driver.refresh()
                    time.sleep(3.0)
                    shared_state["cookies"] = {c["name"]: c["value"] for c in driver.get_cookies()}
                    shared_state["user_agent"] = driver.execute_script("return navigator.userAgent")
                    shared_state["last_refresh_time"] = time.time()
                    log("UC [安全锁]同步刷新成功")
                except Exception as exc:
                    log(f"UC [安全锁]刷新失败: {exc}")
            return shared_state["cookies"], shared_state["user_agent"]

    def _is_retryable_network_error(err: str) -> bool:
        text = str(err or "").strip().lower()
        return any(
            token in text
            for token in (
                "read timed out",
                "timed out",
                "timeout",
                "connection reset",
                "connection aborted",
                "connection pool",
                "temporarily unavailable",
                "http 502",
                "http 503",
                "http 504",
            )
        )

    fetch_success = 0
    fetch_failed = 0
    stats_lock = threading.Lock()

    def _worker(asin: str, seq: int) -> None:
        nonlocal fetch_success, fetch_failed
        try:
            attempt = 0
            cookie_refreshed_for_this_asin = False
            while attempt <= max_retries:
                if attempt == 0 and request_interval != (0, 0):
                    time.sleep(random.uniform(*request_interval))
                cookies, user_agent = _get_current_session()
                req_time = time.time()
                out_asin, path, err = download_history_monthly_one(
                    driver, asin, site, cookies, user_agent, sales_volume_dir, log=log
                )
                if path is not None:
                    size_kb = path.stat().st_size // 1024
                    log(f"UC [{seq}/{len(missing_asins)}][{out_asin}] 下载成功: {path.name} ({size_kb} KB)")
                    with stats_lock:
                        fetch_success += 1
                    return
                if err == "SESSION_EXPIRED":
                    if not cookie_refreshed_for_this_asin:
                        log(f"UC [{seq}/{len(missing_asins)}][{asin}] Session 失效，等待同步锁刷新重试")
                        _refresh_session_if_needed(req_time)
                        cookie_refreshed_for_this_asin = True
                        attempt += 1
                        time.sleep(random.uniform(1.0, 3.0))
                        continue
                    log(f"UC [{seq}/{len(missing_asins)}][{asin}] Session 刷新后仍失效，放弃该项")
                    break
                if err == "RATE_LIMITED":
                    attempt += 1
                    if attempt <= max_retries:
                        log(f"UC [{seq}/{len(missing_asins)}][{asin}] 触发限速，等待 {rate_limit_backoff_sec}s ({attempt}/{max_retries})")
                        time.sleep(rate_limit_backoff_sec)
                        continue
                    log(f"UC [{seq}/{len(missing_asins)}][{asin}] 限速重试耗尽，放弃该项")
                    break
                if _is_retryable_network_error(err):
                    attempt += 1
                    if attempt <= max_retries:
                        wait_sec = random.uniform(8.0, 18.0)
                        log(f"UC [{seq}/{len(missing_asins)}][{asin}] 网络异常[{err}]，等待 {wait_sec:.0f}s ({attempt}/{max_retries})")
                        time.sleep(wait_sec)
                        continue
                    log(f"UC [{seq}/{len(missing_asins)}][{asin}] 网络重试耗尽，放弃该项")
                    break
                log(f"UC [{seq}/{len(missing_asins)}][{asin}] 致命失败: {err}")
                break
            with stats_lock:
                fetch_failed += 1
        except Exception as wk_err:
            log(f"UC [{seq}/{len(missing_asins)}][{asin}] 并发下载线程抛出严重异常: {wk_err}")
            with stats_lock:
                fetch_failed += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_worker, asin, seq) for seq, asin in enumerate(missing_asins, 1)]
        concurrent.futures.wait(futures)
    total_success = len(existing_asins) + fetch_success
    total_failed = len(asins) - total_success
    log(f"UC 历史月销量并发拉取汇总: 成功 {total_success}/{len(asins)}, 失败 {total_failed}")
    return asins
