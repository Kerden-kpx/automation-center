#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [daily_market_jobs] {msg}", flush=True)


def run() -> int:
    _log("start amazon_best_sellers")
    try:
        from domains.amazon.flows.amazon_best_sellers import main as amazon_main

        amazon_main()
    except Exception as exc:
        _log(f"amazon_best_sellers failed: {exc}")
        return 1

    _log("start sellersprite_ccp export")
    try:
        from domains.sellersprite.flows.sellersprite_ccp import (
            login_query_and_export_sellersprite_from_env,
        )

        keyword = (os.getenv("SELLERSPRITE_CCP_KEYWORD") or "").strip()
        ok = login_query_and_export_sellersprite_from_env(
            None,
            keyword=(keyword or None),
            site="US",
        )
        if not ok:
            _log("sellersprite_ccp returned False")
            return 1
    except Exception as exc:
        _log(f"sellersprite_ccp failed: {exc}")
        return 1

    _log("start amazon_product_details")
    try:
        from domains.amazon.flows.amazon_product_details import main as amazon_product_details_main

        amazon_product_details_main()
    except Exception as exc:
        _log(f"amazon_product_details failed: {exc}")
        return 1

    _log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
