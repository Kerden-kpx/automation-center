# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sales export importer."""

from __future__ import annotations

from pathlib import Path

from ..repositories.product_month_repo import upsert_month_rows
from ..support import extract_month_columns


def _build_long_df(excel_path: Path, sheet_name: str, value_col: str):
    import pandas as pd

    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    if "ASIN" not in df.columns:
        raise RuntimeError(f"{sheet_name} 缺少 ASIN 列")
    df, month_cols = extract_month_columns(df)
    if not month_cols:
        raise RuntimeError(f"{sheet_name} 未找到 YYYY-MM 日期列")
    df = df[["ASIN"] + month_cols].copy()
    df["ASIN"] = df["ASIN"].astype(str).str.strip().str.upper()
    df = df[df["ASIN"] != ""]
    return df.melt(id_vars=["ASIN"], value_vars=month_cols, var_name="month", value_name=value_col)


def _try_build_long_df(excel_path: Path, sheet_name: str, value_col: str):
    import pandas as pd

    try:
        return _build_long_df(excel_path, sheet_name, value_col)
    except Exception:
        return pd.DataFrame(columns=["ASIN", "month", value_col])


def import_sales_export(path: Path, site: str) -> int:
    import pandas as pd

    if not path.exists():
        raise RuntimeError(f"导入失败：文件不存在 {path}")

    site_code = (site or "US").strip().upper() or "US"
    volume_df = _build_long_df(path, "产品历史月销量", "sales_volume")
    sales_df = _build_long_df(path, "历史月销售额", "sales")
    child_volume_df = _try_build_long_df(path, "子体历史月销量", "sales_volume")
    child_sales_df = _try_build_long_df(path, "子体历史月销售额", "sales")
    price_df = _try_build_long_df(path, "历史月价格", "price")

    def _to_numeric(series):
        cleaned = series.astype(str).str.replace(",", "", regex=False).str.replace(r"[^\d\.-]", "", regex=True)
        return pd.to_numeric(cleaned, errors="coerce")

    volume_df["sales_volume"] = _to_numeric(volume_df["sales_volume"]).round(0).astype("Int64")
    sales_df["sales"] = _to_numeric(sales_df["sales"])
    if not child_volume_df.empty:
        child_volume_df["sales_volume"] = _to_numeric(child_volume_df["sales_volume"]).round(0).astype("Int64")
    if not child_sales_df.empty:
        child_sales_df["sales"] = _to_numeric(child_sales_df["sales"])
    if not price_df.empty:
        price_df["price"] = _to_numeric(price_df["price"])

    merged_parent = pd.merge(volume_df, sales_df, on=["ASIN", "month"], how="outer")
    merged_parent = merged_parent.rename(columns={"ASIN": "asin"})
    merged_parent["site"] = site_code
    merged_parent["is_child"] = 0

    merged_child = pd.DataFrame(columns=merged_parent.columns)
    if not child_volume_df.empty or not child_sales_df.empty:
        merged_child = pd.merge(child_volume_df, child_sales_df, on=["ASIN", "month"], how="outer")
        merged_child = merged_child.rename(columns={"ASIN": "asin"})
        merged_child["site"] = site_code
        merged_child["is_child"] = 1

    if not price_df.empty:
        price_df = price_df.rename(columns={"ASIN": "asin"})
        price_df = price_df[["asin", "month", "price"]]
        merged_parent = merged_parent.merge(price_df, on=["asin", "month"], how="left")

    merged = pd.concat([merged_parent, merged_child], ignore_index=True)
    merged = merged.sort_values(["site", "asin", "month", "is_child"], ascending=[True, True, True, False])
    merged = merged.drop_duplicates(subset=["site", "asin", "month", "is_child"], keep="last")
    merged = merged[~(merged["sales_volume"].isna() & merged["sales"].isna())]
    merged["sales_volume"] = merged["sales_volume"].where(pd.notna(merged["sales_volume"]), None)
    merged["sales"] = merged["sales"].where(pd.notna(merged["sales"]), None)
    if "price" in merged.columns:
        merged["price"] = merged["price"].where(pd.notna(merged["price"]), None)
    merged = merged.astype(object).where(pd.notna(merged), None)
    if merged.empty:
        return 0

    rows = [
        tuple(row)
        for row in merged[["site", "asin", "month", "sales_volume", "sales", "is_child", "price"]].itertuples(
            index=False, name=None
        )
    ]
    return upsert_month_rows(rows)
