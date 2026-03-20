#!/usr/bin/python3
"""包装 aggregate_data 的功能，提供可调用的聚合函数（已搬迁至 Services 包）。"""

import asyncio
from typing import Any, Dict

import aiomysql
from .aggregate_data import (
    _best_acos_week,
    _best_acos_week_for_sku,
    _calc_derived,
    _compact_metrics,
    _currency_symbol,
    _get_sid_type_country_from_reports,
    _query_campaigns_from_db,
    _query_negative_rules_cross,
    _query_negative_rules_single,
    _recent_ranges,
    _sum_reports_from_db,
    _sum_reports_sb_by_sku,
    _sum_reports_sp_by_sku,
    _query_negative_rules_target,
)
from .synchronize import Settings, OpenApiBase, get_lingxing_access_token


async def aggregate_campaign_data(
    country: str, campaign_name: str, sku: str = None
) -> Dict[str, Any]:
    """聚合广告活动数据，返回完整的聚合结果字典。
    逻辑与原 `campaign_aggregator.py` 保持一致。
    """
    settings = Settings()
    db_name = settings.db_config.get("db") or ""
    if not db_name:
        raise RuntimeError("未设置 DB_NAME，无法在数据库中校验和汇总")

    try:
        pool = await aiomysql.create_pool(**settings.db_config)
    except Exception as exc:
        raise RuntimeError(f"连接数据库失败: {exc}") from exc

    try:
        db_rows = await _query_campaigns_from_db(pool, campaign_name, country)
        if not db_rows:
            raise ValueError(
                f"未找到名称+国家匹配的广告活动: {campaign_name} ({country})"
            )
        if len(db_rows) > 1:
            raise ValueError(
                f"找到 {len(db_rows)} 条同名同国广告活动，请确保名称唯一"
            )

        target_ids = {cid for cid, _ in db_rows}
        cid = next(iter(target_ids))

        sid_type_ctry = await _get_sid_type_country_from_reports(pool, cid)
        if not sid_type_ctry:
            raise ValueError(
                f"在 amazon_campaign_reports 中未找到该 campaign_id 的记录"
            )

        target_sid, target_campaign_type, target_country = sid_type_ctry
        if country and target_country and str(country).strip() != str(target_country).strip():
            country = target_country

        campaign_type_lower = str(target_campaign_type or "").lower()
        is_sb = campaign_type_lower.startswith("sb")
        currency_symbol = _currency_symbol(country)

        ranges = _recent_ranges()

        async def _fetch(label: str):
            start_d, end_d = ranges[label]
            sums = await _sum_reports_from_db(
                pool, target_ids, target_sid, target_campaign_type, start_d, end_d
            )
            derived = _calc_derived(sums, start_d, end_d)
            return label, sums, derived

        needed_labels = ["last_7", "prev_7", "last_14", "prev_14", "last_30", "prev_30"]
        fetched = await asyncio.gather(*[_fetch(label) for label in needed_labels])
        sums_map = {label: sums for label, sums, _ in fetched}
        derived_map = {label: derived for label, _, derived in fetched}

        def _has_data(sums: Dict[str, float]) -> bool:
            return any((sums.get(k, 0) or 0) > 0 for k in ["impressions", "clicks", "cost", "sales", "orders", "units"])

        has_prev_14 = _has_data(sums_map["prev_14"])

        # 趋势判定：仅对 ACoS 做“0 视为更差”的规则
        def _trend_with_zero(prev: float, curr: float) -> str:
            if prev == 0 and curr != 0:
                return "down"
            if prev != 0 and curr == 0:
                return "up"
            if curr > prev:
                return "up"
            if curr < prev:
                return "down"
            return "flat"

        last7_acos = derived_map["last_7"].get("ACoS", 0)
        prev7_acos = derived_map["prev_7"].get("ACoS", 0)
        trend_7 = _trend_with_zero(prev7_acos, last7_acos)
        acos_up_7 = trend_7 == "up"
        acos_down_7 = trend_7 == "down"

        if has_prev_14:
            last14_acos = derived_map["last_14"].get("ACoS", 0)
            prev14_acos = derived_map["prev_14"].get("ACoS", 0)
            # 新规则：前14天有数据时，若近14天 ACoS=0，直接判定变差（不看 7 天）
            if last14_acos == 0:
                is_worse = True
            else:
                trend_14 = _trend_with_zero(prev14_acos, last14_acos)
                acos_up_14 = trend_14 == "up"
                acos_down_14 = trend_14 == "down"
                is_worse = acos_up_7 and acos_up_14
        else:
            is_worse = acos_up_7

        need_30 = is_worse
        result = {
            "campaign_name": campaign_name,
            "sku": sku,
            "compare_7d": {
                "current": _compact_metrics(derived_map["last_7"], currency_symbol),
                "prev": _compact_metrics(derived_map["prev_7"], currency_symbol),
            },
            "compare_14d": {
                "current": _compact_metrics(derived_map["last_14"], currency_symbol),
                "prev": _compact_metrics(derived_map["prev_14"], currency_symbol),
            },
            "compare_30d": {
                "current": _compact_metrics(derived_map["last_30"], currency_symbol),
                "prev": _compact_metrics(derived_map["prev_30"], currency_symbol),
            },
        }

        if need_30:
            best_week = await _best_acos_week(pool, target_ids, target_sid, target_campaign_type)
            if not best_week:
                best_week = await _best_acos_week_for_sku(
                    pool,
                    target_sid,
                    target_campaign_type,
                    base_campaign_id=cid if is_sb else None,
                    sku=sku if not is_sb else None,
                )
            if best_week:
                result["best_week"] = _compact_metrics(best_week["metrics"], currency_symbol)
                bid_reco = best_week["metrics"].get("CPC", 0.0)
                result["recommended_settings"] = {"Bid": f"{currency_symbol}{bid_reco:.2f}"}
            else:
                bid_reco = derived_map["last_14"].get("CPC", 0.0)
                result["recommended_settings"] = {"Bid": f"{currency_symbol}{bid_reco:.2f}"}

        async def _sum_sku_all(start_d: str, end_d: str) -> Dict[str, float]:
            if is_sb:
                return await _sum_reports_sb_by_sku(
                    pool, cid, target_sid, target_campaign_type, start_d, end_d
                )
            if not sku:
                raise ValueError("非SB广告类型需要提供SKU参数")
            return await _sum_reports_sp_by_sku(
                pool, sku, target_sid, target_campaign_type, start_d, end_d
            )

        start_14, end_14 = ranges["last_14"]
        sku_sums = await _sum_sku_all(start_14, end_14)
        sku_summary = _calc_derived(sku_sums, start_14, end_14)
        if sku_summary:
            result["sku_14d_all"] = _compact_metrics(sku_summary, currency_symbol)

            start_30, end_30 = ranges["last_30"]
            sku_30_sums = await _sum_sku_all(start_30, end_30)
            result["sku_30d_all"] = _compact_metrics(
                _calc_derived(sku_30_sums, start_30, end_30),
                currency_symbol,
            )

            acos = sku_summary.get("ACoS", 0.0)
            cvr = sku_summary.get("CVR", 0.0)
            cpo = sku_summary.get("CPO", 0.0)
            result["thresholds"] = {
                "acos_super_high": round(acos * 1.5, 4),
                "acos_high": round(acos * 1.2, 4),
                "acos_low": round(acos * 0.8, 4),
                "cvr_high": round(cvr * 1.2, 4),
                "cvr_low": round(cvr * 0.8, 4),
                "cpo_high_click": round(cpo * 1.5, 2),
                "cpo_low_click": round(cpo * 0.5, 2),
                "double_cpo": round(cpo * 2, 2),
            }

            neg_rules_campaign = await _query_negative_rules_single(
                pool, target_ids, target_campaign_type, start_14, end_14, cpo
            )
            neg_rules_cross = await _query_negative_rules_cross(
                pool,
                target_ids,
                target_campaign_type,
                target_sid,
                start_14,
                end_14,
                cpo,
                base_campaign_id=cid,
                sku=sku,
                is_sb=is_sb,
            )
            try:
                settings = Settings()
                op_api = OpenApiBase(settings.host, settings.app_id, settings.app_secret, enable_cache=False)
                access_token = await get_lingxing_access_token(settings, op_api)
                neg_rules_target = await _query_negative_rules_target(pool, op_api, access_token, cid, target_campaign_type, start_14, end_14, cpo)
            except Exception:
                neg_rules_target = []

            result["negative_rules_target"] = neg_rules_target
            result["negative_rules_ad"] = neg_rules_campaign
            result["negative_rules_ad_groups"] = neg_rules_cross

        return result

    finally:
        pool.close()
        await pool.wait_closed()


