#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Amazon ASIN pricing flag collection via browser automation.

Usage:
    python -m domains.amazon.flows.amazon_product_details

Before running:
- Install Playwright and browsers
- Login to Amazon and the plugin in Chrome profile used by CDP
- Update CONFIG below with selectors and ASIN list
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from core import config as core_config
from ..config.config import build_amazon_config
from ..repositories.amazon_item_repo import load_targets_for_today, update_list_price_rows
from ..services.page_service import configure_async_page, goto_with_fallback, setup_resource_blocking
from ..services.product_details_page_service import (
    ensure_currency_on_first_open as page_ensure_currency_on_first_open,
    ensure_delivery_zip_on_first_open as page_ensure_delivery_zip_on_first_open,
    ensure_sellersprite_logged_in_on_first_asin as page_ensure_sellersprite_logged_in_on_first_asin,
    extract_list_price as page_extract_list_price,
    extract_promotion_tags as page_extract_promotion_tags,
    extract_special_conversion_rate as page_extract_special_conversion_rate,
    process_single_target as page_process_single_target,
)
import yaml


def _load_selectors() -> Dict[str, Any]:
    selectors_path = Path(__file__).resolve().parents[1] / "selectors" / "amazon_product_details_selectors.yaml"
    if not selectors_path.exists():
        raise RuntimeError(f"Missing selectors YAML: {selectors_path}")
    with selectors_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid selectors YAML format: {selectors_path}")
    return data


AMAZON_EXPORT_SELECTORS = _load_selectors()


def _load_target_urls() -> Dict[str, Dict[str, Any]]:
    yaml_path = Path(__file__).resolve().parents[1] / "selectors" / "amazon_target_urls.yaml"
    if not yaml_path.exists():
        return {}
    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _load_sellersprite_login_selectors() -> Dict[str, List[str]]:
    selectors_path = (
        Path(__file__).resolve().parents[2]
        / "sellersprite"
        / "selectors"
        / "sellersprite_ccp_selectors.yaml"
    )
    if not selectors_path.exists():
        raise RuntimeError(f"Missing selectors YAML: {selectors_path}")
    with selectors_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid selectors YAML format: {selectors_path}")

    required_keys = [
        "account_login_tab",
        "account_input",
        "password_input",
        "login_submit_button",
        "asin_count_ready",
    ]
    out: Dict[str, List[str]] = {}
    for key in required_keys:
        value = data.get(key) or []
        if not isinstance(value, list):
            value = []
        out[key] = [str(item) for item in value if str(item).strip()]
    return out


SELLERSPRITE_LOGIN_SELECTORS = _load_sellersprite_login_selectors()
PRODUCT_DETAIL_STATUS_TABLE = "fact_bi_amazon_product_detail_status"
SITE_RUN_ORDER = ["US", "UK", "DE", "JP"]
SITE_TARGET_CONFIGS = _load_target_urls()
SPECIAL_CONVERSION_CATEGORY = "Kids' Paint With Water Kits"


CONFIG = build_amazon_config(
    {
        "amazon_url": "https://www.amazon.com/dp/{asin}",
        "concurrent_tabs": 3,
        "batch_size": 30,
        "batch_rest_sec": (45, 90),
        "site_blocked_streak_limit": 3,
        "site_cooldown_sec": 1800,
        "status_file": r"",
        "sellersprite_login_on_first_asin": False,
        "sellersprite_login_on_first_page": False,
        "set_delivery_zip_on_first_page": True,
        "set_currency_on_first_page": True,
        "delivery_zip_code": "",
    }
)


def _apply_runtime_overrides() -> None:
    site_env = str(os.getenv("AMAZON_PRODUCT_DETAILS_SITE", "")).strip().upper()
    if site_env:
        CONFIG["site"] = site_env


_apply_runtime_overrides()


def _resolve_delivery_zip_code() -> str:
    manual = str(CONFIG.get("delivery_zip_code") or "").strip()
    if manual:
        return manual
    site = str(CONFIG.get("site") or "").strip().upper() or "US"
    site_zip_map = {
        "US": "90001",
        "UK": "EC1A 1BB",
        "GB": "EC1A 1BB",
        "DE": "10115",
        "FR": "75001",
        "IT": "00118",
        "ES": "28001",
        "JP": "100-0001",
        "CA": "M5V 2T6",
        "AU": "2000",
        "MX": "01000",
        "CN": "100000",
        "SG": "018956",
    }
    return site_zip_map.get(site, "90001")


def _resolve_site_base_url() -> str:
    site = str(CONFIG.get("site") or "").strip().upper() or "US"
    site_base_map = {
        "US": "https://www.amazon.com",
        "UK": "https://www.amazon.co.uk",
        "GB": "https://www.amazon.co.uk",
        "DE": "https://www.amazon.de",
        "FR": "https://www.amazon.fr",
        "IT": "https://www.amazon.it",
        "ES": "https://www.amazon.es",
        "JP": "https://www.amazon.co.jp",
        "CA": "https://www.amazon.ca",
        "AU": "https://www.amazon.com.au",
        "MX": "https://www.amazon.com.mx",
        "SG": "https://www.amazon.sg",
    }
    return site_base_map.get(site, "https://www.amazon.com")


def _resolve_currency_code() -> str:
    site = str(CONFIG.get("site") or "").strip().upper() or "US"
    site_currency_map = {
        "US": "USD",
        "UK": "GBP",
        "GB": "GBP",
        "DE": "EUR",
        "FR": "EUR",
        "IT": "EUR",
        "ES": "EUR",
        "JP": "JPY",
        "CA": "CAD",
        "AU": "AUD",
        "MX": "MXN",
        "SG": "SGD",
    }
    return site_currency_map.get(site, "USD")


async def _sleep_ms(min_max: tuple[int, int]) -> None:
    import random

    lo, hi = min_max
    await asyncio.sleep(random.uniform(lo, hi) / 1000.0)


def _random_sec(value: Any, fallback: tuple[int, int]) -> int:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        low = int(value[0])
        high = int(value[1])
    elif value is None:
        low, high = fallback
    else:
        low = high = int(value)
    if high < low:
        low, high = high, low
    return random.randint(low, high)


def _extract_asin_from_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    match = re.search(r"/dp/([A-Z0-9]{10})", text, flags=re.I)
    if match:
        return match.group(1).upper()
    match = re.search(r"/gp/product/([A-Z0-9]{10})", text, flags=re.I)
    return match.group(1).upper() if match else ""

def _load_targets(id_filter: str = "") -> List[Dict[str, str]]:
    return _load_targets_from_db_today(id_filter)


def _resolve_allowed_categories_for_site(site: str, id_filter: str = "") -> List[str]:
    site_code = str(site or "").strip().upper() or "US"
    id_filter_str = str(id_filter or "").strip()
    if not id_filter_str or id_filter_str.upper() == "ALL" or not SITE_TARGET_CONFIGS:
        return []

    allowed = {item.strip().lower() for item in id_filter_str.split(",") if item.strip()}
    categories: List[str] = []
    seen = set()
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


def _load_targets_from_db_today(id_filter: str = "") -> List[Dict[str, str]]:
    site = str(CONFIG.get("site") or "").strip().upper() or "US"
    allowed_categories = _resolve_allowed_categories_for_site(site, id_filter)
    return load_targets_for_today(site, allowed_categories, asin_extractor=_extract_asin_from_url)


def _safe_token(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:80] or fallback


def _parse_args():
    parser = argparse.ArgumentParser(description="Amazon export daily flow")
    parser.add_argument("--id", default="", help="Comma separated category IDs or ALL, e.g. '1,2' or 'ALL'")
    return parser.parse_args()


def _resolve_sites_to_run(id_filter: str = "") -> List[str]:
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
        inferred_sites = set()
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

    site = str(os.getenv("AMAZON_PRODUCT_DETAILS_SITE") or CONFIG.get("site") or "US").strip().upper() or "US"
    return [site]


def _flow_log(message: str) -> None:
    text = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [AmazonDetails] {message}"
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        safe = text.encode(enc, errors="replace").decode(enc, errors="replace")
        print(safe)


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _apply_db_name_from_config() -> None:
    db_name = str(CONFIG.get("db_name") or "").strip()
    if db_name:
        os.environ["DB_NAME"] = db_name


def _ensure_export_dir(path: str) -> Path:
    export_dir = Path(path)
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def _safe_dir_name(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._")
    return text[:80] or fallback


def _resolve_category_dir_name(targets: List[Dict[str, str]]) -> str:
    counts: Dict[str, int] = {}
    for item in targets:
        category = str((item or {}).get("category") or "").strip()
        if not category:
            continue
        counts[category] = counts.get(category, 0) + 1
    if not counts:
        return "uncategorized"
    dominant = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return _safe_dir_name(dominant, "uncategorized")


def _resolve_list_price_csv_path(export_dir: Path) -> Path:
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / "PricingFlags.csv"


def _save_list_price_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "site",
                "asin",
                "list_price",
                "promotion_tags",
                "conversion_rate",
                "conversion_rate_period",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "date": str(row.get("date") or "").strip(),
                    "site": str(row.get("site") or "").strip(),
                    "asin": str(row.get("asin") or "").strip(),
                    "list_price": str(row.get("list_price") or "").strip(),
                    "promotion_tags": str(row.get("promotion_tags") or "").strip(),
                    "conversion_rate": str(row.get("conversion_rate") or "").strip(),
                    "conversion_rate_period": str(row.get("conversion_rate_period") or "").strip(),
                }
            )


def _ensure_pricing_flags_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "site",
                "asin",
                "list_price",
                "promotion_tags",
                "conversion_rate",
                "conversion_rate_period",
            ],
        )
        writer.writeheader()


def _append_pricing_flags_row(path: Path, row: Dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "site",
                "asin",
                "list_price",
                "promotion_tags",
                "conversion_rate",
                "conversion_rate_period",
            ],
        )
        writer.writerow(
            {
                "date": str(row.get("date") or "").strip(),
                "site": str(row.get("site") or "").strip(),
                "asin": str(row.get("asin") or "").strip(),
                "list_price": str(row.get("list_price") or "").strip(),
                "promotion_tags": str(row.get("promotion_tags") or "").strip(),
                "conversion_rate": str(row.get("conversion_rate") or "").strip(),
                "conversion_rate_period": str(row.get("conversion_rate_period") or "").strip(),
            }
        )


def _to_price_decimal_or_none(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9,.\-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        # Use the last separator as decimal mark: 1.234,56 / 1,234.56
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # European decimal comma: 35,60 -> 35.60; 1,234 -> 1234
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) in {1, 2}:
            cleaned = f"{parts[0]}.{parts[1]}"
        else:
            cleaned = "".join(parts)
    else:
        # Dotted decimals or thousand separators: keep the last decimal point if any.
        if cleaned.count(".") > 1:
            last_dot = cleaned.rfind(".")
            integer = cleaned[:last_dot].replace(".", "")
            fraction = cleaned[last_dot + 1 :]
            cleaned = f"{integer}.{fraction}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_rate_decimal_or_none(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = text.replace("%", "").strip()
    cleaned = re.sub(r"[^\d.\-]", "", cleaned)
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if number > 1:
        number = number / 100.0
    return number


def _update_list_price_to_db(rows: List[Dict[str, str]]) -> int:
    return update_list_price_rows(rows, _to_price_decimal_or_none, _to_rate_decimal_or_none)


def _load_pricing_flags_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            asin = str((row or {}).get("asin") or "").strip().upper()
            site = str((row or {}).get("site") or "").strip().upper()
            if not asin or not site:
                continue
            rows.append(
                {
                    "date": str((row or {}).get("date") or "").strip(),
                    "site": site,
                    "asin": asin,
                    "list_price": str((row or {}).get("list_price") or "").strip(),
                    "promotion_tags": str((row or {}).get("promotion_tags") or "").strip(),
                    "conversion_rate": str((row or {}).get("conversion_rate") or "").strip(),
                    "conversion_rate_period": str((row or {}).get("conversion_rate_period") or "").strip(),
                }
            )
    return rows


def _parse_decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    raw = str(value).strip().replace(",", "").replace("%", "")
    raw = re.sub(r"[^\d\.\-]", "", raw)
    if not raw:
        return default
    return Decimal(raw)


def _parse_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    raw = str(value).strip().replace(",", "").replace("+", "")
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _upsert_product_status(
    asin: str,
    status: str,
    message: str = "",
    *,
    category: str = "",
    artifact_path: str = "",
    started_at: str = "",
    ended_at: str = "",
) -> None:
    # Status table writes are temporarily disabled.
    # Keep this function as a no-op so DB status logic can be restored quickly later.
    _ = (
        asin,
        status,
        message,
        category,
        artifact_path,
        started_at,
        ended_at,
    )
    return None


def _load_success_asins_from_status() -> set[str]:
    # Status table reads are temporarily disabled.
    # Always return an empty set so the current site reruns all of today's targets.
    return set()


def _iter_contexts(page) -> List[Tuple[str, Any]]:
    contexts: List[Tuple[str, Any]] = [("page", page)]
    try:
        main_frame = page.main_frame
        for idx, frame in enumerate(page.frames):
            if frame == main_frame:
                continue
            frame_name = frame.name or f"frame_{idx}"
            contexts.append((f"frame:{frame_name}", frame))
    except Exception:
        pass
    return contexts


async def _human_pause(min_ms: int = 300, max_ms: int = 900) -> None:
    low = min(min_ms, max_ms)
    high = max(min_ms, max_ms)
    await asyncio.sleep(random.uniform(low, high) / 1000.0)


async def _wait_for_stability(page, timeout_ms: int = 8000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass
    await _human_pause(200, 500)


async def _random_scroll(page, times: int = 0) -> None:
    if times <= 0:
        times = random.randint(1, 3)
    for _ in range(times):
        distance = random.randint(120, 420)
        if random.choice([False, False, True]):
            distance = -distance
        try:
            await page.mouse.wheel(0, distance)
        except Exception:
            try:
                await page.evaluate(f"window.scrollBy(0, {distance})")
            except Exception:
                pass
        await _human_pause(200, 600)


async def _random_mouse_move(page, times: int = 0) -> None:
    if times <= 0:
        times = random.randint(2, 4)
    width, height = 1280, 720
    try:
        viewport = page.viewport_size or {}
        width = int(viewport.get("width", 1280))
        height = int(viewport.get("height", 720))
    except Exception:
        pass
    for _ in range(times):
        x = random.randint(80, max(120, width - 80))
        y = random.randint(80, max(120, height - 80))
        try:
            await page.mouse.move(x, y, steps=random.randint(8, 20))
        except Exception:
            pass
        await _human_pause(120, 280)


async def _wait_for_any_selector_across_contexts(
    page, selectors: List[str], timeout_ms: int = 10000, visible_only: bool = False
) -> bool:
    deadline = time.time() + max(0.2, timeout_ms / 1000.0)
    while time.time() < deadline:
        for _, ctx in _iter_contexts(page):
            for selector in selectors:
                try:
                    locator = ctx.locator(selector)
                    count = await locator.count()
                    if count <= 0:
                        continue
                    if not visible_only:
                        return True
                    for i in range(count):
                        try:
                            if await locator.nth(i).is_visible():
                                return True
                        except Exception:
                            continue
                except Exception:
                    continue
        await asyncio.sleep(0.25)
    return False


async def _click_first_visible_across_contexts(page, selectors: List[str], timeout_ms: int = 3000) -> bool:
    for _, ctx in _iter_contexts(page):
        for selector in selectors:
            try:
                locator = ctx.locator(selector)
                count = await locator.count()
                if count <= 0:
                    continue
                for i in range(count):
                    target = locator.nth(i)
                    try:
                        if not await target.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        await target.scroll_into_view_if_needed(timeout=1500)
                    except Exception:
                        pass
                    try:
                        await target.click(timeout=timeout_ms)
                    except Exception:
                        try:
                            await target.click(timeout=timeout_ms, force=True)
                        except Exception:
                            try:
                                await target.evaluate("el => el.click()")
                            except Exception:
                                continue
                    await _human_pause(250, 550)
                    return True
            except Exception:
                continue
    return False


async def _fill_first_visible_across_contexts(
    page, selectors: List[str], value: str, field_tag: str = "input"
) -> bool:
    last_err = ""
    for _, ctx in _iter_contexts(page):
        for selector in selectors:
            try:
                locator = ctx.locator(selector)
                count = await locator.count()
                if count <= 0:
                    continue
                for i in range(count):
                    target = locator.nth(i)
                    try:
                        if not await target.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        await target.scroll_into_view_if_needed(timeout=1500)
                    except Exception:
                        pass
                    try:
                        await target.click(timeout=2000)
                    except Exception:
                        pass
                    try:
                        await target.fill("")
                    except Exception:
                        pass
                    try:
                        await target.fill(value, timeout=3000)
                        await _human_pause(200, 450)
                        return True
                    except Exception as exc:
                        last_err = f"{type(exc).__name__}: {exc}"
                        try:
                            await target.press("Control+A", timeout=1200)
                            await target.press("Backspace", timeout=1200)
                            await target.type(value, delay=random.randint(40, 90), timeout=4000)
                            await _human_pause(200, 450)
                            return True
                        except Exception:
                            continue
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                continue
    if last_err:
        _flow_log(f"[鐠嬪啳鐦痌[{field_tag}] 鏉堟挸鍙嗘径杈Е: {last_err}")
    return False


async def _debug_selector_counts(page, selectors: List[str], tag: str) -> None:
    rows = []
    for ctx_name, ctx in _iter_contexts(page):
        for selector in selectors:
            try:
                count = await ctx.locator(selector).count()
                if count > 0:
                    rows.append(f"{ctx_name} | {selector} | count={count}")
            except Exception:
                continue
    if rows:
        _flow_log(f"[鐠嬪啳鐦痌[{tag}] 闁瀚ㄩ崳銊ユ嚒娑擃厼顩ф稉?")
        for row in rows:
            _flow_log(f"[鐠嬪啳鐦痌[{tag}] {row}")


async def _goto_with_fallback(page, url: str, timeout_ms: int) -> None:
    await goto_with_fallback(page, url, timeout_ms)


async def _setup_resource_blocking(page) -> None:
    blocked_types = {"image", "media", "font"}

    async def _handle_route(route):
        if route.request.resource_type in blocked_types:
            try:
                await route.abort()
            except Exception:
                pass
        else:
            try:
                await route.continue_()
            except Exception:
                pass

    try:
        await setup_resource_blocking(page, _handle_route)
    except Exception:
        pass


async def _detect_blocked(page) -> bool:
    try:
        current_url = page.url or ""
        if "/errors/validateCaptcha" in current_url:
            return True
        if await page.locator("#captchacharacters").count() > 0:
            return True
        title = (await page.title() or "").strip().lower()
        if "robot check" in title:
            return True
        blocked_texts = [
            "sorry, we just need to make sure you're not a robot",
            "enter the characters you see below",
            "to discuss automated access to amazon data please contact",
            "we couldn't complete your request",
        ]
        for text in blocked_texts:
            try:
                locator = page.locator(f"text={text}")
                if await locator.count() > 0:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


async def _dismiss_continue_shopping(page) -> None:
    selectors = [
        "button.a-button-text:has-text('Continue shopping')",
        "button:has-text('Continue shopping')",
    ]
    if await _wait_for_any_selector_across_contexts(page, selectors, timeout_ms=2500):
        await _click_first_visible_across_contexts(page, selectors, timeout_ms=3000)
        await _wait_for_stability(page)


async def _read_first_visible_text_across_contexts(page, selectors: List[str]) -> str:
    for _, ctx in _iter_contexts(page):
        for selector in selectors:
            try:
                locator = ctx.locator(selector)
                count = await locator.count()
                if count <= 0:
                    continue
                for i in range(count):
                    target = locator.nth(i)
                    try:
                        if not await target.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        text = (await target.text_content() or "").strip()
                    except Exception:
                        text = ""
                    if text:
                        return text
            except Exception:
                continue
    return ""


def _normalize_zip_text(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def _split_jp_zip_code(value: str) -> tuple[str, str]:
    digits = re.sub(r"[^0-9]", "", str(value or "").strip())
    if len(digits) != 7:
        raise RuntimeError(f"閺冦儲婀扮粩娆撳仏缂傛牕绻€妞ょ粯妲?7 娴ｅ秵鏆熺€涙绱濊ぐ鎾冲閸? {value!r}")
    return digits[:3], digits[3:]


async def _ensure_sellersprite_logged_in_on_first_asin(page) -> None:
    await page_ensure_sellersprite_logged_in_on_first_asin(
        page,
        config=CONFIG,
        log=_flow_log,
        selectors=SELLERSPRITE_LOGIN_SELECTORS,
        wait_for_any_selector_across_contexts=_wait_for_any_selector_across_contexts,
        click_first_visible_across_contexts=_click_first_visible_across_contexts,
        read_first_visible_text_across_contexts=_read_first_visible_text_across_contexts,
        fill_first_visible_across_contexts=_fill_first_visible_across_contexts,
        debug_selector_counts=_debug_selector_counts,
        human_pause=_human_pause,
        iter_contexts=_iter_contexts,
    )


async def _ensure_delivery_zip_on_first_open(page) -> None:
    await page_ensure_delivery_zip_on_first_open(
        page,
        config=CONFIG,
        site_code=str(CONFIG.get("site") or "").strip().upper() or "US",
        export_selectors=AMAZON_EXPORT_SELECTORS,
        resolve_delivery_zip_code=_resolve_delivery_zip_code,
        normalize_zip_text=_normalize_zip_text,
        split_jp_zip_code=_split_jp_zip_code,
        read_first_visible_text_across_contexts=_read_first_visible_text_across_contexts,
        wait_for_any_selector_across_contexts=_wait_for_any_selector_across_contexts,
        click_first_visible_across_contexts=_click_first_visible_across_contexts,
        fill_first_visible_across_contexts=_fill_first_visible_across_contexts,
        debug_selector_counts=_debug_selector_counts,
        human_pause=_human_pause,
        log=_flow_log,
    )


async def _ensure_currency_on_first_open(page) -> None:
    await page_ensure_currency_on_first_open(
        page,
        config=CONFIG,
        site_code=str(CONFIG.get("site") or "").strip().upper() or "US",
        export_selectors=AMAZON_EXPORT_SELECTORS,
        resolve_currency_code=_resolve_currency_code,
        resolve_site_base_url=_resolve_site_base_url,
        goto_with_fallback=_goto_with_fallback,
        wait_for_stability=_wait_for_stability,
        iter_contexts=_iter_contexts,
        read_first_visible_text_across_contexts=_read_first_visible_text_across_contexts,
        wait_for_any_selector_across_contexts=_wait_for_any_selector_across_contexts,
        click_first_visible_across_contexts=_click_first_visible_across_contexts,
        human_pause=_human_pause,
        log=_flow_log,
    )


async def _extract_list_price(page) -> str:
    return await page_extract_list_price(page, iter_contexts=_iter_contexts)


async def _extract_promotion_tags(page) -> str:
    return await page_extract_promotion_tags(
        page,
        site_code=str(CONFIG.get("site") or "").strip().upper() or "US",
        export_selectors=AMAZON_EXPORT_SELECTORS,
        iter_contexts=_iter_contexts,
    )


def _is_special_conversion_category(category: str) -> bool:
    return str(category or "").strip() == SPECIAL_CONVERSION_CATEGORY


def _parse_conversion_rate_text(raw_text: str) -> Tuple[str, str]:
    compact = " ".join(str(raw_text or "").split())
    if not compact:
        return "", ""
    rate_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", compact)
    period_match = re.search(r"(年|月|周|日)$", compact)
    rate_text = f"{rate_match.group(1)}%" if rate_match else ""
    period_text = period_match.group(1) if period_match else ""
    return rate_text, period_text


async def _extract_special_conversion_rate(page, category: str) -> Tuple[str, str]:
    return await page_extract_special_conversion_rate(
        page,
        category=category,
        special_category=SPECIAL_CONVERSION_CATEGORY,
        selectors=AMAZON_EXPORT_SELECTORS.get("special_conversion_rate_value", []),
        read_first_visible_text_across_contexts=_read_first_visible_text_across_contexts,
        parse_conversion_rate_text=_parse_conversion_rate_text,
    )


class ExportFlowError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# _setup_resource_blocking is defined above

async def _process_single_target(
    context,
    target: Dict[str, str],
    idx: int,
    total: int,
    *,
    list_price_csv_path: Path,
    file_write_lock: asyncio.Lock,
    page_holder: Dict[str, Any],
    block_images: bool,
    keep_page_on_error: bool,
) -> Dict[str, str]:
    return await page_process_single_target(
        context,
        target,
        idx,
        total,
        list_price_csv_path=list_price_csv_path,
        file_write_lock=file_write_lock,
        page_holder=page_holder,
        block_images=block_images,
        keep_page_on_error=keep_page_on_error,
        config=CONFIG,
        site_code=str(CONFIG.get("site") or "").strip().upper(),
        export_selectors=AMAZON_EXPORT_SELECTORS,
        sellersprite_login_selectors=SELLERSPRITE_LOGIN_SELECTORS,
        special_category=SPECIAL_CONVERSION_CATEGORY,
        goto_with_fallback=_goto_with_fallback,
        setup_resource_blocking=_setup_resource_blocking,
        wait_for_stability=_wait_for_stability,
        human_pause=_human_pause,
        random_mouse_move=_random_mouse_move,
        random_scroll=_random_scroll,
        dismiss_continue_shopping=_dismiss_continue_shopping,
        detect_blocked=_detect_blocked,
        append_pricing_flags_row=_append_pricing_flags_row,
        upsert_product_status=_upsert_product_status,
        now_text=_now_text,
        sleep_ms=_sleep_ms,
        flow_log=_flow_log,
        safe_token=_safe_token,
        extract_list_price_fn=_extract_list_price,
        extract_promotion_tags_fn=_extract_promotion_tags,
        extract_special_conversion_rate_fn=_extract_special_conversion_rate,
    )


def _resolve_cdp_endpoint() -> str:
    return (
        str(os.getenv("CDP_URL") or "").strip()
        or str(os.getenv("CDP_ENDPOINT") or "").strip()
        or str(getattr(core_config, "CDP_ENDPOINT", "")).strip()
        or "http://127.0.0.1:9222"
    )


def _get_cdp_host_port(cdp_endpoint: str) -> tuple[str, int]:
    parsed = urlparse(cdp_endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    return host, port


def _wait_for_cdp_ready(cdp_endpoint: str, timeout_sec: int) -> bool:
    host, port = _get_cdp_host_port(cdp_endpoint)
    deadline = time.time() + max(1, int(timeout_sec))
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _find_chrome_path() -> str | None:
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidates.append(os.path.join(local_appdata, "Google", "Chrome", "Application", "chrome.exe"))
        commands = ("chrome.exe", "chrome")
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        commands = ("google-chrome", "chromium")
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
        commands = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
    for path in candidates:
        if os.path.exists(path):
            return path
    for cmd in commands:
        found = shutil.which(cmd)
        if found:
            return found
    return None


def _start_cdp_browser(cdp_endpoint: str) -> subprocess.Popen | None:
    chrome_path = _find_chrome_path()
    if not chrome_path:
        return None
    host, port = _get_cdp_host_port(cdp_endpoint)
    user_data_dir = (
        str(getattr(core_config, "CHROME_USER_DATA_DIR", "")).strip()
        or str(Path(__file__).resolve().parents[3] / "web" / "shared" / "chrome-user-data")
    )
    os.makedirs(user_data_dir, exist_ok=True)
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
    ]
    if host:
        args.append(f"--remote-debugging-address={host}")
    try:
        return subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None


async def run_product_details_pipeline(context, id_filter: str = "") -> None:
    _apply_db_name_from_config()
    targets = _load_targets(id_filter)
    if not targets:
        raise SystemExit("No targets found from today's DB rows (dim_bi_amazon_item.product_url).")

    export_base_dir = _ensure_export_dir(CONFIG["export_dir"])
    site_dir = _safe_dir_name(str(CONFIG.get("site") or "").strip().upper() or "US", "US")
    category_dir = _resolve_category_dir_name(targets)
    export_dir = export_base_dir / time.strftime("%Y-%m-%d") / site_dir / category_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    list_price_csv_path = _resolve_list_price_csv_path(export_dir)
    _ensure_pricing_flags_file(list_price_csv_path)

    today_str = time.strftime("%Y-%m-%d")
    already_priced_asins = set()
    try:
        with list_price_csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("date") == today_str and row.get("asin"):
                    already_priced_asins.add(str(row["asin"]).strip().upper())
    except Exception:
        pass

    succeeded_asins = _load_success_asins_from_status()
    succeeded_asins.update(already_priced_asins)

    if succeeded_asins:
        original_count = len(targets)
        targets = [
            item for item in targets if str(item.get("asin") or "").strip().upper() not in succeeded_asins
        ]
        skipped = original_count - len(targets)
        if skipped > 0:
            _flow_log(f"[Phase 0] 断点续跑: 跳过已成功 ASIN {skipped} 个")
    if not targets:
        _flow_log("[Phase 0] 所有目标已成功，无需继续执行")
        return

    concurrent_tabs = max(1, int(CONFIG.get("concurrent_tabs", 3)))
    block_images = bool(CONFIG.get("block_images", True))
    keep_page_on_error = (os.getenv("AMAZON_KEEP_OPEN_ON_ERROR", "0") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    file_write_lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrent_tabs)
    init_page = await context.new_page()
    await configure_async_page(init_page, timeout_ms=CONFIG["page_timeout_ms"])
    init_ok = False
    try:
        _flow_log(f"[Phase 1] 串行初始化: 设置邮编 + 卖家精灵登录 + 设置货币 (targets={len(targets)})")
        first_url = targets[0].get("url", "")
        if first_url:
            await _goto_with_fallback(init_page, first_url, CONFIG["page_timeout_ms"])
            await _wait_for_stability(init_page)
            await _ensure_delivery_zip_on_first_open(init_page)
            await _ensure_sellersprite_logged_in_on_first_asin(init_page)
            await _ensure_currency_on_first_open(init_page)
        _flow_log("[Phase 1] 初始化完成")
        init_ok = True
    finally:
        try:
            if not init_page.is_closed() and not (keep_page_on_error and not init_ok):
                await init_page.close()
            elif keep_page_on_error and not init_ok:
                _flow_log("[Phase 1] 初始化失败，保留页面用于排查")
        except Exception:
            pass

    batch_size = max(1, int(CONFIG.get("batch_size", 12)))
    blocked_streak_limit = max(1, int(CONFIG.get("site_blocked_streak_limit", 3)))
    site_cooldown_sec = max(1, int(CONFIG.get("site_cooldown_sec", 1800)))
    total_batches = (len(targets) + batch_size - 1) // batch_size
    _flow_log(
        f"[Phase 2] 开始批次处理: {len(targets)} 个 ASIN, 并发数={concurrent_tabs}, "
        f"batch_size={batch_size}, batches={total_batches}"
    )
    start_ts = time.time()
    blocked_streak = 0

    async def _worker(idx: int, target: Dict[str, str]) -> Dict[str, str]:
        async with sem:
            holder = {"page": None}
            try:
                return await _process_single_target(
                    context,
                    target,
                    idx,
                    len(targets),
                    list_price_csv_path=list_price_csv_path,
                    file_write_lock=file_write_lock,
                    page_holder=holder,
                    block_images=block_images,
                    keep_page_on_error=keep_page_on_error,
                )
            finally:
                page = holder.get("page")
                if page is not None and not page.is_closed():
                    if not keep_page_on_error:
                        try:
                            await page.close()
                        except Exception:
                            pass

    for batch_no, start_idx in enumerate(range(0, len(targets), batch_size), start=1):
        batch_targets = targets[start_idx : start_idx + batch_size]
        _flow_log(
            f"[Phase 2] 批次 {batch_no}/{total_batches} 开始: {len(batch_targets)} 个 ASIN"
        )
        tasks = []
        for offset, target in enumerate(batch_targets, start=1):
            idx = start_idx + offset
            tasks.append(asyncio.create_task(_worker(idx, target), name=f"asin-{idx}"))
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for result in results:
            if result.get("status") == "blocked":
                blocked_streak += 1
            else:
                blocked_streak = 0
            if blocked_streak >= blocked_streak_limit:
                _flow_log(
                    f"[Phase 2][熔断] 连续触发 blocked 达到 {blocked_streak_limit} 次，"
                    f"当前站点暂停 {site_cooldown_sec}s 后终止本轮"
                )
                await asyncio.sleep(site_cooldown_sec)
                raise RuntimeError("site blocked circuit breaker triggered")

        if batch_no < total_batches:
            rest_sec = _random_sec(CONFIG.get("batch_rest_sec"), (180, 420))
            _flow_log(f"[Phase 2] 批次 {batch_no}/{total_batches} 完成，休息 {rest_sec}s")
            await asyncio.sleep(rest_sec)

    elapsed = time.time() - start_ts
    _flow_log(f"[Phase 2] 并发处理完成, 耗时 {elapsed:.1f}s")
    pricing_rows = _load_pricing_flags_rows(list_price_csv_path)
    affected = _update_list_price_to_db(pricing_rows)
    _flow_log(
        f"[Phase 3] 站点数据库批量更新完成: csv_rows={len(pricing_rows)}, affected={affected}"
    )


async def _run_single_site_async(context, id_filter: str = "") -> None:
    await run_product_details_pipeline(context, id_filter=id_filter)

async def main_async() -> None:
    args = _parse_args()
    _apply_db_name_from_config()
    
    cdp_endpoint = _resolve_cdp_endpoint()
    auto_started_browser = None
    cdp_timeout = int(getattr(core_config, "CDP_TIMEOUT_SEC", 10) or 10)
    cdp_start_timeout = int(getattr(core_config, "CDP_START_TIMEOUT_SEC", 15) or 15)
    auto_start_cdp = bool(getattr(core_config, "AUTO_START_CDP", True))

    _flow_log(f"[Phase 0] 连接 CDP: {cdp_endpoint}")
    if not _wait_for_cdp_ready(cdp_endpoint, cdp_timeout):
        if auto_start_cdp:
            _flow_log("[Phase 0] CDP 不可用，尝试自动启动浏览器")
            auto_started_browser = _start_cdp_browser(cdp_endpoint)
            if auto_started_browser and _wait_for_cdp_ready(cdp_endpoint, cdp_start_timeout):
                _flow_log("[Phase 0] 已自动启动浏览器并连接 CDP")
            else:
                raise RuntimeError(f"CDP endpoint unavailable: {cdp_endpoint}")
        else:
            raise RuntimeError(f"CDP endpoint unavailable: {cdp_endpoint}")

    completed_ok = False
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_endpoint)
            context = browser.contexts[0] if browser.contexts else await browser.new_context(viewport=None)

            try:
                sites_to_run = _resolve_sites_to_run(args.id)
                
                for i, site in enumerate(sites_to_run):
                    if i > 0:
                        delay_sec = random.randint(15, 30)
                        _flow_log(f"[{site}] waiting {delay_sec}s before next site to simulate human behavior...")
                        await asyncio.sleep(delay_sec)
                        
                    CONFIG["site"] = site
                    _flow_log(f"--- Starts processing site: {site} ---")
                    try:
                        await run_product_details_pipeline(context, args.id)
                    except SystemExit as exc:
                        _flow_log(f"[{site}] gracefully skipped: {exc}")
                    except Exception as exc:
                        _flow_log(f"[{site}] run failed: {exc}")
            finally:
                await browser.close()
        completed_ok = True
    finally:
        if auto_started_browser and completed_ok:
            _flow_log("[Phase 4] 自动启动的浏览器已完成任务，准备关闭")
            try:
                auto_started_browser.terminate()
                auto_started_browser.wait(timeout=10)
            except Exception:
                try:
                    auto_started_browser.kill()
                except Exception:
                    pass
        elif auto_started_browser and not completed_ok:
            _flow_log("[Phase 4] 任务未完成，保留自动启动的浏览器用于排查")

def main() -> None:
    try:
        asyncio.run(main_async())
    except Exception as exc:
        raise RuntimeError(f"amazon_product_details run failed: {exc}")

if __name__ == "__main__":
    main()

