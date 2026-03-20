# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Atomic interaction utilities for robust web automation.

This module provides human-like interaction primitives designed to:
- Simulate realistic user behavior (random delays, typing speed).
- Handle unstable elements with retry mechanisms.
- Provide intelligent waiting strategies.

Usage:
    from core.browser import human_pause, click_first_visible, fill_first

    human_pause(300, 800)  # Pause 300-800ms
    click_first_visible(page, ["button.submit", "input[type='submit']"])
    fill_first(page, ["#username", "input[name='user']"], "my_username")
"""

from __future__ import annotations

import random
import time
from typing import Iterable, Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


def human_pause(min_ms: int = 300, max_ms: int = 900) -> None:
    """
    Simulate human-like pause with random duration.

    Args:
        min_ms: Minimum pause duration in milliseconds.
        max_ms: Maximum pause duration in milliseconds.
    """
    low = min(min_ms, max_ms)
    high = max(min_ms, max_ms)
    time.sleep(random.uniform(low, high) / 1000.0)


def wait_for_stability(page: Page, timeout_ms: int = 8000) -> None:
    """
    Wait for page to become stable (network idle + DOM content loaded).

    Args:
        page: Playwright Page object.
        timeout_ms: Maximum time to wait in milliseconds.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except PlaywrightTimeoutError:
            pass
    human_pause(200, 500)


def click_first_visible(
    page: Page,
    selectors: Iterable[str],
    *,
    force: bool = False,
    timeout_ms: int = 3000,
) -> bool:
    """
    Click the first visible element matching any of the given selectors.
    If a selector matches multiple elements, it tries them in order until a visible one is found.

    Args:
        page: Playwright Page object.
        selectors: Iterable of CSS/XPath selectors to try in order.
        force: If True, bypass actionability checks.
        timeout_ms: Timeout for individual click attempts.

    Returns:
        True if an element was clicked, False otherwise.
    """
    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()
        if count == 0:
            continue
            
        for i in range(count):
            target = locator.nth(i)
            try:
                if target.is_visible():
                    target.scroll_into_view_if_needed(timeout=2000)
                    try:
                        target.click(timeout=timeout_ms, force=force)
                    except Exception:
                        # Fallback to JavaScript click
                        target.evaluate("el => el.click()")
                    human_pause()
                    return True
            except Exception:
                continue
    return False



def fill_first(
    page: Page,
    selectors: Iterable[str],
    value: str,
    *,
    clear_first: bool = True,
) -> bool:
    """
    Fill the first visible input element matching any of the given selectors.

    Args:
        page: Playwright Page object.
        selectors: Iterable of CSS/XPath selectors to try in order.
        value: Text value to fill.
        clear_first: If True, clear existing content before filling.

    Returns:
        True if an element was filled, False otherwise.
    """
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            continue
        if count <= 0:
            continue

        for i in range(count):
            target = locator.nth(i)
            try:
                if not target.is_visible():
                    continue
                if clear_first:
                    try:
                        target.click()
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                    except Exception:
                        pass
                # Try typing character by character for human-like behavior
                try:
                    target.press_sequential(value, delay=random.randint(50, 150))
                    human_pause()
                    return True
                except Exception:
                    pass
                # Fallback to fill
                try:
                    target.fill(value)
                    human_pause()
                    return True
                except Exception:
                    pass
            except Exception:
                continue
    return False


def wait_for_any_selector(
    page: Page,
    selectors: Iterable[str],
    timeout_ms: int = 10000,
) -> bool:
    """
    Wait for any of the given selectors to appear.

    Args:
        page: Playwright Page object.
        selectors: Iterable of CSS/XPath selectors to wait for.
        timeout_ms: Maximum time to wait in milliseconds.

    Returns:
        True if any selector appeared, False if timeout.
    """
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=timeout_ms)
            return True
        except PlaywrightTimeoutError:
            continue
    return False


def get_first_text(page: Page, selectors: Iterable[str]) -> Optional[str]:
    """
    Get text content from the first visible element matching any selector.

    Args:
        page: Playwright Page object.
        selectors: Iterable of CSS/XPath selectors to try.

    Returns:
        Text content if found, None otherwise.
    """
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() > 0 and locator.first.is_visible():
                return locator.first.text_content()
        except Exception:
            continue
    return None


def random_scroll(page: Page, times: int = 0, pause_ms: tuple[int, int] = (300, 800)) -> None:
    """
    Simulate human-like random scrolling on the page.

    Args:
        page: Playwright Page object.
        times: Number of scroll actions. 0 means random between 1-3.
        pause_ms: Min/max pause between scrolls in milliseconds.
    """
    if times <= 0:
        times = random.randint(1, 3)
    for _ in range(times):
        direction = random.choice(["down", "down", "up"])  # bias towards down
        distance = random.randint(150, 500)
        if direction == "up":
            distance = -distance
        try:
            page.mouse.wheel(0, distance)
        except Exception:
            try:
                page.evaluate(f"window.scrollBy(0, {distance})")
            except Exception:
                pass
        human_pause(pause_ms[0], pause_ms[1])


def _bezier_point(t: float, p0: tuple, p1: tuple, p2: tuple) -> tuple[float, float]:
    """Calculate a point on a quadratic Bezier curve at parameter t."""
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
    return (x, y)


def random_mouse_move(page: Page, times: int = 0) -> None:
    """
    Simulate natural mouse movements using quadratic Bezier curves.

    Generates arc-shaped trajectories that mimic real human hand movements,
    instead of straight-line jumps which are easily detected as bot behavior.

    Args:
        page: Playwright Page object.
        times: Number of moves. 0 means random between 2-5.
    """
    if times <= 0:
        times = random.randint(2, 5)
    try:
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        width = viewport.get("width", 1280)
        height = viewport.get("height", 720)
    except Exception:
        width, height = 1280, 720

    # Start from a reasonable position
    cur_x = random.randint(100, max(200, width - 100))
    cur_y = random.randint(80, max(200, height - 100))

    for _ in range(times):
        # Random destination
        dest_x = random.randint(100, max(200, width - 100))
        dest_y = random.randint(80, max(200, height - 100))

        # Random control point offset to create arc
        mid_x = (cur_x + dest_x) / 2 + random.randint(-150, 150)
        mid_y = (cur_y + dest_y) / 2 + random.randint(-100, 100)
        control = (mid_x, mid_y)

        # Walk along the Bezier curve
        steps = random.randint(15, 35)
        try:
            for i in range(steps + 1):
                t = i / steps
                bx, by = _bezier_point(t, (cur_x, cur_y), control, (dest_x, dest_y))
                page.mouse.move(int(bx), int(by))
                time.sleep(random.uniform(0.005, 0.02))
        except Exception:
            pass

        cur_x, cur_y = dest_x, dest_y
        human_pause(80, 300)

