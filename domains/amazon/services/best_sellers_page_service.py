#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Page behavior service for amazon_best_sellers."""

from __future__ import annotations

import random
import re
import time
from typing import Any, Dict, List


def ensure_currency_on_first_page(
    page,
    selectors: Dict[str, Any],
    site_code: str,
    *,
    config: dict,
    log,
    resolve_currency_code,
    resolve_site_base_url,
    read_first_text_sync,
    click_first_visible_sync,
    wait_for_any_selector_sync,
    wait_for_stability,
    human_pause,
) -> None:
    if not bool(config.get("set_currency_on_first_page", True)):
        return
    if site_code == "US":
        log("CUR", f"[{site_code}] skip currency setup for US")
        return
    current_selectors = [str(x).strip() for x in selectors.get("currency_selected_option", []) if str(x).strip()]
    save_button_selectors = [str(x).strip() for x in selectors.get("currency_save_button", []) if str(x).strip()]
    jp_dropdown_selectors = [str(x).strip() for x in selectors.get("currency_dropdown_trigger_jp", []) if str(x).strip()]
    jp_option_selectors = [str(x).strip() for x in selectors.get("currency_option_jp", []) if str(x).strip()]
    if not current_selectors or not save_button_selectors:
        raise RuntimeError("货币设置选择器缺失：currency_selected_option/currency_save_button")
    currency_code = resolve_currency_code()
    currency_url = f"{resolve_site_base_url().rstrip('/')}/customer-preferences/edit?ie=UTF8&preferencesReturnUrl=%2F&ref_=topnav_lang"
    log("CUR", f"[{site_code}] open currency preferences: target={currency_code}")
    page.goto(currency_url, wait_until="domcontentloaded")
    wait_for_stability(page)
    human_pause(400, 900)
    checked_selector = f"input[name='cop'][value='{currency_code}']:checked"
    selected_ok = False
    try:
        selected_ok = page.locator(checked_selector).count() > 0
    except Exception:
        selected_ok = False
    if not selected_ok:
        current_text = read_first_text_sync(page, current_selectors).upper()
        if currency_code in current_text:
            selected_ok = True
    if selected_ok:
        log("CUR", f"[{site_code}] currency already selected: {currency_code}")
        return
    if site_code == "JP":
        if not jp_dropdown_selectors or not jp_option_selectors:
            raise RuntimeError("日本站货币设置选择器缺失：currency_dropdown_trigger_jp/currency_option_jp")
        if not click_first_visible_sync(page, jp_dropdown_selectors, timeout_ms=8000):
            raise RuntimeError("点击日本站货币下拉框失败")
        human_pause(300, 700)
        if not click_first_visible_sync(page, jp_option_selectors, timeout_ms=8000):
            raise RuntimeError(f"点击日本站货币选项失败: {currency_code}")
    else:
        radio_selectors = [
            f"input[name='cop'][value='{currency_code}']",
            f"div[data-a-input-name='cop'] input[value='{currency_code}']",
            f"xpath=//input[@name='cop' and @value='{currency_code}']",
        ]
        if not wait_for_any_selector_sync(page, radio_selectors, timeout_ms=8000, visible_only=False):
            raise RuntimeError(f"未找到货币单位选项: {currency_code}")
        clicked = False
        for selector in radio_selectors:
            try:
                locator = page.locator(selector)
                if locator.count() <= 0:
                    continue
                target = locator.first
                try:
                    target.check(force=True)
                except Exception:
                    target.click(force=True)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise RuntimeError(f"点击货币单位选项失败: {currency_code}")
    human_pause(300, 700)
    if not click_first_visible_sync(page, save_button_selectors, timeout_ms=8000):
        raise RuntimeError("点击货币单位保存按钮失败")
    human_pause(1200, 2200)
    log("CUR", f"[{site_code}] currency set done: {currency_code}")


def collect_rows_for_page(
    page,
    selectors: Dict[str, List[str]],
    target_url: str,
    page_idx: int,
    page_total: int,
    *,
    config: dict,
    log,
    clean_text,
    get_category_for_target_url,
    find_duplicated_ranks,
    completion_selectors_for_url,
    fallback_completion_selectors_for_url,
    count_cards,
    scroll_last_card_into_view,
    wait_for_any_selector,
    wait_for_cards_hydrated,
    activate_cards_for_extension,
    wait_for_traffic_score_block,
    extract_cards,
    extract_metrics_from_text,
    parse_rank,
    goto_with_retry,
):
    prefix = f"P{page_idx}/{page_total}"
    site_code = clean_text(config.get("site", "US")).upper() or "US"
    category_name = get_category_for_target_url(site_code, target_url)
    log("NAV", f"{prefix} open: {target_url}")

    def block_unnecessary_resources(route):
        if route.request.resource_type in ["image", "media", "font"]:
            route.abort()
        else:
            route.continue_()

    page.route("**/*", block_unnecessary_resources)
    goto_with_retry(page, target_url, prefix)
    continue_shopping_button = page.locator("button.a-button-text", has_text="ショッピングを続ける")
    if continue_shopping_button.count() > 0:
        log("NAV", f"{prefix} detected continue shopping gate, clicking through")
        continue_shopping_button.first.click()
        page.wait_for_load_state("domcontentloaded")
    from core.browser import human_pause, random_mouse_move, wait_for_stability

    wait_for_stability(page)
    warm_lo, warm_hi = config.get("warmup_pause_ms", (2000, 5000))
    log("NAV", f"{prefix} warmup pause before scrolling: {warm_lo}-{warm_hi}ms")
    human_pause(int(warm_lo), int(warm_hi))
    if not wait_for_any_selector(page, selectors["page_title"], timeout_ms=15000):
        log("NAV", f"{prefix} page title selector not found; continue")
    target_card_count = int(config.get("target_card_count", 50))
    max_rounds = int(config.get("scroll_max_rounds", 30))
    lo, hi = config.get("scroll_gap_ms", (700, 1600))
    completion_selectors = completion_selectors_for_url(selectors, target_url)
    fallback_completion_selectors = fallback_completion_selectors_for_url(target_url)
    completion_reached = False
    marker_desc = "#100" if re.search(r"([?&])pg=2(?:[&#]|$)", target_url) else "#50"
    log("SCROLL", f"{prefix} completion marker target: {marker_desc}")
    log("SCROLL", f"{prefix} start scroll loop, target={target_card_count}, max_rounds={max(0, max_rounds)}")
    card_count = count_cards(page, selectors)
    log("SCROLL", f"{prefix} initial card_count={card_count}")
    for idx in range(max(0, max_rounds)):
        if card_count >= target_card_count:
            completion_reached = True
            log("SCROLL", f"{prefix} target reached by card count ({card_count}/{target_card_count}); wait extra 10s")
            page.wait_for_timeout(10000)
            break
        random_mouse_move(page, times=1)
        scroll_last_card_into_view(page, selectors)
        page.mouse.wheel(0, 2200)
        human_pause(lo, hi)
        card_count = count_cards(page, selectors)
        log("SCROLL", f"{prefix} round {idx + 1}/{max(0, max_rounds)}, card_count={card_count}")
        if completion_selectors and wait_for_any_selector(page, completion_selectors, timeout_ms=800):
            completion_reached = True
            log("SCROLL", f"{prefix} completion marker detected; wait extra 10s")
            page.wait_for_timeout(10000)
            break
    if (not completion_reached) and completion_selectors:
        completion_reached = wait_for_any_selector(page, completion_selectors, timeout_ms=5000)
        if completion_reached:
            log("SCROLL", f"{prefix} completion marker detected after loop; wait extra 10s")
            page.wait_for_timeout(10000)
    if (not completion_reached) and fallback_completion_selectors:
        log("SCROLL", f"{prefix} #100 not found, fallback to #99 marker")
        completion_reached = wait_for_any_selector(page, fallback_completion_selectors, timeout_ms=3000)
        if completion_reached:
            log("SCROLL", f"{prefix} fallback marker #99 detected; wait extra 10s")
            page.wait_for_timeout(10000)
    if not completion_reached:
        log("SCROLL", f"{prefix} did not reach full target; current card_count={card_count}, continue with current page state")
    random_mouse_move(page, times=2)
    wait_for_cards_hydrated(
        page,
        selectors,
        timeout_ms=int(config.get("card_hydration_timeout_ms", 12000)),
        poll_ms=int(config.get("card_hydration_poll_ms", 500)),
        min_ready_ratio=float(config.get("card_hydration_min_ready_ratio", 0.9)),
    )
    page.mouse.wheel(0, -99999)
    human_pause(250, 500)
    activate_cards_for_extension(page, selectors, pause_ms=tuple(config.get("activate_card_pause_ms", (350, 900))))
    wait_for_traffic_score_block(
        page,
        selectors,
        timeout_ms=int(config.get("traffic_block_timeout_ms", 15000)),
        poll_ms=int(config.get("traffic_block_poll_ms", 500)),
        min_ready_ratio=float(config.get("traffic_block_min_ready_ratio", 0.9)),
    )
    log("EXTRACT", f"{prefix} start extracting cards")
    raw_rows = extract_cards(page, selectors)
    log("EXTRACT", f"{prefix} raw rows collected: {len(raw_rows)}")
    normalized: List[Dict[str, Any]] = []
    for item in raw_rows:
        card_text = clean_text(item.get("card_text", ""))
        asin = clean_text(item.get("asin_text", ""))
        metrics = extract_metrics_from_text(card_text)
        try:
            parsed_rank = parse_rank(item.get("rank_badge", ""))
        except ValueError as exc:
            card_index = int(item.get("index") or 0)
            raise ValueError(
                f"{prefix} rank parse failed at card_index={card_index}, asin={asin or '-'}, "
                f"rank_badge={clean_text(item.get('rank_badge', ''))!r}"
            ) from exc
        row = {
            "rank": parsed_rank,
            "asin": asin,
            "category": category_name,
            "price": clean_text(item.get("price_text", "")),
            "organic_traffic_score_7d": metrics["organic_traffic_score_7d"],
            "ad_traffic_score_7d": metrics["ad_traffic_score_7d"],
            "conversion_rate": metrics["conversion_rate"],
            "conversion_rate_period": metrics["conversion_rate_period"],
            "organic_search_terms": metrics["organic_search_terms"],
            "ad_traffic_terms": metrics["ad_traffic_terms"],
            "all_traffic_terms": metrics["all_traffic_terms"],
            "search_recommend_terms": metrics["search_recommend_terms"],
            "source_url": target_url,
            "page_no": page_idx,
        }
        if not row["asin"] and not row["rank"]:
            continue
        normalized.append(row)
    duplicated_ranks = find_duplicated_ranks(normalized)
    if duplicated_ranks:
        raise RuntimeError(f"P{page_idx}/{page_total} duplicated ranks detected: {duplicated_ranks}")
    log("PARSE", f"{prefix} normalized rows: {len(normalized)}")
    return normalized
