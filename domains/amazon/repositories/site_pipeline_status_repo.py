#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Repository for Amazon site pipeline status."""

from __future__ import annotations

from core.data.client import execute, fetch_all


SITE_PIPELINE_STATUS_TABLE = "fact_bi_amazon_site_pipeline_status"


def upsert_status(
    run_date: str,
    site: str,
    target_id: str,
    category: str,
    status: str,
    *,
    started_at: str = "",
    ended_at: str = "",
    error: str = "",
) -> None:
    normalized_site = (site or "").strip().upper()
    normalized_target_id = str(target_id or "").strip()
    normalized_category = str(category or "").strip()
    sql = f"""
    INSERT INTO {SITE_PIPELINE_STATUS_TABLE} (
      run_date,
      site,
      target_id,
      category,
      status,
      started_at,
      ended_at,
      error
    ) VALUES (
      %s, %s, %s, NULLIF(%s, ''), %s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, '')
    )
    ON DUPLICATE KEY UPDATE
      category = VALUES(category),
      status = VALUES(status),
      started_at = COALESCE(VALUES(started_at), started_at),
      ended_at = COALESCE(VALUES(ended_at), ended_at),
      error = VALUES(error)
    """
    execute(
        sql,
        (
            run_date,
            normalized_site,
            normalized_target_id,
            normalized_category,
            status.lower(),
            started_at,
            ended_at,
            error,
        ),
    )


def get_today_success_job_keys(run_date: str) -> set[tuple[str, str]]:
    rows = fetch_all(
        f"""
        SELECT site, target_id
        FROM {SITE_PIPELINE_STATUS_TABLE}
        WHERE run_date = %s
          AND status = 'success'
        """,
        (run_date,),
    )
    keys: set[tuple[str, str]] = set()
    for row in rows:
        site = str(row.get("site") or "").strip().upper()
        target_id = str(row.get("target_id") or "").strip()
        if not site or not target_id:
            continue
        keys.add((site, target_id))
    return keys
