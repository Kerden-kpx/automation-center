#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domains.sellersprite.flows.sellersprite_ccp import _import_daily_sales_volume_from_folder


def _resolve_download_dir(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"path not found: {path}")
    if path.is_dir() and path.name.lower() == "sales volume":
        return path.parent
    sales_volume_dir = path / "sales volume"
    if sales_volume_dir.exists():
        return path
    raise RuntimeError(
        "path must be either the 'sales volume' folder or its parent category folder"
    )


def _infer_site(download_dir: Path) -> str:
    # expected path: .../<date>/<site>/<category>
    parts = list(download_dir.parts)
    if len(parts) >= 3:
        return str(parts[-2]).strip().upper()
    raise RuntimeError("unable to infer site from path, please pass --site")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reimport SellerSprite sales volume files into DB")
    parser.add_argument(
        "path",
        help="Path to the 'sales volume' folder or its parent category folder",
    )
    parser.add_argument(
        "--site",
        default="",
        help="Site code override, e.g. DE/UK/US. If omitted, infer from path.",
    )
    args = parser.parse_args()

    download_dir = _resolve_download_dir(args.path)
    site = str(args.site or "").strip().upper() or _infer_site(download_dir)

    result = _import_daily_sales_volume_from_folder(download_dir, site=site)
    print("reimport finished")
    print(f"download_dir: {download_dir}")
    print(f"site: {site}")
    print(f"files: {result.get('files', 0)}")
    print(f"parsed_rows: {result.get('parsed_rows', 0)}")
    print(f"upserted_rows: {result.get('upserted_rows', 0)}")
    print(f"failed_files: {result.get('failed_files', 0)}")
    print(f"filtered_rows: {result.get('filtered_rows', 0)}")


if __name__ == "__main__":
    main()
