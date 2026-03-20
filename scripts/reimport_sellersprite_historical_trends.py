#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import load_env_files
from domains.amazon.flows.amazon_product_details import (
    _parse_fact_rows_from_export,
    _upsert_fact_daily_rows,
)


def _load_runtime_env() -> None:
    root_env = PROJECT_ROOT / ".env"
    cwd_env = Path.cwd() / ".env"
    load_env_files([root_env], override=False)
    if cwd_env != root_env:
        load_env_files([cwd_env], override=False)
    os.environ["DB_NAME"] = "bi_amazon"


def _resolve_download_dir(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"path not found: {path}")
    if not path.is_dir():
        raise RuntimeError(f"path must be a directory: {path}")
    return path


def _infer_site(download_dir: Path) -> str:
    # expected path: .../<date>/<site>/<category>/historical trends
    parts = list(download_dir.parts)
    if len(parts) >= 4:
        return str(parts[-3]).strip().upper()
    raise RuntimeError("unable to infer site from path, please pass --site")


def _collect_export_files(download_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in download_dir.glob("*.xlsx")
            if path.is_file() and not path.name.startswith("~$")
        ],
        key=lambda item: item.name.lower(),
    )


def _reimport_folder(download_dir: Path, site: str) -> dict[str, int]:
    files = _collect_export_files(download_dir)
    all_rows = []
    failed_files = 0
    for path in files:
        try:
            all_rows.extend(_parse_fact_rows_from_export(path, site))
        except Exception as exc:
            failed_files += 1
            print(f"parse_failed: {path.name}: {exc}")
    upserted_rows = _upsert_fact_daily_rows(all_rows)
    return {
        "files": len(files),
        "parsed_rows": len(all_rows),
        "upserted_rows": int(upserted_rows or 0),
        "failed_files": failed_files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reimport SellerSprite historical trends files into DB")
    parser.add_argument(
        "path",
        nargs="?",
        default=r"D:\Yida_project\automation-center\domains\sellersprite\files\2026-03-09\US\Reciprocating_Saw_Blades\historical trends",
        help="Path to the historical trends folder",
    )
    parser.add_argument(
        "--site",
        default="",
        help="Site code override, e.g. US/UK/DE. If omitted, infer from path.",
    )
    args = parser.parse_args()

    _load_runtime_env()
    download_dir = _resolve_download_dir(args.path)
    site = str(args.site or "").strip().upper() or _infer_site(download_dir)
    print(f"db_name: {os.getenv('DB_NAME', '').strip()}")
    result = _reimport_folder(download_dir, site=site)

    print("reimport finished")
    print(f"download_dir: {download_dir}")
    print(f"site: {site}")
    print(f"files: {result['files']}")
    print(f"parsed_rows: {result['parsed_rows']}")
    print(f"upserted_rows: {result['upserted_rows']}")
    print(f"failed_files: {result['failed_files']}")


if __name__ == "__main__":
    main()
