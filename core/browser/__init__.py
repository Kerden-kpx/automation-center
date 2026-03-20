# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Core browser automation utilities."""

from .base_driver import BrowserDriver
from .interaction import (
    human_pause,
    click_first_visible,
    fill_first,
    wait_for_stability,
    wait_for_any_selector,
    get_first_text,
    random_scroll,
    random_mouse_move,
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
