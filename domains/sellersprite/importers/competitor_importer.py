# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Competitor export importer."""

from __future__ import annotations

from pathlib import Path

from ..repositories.amazon_item_repo import upsert_competitor_items
from ..support import derive_type, find_column_name, parse_date, parse_float, parse_int


def import_competitor_export(path: Path, site: str, category: str = "") -> int:
    import pandas as pd

    if not path.exists():
        raise RuntimeError(f"导入失败：文件不存在 {path}")

    df = pd.read_excel(path, sheet_name=0)
    if "ASIN" not in df.columns:
        raise RuntimeError(f"导入失败：{path.name} 缺少 ASIN 列")

    site_code = (site or "US").strip().upper() or "US"
    df["ASIN"] = df["ASIN"].astype(str).str.strip().str.upper()
    df = df[df["ASIN"] != ""]
    if df.empty:
        return 0

    sales_col = find_column_name(df.columns, r"^月销售额\(", r"^月销售额$")
    category_name = str(category or "").strip() or None
    params: list[tuple] = []

    for _, row in df.iterrows():
        asin = str(row.get("ASIN") or "").strip().upper()
        if not asin:
            continue
        brand = str(row.get("品牌") or "").strip() or None
        params.append(
            (
                asin,
                site_code,
                category_name,
                1,
                str(row.get("父ASIN") or "").strip() or None,
                str(row.get("商品标题") or "").strip() or None,
                str(row.get("商品主图") or "").strip() or None,
                str(row.get("商品详情页链接") or "").strip() or None,
                brand,
                parse_float(row.get("评分")),
                parse_int(row.get("评分数")),
                parse_int(row.get("大类BSR")),
                parse_int(row.get("变体数")),
                parse_date(row.get("上架时间")),
                parse_int(row.get("月销量")),
                parse_float(row.get(sales_col)) if sales_col else None,
                derive_type(brand),
            )
        )

    return upsert_competitor_items(params)
