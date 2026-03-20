# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared SellerSprite helpers."""

from __future__ import annotations

import re


BI_AMAZON_ITEM_TABLE = "bi_amazon.dim_bi_amazon_item"


def safe_dir_name(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._")
    return text[:80] or fallback


def parse_float(value) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    raw = re.sub(r"[^\d\.\-]", "", raw)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_int(value) -> int | None:
    num = parse_float(value)
    if num is None:
        return None
    try:
        return int(round(num))
    except Exception:
        return None


def parse_rate(value) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    number = parse_float(raw)
    if number is None:
        return None
    if "%" in raw or number > 1:
        return round(number / 100.0, 6)
    return round(number, 6)


def parse_date(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        import pandas as pd

        ts = pd.to_datetime(raw, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def derive_type(brand: str | None) -> int | None:
    value = str(brand or "").strip().upper()
    if not value:
        return None
    return 1 if value in {"EZARC", "TOLESA"} else 0


def find_column_name(columns, *patterns: str) -> str | None:
    normalized_map = {}
    for col in columns:
        col_text = str(col).strip()
        normalized = re.sub(r"\s+", "", col_text).lower()
        normalized_map[normalized] = col_text
    for pattern in patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        for normalized, original in normalized_map.items():
            if compiled.search(normalized):
                return original
    return None


def normalize_month_col(col) -> str:
    raw = str(col).strip()
    match = re.match(r"(\d{4}-\d{2})", raw)
    return match.group(1) if match else raw


def extract_month_columns(df):
    col_map = {c: normalize_month_col(c) for c in df.columns}
    df = df.rename(columns=col_map)
    month_cols = [c for c in df.columns if re.fullmatch(r"\d{4}-\d{2}", str(c))]
    return df, month_cols
