# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Backward-compatible shim; browser utilities moved to core.browser."""

from core.browser import (  # noqa: F401
    BrowserDriver,
    click_first_visible,
    fill_first,
    get_first_text,
    human_pause,
    random_mouse_move,
    random_scroll,
    wait_for_any_selector,
    wait_for_stability,
)

__all__ = [
    "BrowserDriver",
    "human_pause",
    "click_first_visible",
    "fill_first",
    "wait_for_stability",
    "wait_for_any_selector",
    "get_first_text",
    "random_scroll",
    "random_mouse_move",
]
