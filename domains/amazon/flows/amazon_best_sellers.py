#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scrape product data from Amazon page:
Best Sellers in Reciprocating Saw Blades.

Usage:
    python -m domains.amazon.flows.amazon_best_sellers
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from core.settings import load_env_files
from core.browser import (
    BrowserDriver,
    human_pause,
    random_mouse_move,
    wait_for_any_selector,
    wait_for_stability,
)
import asyncio
from ..config.config import build_amazon_config
from ..repositories.amazon_item_repo import upsert_best_seller_rows
from ..services.best_sellers_page_service import collect_rows_for_page as page_collect_rows_for_page
from ..services.best_sellers_page_service import ensure_currency_on_first_page as page_ensure_currency_on_first_page
from ..services.page_service import close_cdp_browser_if_needed, configure_sync_page
from .amazon_extension_login import ensure_sellersprite_logged_in
import yaml


def _block_unnecessary_resources(route):
    if route.request.resource_type in ["image", "media", "font"]:
        route.abort()
    else:
        route.continue_()


def _load_selectors() -> Dict[str, Any]:
    selectors_path = Path(__file__).resolve().parents[1] / "selectors" / "amazon_best_sellers_selectors.yaml"
    if not selectors_path.exists():
        raise RuntimeError(f"Missing selectors YAML: {selectors_path}")
    with selectors_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid selectors YAML format: {selectors_path}")
    return data


def _load_flow_env() -> None:
    explicit = os.getenv("AMAZON_ENV_FILE", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(__file__).resolve().parents[3] / ".env")
    candidates.append(Path.cwd() / ".env")
    load_env_files(candidates, override=False)


_load_flow_env()


AMAZON_BEST_SELLERS_BLADES_SELECTORS = _load_selectors()

def _load_target_urls() -> Dict[str, Dict[str, List[str]]]:
    yaml_path = Path(__file__).resolve().parents[1] / "selectors" / "amazon_target_urls.yaml"
    if not yaml_path.exists():
        return {}
    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data

SITE_TARGET_CONFIGS = _load_target_urls()

def _get_urls_for_site(site: str, id_filter: str = "") -> List[str]:
    if not SITE_TARGET_CONFIGS:
        return []
    
    urls = []
    id_filter_str = str(id_filter or "").strip()
    is_all = id_filter_str.upper() == "ALL"
    allowed = {c.strip().lower() for c in id_filter_str.split(",")} if id_filter_str and not is_all else set()
    
    for cat_id, cat_val in SITE_TARGET_CONFIGS.items():
        if not isinstance(cat_val, dict):
            continue
            
        cat_site = str(cat_val.get("site", "")).strip().upper()
        if cat_site != site.strip().upper():
            continue
            
        cat_name = str(cat_val.get("name", ""))
        curr_urls = cat_val.get("urls", [])
        
        if is_all or not id_filter_str or cat_id.strip().lower() in allowed or cat_name.strip().lower() in allowed:
            urls.extend(curr_urls)
            
    return [u for u in urls if u]


def _get_category_for_target_url(site: str, target_url: str) -> str:
    site_code = str(site or "").strip().upper()
    target = _clean_text(target_url)
    if not site_code or not target or not SITE_TARGET_CONFIGS:
        return ""

    for _, cat_val in SITE_TARGET_CONFIGS.items():
        if not isinstance(cat_val, dict):
            continue
        cat_site = str(cat_val.get("site", "")).strip().upper()
        if cat_site != site_code:
            continue
        cat_name = _clean_text(cat_val.get("name", ""))
        urls = cat_val.get("urls", [])
        for url in urls if isinstance(urls, list) else []:
            if _clean_text(url) == target:
                return cat_name
    return ""

SITE_HOST_MARKERS = {
    "US": ("amazon.com",),
    "DE": ("amazon.de",),
    "UK": ("amazon.co.uk",),
    "GB": ("amazon.co.uk",),
    "JP": ("amazon.co.jp",),
}
SITE_RUN_ORDER = ["US", "UK", "DE", "JP"]

CONFIG = build_amazon_config(
    {
        "target_url": "",
        "target_urls": [],
        "output_dir": str(Path(__file__).resolve().parents[3] / "domains" / "amazon" / "files" / "best_sellers"),
        "output_prefix": "best_sellers_blades",
        "page_timeout_ms": 45000,
        "target_card_count": 50,
        "scroll_max_rounds": 30,
        "warmup_pause_ms": (2000, 5000),
        "scroll_gap_ms": (700, 1600),
        "card_hydration_timeout_ms": 12000,
        "card_hydration_poll_ms": 500,
        "card_hydration_min_ready_ratio": 0.9,
        "traffic_block_timeout_ms": 15000,
        "traffic_block_poll_ms": 500,
        "traffic_block_min_ready_ratio": 0.9,
        "activate_card_pause_ms": (350, 900),
        "persist_db": True,
        "persist_db_fail_fast": False,
        "save_page_html": False,
        "close_browser_on_done": True,
        "sellersprite_login_on_first_page": True,
        "set_currency_on_first_page": True,
    }
)


def _apply_runtime_overrides() -> None:
    persist_db_env = str(os.getenv("AMAZON_BEST_SELLERS_PERSIST_DB", "")).strip().lower()
    if persist_db_env:
        CONFIG["persist_db"] = persist_db_env in {"1", "true", "yes", "y", "on"}

    site_env = str(os.getenv("AMAZON_BEST_SELLERS_SITE", "")).strip().upper()
    if site_env:
        CONFIG["site"] = site_env

    urls_env = str(os.getenv("AMAZON_BEST_SELLERS_TARGET_URLS", "")).strip()
    if urls_env:
        CONFIG["target_urls"] = [u.strip() for u in urls_env.splitlines() if u.strip()]

    target_url_env = str(os.getenv("AMAZON_BEST_SELLERS_TARGET_URL", "")).strip()
    if target_url_env:
        CONFIG["target_url"] = target_url_env

    output_prefix_env = str(os.getenv("AMAZON_BEST_SELLERS_OUTPUT_PREFIX", "")).strip()
    if output_prefix_env:
        CONFIG["output_prefix"] = output_prefix_env


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run amazon best sellers flow")
    parser.add_argument("--id", default="", help="Comma separated category IDs or ALL, e.g. '1, 2' or 'ALL'")
    return parser.parse_args()


def _validate_target_urls_for_site(site: str, urls: List[str]) -> None:
    expected_markers = SITE_HOST_MARKERS.get(site, ())
    if not expected_markers:
        return
    invalid = []
    for url in urls:
        host = (urlparse(url).netloc or "").lower()
        if not any(marker in host for marker in expected_markers):
            invalid.append(url)
    if invalid:
        raise RuntimeError(
            f"站点 {site} 的榜单链接与域名不匹配: {invalid}"
        )


_apply_runtime_overrides()


def _log(step: str, message: str) -> None:
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] [{step}] {message}")


def _resolve_site_base_url() -> str:
    site = _clean_text(CONFIG.get("site", "US")).upper() or "US"
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
    site = _clean_text(CONFIG.get("site", "US")).upper() or "US"
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


def _wait_for_any_selector_sync(page, selectors: List[str], timeout_ms: int = 8000, visible_only: bool = True) -> bool:
    deadline = time.time() + max(timeout_ms, 1) / 1000.0
    while time.time() < deadline:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
                if count <= 0:
                    continue
                if not visible_only:
                    return True
                for i in range(count):
                    try:
                        if locator.nth(i).is_visible():
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        page.wait_for_timeout(200)
    return False


def _click_first_visible_sync(page, selectors: List[str], timeout_ms: int = 5000) -> bool:
    if not _wait_for_any_selector_sync(page, selectors, timeout_ms=timeout_ms, visible_only=True):
        return False
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
            if count <= 0:
                continue
            for i in range(count):
                target = locator.nth(i)
                try:
                    if not target.is_visible():
                        continue
                except Exception:
                    continue
                try:
                    target.click()
                except Exception:
                    try:
                        target.click(force=True)
                    except Exception:
                        continue
                return True
        except Exception:
            continue
    return False


def _read_first_text_sync(page, selectors: List[str]) -> str:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
            if count <= 0:
                continue
            for i in range(count):
                target = locator.nth(i)
                try:
                    text = _clean_text(target.text_content() or "")
                except Exception:
                    text = ""
                if text:
                    return text
        except Exception:
            continue
    return ""


def _ensure_currency_on_first_page(page, selectors: Dict[str, Any], site_code: str) -> None:
    return page_ensure_currency_on_first_page(
        page,
        selectors,
        site_code,
        config=CONFIG,
        log=_log,
        resolve_currency_code=_resolve_currency_code,
        resolve_site_base_url=_resolve_site_base_url,
        read_first_text_sync=_read_first_text_sync,
        click_first_visible_sync=_click_first_visible_sync,
        wait_for_any_selector_sync=_wait_for_any_selector_sync,
        wait_for_stability=wait_for_stability,
        human_pause=human_pause,
    )


def _count_cards(page, selectors: Dict[str, List[str]]) -> int:
    return int(page.evaluate(
        r"""
        ({ cardSelectors }) => {
          for (const sel of cardSelectors) {
            const count = document.querySelectorAll(sel).length;
            if (count > 0) return count;
          }
          return 0;
        }
        """,
        {"cardSelectors": selectors["card_roots"]},
    ) or 0)


def _scroll_last_card_into_view(page, selectors: Dict[str, List[str]]) -> None:
    page.evaluate(
        r"""
        ({ cardSelectors }) => {
          for (const sel of cardSelectors) {
            const nodes = document.querySelectorAll(sel);
            if (nodes.length > 0) {
              const last = nodes[nodes.length - 1];
              if (last && typeof last.scrollIntoView === "function") {
                last.scrollIntoView({ behavior: "auto", block: "end" });
              }
              return;
            }
          }
        }
        """,
        {"cardSelectors": selectors["card_roots"]},
    )


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _search_first(patterns: List[str], text: str) -> str:
    for pattern in patterns:
        matched = re.search(pattern, text, flags=re.I)
        if matched:
            return _clean_text(matched.group(1))
    return ""


def _extract_metrics_from_text(text: str) -> Dict[str, str]:
    compact = _clean_text(text)

    conversion_rate = _search_first(
        [
            r"综合转化率\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?%?)",
            r"conversion\s*rate\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?%?)",
        ],
        compact,
    )

    conversion_rate_period = _search_first(
        [
            r"综合转化率\s*[:：]?\s*[0-9]+(?:\.[0-9]+)?%?\s*([年月周日])",
            r"conversion\s*rate\s*[:：]?\s*[0-9]+(?:\.[0-9]+)?%?\s*(year|month|week|day)",
        ],
        compact,
    )

    organic_traffic_score_7d = ""
    ad_traffic_score_7d = ""

    # Parse two-part traffic scores near the 7-day traffic label.
    # Some pages render as "465(67%)239(33%)" with no whitespace between parts.
    traffic_segment = compact
    label_match = re.search(r"7\s*天流量得分|7\s*day\s*traffic\s*score", compact, flags=re.I)
    if label_match:
        traffic_segment = compact[label_match.start() : label_match.start() + 160]

    flow_pair = re.search(
        r"(\d[\d,]*)\s*\((\d{1,3}%?)\)\s*[,，;|/]?\s*(\d[\d,]*)\s*\((\d{1,3}%?)\)",
        traffic_segment,
    )
    if flow_pair:
        organic_traffic_score_7d = _clean_text(flow_pair.group(1))
        ad_traffic_score_7d = _clean_text(flow_pair.group(3))

    organic_search_terms = _search_first(
        [
            r"自然搜索词\s*[:：]?\s*([0-9][0-9,]*)",
            r"organic\s*search\s*terms?\s*[:：]?\s*([0-9][0-9,]*)",
        ],
        compact,
    )

    ad_traffic_terms = _search_first(
        [
            r"广告流量词\s*[:：]?\s*([0-9][0-9,]*)",
            r"ad\s*traffic\s*terms?\s*[:：]?\s*([0-9][0-9,]*)",
        ],
        compact,
    )

    all_traffic_terms = _search_first(
        [
            r"全部流量词\s*[:：]?\s*([0-9][0-9,]*)",
            r"all\s*traffic\s*terms?\s*[:：]?\s*([0-9][0-9,]*)",
        ],
        compact,
    )

    if not all_traffic_terms:
        organic_terms_num = _to_int_or_none(organic_search_terms)
        ad_terms_num = _to_int_or_none(ad_traffic_terms)
        if organic_terms_num is not None or ad_terms_num is not None:
            all_traffic_terms = str((organic_terms_num or 0) + (ad_terms_num or 0))

    search_recommend_terms = _search_first(
        [
            r"搜索推荐词\s*[:：]?\s*([0-9][0-9,]*)",
            r"search\s*recommend(?:ed)?\s*terms?\s*[:：]?\s*([0-9][0-9,]*)",
        ],
        compact,
    )

    return {
        "organic_traffic_score_7d": organic_traffic_score_7d,
        "ad_traffic_score_7d": ad_traffic_score_7d,
        "conversion_rate": conversion_rate,
        "conversion_rate_period": conversion_rate_period,
        "organic_search_terms": organic_search_terms,
        "ad_traffic_terms": ad_traffic_terms,
        "all_traffic_terms": all_traffic_terms,
        "search_recommend_terms": search_recommend_terms,
    }


def _parse_rank(rank_badge: str) -> int:
    text = _clean_text(rank_badge)
    matched = re.search(r"#\s*(\d+)", text)
    if matched:
        return int(matched.group(1))
    raise ValueError(f"rank badge parse failed: {text!r}")


def _ensure_output_dir(path: str) -> Path:
    output_dir = Path(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _safe_file_part(value: Any, fallback: str) -> str:
    text = _clean_text(value)
    if not text:
        text = fallback
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._")
    return text or fallback


def _save_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "rank",
        "asin",
        "price",
        "organic_traffic_score_7d",
        "ad_traffic_score_7d",
        "conversion_rate",
        "conversion_rate_period",
        "organic_search_terms",
        "ad_traffic_terms",
        "all_traffic_terms",
        "search_recommend_terms",
    ]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _extract_cards(page, selectors: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    return page.evaluate(
        r"""
        ({ cardSelectors, rankSelectors }) => {
          // Prefer the first selector that can directly return the big card containers.
          let roots = [];
          for (const sel of cardSelectors) {
            const matched = Array.from(document.querySelectorAll(sel));
            if (matched.length > 0) {
              roots = matched;
              break;
            }
          }

          // Fallback: from product links back to nearest known card root.
          if (roots.length === 0) {
            const seen = new Set();
            for (const link of document.querySelectorAll("a[href*='/dp/']")) {
              const card = link.closest("div#gridItemRoot, div.zg-grid-general-faceout, div.p13n-sc-uncoverable-faceout, li, article");
              if (card && !seen.has(card)) {
                seen.add(card);
                roots.push(card);
              }
            }
          }

          const pickText = (root, selectorList) => {
            for (const sel of selectorList) {
              const el = root.querySelector(sel);
              if (!el) continue;
              const text = (el.textContent || "").trim();
              if (text) return text;
            }
            return "";
          };

          const normalize = (text) => (text || "").replace(/\u00A0/g, " ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();

          const extractPrice = (root, text) => {
            const priceSelectors = [
              "[class*='p13n-sc-price']",
              "span.a-price span.a-offscreen",
              "span.a-color-price span.a-offscreen",
              "span.a-color-price",
            ];
            for (const sel of priceSelectors) {
              const el = root.querySelector(sel);
              if (!el) continue;
              const value = normalize(el.textContent || "");
              if (value) return value;
            }
            const textMatch = text.match(/(?:[$£€¥￥])\s?[0-9][0-9,]*(?:\.[0-9]{1,2})?/);
            return textMatch ? normalize(textMatch[0]) : "";
          };

          const rows = [];
          for (let i = 0; i < roots.length; i += 1) {
            const root = roots[i];
            if (!root) continue;

            const text = normalize(root.innerText || root.textContent || "");

            if (!/ASIN[:：]/i.test(text)) {
              continue;
            }

            const rankBadge = pickText(root, rankSelectors);
            const asinTextMatch = text.match(/ASIN[:：]\s*([A-Z0-9]{10})/i);
            const priceText = extractPrice(root, text);

            rows.push({
              index: i + 1,
              rank_badge: normalize(rankBadge),
              asin_text: asinTextMatch ? asinTextMatch[1].toUpperCase() : "",
              price_text: priceText,
              card_text: text,
            });
          }
          return rows;
        }
        """,
        {
            "cardSelectors": selectors["card_roots"],
            "rankSelectors": selectors["rank_badge"],
        },
    )


def _wait_for_cards_hydrated(page, selectors: Dict[str, List[str]], timeout_ms: int, poll_ms: int, min_ready_ratio: float) -> bool:
    markers = [m for m in selectors.get("card_data_ready_markers", []) if m]
    if not markers:
        return True

    start_ts = time.time()
    timeout_ms = max(0, int(timeout_ms))
    poll_ms = max(100, int(poll_ms))
    min_ready_ratio = max(0.0, min(1.0, float(min_ready_ratio)))

    while (time.time() - start_ts) * 1000 <= timeout_ms:
        state = page.evaluate(
            r"""
            ({ cardSelectors, readinessMarkers }) => {
              let roots = [];
              for (const sel of cardSelectors) {
                const matched = Array.from(document.querySelectorAll(sel));
                if (matched.length > 0) {
                  roots = matched;
                  break;
                }
              }
              if (roots.length === 0) {
                return {total: 0, ready: 0};
              }

              const normalize = (text) => (text || "").replace(/\u00A0/g, " ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();

              let ready = 0;
              for (const root of roots) {
                const text = normalize(root.innerText || root.textContent || "");
                const hasProductBase = /ASIN[:：]\s*[A-Z0-9]{10}/i.test(text) || !!root.querySelector("a[href*='/dp/']");
                const hasHydrationData = readinessMarkers.some((marker) => text.includes(marker));
                if (hasProductBase && hasHydrationData) {
                  ready += 1;
                }
              }

              return {total: roots.length, ready};
            }
            """,
            {
                "cardSelectors": selectors["card_roots"],
                "readinessMarkers": markers,
            },
        )

        total = int(state.get("total") or 0)
        ready = int(state.get("ready") or 0)
        ratio = (ready / total) if total > 0 else 0.0
        elapsed_ms = int((time.time() - start_ts) * 1000)
        _log("HYDRATE", f"ready={ready}/{total} ({ratio:.0%}), elapsed={elapsed_ms}ms")
        if total > 0 and ratio >= min_ready_ratio:
            _log("HYDRATE", "card data hydration reached threshold")
            return True

        page.wait_for_timeout(poll_ms)

    _log("HYDRATE", "timeout; continue with current DOM snapshot")
    return False


def _activate_cards_for_extension(page, selectors: Dict[str, List[str]], pause_ms: tuple[int, int]) -> int:
    roots = page.evaluate(
        r"""
        ({ cardSelectors }) => {
          for (const sel of cardSelectors) {
            const matched = Array.from(document.querySelectorAll(sel));
            if (matched.length > 0) {
              return matched.length;
            }
          }
          return 0;
        }
        """,
        {"cardSelectors": selectors["card_roots"]},
    )
    total = int(roots or 0)
    if total <= 0:
        _log("ACTIVATE", "no cards found to activate")
        return 0

    low, high = pause_ms
    low = int(min(low, high))
    high = int(max(low, high))

    _log("ACTIVATE", f"start activating {total} cards by scrollIntoView")
    for idx in range(total):
        page.evaluate(
            r"""
            ({ cardSelectors, index }) => {
              for (const sel of cardSelectors) {
                const nodes = document.querySelectorAll(sel);
                if (nodes.length > index) {
                  const el = nodes[index];
                  if (el && typeof el.scrollIntoView === "function") {
                    el.scrollIntoView({ behavior: "auto", block: "center" });
                  }
                  return true;
                }
              }
              return false;
            }
            """,
            {"cardSelectors": selectors["card_roots"], "index": idx},
        )

        # Occasional micro-interactions to avoid repetitive movement patterns.
        if random.random() < 0.22:
            random_mouse_move(page, times=1)
            page.mouse.wheel(0, random.randint(-160, 160))

        human_pause(low, high)
        if idx == 0 or (idx + 1) % 10 == 0 or idx + 1 == total:
            _log("ACTIVATE", f"activated {idx + 1}/{total}")

    page.mouse.wheel(0, -99999)
    human_pause(200, 350)
    _log("ACTIVATE", "activation pass finished")
    return total




def _wait_for_traffic_score_block(page, selectors: Dict[str, List[str]], timeout_ms: int, poll_ms: int, min_ready_ratio: float) -> bool:
    start_ts = time.time()
    timeout_ms = max(0, int(timeout_ms))
    poll_ms = max(100, int(poll_ms))
    min_ready_ratio = max(0.0, min(1.0, float(min_ready_ratio)))

    while (time.time() - start_ts) * 1000 <= timeout_ms:
        state = page.evaluate(
            r"""
            ({ cardSelectors }) => {
              let roots = [];
              for (const sel of cardSelectors) {
                const matched = Array.from(document.querySelectorAll(sel));
                if (matched.length > 0) {
                  roots = matched;
                  break;
                }
              }
              if (roots.length === 0) {
                return {total: 0, ready: 0};
              }

              const normalize = (text) => (text || "").replace(/\u00A0/g, " ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();

              let ready = 0;
              for (const root of roots) {
                const text = normalize(root.innerText || root.textContent || "");
                const hasProductBase = /ASIN[:：]\s*[A-Z0-9]{10}/i.test(text) || !!root.querySelector("a[href*='/dp/']");
                const hasTrafficBlock = text.includes("7天流量得分") || /7\s*day\s*traffic\s*score/i.test(text);
                if (hasProductBase && hasTrafficBlock) {
                  ready += 1;
                }
              }

              return {total: roots.length, ready};
            }
            """,
            {"cardSelectors": selectors["card_roots"]},
        )

        total = int(state.get("total") or 0)
        ready = int(state.get("ready") or 0)
        ratio = (ready / total) if total > 0 else 0.0
        elapsed_ms = int((time.time() - start_ts) * 1000)
        _log("TRAFFIC", f"7-day traffic block ready={ready}/{total} ({ratio:.0%}), elapsed={elapsed_ms}ms")

        if total > 0 and ratio >= min_ready_ratio:
            _log("TRAFFIC", "7-day traffic block reached threshold")
            return True

        page.wait_for_timeout(poll_ms)

    _log("TRAFFIC", "timeout; continue with current page state")
    return False


def _build_target_urls() -> List[str]:
    site = _clean_text(CONFIG.get("site", "US")).upper() or "US"
    configured = CONFIG.get("target_urls")
    if isinstance(configured, list) and configured:
        urls = [_clean_text(u) for u in configured if _clean_text(u)]
        deduped = []
        seen = set()
        for u in urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        _validate_target_urls_for_site(site, deduped)
        return deduped

    site_urls = SITE_TARGET_URLS.get(site, [])
    if site_urls:
        deduped = []
        seen = set()
        for u in site_urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        _validate_target_urls_for_site(site, deduped)
        return deduped

    page1 = _clean_text(CONFIG.get("target_url", ""))
    if not page1:
        return []

    if re.search(r"([?&])pg=\d+", page1):
        page2 = re.sub(r"([?&])pg=\d+", r"\1pg=2", page1)
    else:
        sep = "&" if "?" in page1 else "?"
        page2 = f"{page1}{sep}pg=2"

    urls = [page1, page2]
    deduped = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    _validate_target_urls_for_site(site, deduped)
    return deduped


def _completion_selectors_for_url(selectors: Dict[str, List[str]], target_url: str) -> List[str]:
    base = [x for x in selectors.get("completion_rank_marker", []) if _clean_text(x)]
    # Page-specific end markers: pg=1 -> #50, pg=2 -> #100
    if re.search(r"([?&])pg=2(?:[&#]|$)", target_url):
        mapped = []
        for sel in base:
            mapped.append(sel.replace("#50", "#100"))
        if not mapped:
            mapped = ["span.zg-bdg-text:has-text('#100')"]
        return mapped
    if base:
        return base
    return ["span.zg-bdg-text:has-text('#50')"]


def _fallback_completion_selectors_for_url(target_url: str) -> List[str]:
    # Page 2 may occasionally render only up to #99 (missing #100).
    if re.search(r"([?&])pg=2(?:[&#]|$)", target_url):
        return [
            "span.zg-bdg-text:has-text('#99')",
            "span[class*='zg-badge-text']:has-text('#99')",
            "span.a-badge-text:has-text('#99')",
        ]
    return []


def _goto_with_retry(page, target_url: str, prefix: str) -> None:
    attempts = [
        ("domcontentloaded", int(CONFIG.get("page_timeout_ms", 45000))),
        ("domcontentloaded", 65000),
        ("commit", 30000),
    ]
    last_exc = None
    for idx, (wait_until, timeout_ms) in enumerate(attempts, 1):
        try:
            _log("NAV", f"{prefix} goto attempt {idx}/{len(attempts)}: wait_until={wait_until}, timeout={timeout_ms}ms")
            page.goto(target_url, wait_until=wait_until, timeout=timeout_ms)
            return
        except Exception as exc:
            last_exc = exc
            _log("NAV", f"{prefix} goto attempt {idx} failed: {exc}")
            if idx < len(attempts):
                human_pause(1200, 2600)
    if last_exc is not None:
        raise last_exc


def _find_duplicated_ranks(rows: List[Dict[str, Any]]) -> List[int]:
    seen: set[int] = set()
    duplicated: list[int] = []
    for row in rows:
        rank = row.get("rank")
        if not isinstance(rank, int):
            continue
        if rank in seen:
            if rank not in duplicated:
                duplicated.append(rank)
            continue
        seen.add(rank)
    return duplicated




def _collect_rows_for_page(
    page,
    selectors: Dict[str, List[str]],
    target_url: str,
    page_idx: int,
    page_total: int,
) -> List[Dict[str, Any]]:
    return page_collect_rows_for_page(
        page,
        selectors,
        target_url,
        page_idx,
        page_total,
        config=CONFIG,
        log=_log,
        clean_text=_clean_text,
        get_category_for_target_url=_get_category_for_target_url,
        find_duplicated_ranks=_find_duplicated_ranks,
        completion_selectors_for_url=_completion_selectors_for_url,
        fallback_completion_selectors_for_url=_fallback_completion_selectors_for_url,
        count_cards=_count_cards,
        scroll_last_card_into_view=_scroll_last_card_into_view,
        wait_for_any_selector=wait_for_any_selector,
        wait_for_cards_hydrated=_wait_for_cards_hydrated,
        activate_cards_for_extension=_activate_cards_for_extension,
        wait_for_traffic_score_block=_wait_for_traffic_score_block,
        extract_cards=_extract_cards,
        extract_metrics_from_text=_extract_metrics_from_text,
        parse_rank=_parse_rank,
        goto_with_retry=_goto_with_retry,
    )


def _to_int_or_none(value: Any) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _to_rate_decimal_or_none(value: Any) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    text = text.replace("%", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return round(number / 100.0, 4)


def _to_price_decimal_or_none(value: Any) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    cleaned = re.sub(r"[^0-9,.\-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) in {1, 2}:
            cleaned = f"{parts[0]}.{parts[1]}"
        else:
            cleaned = "".join(parts)
    else:
        if cleaned.count(".") > 1:
            last_dot = cleaned.rfind(".")
            integer = cleaned[:last_dot].replace(".", "")
            fraction = cleaned[last_dot + 1 :]
            cleaned = f"{integer}.{fraction}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def _persist_rows_to_db(rows: List[Dict[str, Any]], run_id: str) -> int:
    db_name = _clean_text(CONFIG.get("db_name", ""))
    if db_name:
        os.environ["DB_NAME"] = db_name

    site = _clean_text(CONFIG.get("site", "US")) or "US"
    return upsert_best_seller_rows(
        rows,
        site=site,
        category_field_mapper={
            "clean_text": _clean_text,
            "to_int": _to_int_or_none,
            "to_price": _to_price_decimal_or_none,
            "to_rate": _to_rate_decimal_or_none,
        },
    )


def _close_cdp_browser_if_needed(page, driver) -> None:
    close_cdp_browser_if_needed(
        page,
        driver,
        enabled=bool(CONFIG.get("close_browser_on_done", False)),
        log=_log,
    )


def _resolve_sites_to_run(id_filter: str = "") -> List[str]:
    id_filter_str = str(id_filter or "").strip()
    is_all_ids = id_filter_str.upper() == "ALL"

    if id_filter_str and SITE_TARGET_CONFIGS:
        if is_all_ids:
            inferred_sites = {
                str(val.get("site", "")).strip().upper()
                for val in SITE_TARGET_CONFIGS.values()
                if isinstance(val, dict) and val.get("site")
            }
            if inferred_sites:
                return sorted(list(inferred_sites))
        else:
            allowed = {item.strip().lower() for item in id_filter_str.split(",")}
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

    site = str(os.getenv("AMAZON_BEST_SELLERS_SITE") or CONFIG.get("site") or "US").strip().upper() or "US"
    return [site]


def run_best_sellers_pipeline(site: str, id_filter: str = "") -> None:
    site_code = str(site or "").strip().upper()
    if not site_code:
        raise RuntimeError("empty site")

    CONFIG["site"] = site_code
    
    if not str(os.getenv("AMAZON_BEST_SELLERS_TARGET_URLS") or "").strip():
        site_urls = _get_urls_for_site(site_code, id_filter)
        if not site_urls:
            raise RuntimeError(f"No target URLs configured for site={site_code} ids={id_filter}")
        CONFIG["target_urls"] = site_urls
        CONFIG["target_url"] = site_urls[0]
    if not str(os.getenv("AMAZON_BEST_SELLERS_OUTPUT_PREFIX") or "").strip():
        CONFIG["output_prefix"] = f"best_sellers_{site_code.lower()}"

    run_started = time.time()
    completed_ok = False
    selectors = AMAZON_BEST_SELLERS_BLADES_SELECTORS
    _ensure_output_dir(CONFIG["output_dir"])
    target_urls = _build_target_urls()

    if not target_urls:
        raise RuntimeError("No target URLs configured")

    _log("NAV", f"[{site_code}] pages to crawl: {len(target_urls)}")
    run_id = time.strftime("%Y%m%d%H%M%S")
    _log("DB", f"[{site_code}] run_id={run_id}")

    driver = BrowserDriver(headless=CONFIG["headless"], use_cdp=CONFIG["use_cdp"])

    all_rows: List[Dict[str, Any]] = []
    
    # We use driver.session() which is currently blocking/sync. 
    # To properly do concurrency across multiple pages in playwright sync_api, 
    # we would need to spin up multiple threads, OR switch to async_playwright.
    # Given the extensive sync codebase in base_driver, we process sequentially for now,
    # but the resource blocking added earlier will already provide a massive speedup.
    
    with driver.session() as page:
        try:
            configure_sync_page(page, timeout_ms=CONFIG["page_timeout_ms"])
            try:
                driver.maximize_window(page)
            except Exception:
                pass

            if target_urls:
                ensure_sellersprite_logged_in(
                    page,
                    first_url=target_urls[0],
                    log=lambda msg: _log("SSLOGIN", f"[{site_code}] {msg}"),
                    enabled=bool(CONFIG.get("sellersprite_login_on_first_page", False)),
                    ready_timeout_ms=int(CONFIG.get("sellersprite_post_login_ready_timeout_ms", 60000)),
                )
                _ensure_currency_on_first_page(page, selectors, site_code)

            for idx, target_url in enumerate(target_urls, start=1):
                page_rows = _collect_rows_for_page(
                    page,
                    selectors,
                    target_url,
                    idx,
                    len(target_urls),
                )
                duplicated_ranks = _find_duplicated_ranks(page_rows)
                if duplicated_ranks:
                    raise RuntimeError(
                        f"P{idx}/{len(target_urls)} duplicated ranks detected: {duplicated_ranks}"
                    )
                all_rows.extend(page_rows)

            _log("PARSE", f"[{site_code}] all-page normalized rows: {len(all_rows)}")

            deduped: List[Dict[str, Any]] = []
            seen_keys = set()
            for row in sorted(all_rows, key=lambda x: (x.get("rank") or 9999, x.get("asin") or "")):
                key = row.get("asin") or str(row.get("rank") or "")
                key = _clean_text(key)
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped.append(row)

            _log("PARSE", f"[{site_code}] all-page deduped rows: {len(deduped)}")
            if not deduped:
                raise RuntimeError(
                    f"[{site_code}] parsed 0 rows from best sellers pages; "
                    "likely selector/profile/site rendering issue"
                )

            if CONFIG.get("persist_db", True):
                try:
                    affected = _persist_rows_to_db(deduped, run_id)
                    _log("DB", f"[{site_code}] upsert success, affected={affected}")
                except Exception as exc:
                    _log("DB", f"[{site_code}] upsert failed: {exc}")
                    if CONFIG.get("persist_db_fail_fast", False):
                        raise

            category_name = deduped[0].get("category") if deduped else ""
            safe_site = _safe_file_part(site_code, "US")
            safe_category = _safe_file_part(category_name, "uncategorized")
            output_dir = _ensure_output_dir(str(Path(CONFIG["output_dir"]) / time.strftime("%Y-%m-%d") / safe_site))
            csv_path = output_dir / f"{safe_site}-{safe_category}.csv"
            _save_csv(csv_path, deduped)
            _log("SAVE", f"[{site_code}] csv saved: {csv_path}")
            _log("DONE", f"[{site_code}] items={len(deduped)}, total_elapsed={time.time() - run_started:.1f}s")
            completed_ok = True
        finally:
            if completed_ok:
                _close_cdp_browser_if_needed(page, driver)
            else:
                _log("BROWSER", f"[{site_code}] run failed; keep browser open for debugging")


def _run_single_site(site: str) -> None:
    run_best_sellers_pipeline(site)





def main() -> None:
    args = _parse_args()
    failures: List[str] = []
    sites_to_run = _resolve_sites_to_run(args.id)
    
    for i, site in enumerate(sites_to_run):
        if i > 0:
            delay_sec = random.randint(15, 30)
            _log("START", f"[{site}] waiting {delay_sec}s before next site to simulate human behavior...")
            time.sleep(delay_sec)
            
        try:
            run_best_sellers_pipeline(site, id_filter=args.id)
        except Exception as exc:
            failures.append(f"{site}: {exc}")
            _log("ERR", f"[{site}] run failed: {exc}")
            
    if failures:
        raise RuntimeError("amazon_best_sellers multi-site run failed: " + "; ".join(failures))



if __name__ == "__main__":
    main()
