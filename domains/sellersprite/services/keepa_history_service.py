# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SellerSprite Keepa historical trends service."""

from __future__ import annotations

import json
import random
import re
import time
import concurrent.futures
from datetime import datetime
from pathlib import Path

import requests
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By

from core import config as web_config
from ..repositories.historical_status_repo import load_success_asins, upsert_status
from ..repositories.product_day_repo import upsert_keepa_fact_rows


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_step(message: str) -> None:
    print(f"[{_now_str()}] [SellerSpriteHistoricalTrendsAPI] {message}")


def _upsert_fact_daily_rows(rows: list[tuple]) -> int:
    if not rows:
        return 0
    try:
        return upsert_keepa_fact_rows(rows)
    except Exception as exc:
        _log_step(f"批量插入 Daily Fact 失败: {exc}")
        return 0


def _load_success_asins_from_status(site: str, category: str = "") -> set[str]:
    return load_success_asins(site=site, category=category)


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
    upsert_status(
        site=site,
        asin=asin,
        status=status,
        category=category,
        message=message,
        artifact_path=artifact_path,
        started_at=started_at,
        ended_at=ended_at,
    )


def _load_existing_keepa_json_asins(download_dir: Path) -> set[str]:
    existing: set[str] = set()
    if not download_dir.exists():
        return existing
    for path in download_dir.glob("*_keepa.json"):
        asin = str(path.stem[: -len("_keepa")] if path.stem.endswith("_keepa") else "").strip().upper()
        if asin:
            existing.add(asin)
    return existing


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


def _parse_keepa_json_to_fact_rows(asin: str, keepa_data: dict, site: str) -> list[tuple]:
    if not keepa_data:
        return []

    times = keepa_data.get("times", [])
    if not times:
        return []

    kstats = keepa_data.get("keepa", {})
    bsr_list = kstats.get("bsr", [])
    buy_price_list = kstats.get("buyPrice", [])
    price_list = kstats.get("price", [])
    list_price_list = kstats.get("listPrice", [])
    rating_list = kstats.get("rating", [])
    reviews_list = kstats.get("reviews", [])
    sellers_list = kstats.get("sellers", [])
    monthly_sold_list = kstats.get("monthlySoldHistory", [])

    daily_map = {}

    for i, timestamp in enumerate(times):
        date_str = timestamp[:10]
        bsr = bsr_list[i] if i < len(bsr_list) else None
        buy_price = buy_price_list[i] if i < len(buy_price_list) else None
        price = price_list[i] if i < len(price_list) else None
        list_price = list_price_list[i] if i < len(list_price_list) else None
        rating = rating_list[i] if i < len(rating_list) else None
        reviews = reviews_list[i] if i < len(reviews_list) else None
        sellers = sellers_list[i] if i < len(sellers_list) else None
        monthly_sold = monthly_sold_list[i] if i < len(monthly_sold_list) else None

        if date_str not in daily_map:
            daily_map[date_str] = {}

        if bsr is not None:
            daily_map[date_str]["bsr"] = bsr
        if buy_price is not None:
            daily_map[date_str]["buy_price"] = buy_price
        if price is not None:
            daily_map[date_str]["price"] = price
        if list_price is not None:
            daily_map[date_str]["list_price"] = list_price
        if rating is not None:
            daily_map[date_str]["rating"] = rating
        if reviews is not None:
            daily_map[date_str]["reviews"] = reviews
        if sellers is not None:
            daily_map[date_str]["sellers"] = sellers
        if monthly_sold is not None:
            daily_map[date_str]["monthly_sold"] = monthly_sold

    result = []
    for date_str, stats in daily_map.items():
        try:
            row_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            continue

        from decimal import Decimal, InvalidOperation

        def to_dec(value):
            if value is None:
                return None
            try:
                return Decimal(str(value))
            except InvalidOperation:
                return None

        def to_int(value):
            if value is None:
                return None
            try:
                return int(float(value))
            except ValueError:
                return None

        result.append(
            (
                site,
                asin,
                row_date,
                to_dec(stats.get("buy_price")) or Decimal("0"),
                to_dec(stats.get("price")) or Decimal("0"),
                None,
                None,
                None,
                to_int(stats.get("monthly_sold")),
                None,
                None,
                to_dec(stats.get("list_price")),
                to_int(stats.get("bsr")),
                None,
                to_dec(stats.get("rating")),
                to_int(stats.get("reviews")),
                to_int(stats.get("sellers")),
            )
        )

    return result


def export_historical_trends_via_api(
    driver: WebDriver, download_dir: Path, site: str = "US", category: str = "", asins: list[str] | None = None
) -> tuple[int, int, list[Path]]:
    download_dir.mkdir(parents=True, exist_ok=True)
    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
    user_agent = driver.execute_script("return navigator.userAgent;")
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Referer": web_config.SELLERSPRITE_COMPETITOR_LOOKUP_URL,
    }

    succeeded_asins = _load_success_asins_from_status(site, category)
    existing_json_asins = _load_existing_keepa_json_asins(download_dir)
    category_name = category or download_dir.parent.name

    selected_asins: list[str] = []
    all_rows_to_insert = []
    input_asins = [str(a or "").strip().upper() for a in (asins or []) if str(a or "").strip()]
    if input_asins:
        deduped_input_asins: list[str] = []
        seen_input: set[str] = set()
        for asin in input_asins:
            if asin in seen_input:
                continue
            seen_input.add(asin)
            deduped_input_asins.append(asin)
        for idx, asin in enumerate(deduped_input_asins, 1):
            if asin not in succeeded_asins and asin not in existing_json_asins:
                selected_asins.append(asin)
            else:
                if asin in succeeded_asins:
                    _log_step(f"[{idx}/{len(deduped_input_asins)}][{asin}] 今日已成功，跳过")
                else:
                    _log_step(f"[{idx}/{len(deduped_input_asins)}][{asin}] 检测到已存在 Keepa JSON，跳过")
                save_path = download_dir / f"{asin}_keepa.json"
                if save_path.exists():
                    try:
                        with save_path.open("r", encoding="utf-8") as f:
                            raw_data = json.load(f)
                        skipped_rows_parsed = _parse_keepa_json_to_fact_rows(asin, raw_data.get("keepa", {}), site)
                        if skipped_rows_parsed:
                            all_rows_to_insert.extend(skipped_rows_parsed)
                    except Exception as exc:
                        _log_step(f"尝试解析已跳过的历史 JSON 失败 [{asin}]: {exc}")
    else:
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.el-table__row")
        if not rows:
            _log_step("未找到结果表行，且未提供 ASIN 列表，跳过 API 提取。")
            return 0, 0, []
        for idx, row in enumerate(rows, 1):
            asin = _extract_asin_from_row(row)
            if asin and asin not in succeeded_asins and asin not in existing_json_asins:
                selected_asins.append(asin)
            elif asin in succeeded_asins or asin in existing_json_asins:
                if asin in succeeded_asins:
                    _log_step(f"[{idx}/{len(rows)}][{asin}] 今日已成功，跳过")
                else:
                    _log_step(f"[{idx}/{len(rows)}][{asin}] 检测到已存在 Keepa JSON，跳过")
                save_path = download_dir / f"{asin}_keepa.json"
                if save_path.exists():
                    try:
                        with save_path.open("r", encoding="utf-8") as f:
                            raw_data = json.load(f)
                        skipped_rows_parsed = _parse_keepa_json_to_fact_rows(asin, raw_data.get("keepa", {}), site)
                        if skipped_rows_parsed:
                            all_rows_to_insert.extend(skipped_rows_parsed)
                    except Exception as exc:
                        _log_step(f"尝试解析已跳过的历史 JSON 失败 [{asin}]: {exc}")

    if not selected_asins and not all_rows_to_insert:
        _log_step("所有 ASIN 均已提取完毕或跳过，且没有需要额外入库的历史数据。")
        return 0, 0, []

    success_count = 0
    fail_count = 0
    downloaded_files: list[Path] = []
    site_lower = site.lower()
    total = len(selected_asins)
    _log_step(f"开始使用 API 并发拉取 {total} 个 ASIN 的历史趋势...")

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))

    def _is_retryable_business_error(data: dict | None, text: str) -> bool:
        payload = data if isinstance(data, dict) else {}
        code = str(payload.get("code") or "").strip().upper()
        message = str(payload.get("message") or "").strip()
        merged = f"{code} {message} {text}".upper()
        return "ERR_GLOBAL_500" in merged or "系统异常" in merged or "PLEASE TRY AGAIN LATER" in merged

    def fetch_keepa_data(asin: str):
        url = f"https://www.sellersprite.com/v2/keepa/subTrend/{site_lower}/{asin}?parentModule=ARA"
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        last_err = ""
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    backoff = min(12.0, 1.5 * (2 ** (attempt - 2))) + random.uniform(0.3, 1.2)
                    _log_step(f"[{asin}] Keepa API 业务重试 {attempt}/{max_attempts}, wait={backoff:.1f}s")
                    time.sleep(backoff)
                else:
                    time.sleep(random.uniform(0.5, 1.5))

                resp = session.get(url, headers=headers, cookies=cookies, timeout=30)
                body_preview = resp.text[:200]
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == "OK" and "data" in data and "keepa" in data["data"]:
                        return asin, started_at, data["data"], None
                    if _is_retryable_business_error(data, body_preview) and attempt < max_attempts:
                        last_err = f"HTTP 200 - {body_preview}"
                        continue
                last_err = f"HTTP {resp.status_code} - {body_preview}"
            except Exception as exc:
                last_err = str(exc)
                if attempt < max_attempts:
                    continue
        return asin, started_at, None, last_err

    failed_asins: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_asin = {executor.submit(fetch_keepa_data, asin): asin for asin in selected_asins}

        for future in concurrent.futures.as_completed(future_to_asin):
            asin = future_to_asin[future]
            asin_from_res, started_at, raw_data, err = future.result()
            ended_at = time.strftime("%Y-%m-%d %H:%M:%S")

            if raw_data is not None:
                success_count += 1
                _log_step(f"[{success_count}/{total}][{asin}] API 极速拉取成功！")
                save_path = download_dir / f"{asin}_keepa.json"
                with save_path.open("w", encoding="utf-8") as f:
                    json.dump(raw_data, f, ensure_ascii=False, indent=2)
                downloaded_files.append(save_path)
                _upsert_historical_trend_status(
                    site,
                    asin,
                    "success",
                    category=category_name,
                    artifact_path=str(save_path),
                    started_at=started_at,
                    ended_at=ended_at,
                )
                rows_parsed = _parse_keepa_json_to_fact_rows(asin_from_res, raw_data.get("keepa", {}), site)
                all_rows_to_insert.extend(rows_parsed)
            else:
                fail_count += 1
                failed_asins.append(asin)
                _log_step(f"[{fail_count}个失败] [{asin}] 拉取报错: {err}")
                _upsert_historical_trend_status(
                    site,
                    asin,
                    "error",
                    category=category_name,
                    message=err or "",
                    started_at=started_at,
                    ended_at=ended_at,
                )

    if all_rows_to_insert:
        upserted = _upsert_fact_daily_rows(all_rows_to_insert)
        _log_step(f"极速入库完成! 新增/更新行数: {upserted}")
    else:
        _log_step("已成功极速拉取 JSON 落盘，等待后续完善解析逻辑后即可入库。")

    if failed_asins:
        _log_step("最终失败 ASIN: " + ", ".join(failed_asins))

    return success_count, fail_count, downloaded_files


def _export_historical_trends_via_api(
    driver: WebDriver, download_dir: Path, site: str = "US", category: str = "", asins: list[str] | None = None
) -> tuple[int, int, list[Path]]:
    return export_historical_trends_via_api(driver, download_dir, site=site, category=category, asins=asins)
