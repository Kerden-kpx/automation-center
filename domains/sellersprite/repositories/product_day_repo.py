# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Repository helpers for fact_bi_amazon_product_day."""

from __future__ import annotations

from core.data.client import execute_many


def upsert_daily_sales_volume_rows(rows: list[tuple]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO fact_bi_amazon_product_day (
      site, asin, date, sales_volume
    ) VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
      sales_volume = VALUES(sales_volume)
    """
    return int(execute_many(sql, rows) or 0)


def upsert_keepa_fact_rows(rows: list[tuple]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO fact_bi_amazon_product_day (
        site, asin, date,
        buybox_price, price, prime_price,
        coupon_price, coupon_discount, child_sales,
        fba_price, fbm_price, strikethrough_price,
        bsr_rank, bsr_reciprocating_saw_blades, rating, rating_count, seller_count
    ) VALUES (
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        buybox_price = VALUES(buybox_price),
        price = VALUES(price),
        prime_price = COALESCE(VALUES(prime_price), prime_price),
        coupon_price = COALESCE(VALUES(coupon_price), coupon_price),
        coupon_discount = COALESCE(VALUES(coupon_discount), coupon_discount),
        child_sales = COALESCE(VALUES(child_sales), child_sales),
        fba_price = COALESCE(VALUES(fba_price), fba_price),
        fbm_price = COALESCE(VALUES(fbm_price), fbm_price),
        strikethrough_price = COALESCE(VALUES(strikethrough_price), strikethrough_price),
        bsr_rank = COALESCE(VALUES(bsr_rank), bsr_rank),
        bsr_reciprocating_saw_blades = COALESCE(VALUES(bsr_reciprocating_saw_blades), bsr_reciprocating_saw_blades),
        rating = COALESCE(VALUES(rating), rating),
        rating_count = COALESCE(VALUES(rating_count), rating_count),
        seller_count = COALESCE(VALUES(seller_count), seller_count)
    """
    return int(execute_many(sql, rows) or 0)
