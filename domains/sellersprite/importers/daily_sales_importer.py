# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Daily sales volume importer."""

from __future__ import annotations

import time
from pathlib import Path

import pymysql

from ..repositories.product_day_repo import upsert_daily_sales_volume_rows


def _normalize_site(value: str | None, default_site: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default_site
    upper = raw.upper()
    mapping = {
        "美国": "US",
        "英国": "UK",
        "德国": "DE",
        "法国": "FR",
        "意大利": "IT",
        "西班牙": "ES",
        "日本": "JP",
        "加拿大": "CA",
        "澳大利亚": "AU",
        "墨西哥": "MX",
        "印度": "IN",
    }
    return mapping.get(raw, upper)


def import_daily_sales_volume_from_folder(download_dir: Path, site: str, log=None) -> dict[str, int]:
    import pandas as pd

    logger = log or (lambda _message: None)
    sales_volume_dir = download_dir / "sales volume"
    if not sales_volume_dir.exists():
        return {"files": 0, "parsed_rows": 0, "upserted_rows": 0, "failed_files": 0}

    excel_files = sorted([p for p in sales_volume_dir.glob("*.xlsx") if p.is_file()])
    if not excel_files:
        return {"files": 0, "parsed_rows": 0, "upserted_rows": 0, "failed_files": 0}

    fallback_site = (site or "US").strip().upper() or "US"
    parsed_rows = 0
    failed_files = 0
    filtered_rows = 0
    params: list[tuple] = []

    for path in excel_files:
        try:
            df = pd.read_excel(path, sheet_name=1)
            df.columns = [str(c).strip() for c in df.columns]
            required = ["站点", "时间", "ASIN", "日销量"]
            missing = [c for c in required if c not in df.columns]
            if missing:
                raise RuntimeError(f"缺少列: {', '.join(missing)}")

            tmp = df[required].copy()
            tmp["site"] = tmp["站点"].apply(lambda v: _normalize_site(v, fallback_site))
            tmp["ASIN"] = tmp["ASIN"].astype(str).str.strip().str.upper()
            tmp = tmp[(tmp["ASIN"] != "") & (tmp["site"] != "")]
            original_count = len(tmp)
            tmp = tmp[tmp["site"] == fallback_site]
            filtered_rows += max(0, original_count - len(tmp))
            raw_date = tmp["时间"].astype(str).str.strip()
            parsed_date = pd.to_datetime(raw_date, format="%Y/%m/%d", errors="coerce")
            if parsed_date.isna().any():
                fallback_mask = parsed_date.isna()
                fallback_raw = raw_date[fallback_mask]
                fallback_parsed = pd.to_datetime(fallback_raw, format="%Y-%m-%d", errors="coerce")
                if fallback_parsed.isna().any():
                    second_mask = fallback_parsed.isna()
                    second_raw = fallback_raw[second_mask]
                    second_parsed = pd.to_datetime(second_raw, errors="coerce")
                    fallback_parsed.loc[second_mask] = second_parsed
                parsed_date.loc[fallback_mask] = fallback_parsed
            tmp["date"] = parsed_date.dt.date
            tmp["sales_volume"] = pd.to_numeric(
                tmp["日销量"].astype(str).str.replace(",", "", regex=False).str.replace(r"[^\d\.-]", "", regex=True),
                errors="coerce",
            )
            tmp["sales_volume"] = tmp["sales_volume"].round(0).astype("Int64")
            tmp = tmp.dropna(subset=["date", "sales_volume"])
            if tmp.empty:
                continue
            tmp = tmp.drop_duplicates(subset=["site", "ASIN", "date"], keep="last")
            parsed_rows += len(tmp)
            params.extend(
                (
                    str(r["site"]),
                    str(r["ASIN"]),
                    r["date"],
                    int(r["sales_volume"]),
                )
                for _, r in tmp.iterrows()
            )
        except Exception as exc:
            failed_files += 1
            logger(f"UC 日销量入库跳过文件[{path.name}]: {exc}")

    if not params:
        return {
            "files": len(excel_files),
            "parsed_rows": parsed_rows,
            "upserted_rows": 0,
            "failed_files": failed_files,
            "filtered_rows": filtered_rows,
        }

    batch_size = 500
    upserted_rows = 0
    for start in range(0, len(params), batch_size):
        batch = params[start : start + batch_size]
        try:
            upserted_rows += upsert_daily_sales_volume_rows(batch)
        except (pymysql.err.OperationalError, pymysql.err.InterfaceError) as exc:
            logger(
                "UC 日销量入库批次失败，准备重试: "
                f"batch={start // batch_size + 1}, size={len(batch)}, err={exc}"
            )
            time.sleep(2.0)
            upserted_rows += upsert_daily_sales_volume_rows(batch)
    return {
        "files": len(excel_files),
        "parsed_rows": parsed_rows,
        "upserted_rows": upserted_rows,
        "failed_files": failed_files,
        "filtered_rows": filtered_rows,
    }
