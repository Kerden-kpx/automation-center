#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Page behavior service for amazon_product_details."""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any, Dict, List, Tuple


async def ensure_sellersprite_logged_in_on_first_asin(
    page,
    *,
    config: dict,
    log,
    selectors: dict,
    wait_for_any_selector_across_contexts,
    click_first_visible_across_contexts,
    read_first_visible_text_across_contexts,
    fill_first_visible_across_contexts,
    debug_selector_counts,
    human_pause,
    iter_contexts,
) -> None:
    if not bool(config.get("sellersprite_login_on_first_page", True)):
        return
    launcher_selectors = [
        "div.ss-name:has-text('卖家精灵')",
        "text=卖家精灵",
        "xpath=//div[contains(@class,'ss-name') and contains(normalize-space(.), '卖家精灵')]",
    ]
    tab_selectors = list(selectors.get("account_login_tab", [])) + ["text=账号登录"]
    account_selectors = selectors.get("account_input", [])
    password_selectors = selectors.get("password_input", [])
    submit_selectors = selectors.get("login_submit_button", [])
    ready_selectors = selectors.get("asin_count_ready", [])
    user_name_selectors = ["span.hide-nickname-more", "xpath=//span[contains(@class,'hide-nickname-more')]"]
    log("[初始化][S1] 打开卖家精灵入口")
    if not await wait_for_any_selector_across_contexts(page, launcher_selectors, timeout_ms=15000):
        await debug_selector_counts(page, launcher_selectors, "sellersprite_launcher")
        raise RuntimeError("未找到卖家精灵入口")
    if not await click_first_visible_across_contexts(page, launcher_selectors, timeout_ms=5000):
        raise RuntimeError("点击卖家精灵入口失败")
    await human_pause(400, 900)
    user_name = await read_first_visible_text_across_contexts(page, user_name_selectors)
    if user_name and user_name != "未登录":
        log(f"[初始化][S] 检测到已登录用户: {user_name}")
        return
    tab_visible = await wait_for_any_selector_across_contexts(page, tab_selectors, timeout_ms=5000, visible_only=True)
    if not tab_visible:
        log("[初始化][S] 未检测到账号登录Tab，判定已登录，跳过登录流程")
        return
    import os

    account = str(os.getenv("SELLERSPRITE_ACCOUNT") or "").strip()
    password = str(os.getenv("SELLERSPRITE_PASSWORD") or "").strip()
    if not account or not password:
        raise RuntimeError("缺少环境变量：SELLERSPRITE_ACCOUNT / SELLERSPRITE_PASSWORD")
    if not await click_first_visible_across_contexts(page, tab_selectors, timeout_ms=3000):
        raise RuntimeError("卖家精灵账号登录Tab点击失败")
    await human_pause(300, 700)
    account_visible = await wait_for_any_selector_across_contexts(page, account_selectors, timeout_ms=5000, visible_only=True)
    if not account_visible:
        await debug_selector_counts(page, account_selectors, "ss_account_input")
        raise RuntimeError("点击账号登录Tab后未检测到账号输入框")
    if not await fill_first_visible_across_contexts(page, account_selectors, account, field_tag="ss_account"):
        raise RuntimeError("卖家精灵账号输入失败")
    if not await fill_first_visible_across_contexts(page, password_selectors, password, field_tag="ss_password"):
        raise RuntimeError("卖家精灵密码输入失败")
    if not await click_first_visible_across_contexts(page, submit_selectors, timeout_ms=4000):
        raise RuntimeError("卖家精灵点击登录失败")
    ready_timeout = int(config.get("sellersprite_post_login_ready_timeout_ms", 60000))
    if ready_selectors and not await wait_for_any_selector_across_contexts(page, ready_selectors, timeout_ms=ready_timeout):
        raise RuntimeError("卖家精灵登录后未进入可用状态")
    log("[初始化][S2] 卖家精灵登录完成")


async def ensure_delivery_zip_on_first_open(
    page,
    *,
    config: dict,
    site_code: str,
    export_selectors: dict,
    resolve_delivery_zip_code,
    normalize_zip_text,
    split_jp_zip_code,
    read_first_visible_text_across_contexts,
    wait_for_any_selector_across_contexts,
    click_first_visible_across_contexts,
    fill_first_visible_across_contexts,
    debug_selector_counts,
    human_pause,
    log,
) -> None:
    if not bool(config.get("set_delivery_zip_on_first_page", True)):
        return
    zip_code = resolve_delivery_zip_code()
    trigger_selectors = export_selectors.get("delivery_location_trigger", [])
    input_selectors = export_selectors.get("delivery_zip_input", [])
    jp_prefix_selectors = export_selectors.get("delivery_zip_input_jp_prefix", [])
    jp_suffix_selectors = export_selectors.get("delivery_zip_input_jp_suffix", [])
    done_selectors = export_selectors.get("delivery_done_button", [])
    apply_selectors = [
        "input[aria-labelledby='GLUXZipUpdate-announce']",
        "input.a-button-input[aria-labelledby='GLUXZipUpdate-announce']",
        "xpath=//input[contains(@aria-labelledby,'GLUXZipUpdate-announce')]",
    ]
    confirm_selectors = [
        "#GLUXConfirmClose",
        "input#GLUXConfirmClose",
        "input[aria-labelledby='GLUXConfirmClose-announce']",
        "xpath=//input[@id='GLUXConfirmClose']",
    ]
    current_zip_selectors = export_selectors.get("current_delivery_zip", [])
    current_zip_text = await read_first_visible_text_across_contexts(page, current_zip_selectors)
    current_zip_normalized = normalize_zip_text(current_zip_text)
    target_zip_normalized = normalize_zip_text(zip_code)
    if target_zip_normalized and current_zip_normalized and target_zip_normalized in current_zip_normalized:
        log(f"[初始化][D0] 当前 Deliver 邮编已命中目标值，跳过设置: {current_zip_text}")
        return
    log(f"[初始化][D1] 开始设置 Deliver 邮编: {zip_code}")
    if not await wait_for_any_selector_across_contexts(page, trigger_selectors, timeout_ms=15000, visible_only=True):
        await debug_selector_counts(page, trigger_selectors, "delivery_location_trigger")
        raise RuntimeError("未找到 Deliver 入口")
    if not await click_first_visible_across_contexts(page, trigger_selectors, timeout_ms=5000):
        raise RuntimeError("点击 Deliver 入口失败")
    await human_pause(600, 1200)
    if not await wait_for_any_selector_across_contexts(page, input_selectors, timeout_ms=12000, visible_only=True):
        if site_code != "JP":
            await debug_selector_counts(page, input_selectors, "delivery_zip_input")
            raise RuntimeError("未找到邮编输入框")
    if site_code == "JP":
        jp_prefix, jp_suffix = split_jp_zip_code(zip_code)
        if not await wait_for_any_selector_across_contexts(page, jp_prefix_selectors, timeout_ms=12000, visible_only=True):
            await debug_selector_counts(page, jp_prefix_selectors, "delivery_zip_input_jp_prefix")
            raise RuntimeError("未找到日本站邮编前缀输入框")
        if not await wait_for_any_selector_across_contexts(page, jp_suffix_selectors, timeout_ms=12000, visible_only=True):
            await debug_selector_counts(page, jp_suffix_selectors, "delivery_zip_input_jp_suffix")
            raise RuntimeError("未找到日本站邮编后缀输入框")
        if not await fill_first_visible_across_contexts(page, jp_prefix_selectors, jp_prefix, field_tag="delivery_zip_input_jp_prefix"):
            raise RuntimeError("日本站邮编前缀输入失败")
        if not await fill_first_visible_across_contexts(page, jp_suffix_selectors, jp_suffix, field_tag="delivery_zip_input_jp_suffix"):
            raise RuntimeError("日本站邮编后缀输入失败")
    else:
        if not await fill_first_visible_across_contexts(page, input_selectors, zip_code, field_tag="delivery_zip_input"):
            raise RuntimeError("邮编输入失败")
    if not await click_first_visible_across_contexts(page, apply_selectors, timeout_ms=5000):
        raise RuntimeError("点击 Apply 按钮失败")
    await human_pause(400, 900)
    if await wait_for_any_selector_across_contexts(page, confirm_selectors, timeout_ms=3000, visible_only=True):
        if not await click_first_visible_across_contexts(page, confirm_selectors, timeout_ms=5000):
            raise RuntimeError("检测到确认弹窗但点击确认按钮失败")
        await human_pause(1000, 1800)
        return
    if not await wait_for_any_selector_across_contexts(page, done_selectors, timeout_ms=10000, visible_only=True):
        log("[初始化][D1] Apply 后未出现确认弹窗和 Done，视为地址已生效")
        return
    if not await click_first_visible_across_contexts(page, done_selectors, timeout_ms=5000):
        raise RuntimeError("点击 Done 按钮失败")
    await human_pause(1200, 2200)


async def ensure_currency_on_first_open(
    page,
    *,
    config: dict,
    site_code: str,
    export_selectors: dict,
    resolve_currency_code,
    resolve_site_base_url,
    goto_with_fallback,
    wait_for_stability,
    iter_contexts,
    read_first_visible_text_across_contexts,
    wait_for_any_selector_across_contexts,
    click_first_visible_across_contexts,
    human_pause,
    log,
) -> None:
    if not bool(config.get("set_currency_on_first_page", True)):
        return
    if site_code == "US":
        log("[初始化][C1] US 站点跳过货币设置")
        return
    base_url = resolve_site_base_url().rstrip("/")
    currency_code = resolve_currency_code()
    currency_url = f"{base_url}/customer-preferences/edit?ie=UTF8&preferencesReturnUrl=%2F&ref_=topnav_lang"
    current_selectors = export_selectors.get("currency_selected_option", [])
    save_button_selectors = export_selectors.get("currency_save_button", [])
    jp_dropdown_selectors = export_selectors.get("currency_dropdown_trigger_jp", [])
    jp_option_selectors = export_selectors.get("currency_option_jp", [])
    log(f"[初始化][C1] 检查货币单位: target={currency_code}")
    await goto_with_fallback(page, currency_url, config["page_timeout_ms"])
    await wait_for_stability(page)
    selected_ok = False
    checked_selector = f"input[name='cop'][value='{currency_code}']:checked"
    for _, ctx in iter_contexts(page):
        try:
            if await ctx.locator(checked_selector).count() > 0:
                selected_ok = True
                break
        except Exception:
            continue
    if not selected_ok:
        current_text = await read_first_visible_text_across_contexts(page, current_selectors)
        if currency_code in str(current_text or "").strip().upper():
            selected_ok = True
    if selected_ok:
        log(f"[初始化][C1] 当前货币已命中目标值，跳过设置: {currency_code}")
        return
    if site_code == "JP":
        if not await wait_for_any_selector_across_contexts(page, jp_dropdown_selectors, timeout_ms=12000, visible_only=True):
            raise RuntimeError("未找到日本站货币下拉框")
        if not await click_first_visible_across_contexts(page, jp_dropdown_selectors, timeout_ms=5000):
            raise RuntimeError("点击日本站货币下拉框失败")
        await human_pause(300, 700)
        if not await wait_for_any_selector_across_contexts(page, jp_option_selectors, timeout_ms=8000, visible_only=True):
            raise RuntimeError(f"未找到日本站货币选项: {currency_code}")
        if not await click_first_visible_across_contexts(page, jp_option_selectors, timeout_ms=5000):
            raise RuntimeError(f"点击日本站货币选项失败: {currency_code}")
    else:
        radio_selectors = [
            f"input[name='cop'][value='{currency_code}']",
            f"div[data-a-input-name='cop'] input[value='{currency_code}']",
            f"xpath=//input[@name='cop' and @value='{currency_code}']",
        ]
        if not await wait_for_any_selector_across_contexts(page, radio_selectors, timeout_ms=12000, visible_only=False):
            raise RuntimeError(f"未找到货币单位选项: {currency_code}")
        clicked = False
        for _, ctx in iter_contexts(page):
            for selector in radio_selectors:
                try:
                    locator = ctx.locator(selector)
                    count = await locator.count()
                    if count <= 0:
                        continue
                    target = locator.first
                    try:
                        await target.check(force=True)
                    except Exception:
                        await target.click(force=True)
                    clicked = True
                    break
                except Exception:
                    continue
            if clicked:
                break
        if not clicked:
            raise RuntimeError(f"点击货币单位选项失败: {currency_code}")
    await human_pause(300, 700)
    if not await click_first_visible_across_contexts(page, save_button_selectors, timeout_ms=8000):
        raise RuntimeError("点击货币单位保存按钮失败")
    await human_pause(1200, 2200)
    log(f"[初始化][C1] 货币单位设置完成: {currency_code}")


async def extract_list_price(page, *, iter_contexts) -> str:
    selectors = [
        "span.basisPrice span.a-price.a-text-price.apex-basisprice-value span.a-offscreen",
        "span.basisPrice span.a-offscreen",
        "span:has-text('List Price') span.a-offscreen",
    ]
    for _, ctx in iter_contexts(page):
        for selector in selectors:
            try:
                locator = ctx.locator(selector)
                if await locator.count() <= 0:
                    continue
                text = (await locator.first.text_content() or "").strip()
                if text:
                    return text
            except Exception:
                continue
    return ""


async def extract_promotion_tags(page, *, site_code: str, export_selectors: dict, iter_contexts) -> str:
    raw_config = export_selectors.get(
        "promotion_tag_selectors_jp" if site_code == "JP" else "promotion_tag_selectors_us",
        [],
    )
    selector_pairs: list[tuple[list[str], str]] = []
    for item in raw_config if isinstance(raw_config, list) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        selectors = [str(sel).strip() for sel in (item.get("selectors") or []) if str(sel).strip()]
        if not label or not selectors:
            continue
        selector_pairs.append((selectors, label))
    tags: list[str] = []
    for selectors, label in selector_pairs:
        matched = False
        for _, ctx in iter_contexts(page):
            for selector in selectors:
                try:
                    locator = ctx.locator(selector)
                    count = await locator.count()
                except Exception:
                    continue
                if count <= 0:
                    continue
                for i in range(count):
                    try:
                        text = str(await locator.nth(i).text_content() or "").strip()
                    except Exception:
                        text = ""
                    normalized = re.sub(r"\s+", " ", text)
                    if normalized and label in normalized:
                        tags.append(label)
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break
    return "|".join(tags)


async def extract_special_conversion_rate(page, *, category: str, special_category: str, selectors: list[str], read_first_visible_text_across_contexts, parse_conversion_rate_text):
    if str(category or "").strip() != special_category:
        return "", ""
    raw_text = await read_first_visible_text_across_contexts(page, selectors)
    return parse_conversion_rate_text(raw_text)


async def process_single_target(
    context,
    target: Dict[str, str],
    idx: int,
    total: int,
    *,
    list_price_csv_path,
    file_write_lock: asyncio.Lock,
    page_holder: Dict[str, Any],
    block_images: bool,
    keep_page_on_error: bool,
    config: dict,
    site_code: str,
    export_selectors: dict,
    sellersprite_login_selectors: dict,
    special_category: str,
    goto_with_fallback,
    setup_resource_blocking,
    wait_for_stability,
    human_pause,
    random_mouse_move,
    random_scroll,
    dismiss_continue_shopping,
    detect_blocked,
    append_pricing_flags_row,
    upsert_product_status,
    now_text,
    sleep_ms,
    flow_log,
    safe_token,
    extract_list_price_fn,
    extract_promotion_tags_fn,
    extract_special_conversion_rate_fn,
) -> Dict[str, str]:
    asin = target.get("asin", "")
    url = target.get("url", "")
    category = str(target.get("category") or "").strip()
    asin_token = safe_token(asin, f"NOASIN_{idx}")
    task_name = asyncio.current_task().get_name() if asyncio.current_task() else "worker"
    task_tag = f"[{task_name}]"
    started_at = now_text()

    async def _get_or_create_page():
        page = page_holder.get("page")
        if page is None or page.is_closed():
            page = await context.new_page()
            page.set_default_timeout(config["page_timeout_ms"])
            if block_images:
                await setup_resource_blocking(page)
            page_holder["page"] = page
        return page

    if not url:
        async with file_write_lock:
            upsert_product_status(asin_token, "invalid_url", "empty url", category=category, started_at=started_at, ended_at=now_text())
        return {"asin": asin_token, "status": "invalid_url"}

    max_attempts = max(1, int(config.get("blocked_retry_limit", 2)))
    completed_ok = False
    result = {"asin": asin_token, "status": "unknown"}
    page = await _get_or_create_page()
    try:
        for attempt in range(1, max_attempts + 1):
            flow_log(f"{task_tag} [{idx}/{total}] 打开 {asin_token}: {url}（第 {attempt} 次）")
            try:
                if page.is_closed():
                    page = await _get_or_create_page()
                await goto_with_fallback(page, url, config["page_timeout_ms"])
                current_url = page.url or ""
                if current_url.startswith("about:blank") or current_url.startswith("chrome-error://"):
                    raise RuntimeError(f"unexpected page url: {current_url}")
                await wait_for_stability(page)
                await human_pause(200, 500)
                await random_mouse_move(page, times=1)
                await random_scroll(page, times=1)
                await dismiss_continue_shopping(page)
                if await detect_blocked(page):
                    wait_sec = int(config.get("blocked_wait_sec", 120))
                    raise RuntimeError(f"bot check detected, wait {wait_sec}s")
                list_price = await extract_list_price_fn(page)
                promotion_tags = await extract_promotion_tags_fn(page)
                conversion_rate, conversion_rate_period = await extract_special_conversion_rate_fn(page, category)
                pricing_row = {
                    "date": time.strftime("%Y-%m-%d"),
                    "site": site_code,
                    "asin": asin or asin_token,
                    "list_price": list_price if list_price else "",
                    "promotion_tags": promotion_tags,
                    "conversion_rate": conversion_rate,
                    "conversion_rate_period": conversion_rate_period,
                }
                async with file_write_lock:
                    append_pricing_flags_row(list_price_csv_path, pricing_row)
                    upsert_product_status(asin_token, "success", "", category=category, started_at=started_at, ended_at=now_text())
                flow_log(f"{task_tag} [{idx}/{total}] {asin_token} 完成")
                completed_ok = True
                result = {"asin": asin_token, "status": "success"}
                break
            except Exception as exc:
                flow_log(f"{task_tag} [{idx}/{total}] {asin_token} 异常: {exc} (attempt {attempt}/{max_attempts})")
                if attempt < max_attempts:
                    try:
                        if page.is_closed():
                            page = await _get_or_create_page()
                        else:
                            await page.reload(wait_until="domcontentloaded", timeout=config["page_timeout_ms"])
                            await wait_for_stability(page)
                    except Exception:
                        try:
                            if not page.is_closed():
                                await page.close()
                        except Exception:
                            pass
                        page_holder["page"] = None
                        page = await _get_or_create_page()
                    await human_pause(300, 700)
                    continue
                async with file_write_lock:
                    upsert_product_status(asin_token, "error", str(exc), category=category, started_at=started_at, ended_at=now_text())
                result = {"asin": asin_token, "status": "error"}
                break
        await sleep_ms(config["per_asin_delay_ms"])
    finally:
        try:
            if keep_page_on_error and not completed_ok:
                flow_log(f"{task_tag} 保留失败页面用于排查: {asin_token}")
            elif page.is_closed():
                page_holder["page"] = None
        except Exception:
            pass
    return result
