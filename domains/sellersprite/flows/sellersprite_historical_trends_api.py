# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deprecated compatibility wrapper for SellerSprite Keepa history service."""

from __future__ import annotations

import argparse
import os

from . import sellersprite_ccp as ccp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deprecated wrapper for SellerSprite CCP flow")
    parser.add_argument("--sites", default="", help="Comma separated site codes or ALL, e.g. UK or US,UK or ALL")
    parser.add_argument("--keyword", default="", help="Optional manual ASIN keyword input")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    keyword = (args.keyword or os.getenv("SELLERSPRITE_KEYWORD") or "").strip() or None
    raw_sites = str(args.sites or "").strip()
    if raw_sites.upper() == "ALL":
        sites = list(ccp.SITE_RUN_ORDER)
    else:
        sites = [item.strip().upper() for item in raw_sites.split(",") if item.strip()]
    if not sites:
        env_site = str(os.getenv("SELLERSPRITE_SITE") or "US").strip().upper() or "US"
        sites = [env_site]

    print("[SellerSpriteHistoricalTrendsAPI] 独立入口已弃用，转交 sellersprite_ccp 主流程执行。")
    ccp._run_sites(sites, keyword=keyword, id_filter="")


if __name__ == "__main__":
    main()
