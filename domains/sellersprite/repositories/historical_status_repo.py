# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Repository helpers for historical trend task status."""

from __future__ import annotations

import time

from core.data.client import execute, fetch_all


HISTORICAL_TREND_STATUS_TABLE = "auto_scheduler.fact_bi_amazon_product_detail_status"


def load_success_asins(site: str, category: str = "") -> set[str]:
    run_date = time.strftime("%Y-%m-%d")
    site_code = (site or "US").strip().upper() or "US"

    query = f"""
        SELECT asin
        FROM {HISTORICAL_TREND_STATUS_TABLE}
        WHERE run_date = %s
          AND site = %s
          AND status = 'success'
    """
    params = [run_date, site_code]

    if category:
        query += " AND category = %s"
        params.append(category)

    rows = fetch_all(query, tuple(params))
    return {
        str(row.get("asin") or "").strip().upper()
        for row in rows
        if str(row.get("asin") or "").strip()
    }


def upsert_status(
    site: str,
    asin: str,
    status: str,
    *,
    category: str = "",
    message: str = "",
    artifact_path: str = "",
    started_at: str = "",
    ended_at: str = "",
) -> None:
    run_date = time.strftime("%Y-%m-%d")
    site_code = (site or "US").strip().upper() or "US"
    sql = f"""
    INSERT INTO {HISTORICAL_TREND_STATUS_TABLE} (
      run_date,
      site,
      category,
      asin,
      status,
      message,
      artifact_path,
      started_at,
      ended_at
    ) VALUES (
      %s, %s, %s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, '')
    )
    ON DUPLICATE KEY UPDATE
      category = VALUES(category),
      status = VALUES(status),
      message = VALUES(message),
      artifact_path = VALUES(artifact_path),
      started_at = COALESCE(VALUES(started_at), started_at),
      ended_at = COALESCE(VALUES(ended_at), ended_at)
    """
    execute(
        sql,
        (
            run_date,
            site_code,
            str(category or "").strip(),
            str(asin or "").strip().upper(),
            str(status or "").strip().lower(),
            message,
            artifact_path,
            started_at,
            ended_at,
        ),
    )
