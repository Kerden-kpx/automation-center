#!/usr/bin/env python
"""调用日志记录服务：记录每次机器人被调用的信息。"""

import asyncio
from datetime import datetime
from typing import Optional

import aiomysql

from .synchronize import Settings, _get_db_pool


# 表名
TABLE_NAME = "dingtalk_gpt_bot_logs"


async def log_bot_call(
    user_id: str,
    user_name: Optional[str] = None,
    message_text: Optional[str] = None,
) -> bool:
    """
    记录一次机器人调用到数据库。
    
    Args:
        user_id: 钉钉用户ID
        user_name: 用户名称（可选）
        message_text: 用户发送的问题（可选）
    
    Returns:
        bool: 记录成功返回 True，失败返回 False
    """
    settings = Settings()
    pool = await _get_db_pool(settings.db_config)
    
    if pool is None:
        print(f"[warn] 无法获取数据库连接池，跳过日志记录")
        return False
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                sql = f"""
                    INSERT INTO `{TABLE_NAME}` 
                    (`created_at`, `user_id`, `user_name`, `message_text`)
                    VALUES (%s, %s, %s, %s)
                """
                await cur.execute(sql, (
                    datetime.now(),
                    user_id,
                    user_name,
                    message_text,
                ))
                return True
    except Exception as exc:
        print(f"[error] 记录调用日志失败: {exc}")
        return False


async def get_call_stats() -> dict:
    """
    获取调用统计信息。
    
    Returns:
        dict: 包含统计信息的字典
    """
    settings = Settings()
    pool = await _get_db_pool(settings.db_config)
    
    if pool is None:
        return {"error": "无法获取数据库连接池"}
    
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # 总调用次数
                await cur.execute(f"SELECT COUNT(*) AS total FROM `{TABLE_NAME}`")
                total_row = await cur.fetchone()
                total_calls = total_row["total"] if total_row else 0
                
                # 按用户统计
                await cur.execute(f"""
                    SELECT user_id, user_name, COUNT(*) AS call_count 
                    FROM `{TABLE_NAME}` 
                    GROUP BY user_id, user_name 
                    ORDER BY call_count DESC
                    LIMIT 20
                """)
                user_stats = await cur.fetchall()
                
                # 最近7天统计
                await cur.execute(f"""
                    SELECT DATE(created_at) AS call_date, COUNT(*) AS call_count 
                    FROM `{TABLE_NAME}` 
                    WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    GROUP BY DATE(created_at) 
                    ORDER BY call_date DESC
                """)
                daily_stats = await cur.fetchall()
                
                return {
                    "total_calls": total_calls,
                    "user_stats": list(user_stats),
                    "daily_stats": list(daily_stats),
                }
    except Exception as exc:
        return {"error": str(exc)}
