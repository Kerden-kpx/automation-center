#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domains.sellersprite.flows import sellersprite_ccp as ccp
from domains.sellersprite.services.traffic_source_service import export_traffic_source_via_api


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test SellerSprite traffic source API for the special category")
    parser.add_argument("--id", default="1", help="Category id, default: 1")
    parser.add_argument("--site", default="US", help="Site code, default: US")
    parser.add_argument(
        "--keyword",
        default="",
        help="Optional manual ASIN input. Supports comma/newline separated values.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    site = str(args.site or "US").strip().upper() or "US"
    id_filter = str(args.id or "1").strip() or "1"
    keyword = str(args.keyword or "").strip() or None

    queries = ccp._resolve_query_keywords(keyword=keyword, site=site, id_filter=id_filter)[:100]
    category_name = ccp._resolve_primary_category(site, id_filter)
    category_dir = ccp._resolve_category_dir_from_id(site, id_filter)
    download_dir = ccp._uc_resolve_download_dir() / site / category_dir
    download_dir.mkdir(parents=True, exist_ok=True)

    print(f"site: {site}")
    print(f"id: {id_filter}")
    print(f"category: {category_name}")
    print(f"download_dir: {download_dir}")
    print(f"query_asins: {len(queries)}")

    driver = ccp._uc_build_driver(download_dir)
    try:
        ccp._run_uc(
            site=site,
            keyword=None,
            id_filter=id_filter,
            do_query=False,
            do_export=False,
            driver=driver,
        )
        succ, fail, files, dim_rows = export_traffic_source_via_api(
            driver,
            download_dir,
            site=site,
            category=category_name,
            asins=queries,
            market_resolver=ccp._resolve_source_api_market,
            log=print,
        )
        print("traffic source test finished")
        print(f"success_batches: {succ}")
        print(f"failed_batches: {fail}")
        print(f"dim_rows: {dim_rows}")
        print("files:")
        for path in files:
            print(str(path))
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
