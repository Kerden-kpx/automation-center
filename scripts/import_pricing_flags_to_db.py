#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import load_env_files


def _load_env() -> None:
    load_env_files(
        [
            PROJECT_ROOT / ".env",
            Path.cwd() / ".env",
        ],
        override=False,
    )
    os.environ["DB_NAME"] = "bi_amazon"


_load_env()

from core.data.client import execute_many


DEFAULT_CSV = PROJECT_ROOT / "domains" / "amazon" / "files" / "2026-03-11" / "DE" / "Säbelsägeblätter" / "PricingFlags.csv"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import PricingFlags.csv into bi_amazon.dim_bi_amazon_item")
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help="Path to PricingFlags.csv",
    )
    return parser.parse_args()


def _to_price_decimal_or_none(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9,.\-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) in {1, 2}:
            cleaned = f"{parts[0]}.{parts[1]}"
        else:
            cleaned = "".join(parts)
    elif cleaned.count(".") > 1:
        last_dot = cleaned.rfind(".")
        integer = cleaned[:last_dot].replace(".", "")
        fraction = cleaned[last_dot + 1 :]
        cleaned = f"{integer}.{fraction}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _build_params(rows: list[dict[str, str]]) -> list[tuple[float | None, str | None, str, str, str]]:
    params: list[tuple[float | None, str | None, str, str, str]] = []
    for row in rows:
        run_date = str(row.get("date") or "").strip()
        site = str(row.get("site") or "").strip().upper()
        asin = str(row.get("asin") or "").strip().upper()
        list_price = _to_price_decimal_or_none(str(row.get("list_price") or ""))
        promotion_tags = str(row.get("promotion_tags") or "").strip() or None
        if not run_date or not site or not asin:
            continue
        if list_price is None and promotion_tags is None:
            continue
        params.append((list_price, promotion_tags, asin, site, run_date))
    return params


def main() -> int:
    args = _parse_args()
    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    rows = _load_rows(csv_path)
    params = _build_params(rows)
    if not params:
        print(f"no valid rows to import: {csv_path}")
        return 0

    sql = """
    UPDATE dim_bi_amazon_item
    SET list_price = COALESCE(%s, list_price),
        promotion_tags = %s
    WHERE asin = %s
      AND site = %s
      AND createtime = %s
    """
    affected = int(execute_many(sql, params) or 0)
    print(f"csv={csv_path}")
    print(f"rows={len(rows)}")
    print(f"update_params={len(params)}")
    print(f"affected={affected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
