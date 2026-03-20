#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Repository for dim_bi_amazon_item."""

from __future__ import annotations

from typing import Any, Dict, List

from core.data.client import execute_many, fetch_all


def upsert_best_seller_rows(rows: List[Dict[str, Any]], site: str, category_field_mapper) -> int:
    sql = """
    INSERT INTO dim_bi_amazon_item (
      asin,
      site,
      category,
      bsr_rank,
      price,
      is_variation,
      conversion_rate,
      conversion_rate_period,
      organic_traffic_count,
      organic_search_terms,
      ad_traffic_count,
      ad_search_terms,
      all_traffic_terms,
      search_recommend_terms,
      createtime
    ) VALUES (
      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE()
    )
    ON DUPLICATE KEY UPDATE
      category = VALUES(category),
      bsr_rank = VALUES(bsr_rank),
      price = VALUES(price),
      is_variation = VALUES(is_variation),
      conversion_rate = VALUES(conversion_rate),
      conversion_rate_period = VALUES(conversion_rate_period),
      organic_traffic_count = VALUES(organic_traffic_count),
      organic_search_terms = VALUES(organic_search_terms),
      ad_traffic_count = VALUES(ad_traffic_count),
      ad_search_terms = VALUES(ad_search_terms),
      all_traffic_terms = VALUES(all_traffic_terms),
      search_recommend_terms = VALUES(search_recommend_terms)
    """
    data = []
    for row in rows:
        asin = category_field_mapper["clean_text"](row.get("asin"))
        if not asin:
            continue
        data.append(
            (
                asin,
                site,
                category_field_mapper["clean_text"](row.get("category")) or None,
                category_field_mapper["to_int"](row.get("rank")),
                category_field_mapper["to_price"](row.get("price")),
                0,
                category_field_mapper["to_rate"](row.get("conversion_rate")),
                category_field_mapper["clean_text"](row.get("conversion_rate_period")) or None,
                category_field_mapper["to_int"](row.get("organic_traffic_score_7d")),
                category_field_mapper["to_int"](row.get("organic_search_terms")),
                category_field_mapper["to_int"](row.get("ad_traffic_score_7d")),
                category_field_mapper["to_int"](row.get("ad_traffic_terms")),
                category_field_mapper["to_int"](row.get("all_traffic_terms")),
                category_field_mapper["to_int"](row.get("search_recommend_terms")),
            )
        )
    if not data:
        return 0
    return int(execute_many(sql, data) or 0)


def load_targets_for_today(site: str, allowed_categories: list[str], asin_extractor) -> List[Dict[str, str]]:
    sql = """
        SELECT asin, product_url, category
        FROM dim_bi_amazon_item
        WHERE createtime = CURDATE()
          AND site = %s
          AND product_url IS NOT NULL
          AND product_url <> ''
    """
    params: List[Any] = [site]
    if allowed_categories:
        placeholders = ", ".join(["%s"] * len(allowed_categories))
        sql += f"\n          AND category IN ({placeholders})"
        params.extend(allowed_categories)
    sql += "\n        ORDER BY asin"

    rows = fetch_all(sql, tuple(params))
    seen_asin = set()
    seen_url = set()
    targets: List[Dict[str, str]] = []
    for row in rows:
        asin = str((row or {}).get("asin") or "").strip().upper()
        url = str((row or {}).get("product_url") or "").strip()
        category = str((row or {}).get("category") or "").strip()
        if not url:
            continue
        if not asin:
            asin = asin_extractor(url)
        if asin:
            if asin in seen_asin:
                continue
            seen_asin.add(asin)
        else:
            if url in seen_url:
                continue
            seen_url.add(url)
        targets.append({"asin": asin, "url": url, "category": category})
    return targets


def update_list_price_rows(rows: List[Dict[str, str]], to_price_decimal, to_rate_decimal) -> int:
    sql = """
    UPDATE dim_bi_amazon_item
    SET list_price = COALESCE(%s, list_price),
        promotion_tags = %s,
        conversion_rate = COALESCE(%s, conversion_rate),
        conversion_rate_period = COALESCE(%s, conversion_rate_period)
    WHERE asin = %s
      AND site = %s
      AND createtime = CURDATE()
    """

    params = []
    for row in rows:
        asin = str(row.get("asin") or "").strip().upper()
        site = str(row.get("site") or "").strip().upper()
        list_price = to_price_decimal(str(row.get("list_price") or ""))
        promotion_tags = str(row.get("promotion_tags") or "").strip() or None
        conversion_rate = to_rate_decimal(str(row.get("conversion_rate") or ""))
        conversion_rate_period = str(row.get("conversion_rate_period") or "").strip() or None
        if not asin or not site:
            continue
        if list_price is None and promotion_tags is None and conversion_rate is None and conversion_rate_period is None:
            continue
        params.append((list_price, promotion_tags, conversion_rate, conversion_rate_period, asin, site))

    if not params:
        return 0
    return int(execute_many(sql, params) or 0)
