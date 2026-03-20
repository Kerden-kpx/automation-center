# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Repository helpers for fact_bi_amazon_product_month."""

from __future__ import annotations

from core.data.client import execute_many


def upsert_month_rows(rows: list[tuple]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO fact_bi_amazon_product_month (
      site, asin, month, sales_volume, sales, is_child, price
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
      sales_volume = VALUES(sales_volume),
      sales = VALUES(sales),
      is_child = VALUES(is_child),
      price = VALUES(price)
    """
    return int(execute_many(sql, rows) or 0)
