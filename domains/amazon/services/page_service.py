#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared Playwright page helpers for Amazon flows."""

from __future__ import annotations


def configure_sync_page(page, *, timeout_ms: int) -> None:
    page.set_default_timeout(timeout_ms)


def close_cdp_browser_if_needed(page, driver, *, enabled: bool, log) -> None:
    if not enabled:
        return
    if not bool(getattr(driver, "_is_cdp_session", False)):
        return
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Browser.close")
        log("BROWSER", "CDP browser closed")
    except Exception as exc:
        log("BROWSER", f"failed to close CDP browser: {exc}")


async def configure_async_page(page, *, timeout_ms: int) -> None:
    page.set_default_timeout(timeout_ms)


async def goto_with_fallback(page, url: str, timeout_ms: int) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        await page.goto(url, wait_until="commit", timeout=max(timeout_ms, 60000))


async def setup_resource_blocking(page, handler) -> None:
    await page.route("**/*", handler)
