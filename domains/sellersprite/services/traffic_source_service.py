# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Traffic source API service."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core import config as web_config

from ..repositories.amazon_item_repo import upsert_traffic_source_items


def export_traffic_source_via_api(
    driver,
    download_dir: Path,
    site: str,
    category: str,
    asins: list[str] | None = None,
    *,
    page_size: int | None = 100,
    batch_size: int = 20,
    market_resolver=None,
    log=None,
) -> tuple[int, int, list[Path], int]:
    logger = log or (lambda _message: None)
    normalized_asins: list[str] = []
    seen: set[str] = set()
    for asin in asins or []:
        value = str(asin or "").strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized_asins.append(value)

    if not normalized_asins:
        logger("UC 流量来源接口跳过：无可用 ASIN")
        return 0, 0, [], 0

    if market_resolver is None:
        raise RuntimeError("traffic source service requires market_resolver")
    market = market_resolver(site)
    save_dir = download_dir / "traffic source api"
    save_dir.mkdir(parents=True, exist_ok=True)

    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
    user_agent = driver.execute_script("return navigator.userAgent;")
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Referer": web_config.SELLERSPRITE_COMPETITOR_LOOKUP_URL,
    }

    session = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    def _extract_records(payload):
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("records", "list", "rows", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []

    success_count = 0
    fail_count = 0
    downloaded_files: list[Path] = []
    upserted_rows = 0
    total_items: list[dict] = []
    total_records: list[dict] = []
    total_seen_asins: set[str] = set()
    normalized_batch_size = max(1, int(batch_size or 20))
    try:
        batches = [
            normalized_asins[idx : idx + normalized_batch_size]
            for idx in range(0, len(normalized_asins), normalized_batch_size)
        ]
        for batch_no, batch_asins in enumerate(batches, 1):
            base_params = {
                "keywordOrAsin": " ".join(batch_asins),
                "market": market,
                "order": 1,
                "desc": "true",
                "month": "",
            }
            if page_size is not None:
                base_params["pageSize"] = int(page_size)

            batch_items: list[dict] = []
            batch_records: list[dict] = []
            page_responses: list[dict] = []
            batch_seen_asins: set[str] = set()
            params = dict(base_params)
            params["pageNo"] = 1
            time.sleep(random.uniform(0.5, 1.3))
            resp = session.get(
                "https://www.sellersprite.com/v3/api/relation/ta/source",
                params=params,
                headers=headers,
                cookies=cookies,
                timeout=30,
            )
            body_preview = resp.text[:300]
            resp.raise_for_status()
            data = resp.json()
            code = str(data.get("code") or "").strip().upper() if isinstance(data, dict) else ""
            if code and code != "OK":
                raise RuntimeError(f"code={code}, body={body_preview}")

            payload = data.get("data") if isinstance(data, dict) else data
            records = _extract_records(payload)
            pager = payload.get("pager") if isinstance(payload, dict) else {}
            items = pager.get("items") if isinstance(pager, dict) else []
            if not isinstance(items, list):
                items = []
            if not records:
                records = items

            total = pager.get("total") if isinstance(pager, dict) else None
            pages = pager.get("pages") if isinstance(pager, dict) else None
            has_next_page = pager.get("hasNextPage") if isinstance(pager, dict) else None
            missing = payload.get("missing") if isinstance(payload, dict) else None
            page_responses.append(
                {
                    "pageNo": 1,
                    "request": params,
                    "response": data,
                    "returned_items": len(items),
                    "records": len(records),
                    "total": total,
                    "pages": pages,
                    "hasNextPage": has_next_page,
                    "missing": missing,
                }
            )

            new_item_count = 0
            for item in items:
                asin = str((item or {}).get("asin") or "").strip().upper()
                if asin and asin not in batch_seen_asins:
                    batch_seen_asins.add(asin)
                    batch_items.append(item)
                    new_item_count += 1
            batch_records.extend(records if isinstance(records, list) else [])

            logger(
                f"UC 流量来源接口分页成功: batch={batch_no}/{len(batches)}, pageNo=1, "
                f"batch_asins={len(batch_asins)}, returned_items={len(items)}, new_items={new_item_count}, "
                f"total={total}, pages={pages}, hasNextPage={has_next_page}, missing={missing}"
            )

            safe_joined = "_".join(batch_asins[:3])
            if len(batch_asins) > 3:
                safe_joined += f"_plus{len(batch_asins) - 3}"
            save_path = save_dir / f"source_{safe_joined}.json"
            save_path.write_text(
                json.dumps(
                    {
                        "site": (site or "US").strip().upper() or "US",
                        "market": market,
                        "batch_no": batch_no,
                        "batch_count": len(batches),
                        "batch_asins": batch_asins,
                        "request": base_params,
                        "page_responses": page_responses,
                        "items": batch_items,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            downloaded_files.append(save_path)

            new_total_items = 0
            for item in batch_items:
                asin = str((item or {}).get("asin") or "").strip().upper()
                if asin and asin not in total_seen_asins:
                    total_seen_asins.add(asin)
                    total_items.append(item)
                    new_total_items += 1
            total_records.extend(batch_records)
            logger(
                f"UC 流量来源接口批次完成: batch={batch_no}/{len(batches)}, "
                f"batch_returned={len(batch_items)}, total_unique_items={len(total_items)}, "
                f"new_total_items={new_total_items}, file={save_path.name}"
            )

        upserted_rows = upsert_traffic_source_items(site=site, category=category, items=total_items)
        logger(
            f"UC 流量来源接口成功: asins={len(normalized_asins)}, "
            f"returned_items={len(total_items)}, records={len(total_records)}, dim_upsert={upserted_rows}, "
            f"batches={len(batches)}, files={len(downloaded_files)}"
        )
        success_count += 1
    except Exception as exc:
        fail_count += 1
        logger(f"UC 流量来源接口失败: asins={len(normalized_asins)}, err={exc}")

    return success_count, fail_count, downloaded_files, upserted_rows
