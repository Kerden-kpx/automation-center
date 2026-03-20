#!/usr/bin/env python3
"""Auto-sync utilities: provide callable functions to run periodic synchronization.

Usage:
  - Import and call `await auto_sync_once()` to run one sync.
  - Use `auto_sync_loop()` to run continuously (awaitable).
  - Use `start_auto_sync_in_background()` to schedule the loop in an existing event loop.
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import date, datetime, timedelta
from functools import partial
from typing import List, Optional, Tuple

import aiomysql

from .synchronize import (
    Settings,
    OpenApiBase,
    get_lingxing_access_token,
    fetch_seller_lists,
    filter_active_sellers,
    _run_reports,
    _run_queryword_reports,
    _run_campaign_names,
    _run_sb_creativity,
    _run_sp_product_ads,
    QUERY_WORD_ROUTES,
    _close_http_session,
    _close_db_pool,
    _get_db_pool,
)

_AUTO_SYNC_RUNNING = threading.Event()
_LAST_DAILY_RUN_DATE: Optional[date] = None
_LAST_REPORT_DATE: Optional[date] = None


def _get_report_recipients() -> List[str]:
    """从环境变量获取报告接收者列表。"""
    import os
    recipients_str = os.getenv("DAILY_REPORT_RECIPIENTS", "")
    if not recipients_str:
        return []
    return [r.strip() for r in recipients_str.split(",") if r.strip()]


async def _generate_daily_report(settings: Settings) -> str:
    """生成每周调用统计报告（Markdown 格式）。"""
    pool = await _get_db_pool(settings.db_config)
    if pool is None:
        return "❌ 无法连接数据库，报告生成失败"
    
    today = date.today()
    end_date = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    end_date_str = end_date.strftime("%Y-%m-%d")
    week_ago_str = week_ago.strftime("%Y-%m-%d")
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # 上周调用统计（过去7天，不包含今天）
                await cur.execute("""
                    SELECT user_id, user_name, COUNT(*) as call_count
                    FROM dingtalk_gpt_bot_logs
                    WHERE DATE(created_at) >= %s AND DATE(created_at) <= %s
                    GROUP BY user_id, user_name
                    ORDER BY call_count DESC
                """, (week_ago_str, end_date_str))
                week_stats = await cur.fetchall()
                week_total = sum(u["call_count"] for u in week_stats)
                
                # 累计统计
                await cur.execute("""
                    SELECT user_id, user_name, COUNT(*) as call_count
                    FROM dingtalk_gpt_bot_logs
                    GROUP BY user_id, user_name
                    ORDER BY call_count DESC
                """)
                all_stats = await cur.fetchall()
                total_calls = sum(u["call_count"] for u in all_stats)
                total_users = len(all_stats)
        
        # 构建报告
        lines = [
            f"## 📊 自动规则GPT调用统计（周报）",
            f"**统计周期**: {week_ago_str} ~ {end_date_str}",
            "",
            f"### 上周调用 ({week_total} 次)",
        ]
        
        if week_stats:
            lines.append("| 用户 | 调用次数 |")
            lines.append("|------|---------|")
            for u in week_stats[:10]:
                name = u["user_name"] or u["user_id"][:8]
                lines.append(f"| {name} | {u['call_count']} 次 |")
        else:
            lines.append("*本周暂无调用记录*")
        
        lines.extend([
            "",
            f"### 累计统计",
            f"- 总调用次数: **{total_calls}** 次",
            f"- 活跃用户数: **{total_users}** 人",
            "",
            "#### 用户累计排行",
            "| 用户 | 累计调用 |",
            "|------|---------|",
        ])
        
        for u in all_stats[:10]:
            name = u["user_name"] or u["user_id"][:8]
            lines.append(f"| {name} | {u['call_count']} 次 |")
        
        return "\n".join(lines)
        
    except Exception as exc:
        return f"❌ 报告生成失败: {exc}"


async def _send_daily_report(settings: Settings) -> None:
    """发送每周调用统计报告给指定用户。"""
    from ..utils.dingtalk_api import get_token, send_robot_private_message
    from dataclasses import dataclass
    
    recipients = _get_report_recipients()
    if not recipients:
        print("[weekly_report] 未配置 DAILY_REPORT_RECIPIENTS，跳过报告发送")
        return
    
    @dataclass
    class Config:
        client_id: str
        client_secret: str
        robot_code: str
    
    # 从环境变量获取凭证
    import os
    config = Config(
        client_id=os.getenv("DING_CLIENT_ID", ""),
        client_secret=os.getenv("DING_CLIENT_SECRET", ""),
        robot_code=os.getenv("DING_ROBOT_CODE", ""),
    )
    
    if not config.client_id or not config.client_secret:
        print("[weekly_report] 缺少钉钉凭证，跳过报告发送")
        return
    
    report = await _generate_daily_report(settings)
    access_token = await get_token(config)
    
    if not access_token:
        print("[weekly_report] 获取 access_token 失败")
        return
    
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            partial(
                send_robot_private_message,
                access_token=access_token,
                config=config,
                user_ids=recipients,
                message=report,
                msg_title="每周调用统计",
                use_markdown=True,
            ),
        )
        print(f"[weekly_report] 报告已发送给 {len(recipients)} 个用户")
    except Exception as exc:
        print(f"[weekly_report] 发送失败: {exc}")


def _build_recent_30_date_list(today: Optional[date] = None) -> List[str]:
    """Build a 30-day list ending the day before yesterday (exclude today/yesterday)."""
    today = today or date.today()
    end_dt = today - timedelta(days=2)
    start_dt = end_dt - timedelta(days=29)
    date_list: List[str] = []
    cur = start_dt
    while cur <= end_dt:
        date_list.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return date_list


async def auto_sync_once(settings: Optional[Settings] = None) -> None:
    """Run one sync for the past 30 days (ending the day before yesterday).
    Excludes today and yesterday. Raises exceptions to the caller.
    """
    settings = settings or Settings()
    _AUTO_SYNC_RUNNING.set()
    try:
        date_list = _build_recent_30_date_list()

        if not settings.app_id or not settings.app_secret:
            raise RuntimeError("APP_ID/APP_SECRET not configured for auto-sync")

        op_api = OpenApiBase(
            settings.host,
            settings.app_id,
            settings.app_secret,
            enable_cache=settings.enable_request_cache,
            cache_ttl=settings.cache_ttl,
            enable_prefetch=settings.enable_page_prefetch,
            prefetch_pages=settings.prefetch_pages,
        )

        access_token = await get_lingxing_access_token(settings, op_api)

        sellers = await fetch_seller_lists(op_api, access_token)
        active_sellers = filter_active_sellers(sellers)
        if not active_sellers:
            return

        sem = asyncio.Semaphore(settings.max_concurrency)

        # 1) campaign (campaign-level only)
        failed_campaign = await _run_reports(
            op_api,
            access_token,
            active_sellers,
            date_list,
            sem,
            settings.page_size,
            settings.db_config,
            settings.retries,
            settings.retry_on_empty,
            settings.slow_retry_on_empty,
            settings.slow_retry_concurrency,
            settings.slow_retry_retries,
            settings.slow_retry_delay,
            fetch_campaign=True,
            fetch_product=False,
            date_concurrency=settings.date_concurrency,
        )

        # 2) queryword
        queryword_configs: List[Tuple[str, str, str]] = [
            ("/pb/openapi/newad/queryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/queryWordReports"], settings.queryword_target_type),
            ("/pb/openapi/newad/queryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/queryWordReports"], settings.queryword_target_type_extra),
            ("/pb/openapi/newad/hsaQueryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/hsaQueryWordReports"], settings.queryword_target_type_extra),
        ]

        failed_qw = await _run_queryword_reports(
            op_api,
            access_token,
            active_sellers,
            date_list,
            sem,
            settings.page_size,
            settings.db_config,
            settings.retries,
            settings.retry_on_empty,
            settings.slow_retry_on_empty,
            settings.slow_retry_concurrency,
            settings.slow_retry_retries,
            settings.slow_retry_delay,
            queryword_configs,
            date_concurrency=settings.date_concurrency,
        )

        # 3) names/ad groups, SB creativity, SP product ads
        await _run_campaign_names(
            op_api,
            access_token,
            active_sellers,
            sem,
            settings.page_size,
            settings.db_config,
            settings.retries,
            True,
            True,
        )
        await _run_sb_creativity(
            op_api,
            access_token,
            active_sellers,
            sem,
            settings.page_size,
            settings.db_config,
            settings.retries,
            True,
        )
        await _run_sp_product_ads(
            op_api,
            access_token,
            active_sellers,
            sem,
            settings.page_size,
            settings.db_config,
            settings.retries,
            True,
        )

        # Optionally return or log failures; here we just print summaries
        if failed_campaign:
            print(f"[auto_sync] Campaign failed dates: {failed_campaign}")
        if failed_qw:
            print(f"[auto_sync] Queryword failed dates: {failed_qw}")
        if not failed_campaign:
            print("[auto_sync] Sync completed successfully")

    finally:
        await _close_http_session()
        await _close_db_pool()
        _AUTO_SYNC_RUNNING.clear()


async def auto_sync_daily_once(settings: Optional[Settings] = None) -> None:
    """Run daily sync for names/ad groups/SB creativity/SP product ads and queryword reports.
    Queryword reports cover the past 30 days (exclude today and yesterday).
    """
    settings = settings or Settings()
    _AUTO_SYNC_RUNNING.set()
    try:
        date_list = _build_recent_30_date_list()

        if not settings.app_id or not settings.app_secret:
            raise RuntimeError("APP_ID/APP_SECRET not configured for auto-sync")

        op_api = OpenApiBase(
            settings.host,
            settings.app_id,
            settings.app_secret,
            enable_cache=settings.enable_request_cache,
            cache_ttl=settings.cache_ttl,
            enable_prefetch=settings.enable_page_prefetch,
            prefetch_pages=settings.prefetch_pages,
        )

        access_token = await get_lingxing_access_token(settings, op_api)

        sellers = await fetch_seller_lists(op_api, access_token)
        active_sellers = filter_active_sellers(sellers)
        if not active_sellers:
            return

        sem = asyncio.Semaphore(settings.max_concurrency)

        queryword_configs: List[Tuple[str, str, str]] = [
            ("/pb/openapi/newad/queryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/queryWordReports"], settings.queryword_target_type),
            ("/pb/openapi/newad/queryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/queryWordReports"], settings.queryword_target_type_extra),
            ("/pb/openapi/newad/hsaQueryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/hsaQueryWordReports"], settings.queryword_target_type_extra),
        ]

        qw_failed = await _run_queryword_reports(
            op_api,
            access_token,
            active_sellers,
            date_list,
            sem,
            settings.page_size,
            settings.db_config,
            settings.retries,
            settings.retry_on_empty,
            settings.slow_retry_on_empty,
            settings.slow_retry_concurrency,
            settings.slow_retry_retries,
            settings.slow_retry_delay,
            queryword_configs,
            date_concurrency=settings.date_concurrency,
        )
        if qw_failed:
            print(f"[auto_sync_daily] Queryword failed dates: {qw_failed}")

        print("[auto_sync_daily] Sync completed successfully")

    finally:
        await _close_http_session()
        await _close_db_pool()
        _AUTO_SYNC_RUNNING.clear()


async def auto_sync_loop(settings: Optional[Settings] = None) -> None:
    """Run auto-sync loop forever. Sleeps until next full hour between runs.
    Also sends weekly report at 17:00 on Mondays.
    """
    global _LAST_REPORT_DATE
    settings = settings or Settings()
    while True:
        now = time.time()
        secs_to_next_hour = 3600 - (now % 3600)
        await asyncio.sleep(secs_to_next_hour + 5)
        
        # 检查是否需要发送每周报告（每周一 17:00）
        current_hour = datetime.now().hour
        current_weekday = datetime.now().weekday()  # 0=周一, 6=周日
        today = date.today()
        if current_weekday == 0 and current_hour == 17 and _LAST_REPORT_DATE != today:
            try:
                print("[auto_sync] 发送每周调用统计报告...")
                await _send_daily_report(settings)
                _LAST_REPORT_DATE = today
            except Exception as exc:
                print(f"[auto_sync] 发送报告失败: {exc}")
        
        try:
            await auto_sync_once(settings)
        except Exception as exc:
            print(f"[auto_sync] Error during sync: {exc}")
        # Daily sync disabled; keep hourly sync only.


_AUTO_SYNC_TASK: Optional[asyncio.Task] = None
_AUTO_SYNC_THREAD: Optional[threading.Thread] = None


def _run_auto_sync_loop_in_thread() -> None:
    asyncio.run(auto_sync_loop())


def start_auto_sync_in_background(loop: Optional[asyncio.AbstractEventLoop] = None):
    """Schedule the auto_sync_loop in the given event loop.
    If no running loop is available, start a daemon thread with its own loop.
    Returns a Task when scheduled on an event loop, or a Thread otherwise.
    """
    global _AUTO_SYNC_TASK, _AUTO_SYNC_THREAD
    if _AUTO_SYNC_TASK is not None and not _AUTO_SYNC_TASK.done():
        return _AUTO_SYNC_TASK
    if _AUTO_SYNC_THREAD is not None and _AUTO_SYNC_THREAD.is_alive():
        return _AUTO_SYNC_THREAD
    try:
        loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        _AUTO_SYNC_THREAD = threading.Thread(target=_run_auto_sync_loop_in_thread, daemon=True)
        _AUTO_SYNC_THREAD.start()
        return _AUTO_SYNC_THREAD
    _AUTO_SYNC_TASK = loop.create_task(auto_sync_loop())
    return _AUTO_SYNC_TASK


def is_auto_sync_running() -> bool:
    return _AUTO_SYNC_RUNNING.is_set()
