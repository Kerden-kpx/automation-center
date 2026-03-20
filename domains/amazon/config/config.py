#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared configuration helpers for Amazon flows."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


AMAZON_SHARED_DEFAULTS: Dict[str, Any] = {
    "site": "US",
    "headless": False,
    "use_cdp": True,
    "page_timeout_ms": 30000,
    "export_dir": str(PROJECT_ROOT / "domains" / "amazon" / "files"),
    "per_asin_delay_ms": (5000, 15000),
    "blocked_wait_sec": 900,
    "blocked_retry_limit": 5,
    "db_name": "bi_amazon",
    "sellersprite_login_on_first_page": False,
    "sellersprite_post_login_ready_timeout_ms": 60000,
    "concurrent_tabs": 3,
    "block_images": True,
}


def build_amazon_config(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a flow config by merging shared defaults with flow-specific overrides."""
    cfg = deepcopy(AMAZON_SHARED_DEFAULTS)
    if overrides:
        cfg.update(overrides)
    return cfg
