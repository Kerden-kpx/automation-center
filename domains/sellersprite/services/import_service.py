# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Import orchestration service."""

from __future__ import annotations

from pathlib import Path

from ..importers.competitor_importer import import_competitor_export
from ..importers.daily_sales_importer import import_daily_sales_volume_from_folder
from ..importers.sales_importer import import_sales_export


def import_exports(export_files: dict[str, Path], site: str, category: str = "", log=None) -> dict[str, int]:
    logger = log or (lambda _message: None)
    monthly_rows = 0
    dim_rows = 0
    site_code = (site or "US").strip().upper() or "US"
    sales_prefix = f"product-{site_code}-sales-"
    competitor_prefix = f"Competitor-{site_code}-Last-30-days"
    for prefix, path in export_files.items():
        name = path.name
        if prefix.startswith(sales_prefix) or name.startswith(sales_prefix):
            logger(f"入库: {sales_prefix} 文件 -> fact_bi_amazon_product_month ({name})")
            monthly_rows += import_sales_export(path, site=site)
        elif prefix == competitor_prefix or name.startswith(competitor_prefix):
            logger(f"入库: {competitor_prefix} 文件 -> 更新 dim_bi_amazon_item ({name})")
            dim_rows += import_competitor_export(path, site=site, category=category)
    return {"monthly_rows": monthly_rows, "dim_rows": dim_rows}


def import_daily_sales(download_dir: Path, site: str, log=None) -> dict[str, int]:
    return import_daily_sales_volume_from_folder(download_dir, site=site, log=log)
