# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SellerSprite query service."""

from __future__ import annotations

from selenium.webdriver.common.keys import Keys


def run_competitor_query(browser, site: str, queries: list[str], log) -> str:
    payload = ",".join(queries)
    browser.select_site(site=site, timeout=20)
    log(f"UC 批量查询: 共 {len(queries)} 个 ASIN")
    browser.fill("competitor_query_input", payload, timeout=20)
    try:
        browser.click("competitor_query_button", timeout=20)
    except Exception:
        elem = browser.first_present(browser.selector_xpaths("competitor_query_input"), timeout=10)
        elem.send_keys(Keys.ENTER)
    browser.pause(2.0, 3.5)
    return payload
