#!/usr/bin/python3
"""给定广告活动名称，直接在数据库里汇总 7/14 天对比，并按条件获取 30 天对比或 14 天汇总（不调用 OpenAPI）。"""

import asyncio
import re
from datetime import date, timedelta
import json
from typing import Any, Dict, List, Set, Tuple
import aiomysql
from .synchronize import Settings, OpenApiBase
# 全局调试开关，设置为 False 可临时屏蔽调试打印
DEBUG = False
import logging
logger = logging.getLogger(__name__)

async def _query_campaigns_from_db(pool, target_name: str, country: str) -> List[Tuple[str, str]]:
    """按名称+国家查询活动列表，区分大小写；从报表表校验国家。"""
    rows: List[Tuple[str, str]] = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            sql = (
                "SELECT DISTINCT A.campaign_id, A.name "
                "FROM dim_amazon_campaign A "
                "LEFT JOIN amazon_campaign_reports B ON A.campaign_id = B.campaign_id "
                "WHERE A.name = %s AND B.country = %s"
            )
            await cur.execute(sql, (target_name, country))
            rows = await cur.fetchall()
    return rows


async def _query_campaigns_like_sku(pool, sku: str, country: str) -> Set[str]:
    """按名称包含 sku 且国家匹配的 campaign_id 集合。"""
    if not sku:
        return set()

    rows: List[Tuple[str]] = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            sql = (
                "SELECT DISTINCT A.campaign_id "
                "FROM dim_amazon_campaign A "
                "LEFT JOIN amazon_campaign_reports B ON A.campaign_id = B.campaign_id "
                "WHERE A.name LIKE %s AND B.country = %s"
            )
            await cur.execute(sql, (f"%{sku}%", country))
            rows = await cur.fetchall()

    return {row[0] for row in rows if row and row[0]}


async def _get_sid_type_country_from_reports(pool, campaign_id: str) -> Tuple[int | str, str, str | None] | None:
    """根据唯一 campaign_id，从 amazon_campaign_reports 取 sid、campaign_type、country（优先最新记录）。"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            sql = (
                "SELECT sid, campaign_type, country "
                "FROM amazon_campaign_reports "
                "WHERE campaign_id=%s "
                "ORDER BY createtime DESC LIMIT 1"
            )
            await cur.execute(sql, (campaign_id,))
            row = await cur.fetchone()
            if row:
                return row[0], row[1], row[2]
    return None


def _recent_ranges(today: date | None = None) -> Dict[str, Tuple[str, str]]:
    """返回 7/14/30 天的 rolling 窗口（最近 N 天与前 N 天），日期为闭区间。

    约定：不包含今天和昨天，最近窗口的结束日是前天。
    """
    if today is None:
        today = date.today()

    def span(days: int, offset: int = 0) -> Tuple[str, str]:
        """最近/前 N 天，结束日为前天减去 offset 天。"""
        end = today - timedelta(days=2 + offset)
        start = end - timedelta(days=days - 1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    ranges: Dict[str, Tuple[str, str]] = {}
    for days in (7, 14, 30):
        ranges[f"last_{days}"] = span(days)
        ranges[f"prev_{days}"] = span(days, offset=days)
    return ranges


async def _sum_reports_from_db(
    pool,
    campaign_ids: Set[str],
    sid: int | str,
    campaign_type: str,
    start_date: str,
    end_date: str,
) -> Dict[str, float]:
    """在 amazon_campaign_reports 中聚合指定 campaign_id、sid、campaign_type 的指标。日期为闭区间。"""
    if not campaign_ids:
        return {k: 0.0 for k in ["impressions", "clicks", "cost", "sales", "orders", "units"]}

    # 使用半开区间 [start_date, end_date+1) 以覆盖整天
    end_next = (date.fromisoformat(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")

    placeholders = ",".join(["%s"] * len(campaign_ids))
    sql = (
        f"SELECT "
        f"COALESCE(SUM(impressions),0), COALESCE(SUM(clicks),0), COALESCE(SUM(cost),0), "
        f"COALESCE(SUM(sales),0), COALESCE(SUM(orders),0), COALESCE(SUM(units),0) "
        f"FROM amazon_campaign_reports "
        f"WHERE campaign_id IN ({placeholders}) AND sid=%s AND LOWER(campaign_type)=LOWER(%s) AND createtime >= %s AND createtime < %s"
    )

    values = list(campaign_ids) + [sid, campaign_type, start_date, end_next]
    result = [0.0] * 6
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
            fetch = await cur.fetchone()
            if fetch:
                result = [float(x or 0) for x in fetch]

    keys = ["impressions", "clicks", "cost", "sales", "orders", "units"]
    return dict(zip(keys, result))

async def _sum_reports_sb_by_sku(
    pool,
    base_campaign_id: str,
    sid: int | str,
    campaign_type: str,
    start_date: str,
    end_date: str,
) -> Dict[str, float]:
    """按基准 campaign_id 所属 ASIN 汇总同 sid、campaign_type 下的所有相关 campaign_id 的指标。"""
    if not base_campaign_id:
        return {k: 0.0 for k in ["impressions", "clicks", "cost", "sales", "orders", "units"]}

    end_next = (date.fromisoformat(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")

    sql = (
        "WITH target_asin AS ("
        "    SELECT DISTINCT asin FROM dim_amazon_sb_creativity WHERE campaign_id=%s LIMIT 1"
        "), "
        "cids AS ("
        "    SELECT DISTINCT a.campaign_id "
        "    FROM dim_amazon_sb_creativity a "
        "    JOIN target_asin ta ON a.asin = ta.asin "
        "    LEFT JOIN dim_amazon_campaign b ON a.campaign_id = b.campaign_id "
        "    WHERE a.sid=%s AND b.state = 'enabled' AND (b.name IS NULL OR b.name NOT LIKE %s)"
        ") "
        "SELECT "
        "COALESCE(SUM(r.impressions),0), COALESCE(SUM(r.clicks),0), COALESCE(SUM(r.cost),0), "
        "COALESCE(SUM(r.sales),0), COALESCE(SUM(r.orders),0), COALESCE(SUM(r.units),0) "
        "FROM amazon_campaign_reports r "
        "JOIN cids c ON r.campaign_id = c.campaign_id "
        "WHERE r.sid=%s AND LOWER(r.campaign_type) LIKE LOWER(%s) AND r.createtime >= %s AND r.createtime < %s"
    )

    values = [base_campaign_id, sid, "%捡漏%", sid, campaign_type, start_date, end_next]
    result = [0.0] * 6
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
            fetch = await cur.fetchone()
            if fetch:
                result = [float(x or 0) for x in fetch]

    keys = ["impressions", "clicks", "cost", "sales", "orders", "units"]
    return dict(zip(keys, result))


async def _sum_reports_sp_by_sku(
    pool,
    sku: str,
    sid: int | str,
    campaign_type: str,
    start_date: str,
    end_date: str,
) -> Dict[str, float]:
    """非 SB（SP/SD）使用商品报表 dim_amazon_product 通过 SKU 反查相关 campaign 汇总。"""
    if not sku:
        return {k: 0.0 for k in ["impressions", "clicks", "cost", "sales", "orders", "units"]}

    end_next = (date.fromisoformat(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")

    sql = (
        "WITH cids AS ("
        "    SELECT DISTINCT dp.campaign_id "
        "    FROM dim_amazon_product dp "
        "    LEFT JOIN dim_amazon_campaign dc ON dp.campaign_id = dc.campaign_id "
        "    WHERE dp.sku=%s and dc.state = 'enabled' AND (dc.name IS NULL OR dc.name NOT LIKE %s)"
        ") "
        "SELECT "
        "COALESCE(SUM(r.impressions),0), COALESCE(SUM(r.clicks),0), COALESCE(SUM(r.cost),0), "
        "COALESCE(SUM(r.sales),0), COALESCE(SUM(r.orders),0), COALESCE(SUM(r.units),0) "
        "FROM amazon_campaign_reports r "
        "JOIN cids c ON r.campaign_id = c.campaign_id "
        "WHERE r.sid=%s AND LOWER(r.campaign_type) LIKE LOWER(%s) AND r.createtime >= %s AND r.createtime < %s"
    )

    values = [sku, "%捡漏%", sid, campaign_type, start_date, end_next]
    result = [0.0] * 6
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
            fetch = await cur.fetchone()
            if fetch:
                result = [float(x or 0) for x in fetch]

    keys = ["impressions", "clicks", "cost", "sales", "orders", "units"]
    return dict(zip(keys, result))


async def _sum_reports_sb_by_asin(
    pool,
    asin: str | None,
    sid: int | str,
    start_date: str,
    end_date: str,
    campaign_type_pattern: str = "sb%",
) -> Dict[str, float]:
    """基于 ASIN 汇总同 sid、SB 系列广告的指标，用于 SP 回退时复用 SB 全品逻辑。"""
    if not asin:
        return {k: 0.0 for k in ["impressions", "clicks", "cost", "sales", "orders", "units"]}

    end_next = (date.fromisoformat(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")

    sql = (
        "WITH cids AS ("
        "    SELECT DISTINCT a.campaign_id "
        "    FROM dim_amazon_sb_creativity a "
        "    LEFT JOIN dim_amazon_campaign b ON a.campaign_id = b.campaign_id "
        "    WHERE a.asin=%s AND a.sid=%s AND b.state = 'enabled' AND (b.name IS NULL OR b.name NOT LIKE %s)"
        ") "
        "SELECT "
        "COALESCE(SUM(r.impressions),0), COALESCE(SUM(r.clicks),0), COALESCE(SUM(r.cost),0), "
        "COALESCE(SUM(r.sales),0), COALESCE(SUM(r.orders),0), COALESCE(SUM(r.units),0) "
        "FROM amazon_campaign_reports r "
        "JOIN cids c ON r.campaign_id = c.campaign_id "
        "WHERE r.sid=%s AND LOWER(r.campaign_type) LIKE %s AND r.createtime >= %s AND r.createtime < %s"
    )

    values = [asin, sid, "%捡漏%", sid, campaign_type_pattern, start_date, end_next]
    result = [0.0] * 6
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
            fetch = await cur.fetchone()
            if fetch:
                result = [float(x or 0) for x in fetch]

    keys = ["impressions", "clicks", "cost", "sales", "orders", "units"]
    return dict(zip(keys, result))


async def _get_asin_by_sku(pool, sku: str) -> str | None:
    """从 dim_amazon_product 获取给定 SKU 的 ASIN（任意一条）。"""
    if not sku:
        return None

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT asin FROM dim_amazon_product WHERE sku=%s AND asin IS NOT NULL AND asin <> '' LIMIT 1",
                (sku,),
            )
            row = await cur.fetchone()
            if row and row[0]:
                return str(row[0])
    return None


async def _query_negative_rules_single(
    pool,
    campaign_ids: Set[str],
    campaign_type: str,
    start_date: str,
    end_date: str,
    cpo_all: float,
) -> List[Dict[str, Any]]:
    """修改后逻辑：先查找广告活动所在的广告组，然后查找这些广告组里满足条件的否词。"""
    if not campaign_ids:
        return []

    placeholders = ",".join(["%s"] * len(campaign_ids))
    end_next = (date.fromisoformat(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")
    sql = (
        "WITH target_ad_groups AS ("
        "    SELECT DISTINCT ad_group_id "
        "    FROM amazon_queryword_reports "
        f"    WHERE campaign_id IN ({placeholders}) "
        "      AND createtime >= %s AND createtime < %s"
        ") "
        "SELECT query, is_asin, SUM(clicks) AS clicks "
        "FROM amazon_queryword_reports "
        "WHERE ad_group_id IN (SELECT ad_group_id FROM target_ad_groups) "
        "  AND LOWER(campaign_type)=LOWER(%s) "
        "  AND createtime >= %s AND createtime < %s "
        "GROUP BY query, is_asin "
        "HAVING SUM(orders) = 0 AND SUM(clicks) >= %s AND SUM(clicks) >= CASE WHEN is_asin = 1 THEN %s ELSE %s END "
        "ORDER BY clicks DESC"
    )

    values = (
        list(campaign_ids)
        + [start_date, end_next, campaign_type, start_date, end_next, 15, 1.5 * cpo_all, 2 * cpo_all]
    )
    rows: List[Tuple[Any, Any, Any]] = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
            fetch = await cur.fetchall()
            if fetch:
                rows = fetch

    neg_rules: List[Dict[str, Any]] = []
    for query, is_asin, clicks in rows:
        clicks_val = float(clicks or 0)
        is_asin_bool = bool(is_asin)
        neg_rules.append(
            {
                "query": query or "",
                "type": "Asin" if is_asin_bool else "词",
                "clicks": int(clicks_val),
            }
        )

    # 按类型分组输出：先 Asin 再 词，同组内按点击降序
    neg_rules.sort(key=lambda x: (0 if x["type"] == "Asin" else 1, -x["clicks"]))
    return neg_rules


async def _query_negative_rules_cross(
    pool,
    campaign_ids: Set[str],
    campaign_type: str,
    sid: int | str,
    start_date: str,
    end_date: str,
    cpo_all: float,
    base_campaign_id: str | None = None,
    sku: str | None = None,
    is_sb: bool = False,
) -> List[Dict[str, Any]]:
    """
    修改后逻辑：在基准广告活动的 query 集合基础上，查找相关广告组的表现，筛选精否候选。

    规则：
    - 基准 query：来自 campaign_ids 的用户搜索词，时间窗为 start_date~end_date。
    - SB 类型：通过基准 campaign_id 的 ASIN，查找同 sid、同 ASIN 的所有 campaign_id，再找这些 campaign_id 对应的广告组。
    - 非 SB 类型：通过 SKU 查找相关 campaign_id，过滤掉名称包含"捡漏"的，再找这些 campaign_id 对应的广告组。
    - 只查询指定 campaign_type 的数据。
    - 按 (query, is_asin) 维度汇总所有广告组的数据，要求 clicks>15 且 orders=0。
    - 阈值：Asin 用 1.5*CPO，普通词用 2*CPO（CPO 来自品 14 天汇总）。
    - 返回汇总数据，按 query 和类型分组。
    """
    if not campaign_ids:
        return []

    placeholders = ",".join(["%s"] * len(campaign_ids))
    end_next = (date.fromisoformat(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")

    # 根据广告类型构建不同的 SQL
    if is_sb:
        # SB 类型：通过 ASIN 查找相关 campaign_id 和广告组；
        # 去掉“仅限当前广告 query 集合”的限制，直接在同 ASIN、同 sid 的全部相关广告组里按 query 聚合。
        if not base_campaign_id:
            return []
        sql = (
            "WITH temp2 AS ("
            "    SELECT DISTINCT asin "
            "    FROM dim_amazon_sb_creativity "
            "    WHERE campaign_id = %s "
            "    LIMIT 1"
            "), "
            "temp3 AS ("
            "    SELECT DISTINCT a.campaign_id "
            "    FROM dim_amazon_sb_creativity a "
            "    JOIN temp2 ta ON a.asin = ta.asin "
            "    LEFT JOIN dim_amazon_campaign b ON a.campaign_id = b.campaign_id "
            "    WHERE a.sid = %s"
            "), "
            "temp4 AS ("
            "    SELECT DISTINCT ad_group_id "
            "    FROM amazon_queryword_reports "
            "    WHERE campaign_id IN (SELECT campaign_id FROM temp3) "
            "      AND createtime >= %s AND createtime < %s"
            "), "
            "temp5 AS ("
            "    SELECT query, is_asin, clicks, orders "
            "    FROM amazon_queryword_reports "
            "    WHERE createtime >= %s AND createtime < %s "
            "      AND ad_group_id IN (SELECT ad_group_id FROM temp4) "
            "      AND LOWER(campaign_type)=LOWER(%s)"
            "), "
            "temp6 AS ("
            "    SELECT query, is_asin, "
            "           SUM(clicks) AS clicks, SUM(orders) AS orders "
            "    FROM temp5 "
            "    GROUP BY query, is_asin "
            "    HAVING SUM(orders) = 0 AND SUM(clicks) >= %s"
            ") "
            "SELECT t6.query, t6.is_asin, t6.clicks "
            "FROM temp6 t6 "
            "WHERE t6.clicks >= CASE WHEN t6.is_asin = 1 THEN %s ELSE %s END "
            "ORDER BY t6.is_asin DESC, t6.clicks DESC"
        )
        # 占位符顺序：base_campaign_id, sid, start_date, end_next, start_date, end_next, campaign_type, min_clicks(15), 1.5*CPO, 2*CPO
        values = [
            base_campaign_id,
            sid,
            start_date,
            end_next,
            start_date,
            end_next,
            campaign_type,
            15,
            1.5 * cpo_all,
            2 * cpo_all,
        ]
    else:
        # 非 SB 类型：通过 SKU 查找相关 campaign_id（过滤\"捡漏\"）和广告组；
        # 不再限定“只看当前广告自身出现过的 query”，而是直接基于同品全部相关广告组的表现来筛选候选否词。
        if not sku:
            return []
        sql = (
            "WITH temp2 AS ("
            "    SELECT DISTINCT dp.campaign_id "
            "    FROM dim_amazon_product dp "
            "    LEFT JOIN dim_amazon_campaign dc ON dp.campaign_id = dc.campaign_id "
            "    INNER JOIN amazon_campaign_reports r ON dp.campaign_id = r.campaign_id "
            "    WHERE dp.sku = %s AND dp.state = 'enabled'"
            "      AND r.sid = %s AND r.campaign_type = %s"
            "      AND dc.name NOT LIKE %s"
            "), "
            "temp4 AS ("
            "    SELECT DISTINCT ad_group_id "
            "    FROM amazon_queryword_reports "
            "    WHERE campaign_id IN (SELECT campaign_id FROM temp2) "
            "      AND createtime >= %s AND createtime < %s"
            "), "
            "temp5 AS ("
            "    SELECT query, is_asin, clicks, orders "
            "    FROM amazon_queryword_reports "
            "    WHERE createtime >= %s AND createtime < %s "
            "      AND ad_group_id IN (SELECT ad_group_id FROM temp4) "
            "      AND LOWER(campaign_type)=LOWER(%s)"
            "), "
            "temp6 AS ("
            "    SELECT query, is_asin, "
            "           SUM(clicks) AS clicks, SUM(orders) AS orders "
            "    FROM temp5 "
            "    GROUP BY query, is_asin "
            "    HAVING SUM(orders) = 0 AND SUM(clicks) >= %s"
            ") "
            "SELECT t6.query, t6.is_asin, t6.clicks "
            "FROM temp6 t6 "
            "WHERE t6.clicks >= CASE WHEN t6.is_asin = 1 THEN %s ELSE %s END "
            "ORDER BY t6.is_asin DESC, t6.clicks DESC"
        )
        # 占位符顺序：sku, sid, campaign_type, "%捡漏%", start_date, end_next, start_date, end_next, campaign_type, min_clicks(15), 1.5*CPO, 2*CPO
        values = [
            sku,
            sid,
            campaign_type,
            "%捡漏%",
            start_date,
            end_next,
            start_date,
            end_next,
            campaign_type,
            15,
            1.5 * cpo_all,
            2 * cpo_all,
        ]

    # 调试信息：分步骤查询并打印详细信息
    if DEBUG:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                logger.debug("\n" + "=" * 120)
                logger.debug("[debug] negative_rules_ad_groups 调试信息")
                logger.debug("=" * 120)

                # 1. 查询广告组信息
                if is_sb:
                    debug_sql = (
                        "WITH temp2 AS ("
                        "    SELECT DISTINCT asin "
                        "    FROM dim_amazon_sb_creativity "
                        "    WHERE campaign_id = %s "
                        "    LIMIT 1"
                        "), "
                        "temp3 AS ("
                        "    SELECT DISTINCT a.campaign_id "
                        "    FROM dim_amazon_sb_creativity a "
                        "    JOIN temp2 ta ON a.asin = ta.asin "
                        "    LEFT JOIN dim_amazon_campaign b ON a.campaign_id = b.campaign_id "
                        "    WHERE a.sid = %s"
                        "), "
                        "temp4 AS ("
                        "    SELECT DISTINCT ad_group_id "
                        "    FROM amazon_queryword_reports "
                        "    WHERE campaign_id IN (SELECT campaign_id FROM temp3) "
                        "      AND createtime >= %s AND createtime < %s"
                        ") "
                        "SELECT DISTINCT t4.ad_group_id, g.name, dc.campaign_id, dc.name as campaign_name "
                        "FROM temp4 t4 "
                        "LEFT JOIN dim_amazon_campaign_groups g ON t4.ad_group_id = g.ad_group_id "
                        "LEFT JOIN amazon_queryword_reports qr ON t4.ad_group_id = qr.ad_group_id "
                        "LEFT JOIN dim_amazon_campaign dc ON qr.campaign_id = dc.campaign_id "
                        "WHERE qr.campaign_id IN (SELECT campaign_id FROM temp3) "
                        "  AND qr.createtime >= %s AND qr.createtime < %s"
                    )
                    debug_values = [base_campaign_id, sid, start_date, end_next, start_date, end_next]
                else:
                    debug_sql = (
                        "WITH temp2 AS ("
                        "    SELECT DISTINCT dp.campaign_id "
                        "    FROM dim_amazon_product dp "
                        "    LEFT JOIN dim_amazon_campaign dc ON dp.campaign_id = dc.campaign_id "
                        "    INNER JOIN amazon_campaign_reports r ON dp.campaign_id = r.campaign_id "
                        "    WHERE dp.sku = %s AND dp.state = 'enabled'"
                        "      AND r.sid = %s AND r.campaign_type = %s"
                        "), "
                        "temp3 AS ("
                        "    SELECT t2.campaign_id "
                        "    FROM temp2 t2 "
                        "    JOIN dim_amazon_campaign dc ON t2.campaign_id = dc.campaign_id "
                        "    WHERE dc.name NOT LIKE %s"
                        "), "
                        "temp4 AS ("
                        "    SELECT DISTINCT ad_group_id "
                        "    FROM amazon_queryword_reports "
                        "    WHERE campaign_id IN (SELECT campaign_id FROM temp3) "
                        "      AND createtime >= %s AND createtime < %s"
                        ") "
                        "SELECT DISTINCT t4.ad_group_id, g.name, dc.campaign_id, dc.name as campaign_name "
                        "FROM temp4 t4 "
                        "LEFT JOIN dim_amazon_campaign_groups g ON t4.ad_group_id = g.ad_group_id "
                        "LEFT JOIN amazon_queryword_reports qr ON t4.ad_group_id = qr.ad_group_id "
                        "LEFT JOIN dim_amazon_campaign dc ON qr.campaign_id = dc.campaign_id "
                        "WHERE qr.campaign_id IN (SELECT campaign_id FROM temp3) "
                        "  AND qr.createtime >= %s AND qr.createtime < %s"
                    )
                    debug_values = [sku, sid, campaign_type, "%捡漏%", start_date, end_next, start_date, end_next]

                await cur.execute(debug_sql, debug_values)
                debug_rows = await cur.fetchall()

                logger.debug(f"\n[1] 相关广告组信息 (temp4): 共 {len(debug_rows)} 个")
                if debug_rows:
                    logger.debug(f"{'广告组ID':<20} {'广告组名称':<30} {'广告活动ID':<20} {'广告活动名称':<50}")
                    logger.debug("-" * 120)
                    for ad_group_id, ad_group_name, campaign_id, campaign_name in debug_rows[:10]:
                        logger.debug(f"{str(ad_group_id or ''):<20} {str(ad_group_name or ''):<30} {str(campaign_id or ''):<20} {str(campaign_name or ''):<50}")
                    if len(debug_rows) > 10:
                        logger.debug(f"... 还有 {len(debug_rows) - 10} 个广告组")

                # 2. 查询 temp5 阶段：相关广告组内 query 汇总数据（前50个，按点击降序）
                if is_sb:
                    temp4_sql = (
                        "WITH temp2 AS ("
                        "    SELECT DISTINCT asin "
                        "    FROM dim_amazon_sb_creativity "
                        "    WHERE campaign_id = %s "
                        "    LIMIT 1"
                        "), "
                        "temp3 AS ("
                        "    SELECT DISTINCT a.campaign_id "
                        "    FROM dim_amazon_sb_creativity a "
                        "    JOIN temp2 ta ON a.asin = ta.asin "
                        "    LEFT JOIN dim_amazon_campaign b ON a.campaign_id = b.campaign_id "
                        "    WHERE a.sid = %s"
                        "), "
                        "temp4 AS ("
                        "    SELECT DISTINCT ad_group_id "
                        "    FROM amazon_queryword_reports "
                        "    WHERE campaign_id IN (SELECT campaign_id FROM temp3) "
                        "      AND createtime >= %s AND createtime < %s"
                        ") "
                        "SELECT query, is_asin, "
                        "       SUM(clicks) AS clicks, SUM(orders) AS orders "
                        "FROM amazon_queryword_reports "
                        "WHERE createtime >= %s AND createtime < %s "
                        "  AND ad_group_id IN (SELECT ad_group_id FROM temp4) "
                        "  AND LOWER(campaign_type)=LOWER(%s) "
                        "GROUP BY query, is_asin "
                        "ORDER BY SUM(clicks) DESC "
                        "LIMIT 50"
                    )
                    temp5_values = [
                        base_campaign_id,
                        sid,
                        start_date,
                        end_next,
                        start_date,
                        end_next,
                        campaign_type,
                    ]
                else:
                    temp4_sql = (
                        "WITH temp2 AS ("
                        "    SELECT DISTINCT dp.campaign_id "
                        "    FROM dim_amazon_product dp "
                        "    LEFT JOIN dim_amazon_campaign dc ON dp.campaign_id = dc.campaign_id "
                        "    INNER JOIN amazon_campaign_reports r ON dp.campaign_id = r.campaign_id "
                        "    WHERE dp.sku = %s AND dp.state = 'enabled'"
                        "      AND r.sid = %s AND r.campaign_type = %s"
                        "), "
                        "temp3 AS ("
                        "    SELECT t2.campaign_id "
                        "    FROM temp2 t2 "
                        "    JOIN dim_amazon_campaign dc ON t2.campaign_id = dc.campaign_id "
                        "    WHERE dc.name NOT LIKE %s"
                        "), "
                        "temp4 AS ("
                        "    SELECT DISTINCT ad_group_id "
                        "    FROM amazon_queryword_reports "
                        "    WHERE campaign_id IN (SELECT campaign_id FROM temp3) "
                        "      AND createtime >= %s AND createtime < %s"
                        ") "
                        "SELECT query, is_asin, "
                        "       SUM(clicks) AS clicks, SUM(orders) AS orders "
                        "FROM amazon_queryword_reports "
                        "WHERE createtime >= %s AND createtime < %s "
                        "  AND ad_group_id IN (SELECT ad_group_id FROM temp4) "
                        "  AND LOWER(campaign_type)=LOWER(%s) "
                        "GROUP BY query, is_asin "
                        "ORDER BY SUM(clicks) DESC "
                        "LIMIT 50"
                    )
                    temp5_values = [
                        sku,
                        sid,
                        campaign_type,
                        "%捡漏%",
                        start_date,
                        end_next,
                        start_date,
                        end_next,
                        campaign_type,
                    ]

                await cur.execute(temp4_sql, temp5_values)
                temp5_rows = await cur.fetchall()

                logger.debug(f"\n[2] temp5 阶段：相关广告组内 query 汇总数据 (前50个，按点击降序):")
                if temp5_rows:
                    logger.debug(f"{'类型':<6} {'搜索词/ASIN':<50} {'点击':<10} {'订单':<10}")
                    logger.debug("-" * 80)
                    for row in temp5_rows:
                        query, is_asin, clicks, orders = row
                        type_str = "Asin" if is_asin else "词"
                        query_str = str(query or "")[:48]
                        logger.debug(f"{type_str:<6} {query_str:<50} {int(clicks or 0):<10} {int(orders or 0):<10}")
                else:
                    logger.debug("    未找到匹配的 query 数据")

                # 3. 查询 temp6 阶段：相关广告组内 query 全量汇总（带阈值标记）
                if is_sb:
                    temp6_sql = (
                        "WITH temp2 AS ("
                        "    SELECT DISTINCT asin "
                        "    FROM dim_amazon_sb_creativity "
                        "    WHERE campaign_id = %s "
                        "    LIMIT 1"
                        "), "
                        "temp3 AS ("
                        "    SELECT DISTINCT a.campaign_id "
                        "    FROM dim_amazon_sb_creativity a "
                        "    JOIN temp2 ta ON a.asin = ta.asin "
                        "    LEFT JOIN dim_amazon_campaign b ON a.campaign_id = b.campaign_id "
                        "    WHERE a.sid = %s"
                        "), "
                        "temp4 AS ("
                        "    SELECT DISTINCT ad_group_id "
                        "    FROM amazon_queryword_reports "
                        "    WHERE campaign_id IN (SELECT campaign_id FROM temp3) "
                        "      AND createtime >= %s AND createtime < %s"
                        "), "
                        "temp5 AS ("
                        "    SELECT query, is_asin, clicks, orders "
                        "    FROM amazon_queryword_reports "
                        "    WHERE createtime >= %s AND createtime < %s "
                        "      AND ad_group_id IN (SELECT ad_group_id FROM temp4) "
                        "      AND LOWER(campaign_type)=LOWER(%s)"
                        "), "
                        "temp6 AS ("
                        "    SELECT query, is_asin, "
                        "           SUM(clicks) AS clicks, SUM(orders) AS orders "
                        "    FROM temp5 "
                        "    GROUP BY query, is_asin "
                        ") "
                        "SELECT t6.query, t6.is_asin, t6.clicks, t6.orders "
                        "FROM temp6 t6 "
                        "ORDER BY t6.is_asin DESC, t6.clicks DESC"
                    )
                    temp6_values = [
                        base_campaign_id,
                        sid,
                        start_date,
                        end_next,
                        start_date,
                        end_next,
                        campaign_type,
                    ]
                else:
                    temp6_sql = (
                        "WITH temp2 AS ("
                        "    SELECT DISTINCT dp.campaign_id "
                        "    FROM dim_amazon_product dp "
                        "    LEFT JOIN dim_amazon_campaign dc ON dp.campaign_id = dc.campaign_id "
                        "    INNER JOIN amazon_campaign_reports r ON dp.campaign_id = r.campaign_id "
                        "    WHERE dp.sku = %s AND dp.state = 'enabled'"
                        "      AND r.sid = %s AND r.campaign_type = %s"
                        "      AND dc.name NOT LIKE %s"
                        "), "
                        "temp4 AS ("
                        "    SELECT DISTINCT ad_group_id "
                        "    FROM amazon_queryword_reports "
                        "    WHERE campaign_id IN (SELECT campaign_id FROM temp2) "
                        "      AND createtime >= %s AND createtime < %s"
                        "), "
                        "temp5 AS ("
                        "    SELECT query, is_asin, clicks, orders "
                        "    FROM amazon_queryword_reports "
                        "    WHERE createtime >= %s AND createtime < %s "
                        "      AND ad_group_id IN (SELECT ad_group_id FROM temp4) "
                        "      AND LOWER(campaign_type)=LOWER(%s)"
                        "), "
                        "temp6 AS ("
                        "    SELECT query, is_asin, "
                        "           SUM(clicks) AS clicks, SUM(orders) AS orders "
                        "    FROM temp5 "
                        "    GROUP BY query, is_asin "
                        ") "
                        "SELECT t6.query, t6.is_asin, t6.clicks, t6.orders "
                        "FROM temp6 t6 "
                        "ORDER BY t6.is_asin DESC, t6.clicks DESC"
                    )
                    temp6_values = [
                        sku,
                        sid,
                        campaign_type,
                        "%捡漏%",
                        start_date,
                        end_next,
                        start_date,
                        end_next,
                        campaign_type,
                    ]

                await cur.execute(temp6_sql, temp6_values)
                temp6_rows = await cur.fetchall()

                logger.debug(f"\n[3] temp6 阶段：过滤后的 query (clicks>15 且 orders=0): 共 {len(temp6_rows)} 个")
                if temp6_rows:
                    logger.debug(f"{'类型':<6} {'搜索词/ASIN':<50} {'点击':<10} {'订单':<10} {'阈值要求':<20}")
                    logger.debug("-" * 120)
                    asin_threshold = 1.5 * cpo_all
                    word_threshold = 2 * cpo_all
                    for row in temp6_rows:
                        query, is_asin, clicks, orders = row
                        type_str = "Asin" if is_asin else "词"
                        query_str = str(query or "")[:48]
                        threshold = asin_threshold if is_asin else word_threshold
                        meets_threshold = clicks >= threshold
                        status = "✓ 满足" if meets_threshold else "✗ 不满足"
                        logger.debug(f"{type_str:<6} {query_str:<50} {int(clicks or 0):<10} {int(orders or 0):<10} "
                                     f"{status} (阈值: {threshold:.2f})")
                else:
                    logger.debug("    未找到满足条件的 query")

                logger.debug("\n" + "=" * 120 + "\n")
    
    rows: List[Tuple[Any, ...]] = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
            fetch = await cur.fetchall()
            if fetch:
                rows = fetch

    grouped_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for query, is_asin, clicks in rows:
        clicks_val = float(clicks or 0)
        is_asin_bool = bool(is_asin)
        type_label = "Asin" if is_asin_bool else "词"
        item = {
            "query": query or "",
            "clicks": int(clicks_val),
        }
        grouped_by_type.setdefault(type_label, []).append(item)

    result: List[Dict[str, Any]] = []
    for type_label in ("Asin", "词"):
        items = grouped_by_type.get(type_label, [])
        if not items:
            continue
        # 按点击量降序排序
        items.sort(key=lambda x: -x["clicks"])
        result.append({"type": type_label, "queries": items})

    return result


async def _query_negative_rules_target(
    pool,
    op_api: OpenApiBase,
    access_token: str,
    campaign_id: str,
    campaign_type: str,
    start_date: str,
    end_date: str,
    cpo_all: float,
) -> List[Dict[str, Any]]:
    """
    基于 Target 小时报表（SP: /pb/openapi/newad/spTargetHourData, SB: /pb/openapi/newad/sbTargetHourData）
    对给定 campaign_id 所属广告组下的所有 campaign 进行小时级数据拉取并汇总，生成否词候选。
    逻辑：
      1. 从 dim_amazon_campaign 查询该 campaign 的 targeting_type，若为 'auto' 则返回 []。
      2. 从 dim_amazon_campaign_groups 找到该 campaign 的 ad_group_id（取任一匹配），
         再查询该 ad_group_id 下的所有 campaign_id。
      3. 对这些 campaign_id 在日期区间 [start_date, end_date] 的每一天，按广告类型调用对应接口拉取小时数据并聚合
         （按 targeting_id + targeting 聚合 clicks/orders）。
      4. 过滤 orders == 0 且 clicks >= 15 的候选；阈值判断同 negative_rules_single：Asin 使用 1.5*CPO，普通词使用 2*CPO。
      5. 返回与 negative_rules_ad 相同格式的列表。
    """
    # 1. 检查 targeting_type
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT targeting_type FROM dim_amazon_campaign WHERE campaign_id=%s LIMIT 1", (campaign_id,))
            row = await cur.fetchone()
            targeting_type = row[0] if row and row[0] is not None else None
    if targeting_type and str(targeting_type).strip().lower() == "auto":
        return []

    # 2. 查找广告组及所属 campaign 集合
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT ad_group_id FROM dim_amazon_campaign_groups WHERE campaign_id=%s LIMIT 1", (campaign_id,))
            row = await cur.fetchone()
            if not row or not row[0]:
                return []
            ad_group_id = row[0]
            await cur.execute("SELECT DISTINCT campaign_id FROM dim_amazon_campaign_groups WHERE ad_group_id=%s", (ad_group_id,))
            fetch = await cur.fetchall()
            campaign_ids = [r[0] for r in fetch if r and r[0]]
    if not campaign_ids:
        return []

    # 3. 对每个 campaign_id 和每个日期拉取小时数据并聚合
    # 生成日期列表（闭区间）
    start_dt = date.fromisoformat(start_date)
    end_dt = date.fromisoformat(end_date)
    day_list = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_dt - start_dt).days + 1)]

    agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
    # 选择接口路由
    is_sb = str(campaign_type or "").lower().startswith("sb")
    route = "/pb/openapi/newad/sbTargetHourData" if is_sb else "/pb/openapi/newad/spTargetHourData"

    for cid in campaign_ids:
        for day in day_list:
            req_body = {"campaign_id": int(cid) if str(cid).isdigit() else cid, "report_date": day, "agg_dimension": "both_ad_target"}
            try:
                resp = await op_api.request(access_token, route, "POST", req_body=req_body, use_cache=False)
            except Exception:
                continue
            if not resp or resp.code not in (0, 200):
                continue
            data_list = resp.data
            if data_list is None:
                continue
            if isinstance(data_list, dict):
                data_list = [data_list]
            if not isinstance(data_list, list):
                continue
            for item in data_list:
                targeting_id = item.get("targeting_id") or item.get("targetingId") or ""
                targeting_text = item.get("targeting") or ""
                clicks = int(item.get("clicks") or item.get("same_clicks") or 0)
                orders = int(item.get("orders") or item.get("same_orders") or 0)
                key = (str(targeting_id), str(targeting_text))
                entry = agg.get(key)
                if entry is None:
                    entry = {"targeting": targeting_text, "clicks": 0, "orders": 0}
                    agg[key] = entry
                entry["clicks"] += clicks
                entry["orders"] += orders
    # 调试：打印未过滤前的聚合原始数据（用于校对）
    if DEBUG and agg:
        try:
            raw_samples = []
            for (tid, ttext), vals in list(agg.items())[:50]:
                raw_samples.append((tid, ttext, int(vals.get("clicks", 0)), int(vals.get("orders", 0))))
            logger.debug(f"[debug] negative_rules_target 原始聚合条目: {len(agg)}，示例（最多50）：{raw_samples}")
        except Exception:
            # 容错：打印可能包含不可序列化对象
            logger.debug(f"[debug] negative_rules_target 原始聚合条目: {len(agg)} (samples omitted due to formatting error)")
        logger.debug("=" * 120)

    # 4. 过滤并构建返回结果
    neg_rules: List[Dict[str, Any]] = []
    asin_re = re.compile(r"[A-Za-z0-9]{10}")
    for (tid, ttext), vals in agg.items():
        clicks = vals["clicks"]
        orders = vals["orders"]
        if orders != 0:
            continue
        if clicks < 15:
            continue
        # 判断是否是 Asin（简单通过 ASIN 10位字母数字检测）
        is_asin = bool(asin_re.search(str(ttext or "")))
        threshold = 1.5 * cpo_all if is_asin else 2 * cpo_all
        if clicks < threshold:
            continue
        neg_rules.append({"query": ttext or "", "type": "Asin" if is_asin else "词", "clicks": int(clicks)})

    neg_rules.sort(key=lambda x: (0 if x["type"] == "Asin" else 1, -x["clicks"]))
    return neg_rules


async def _best_acos_week(
    pool,
    campaign_ids: Set[str],
    sid: int | str,
    campaign_type: str,
    today: date | None = None,
) -> Dict[str, Any] | None:
    """返回最近 30 天内（按周聚合）orders>=2 且 ACoS 最低的周，限定 sid 与 campaign_type。
    仅保留跨度>=7天的周，避免单日被选为“最佳周”。
    """
    if not campaign_ids:
        return None
    if today is None:
        today = date.today()

    start_30 = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end_30 = today.strftime("%Y-%m-%d")

    placeholders = ",".join(["%s"] * len(campaign_ids))
    sql = (
        "WITH weekly AS ("
        "    SELECT YEARWEEK(createtime, 1) AS yw, "
        "           MIN(DATE(createtime)) AS start_date, "
        "           MAX(DATE(createtime)) AS end_date, "
        "           SUM(impressions) AS impressions, "
        "           SUM(clicks) AS clicks, "
        "           SUM(cost) AS cost, "
        "           SUM(sales) AS sales, "
        "           SUM(orders) AS orders, "
        "           SUM(units) AS units "
        "    FROM amazon_campaign_reports "
        f"    WHERE campaign_id IN ({placeholders}) AND sid=%s AND campaign_type=%s AND createtime >= %s AND createtime < %s "
        "    GROUP BY YEARWEEK(createtime, 1) "
        "    HAVING DATEDIFF(MAX(DATE(createtime)), MIN(DATE(createtime))) >= 6"  # 至少覆盖7天
        ") "
        "SELECT start_date, end_date, impressions, clicks, cost, sales, orders, units "
        "FROM weekly "
        "WHERE orders >= 2 "
        "ORDER BY (sales IS NULL OR sales = 0), cost / NULLIF(sales, 0) ASC "
        "LIMIT 1"
    )

    values = list(campaign_ids) + [sid, campaign_type, start_30, end_30]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
            row = await cur.fetchone()
            if not row:
                return None

    start_date, end_date, imp, clicks, cost, sales, orders, units = row
    sums = {
        "impressions": float(imp or 0),
        "clicks": float(clicks or 0),
        "cost": float(cost or 0),
        "sales": float(sales or 0),
        "orders": float(orders or 0),
        "units": float(units or 0),
    }
    derived = _calc_derived(
        sums,
        start_date.strftime("%Y-%m-%d") if hasattr(start_date, "strftime") else str(start_date),
        end_date.strftime("%Y-%m-%d") if hasattr(end_date, "strftime") else str(end_date),
    )
    return {"label": "best_acos_week", "metrics": derived, "sums": sums}


async def _best_acos_week_for_sku(
    pool,
    sid: int | str,
    campaign_type: str,
    *,
    base_campaign_id: str | None = None,
    sku: str | None = None,
    today: date | None = None,
) -> Dict[str, Any] | None:
    """SKU 维度最佳周：近 30 天按周聚合，orders>=2 且 ACoS 最低。
    SB 使用 base_campaign_id 反查 ASIN；非 SB 使用 SKU 反查相关 campaign。
    """
    if today is None:
        today = date.today()

    start_30 = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end_30 = today.strftime("%Y-%m-%d")

    is_sb = str(campaign_type or "").lower().startswith("sb")
    if is_sb:
        if not base_campaign_id:
            return None
        sql = (
            "WITH target_asin AS ("
            "    SELECT DISTINCT asin FROM dim_amazon_sb_creativity WHERE campaign_id=%s LIMIT 1"
            "), "
            "cids AS ("
            "    SELECT DISTINCT a.campaign_id "
            "    FROM dim_amazon_sb_creativity a "
            "    JOIN target_asin ta ON a.asin = ta.asin "
            "    LEFT JOIN dim_amazon_campaign b ON a.campaign_id = b.campaign_id "
            "    WHERE a.sid=%s AND b.state = 'enabled' AND (b.name IS NULL OR b.name NOT LIKE %s)"
            "), "
            "weekly AS ("
            "    SELECT YEARWEEK(r.createtime, 1) AS yw, "
            "           MIN(DATE(r.createtime)) AS start_date, "
            "           MAX(DATE(r.createtime)) AS end_date, "
            "           SUM(r.impressions) AS impressions, "
            "           SUM(r.clicks) AS clicks, "
            "           SUM(r.cost) AS cost, "
            "           SUM(r.sales) AS sales, "
            "           SUM(r.orders) AS orders, "
            "           SUM(r.units) AS units "
            "    FROM amazon_campaign_reports r "
            "    JOIN cids c ON r.campaign_id = c.campaign_id "
            "    WHERE r.sid=%s AND r.campaign_type=%s AND r.createtime >= %s AND r.createtime < %s "
            "    GROUP BY YEARWEEK(r.createtime, 1) "
            "    HAVING DATEDIFF(MAX(DATE(r.createtime)), MIN(DATE(r.createtime))) >= 6"
            ") "
            "SELECT start_date, end_date, impressions, clicks, cost, sales, orders, units "
            "FROM weekly "
            "WHERE orders >= 2 "
            "ORDER BY (sales IS NULL OR sales = 0), cost / NULLIF(sales, 0) ASC "
            "LIMIT 1"
        )
        values = [base_campaign_id, sid, "%捡漏%", sid, campaign_type, start_30, end_30]
    else:
        if not sku:
            return None
        sql = (
            "WITH cids AS ("
            "    SELECT DISTINCT dp.campaign_id "
            "    FROM dim_amazon_product dp "
            "    LEFT JOIN dim_amazon_campaign dc ON dp.campaign_id = dc.campaign_id "
            "    WHERE dp.sku=%s AND dc.state = 'enabled' AND (dc.name IS NULL OR dc.name NOT LIKE %s)"
            "), "
            "weekly AS ("
            "    SELECT YEARWEEK(r.createtime, 1) AS yw, "
            "           MIN(DATE(r.createtime)) AS start_date, "
            "           MAX(DATE(r.createtime)) AS end_date, "
            "           SUM(r.impressions) AS impressions, "
            "           SUM(r.clicks) AS clicks, "
            "           SUM(r.cost) AS cost, "
            "           SUM(r.sales) AS sales, "
            "           SUM(r.orders) AS orders, "
            "           SUM(r.units) AS units "
            "    FROM amazon_campaign_reports r "
            "    JOIN cids c ON r.campaign_id = c.campaign_id "
            "    WHERE r.sid=%s AND r.campaign_type=%s AND r.createtime >= %s AND r.createtime < %s "
            "    GROUP BY YEARWEEK(r.createtime, 1) "
            "    HAVING DATEDIFF(MAX(DATE(r.createtime)), MIN(DATE(r.createtime))) >= 6"
            ") "
            "SELECT start_date, end_date, impressions, clicks, cost, sales, orders, units "
            "FROM weekly "
            "WHERE orders >= 2 "
            "ORDER BY (sales IS NULL OR sales = 0), cost / NULLIF(sales, 0) ASC "
            "LIMIT 1"
        )
        values = [sku, "%捡漏%", sid, campaign_type, start_30, end_30]

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
            row = await cur.fetchone()
            if not row:
                return None

    start_date, end_date, imp, clicks, cost, sales, orders, units = row
    sums = {
        "impressions": float(imp or 0),
        "clicks": float(clicks or 0),
        "cost": float(cost or 0),
        "sales": float(sales or 0),
        "orders": float(orders or 0),
        "units": float(units or 0),
    }
    derived = _calc_derived(
        sums,
        start_date.strftime("%Y-%m-%d") if hasattr(start_date, "strftime") else str(start_date),
        end_date.strftime("%Y-%m-%d") if hasattr(end_date, "strftime") else str(end_date),
    )
    return {"label": "best_acos_week", "metrics": derived, "sums": sums}


def _calc_derived(sums: Dict[str, float], start: str, end: str, total_cost: float | None = None) -> Dict[str, float | str]:
    imp = sums.get("impressions", 0.0)
    clk = sums.get("clicks", 0.0)
    cost = sums.get("cost", 0.0)
    sales = sums.get("sales", 0.0)
    orders = sums.get("orders", 0.0)

    ctr = clk / imp if imp else 0.0
    cpc = cost / clk if clk else 0.0
    acos = cost / sales if sales else 0.0
    cpa = cost / orders if orders else 0.0
    cvr = orders / clk if clk else 0.0
    cpo = (1 / cvr) if cvr else 0.0  # 每转化曝光成本的倒数，即 1/CVR
    return {
        "date_range": f"{start}~{end}",
        "impressions": imp,
        "clicks": clk,
        "cost": round(cost, 2),
        "sales": round(sales, 2),
        "orders": orders,
        "units": sums.get("units", 0.0),
        "CTR": round(ctr, 4),   # 保留四位用于百分比两位
        "CPC": round(cpc, 2),
        "ACoS": round(acos, 4),
        "CPA": round(cpa, 2),
        "CVR": round(cvr, 4),
        "CPO": round(cpo, 2),
    }


def _currency_symbol(country: str | None) -> str:
    """根据国家返回货币符号，默认美元。"""
    mapping = {
        "美国": "$",
        "加拿大": "C$",
        "英国": "£",
        "德国": "€",
        "法国": "€",
        "意大利": "€",
        "西班牙": "€",
        "日本": "¥",
        "DE": "€",
        "DEU": "€",
        "UK": "£",
        "GB": "£",
        "GBR": "£",
        "US": "$",
        "USA": "$",
        "CA": "C$",
        "CAN": "C$",
        "JP": "¥",
        "JPN": "¥",
        "ES": "€",
        "FR": "€",
        "IT": "€",
    }
    if not country:
        return "$"
    country_up = str(country).strip()
    return mapping.get(country_up, "$")


def _compact_metrics(metrics: Dict[str, Any], currency_symbol: str = "$") -> Dict[str, Any]:
    """筛选并保留对 Agent 友好的字段，附带基础格式化（货币符号与 %），去掉 CPA 等冗余项。"""
    keep = [
        "date_range",
        "impressions",
        "clicks",
        "cost",
        "CTR",
        "CPC",
        "ACoS",
        "orders",
        "CVR",
        "CPO",
        "sales",
        "units",
    ]
    compact = {k: metrics[k] for k in keep if k in metrics}

    # 在原字段上进行格式化，避免 *_str 冗余
    if "cost" in compact:
        compact["cost"] = f"{currency_symbol}{compact['cost']:.2f}"
    if "CPC" in compact:
        compact["CPC"] = f"{currency_symbol}{compact['CPC']:.2f}"
    # CPO 表示每单花费，用纯数值（不加货币符号）便于直接对比阈值
    if "sales" in compact:
        compact["sales"] = f"{currency_symbol}{compact['sales']:.2f}"
    if "ACoS" in compact:
        compact["ACoS"] = f"{compact['ACoS']*100:.2f}%"
    if "CTR" in compact:
        compact["CTR"] = f"{compact['CTR']*100:.2f}%"
    if "CVR" in compact:
        compact["CVR"] = f"{compact['CVR']*100:.2f}%"

    return compact


async def main():
    country = "美国"
    # 广告名称（精确匹配 dim_amazon_campaign.name）
    target_name = "8061001-nut driver set-0.68-ROS20-仅降低-递增预算"
    # 可选：SKU，仅 SB 汇总时需要；非 SB 将基于广告自身 ASIN 反查
    sku = "8061001"
    # sid / campaign_type 将在查询报表时由唯一 campaign_id 反查得到
    target_sid = None
    target_campaign_type = None
    settings = Settings()

    db_name = settings.db_config.get("db") or ""
    if not db_name:
        print("[warn] 未设置 DB_NAME，无法在数据库中校验和汇总")
        return

    try:
        pool = await aiomysql.create_pool(**settings.db_config)
    except Exception as exc:
        print(f"[error] 连接数据库失败: {exc}")
        return

    # 先查数据库是否存在该广告名称 + 国家
    db_rows = await _query_campaigns_from_db(pool, target_name, country)
    if not db_rows:
        print("[error] 未找到名称+国家匹配的广告活动 (dim_amazon_campaign/amazon_campaign_reports 无记录)")
        pool.close()
        await pool.wait_closed()
        return
    if len(db_rows) > 1:
        print(f"[error] 找到 {len(db_rows)} 条同名同国广告活动，请确保名称唯一后再查询")
        pool.close()
        await pool.wait_closed()
        return

    target_ids = {cid for cid, _ in db_rows}

    # 通过唯一 campaign_id 反查 sid / campaign_type / country
    cid = next(iter(target_ids))
    sid_type_ctry = await _get_sid_type_country_from_reports(pool, cid)
    if not sid_type_ctry:
        print("[error] 在 amazon_campaign_reports 中未找到该 campaign_id 的 sid/campaign_type 记录")
        pool.close()
        await pool.wait_closed()
        return
    target_sid, target_campaign_type, target_country = sid_type_ctry
    if country and target_country and str(country).strip() != str(target_country).strip():
        print(f"[warn] 输入国家 {country} 与报表国家 {target_country} 不一致，已以报表国家为准")
    country = target_country or country
    # SB 广告类型在报表里可能出现 "sb"、"sbv"、"sb_video" 等，统一用前缀判断
    campaign_type_lower = str(target_campaign_type or "").lower()
    is_sb = campaign_type_lower.startswith("sb")
    currency_symbol = _currency_symbol(country)

    # 保持按广告名称精确匹配得到的 campaign_id 集合；SB 不再强制用 SKU 模糊替换

    # 仅走数据库聚合：先算 7/14 天对比，条件满足再算 30 天，否则输出 14 天汇总
    ranges = _recent_ranges()

    async def _fetch(label: str) -> Tuple[str, Dict[str, float], Dict[str, Any]]:
        start_d, end_d = ranges[label]
        # 区间汇总不区分 SB/非 SB，统一按 campaign_id 集合聚合
        sums = await _sum_reports_from_db(pool, target_ids, target_sid, target_campaign_type, start_d, end_d)
        derived = _calc_derived(sums, start_d, end_d)
        return label, sums, derived

    # 先获取 7/14 天所需的 4 个区间
    needed_labels = ["last_7", "prev_7", "last_14", "prev_14"]
    fetched = await asyncio.gather(*[_fetch(label) for label in needed_labels])
    sums_map: Dict[str, Dict[str, float]] = {label: sums for label, sums, _ in fetched}
    derived_map: Dict[str, Dict[str, Any]] = {label: derived for label, _, derived in fetched}

    def _has_data(sums: Dict[str, float]) -> bool:
        """判断一个区间是否有数据（任一核心指标>0）。"""
        return any((sums.get(k, 0) or 0) > 0 for k in ["impressions", "clicks", "cost", "sales", "orders", "units"])

    has_prev_14 = _has_data(sums_map["prev_14"])

    # 趋势判定：正常有 14d 对比时看 7d+14d；仅开满 14 天且 prev_14 无数据时，仅看 7d。
    # 规则调整：若前14天有数据且近14天 ACoS=0，直接判定变差，不看 7 天对比
    last7_acos = derived_map["last_7"].get("ACoS", 0)
    prev7_acos = derived_map["prev_7"].get("ACoS", 0)
    acos_up_7 = (last7_acos == 0) or (last7_acos > prev7_acos)
    acos_down_7 = last7_acos < prev7_acos

    if has_prev_14:
        last14_acos = derived_map["last_14"].get("ACoS", 0)
        prev14_acos = derived_map["prev_14"].get("ACoS", 0)
        # 新规则：前14天有数据时，若近14天 ACoS=0，直接判定变差（不看 7 天）
        if last14_acos == 0:
            is_worse = True
            is_better = False
        else:
            acos_up_14 = last14_acos > prev14_acos
            acos_down_14 = last14_acos < prev14_acos
            is_worse = acos_up_7 and acos_up_14          # 持续变差
            is_better = acos_down_7 and acos_down_14     # 持续变好
    else:
        # 只有 14 天数据：用 7d 对比判断趋势
        is_worse = acos_up_7
        is_better = acos_down_7

    # 仅持续变差时需要 30 天最佳周；波动/变好与原样保持一致（不拉 30 天）
    need_30 = is_worse
    result: Dict[str, Any] = {
        "campaign_name": target_name,
        "sku": sku,
        "compare_7d": {
            "current": _compact_metrics(derived_map["last_7"], currency_symbol),
            "prev": _compact_metrics(derived_map["prev_7"], currency_symbol),
        },
        "compare_14d": {
            "current": _compact_metrics(derived_map["last_14"], currency_symbol),
            "prev": _compact_metrics(derived_map["prev_14"], currency_symbol),
        },
    }

    best_week = None
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

            # 推荐参数：Bid 取最佳周 CPC；ACoS/CPO 取近 14 天当前值
            bid_reco = best_week["metrics"].get("CPC", 0.0)
            result["recommended_settings"] = {
                "Bid": f"{currency_symbol}{bid_reco:.2f}",
            }
        else:
            # 若未找到最佳周，也给出基于最近 14 天的保底推荐
            bid_reco = derived_map["last_14"].get("CPC", 0.0)
            result["recommended_settings"] = {
                "Bid": f"{currency_symbol}{bid_reco:.2f}",
            }

    def _is_all_zero_summary(summary: Dict[str, Any] | None) -> bool:
        """判定 ACoS/CVR/CPO 是否全为 0，用于全品数据回退与终止提示。"""
        if not summary:
            return True
        return all(float(summary.get(k, 0) or 0) == 0 for k in ("ACoS", "CVR", "CPO"))

    # 品维度 14 天汇总与阈值（无论是否波动都输出），支持 SB<->SP 回退
    start_14, end_14 = ranges["last_14"]
    sku_sums: Dict[str, float] = {}
    sku_summary: Dict[str, Any] = {}
    primary_zero = False
    fallback_zero = False

    if is_sb:
        sku_sums = await _sum_reports_sb_by_sku(pool, cid, target_sid, target_campaign_type, start_14, end_14)
        sku_summary = _calc_derived(sku_sums, start_14, end_14)
        primary_zero = _is_all_zero_summary(sku_summary)
        if primary_zero:
            # SB → SP 回退
            sp_sums = await _sum_reports_sp_by_sku(pool, sku, target_sid, "sp%", start_14, end_14)
            sp_summary = _calc_derived(sp_sums, start_14, end_14)
            fallback_zero = _is_all_zero_summary(sp_summary)
            if not fallback_zero:
                sku_sums = sp_sums
                sku_summary = sp_summary
    else:
        sku_sums = await _sum_reports_sp_by_sku(pool, sku, target_sid, target_campaign_type, start_14, end_14)
        sku_summary = _calc_derived(sku_sums, start_14, end_14)
        primary_zero = _is_all_zero_summary(sku_summary)
        if primary_zero and str(target_campaign_type or "").lower().startswith("sp"):
            # SP → SB 回退（通过商品表获取 ASIN）
            asin_from_sku = await _get_asin_by_sku(pool, sku)
            sb_sums = await _sum_reports_sb_by_asin(pool, asin_from_sku, target_sid, start_14, end_14)
            sb_summary = _calc_derived(sb_sums, start_14, end_14)
            fallback_zero = _is_all_zero_summary(sb_summary)
            if not fallback_zero:
                sku_sums = sb_sums
                sku_summary = sb_summary

    if (is_sb or str(target_campaign_type or "").lower().startswith("sp")) and primary_zero and fallback_zero:
        print("建议重新开测试广告，有2周数据再来做自动规则")
        pool.close()
        await pool.wait_closed()
        return

    if sku_summary:
        result["sku_14d_all"] = _compact_metrics(sku_summary, currency_symbol)
        acos = sku_summary.get("ACoS", 0.0)
        cvr = sku_summary.get("CVR", 0.0)
        cpo = sku_summary.get("CPO", 0.0)
        thresholds = {
            "acos_super_high": round(acos * 1.5, 4),
            "acos_high": round(acos * 1.2, 4),
            "acos_low": round(acos * 0.8, 4),
            "cvr_high": round(cvr * 1.2, 4),
            "cvr_low": round(cvr * 0.8, 4),
            "cpo_high_click": round(cpo * 1.5, 2),
            "cpo_low_click": round(cpo * 0.5, 2),
            "double_cpo": round(cpo * 2, 2),
        }
        result["thresholds"] = thresholds

        # 无论是否波动，都给出否词规则；用品维度 14 天 CPO 作为阈值基础
        neg_rules_campaign = await _query_negative_rules_single(
            pool, target_ids, target_campaign_type, start_14, end_14, cpo
        )
        neg_rules_cross = await _query_negative_rules_cross(
            pool, target_ids, target_campaign_type, target_sid, start_14, end_14, cpo,
            base_campaign_id=cid, sku=sku, is_sb=is_sb
        )
        # 额外：基于 Target 小时报表的否词，使用 OpenAPI 拉取小时级 Target 数据并汇总
        try:
            settings = Settings()
            op_api = OpenApiBase(settings.host, settings.app_id, settings.app_secret, enable_cache=False)
            if settings.manual_access_token:
                access_token = settings.manual_access_token
            else:
                token_resp = await op_api.generate_access_token()
                access_token = token_resp.access_token
            neg_rules_target = await _query_negative_rules_target(pool, op_api, access_token, cid, target_campaign_type, start_14, end_14, cpo)
        except Exception as e:
            print(f"[warn] 拉取 negative_rules_target 失败: {e}")
            neg_rules_target = []
        # 将 Target 来源的否词放在广告级否词之前
        result["negative_rules_target"] = neg_rules_target
        # 保留单广告活动精否结果，键名调整为 negative_rules_ad
        result["negative_rules_ad"] = neg_rules_campaign
        result["negative_rules_ad_groups"] = neg_rules_cross

    # 输出紧凑 JSON，便于直接作为 Agent 上下文
    print(f"匹配到 {len(db_rows)} 条记录 (去重后 {len(target_ids)} 个 campaign_id)")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    pool.close()
    await pool.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
