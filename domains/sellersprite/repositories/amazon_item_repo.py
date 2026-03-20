# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Repository helpers for dim_bi_amazon_item."""

from __future__ import annotations

from core.data.client import execute_many, fetch_all

from ..support import BI_AMAZON_ITEM_TABLE, parse_float, parse_int


def upsert_competitor_items(rows: list[tuple]) -> int:
    if not rows:
        return 0
    sql = f"""
    INSERT INTO {BI_AMAZON_ITEM_TABLE} (
      asin, site, category, createtime,
      is_variation,
      parent_asin, title, image_url, product_url, brand,
      score, comment_count, category_rank, variation_count,
      launch_date, sales_volume, sales, type
    ) VALUES (
      %s, %s, %s, CURDATE(),
      %s,
      %s, %s, %s, %s, %s,
      %s, %s, %s, %s,
      %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
      category = COALESCE(category, VALUES(category)),
      is_variation = COALESCE(is_variation, VALUES(is_variation)),
      parent_asin = COALESCE(VALUES(parent_asin), parent_asin),
      title = COALESCE(VALUES(title), title),
      image_url = COALESCE(VALUES(image_url), image_url),
      product_url = COALESCE(VALUES(product_url), product_url),
      brand = COALESCE(VALUES(brand), brand),
      score = COALESCE(VALUES(score), score),
      comment_count = COALESCE(VALUES(comment_count), comment_count),
      category_rank = COALESCE(VALUES(category_rank), category_rank),
      variation_count = COALESCE(VALUES(variation_count), variation_count),
      launch_date = COALESCE(VALUES(launch_date), launch_date),
      sales_volume = COALESCE(VALUES(sales_volume), sales_volume),
      sales = COALESCE(VALUES(sales), sales),
      type = COALESCE(VALUES(type), type)
    """
    return int(execute_many(sql, rows) or 0)


def upsert_traffic_source_items(site: str, category: str, items: list[dict]) -> int:
    if not items:
        return 0

    site_code = (site or "US").strip().upper() or "US"
    category_name = str(category or "").strip() or None
    sql = f"""
    INSERT INTO {BI_AMAZON_ITEM_TABLE} (
      asin,
      site,
      category,
      createtime,
      price,
      organic_search_terms,
      ad_search_terms,
      all_traffic_terms,
      search_recommend_terms
    ) VALUES (
      %s, %s, %s, CURDATE(), %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
      category = COALESCE(category, VALUES(category)),
      price = COALESCE(VALUES(price), price),
      organic_search_terms = COALESCE(VALUES(organic_search_terms), organic_search_terms),
      ad_search_terms = COALESCE(VALUES(ad_search_terms), ad_search_terms),
      all_traffic_terms = COALESCE(VALUES(all_traffic_terms), all_traffic_terms),
      search_recommend_terms = COALESCE(VALUES(search_recommend_terms), search_recommend_terms)
    """

    params: list[tuple] = []
    for item in items:
        asin = str((item or {}).get("asin") or "").strip().upper()
        if not asin:
            continue
        counter = (item or {}).get("counter") or {}
        if not isinstance(counter, dict):
            counter = {}
        organic_terms = parse_int(counter.get("NATURAL_SEARCHING"))
        ad_terms = parse_int(counter.get("ADS"))
        recommend_terms = parse_int(counter.get("AMAZON_CHOICE"))
        params.append(
            (
                asin,
                site_code,
                category_name,
                parse_float((item or {}).get("price")),
                organic_terms,
                ad_terms,
                parse_int((item or {}).get("keywords")),
                recommend_terms or None,
            )
        )

    if not params:
        return 0
    return int(execute_many(sql, params) or 0)


def fetch_asins_for_today(site: str, categories: list[str] | None = None) -> list[str]:
    site_code = (site or "US").strip().upper() or "US"
    sql = f"""
        SELECT asin
        FROM {BI_AMAZON_ITEM_TABLE}
        WHERE createtime = CURDATE()
          AND site = %s
          AND asin IS NOT NULL
          AND asin <> ''
          AND bsr_rank IS NOT NULL
          AND bsr_rank <= 100
    """
    params: list[str] = [site_code]
    if categories:
        placeholders = ", ".join(["%s"] * len(categories))
        sql += f"\n          AND category IN ({placeholders})"
        params.extend(categories)
    sql += "\n        ORDER BY bsr_rank ASC, asin ASC"
    sql += "\n        LIMIT 100"
    rows = fetch_all(sql, tuple(params))
    asins: list[str] = []
    seen: set[str] = set()
    for row in rows:
        asin = str((row or {}).get("asin") or "").strip().upper()
        if not asin or asin in seen:
            continue
        seen.add(asin)
        asins.append(asin)
    return asins


def fetch_history_export_asins(site: str, category: str = "") -> list[str]:
    site_code = (site or "US").strip().upper() or "US"
    sql = f"""
        SELECT asin
        FROM {BI_AMAZON_ITEM_TABLE}
        WHERE createtime = CURDATE()
          AND site = %s
          AND asin IS NOT NULL
          AND asin <> ''
    """
    params: list[str] = [site_code]
    category_name = str(category or "").strip()
    if category_name:
        sql += "\n          AND category = %s"
        params.append(category_name)
    sql += "\n        ORDER BY asin"
    rows = fetch_all(sql, tuple(params))
    asins: list[str] = []
    seen: set[str] = set()
    for row in rows:
        asin = str((row or {}).get("asin") or "").strip().upper()
        if not asin or asin in seen:
            continue
        seen.add(asin)
        asins.append(asin)
    return asins


def fetch_top_category_for_today(site: str) -> str:
    site_code = (site or "US").strip().upper() or "US"
    rows = fetch_all(
        f"""
        SELECT category, COUNT(*) AS cnt
        FROM {BI_AMAZON_ITEM_TABLE}
        WHERE createtime = CURDATE()
          AND site = %s
          AND category IS NOT NULL
          AND category <> ''
        GROUP BY category
        ORDER BY cnt DESC, category ASC
        LIMIT 1
        """,
        (site_code,),
    )
    if not rows:
        return ""
    return str((rows[0] or {}).get("category") or "").strip()
