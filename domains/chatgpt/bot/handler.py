#!/usr/bin/env python
"""EchoTextHandler（消息处理）已搬迁到 Dingtalk-Bot 包。"""
import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import re
import time
from functools import partial
from typing import Optional, Tuple

from dingtalk_stream import AckMessage
import dingtalk_stream

from ..services.aggregator import aggregate_campaign_data
from ..services.auto_sync import is_auto_sync_running
from ..services.gpt import send_to_gpt_and_get_response
from ..services.call_logger import log_bot_call
from ..utils.formatting import format_gpt_response
from ..utils.dingtalk_api import get_token, send_robot_private_message


# 消息去重缓存：存储已处理的消息标识符，避免重复处理
# 格式：{message_key: timestamp}
_processed_messages = {}
# 消息去重缓存过期时间（秒），超过此时间的记录会被清理
_MESSAGE_DEDUP_EXPIRE_TIME = 300  # 5分钟
_CAMPAIGN_NOT_FOUND_KEY = "未找到名称+国家匹配的广告活动"

# ========== 队列配置 ==========
MAX_QUEUE_SIZE = 50
_job_queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
_worker_task: Optional[asyncio.Task] = None


@dataclass
class Job:
    user_id: str
    message_text: str
    created_at: float


async def _queue_worker(handler_ref: "EchoTextHandler") -> None:
    """队列单 worker：串行处理 GPT 相关任务。"""
    while True:
        job = await _job_queue.get()
        try:
            if is_auto_sync_running():
                await handler_ref._send_info_message_async(job.user_id, "正在同步数据，请稍等")
                while is_auto_sync_running():
                    await asyncio.sleep(1)
            await handler_ref._handle_message_async(job.message_text, job.user_id)
        finally:
            _job_queue.task_done()


def _ensure_worker_started(handler_ref: "EchoTextHandler") -> None:
    """确保队列 worker 已启动。"""
    global _worker_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _worker_task is None or _worker_task.done():
        _worker_task = loop.create_task(_queue_worker(handler_ref))


class EchoTextHandler(dingtalk_stream.ChatbotHandler):
    """处理钉钉消息的处理器"""
    
    def __init__(self, logger: Optional[logging.Logger] = None, config: Optional[object] = None):
        super().__init__()
        self.logger = logger
        self.config = config

    def _log(self, level: str, message: str, *args, **kwargs):
        if self.logger:
            getattr(self.logger, level)(message, *args, **kwargs)
        else:
            print(f"[{level.upper()}] {message}")

    async def _send_error_message(self, user_id: str, error_msg: str):
        self._log("error", error_msg)
        access_token = await get_token(self.config)
        if access_token:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                send_robot_private_message,
                access_token,
                self.config,
                [user_id],
                error_msg,
            )
        else:
            self._log("error", "access_token 获取失败，无法发送错误消息")

    async def _send_info_message(self, user_id: str, info_msg: str) -> None:
        self._log("info", info_msg)
        access_token = await get_token(self.config)
        if access_token:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                send_robot_private_message,
                access_token,
                self.config,
                [user_id],
                info_msg,
            )
        else:
            self._log("error", "access_token 获取失败，无法发送消息")

    async def _send_info_message_async(self, user_id: str, info_msg: str) -> None:
        await self._send_info_message(user_id, info_msg)

    async def _process_message(self, message_text: str) -> str:
        country, campaign_name, sku = self._parse_message(message_text)
        
        if country and campaign_name:
            sku_str = sku if sku else "(无SKU)"
            self._log("info", f"查询广告活动: {country} {campaign_name} {sku_str}")
            
            try:
                aggregate_result = await aggregate_campaign_data(country, campaign_name, sku)
                return json.dumps(aggregate_result, ensure_ascii=False, indent=2)
            except Exception as e:
                if _CAMPAIGN_NOT_FOUND_KEY in str(e):
                    raise ValueError(_CAMPAIGN_NOT_FOUND_KEY)
                self._log("warning", f"查询失败，直接转发消息到GPT: {e}")
                return message_text
        else:
            self._log("info", "消息格式不匹配，直接转发消息到GPT")
            return message_text

    async def _handle_message_async(
        self, 
        message_text: str, 
        user_id: str
    ):
        try:
            content_for_gpt = await self._process_message(message_text)
            
            self._log("info", "发送到GPT...")
            gpt_response, _ = await asyncio.shield(
                send_to_gpt_and_get_response(content_for_gpt)
            )
            
            gpt_response = format_gpt_response(gpt_response)
            msg_title = "GPT 回复"
            for line in gpt_response.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    msg_title = stripped.lstrip("#").strip() or msg_title
                break
            
            access_token = await get_token(self.config)
            if access_token:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    partial(
                        send_robot_private_message,
                        access_token,
                        self.config,
                        [user_id],
                        gpt_response,
                        msg_title=msg_title,
                        use_markdown=True,
                    ),
                )
            else:
                self._log("error", "access_token 获取失败")

        except ValueError as e:
            if _CAMPAIGN_NOT_FOUND_KEY in str(e):
                await self._send_info_message(user_id, "未找到名称+国家匹配的广告活动,请确认填写正确")
                return
            await self._send_error_message(user_id, f"查询失败: {str(e)}")
        except ConnectionError as e:
            await self._send_error_message(user_id, f"连接浏览器失败: {str(e)}")
        except TimeoutError as e:
            await self._send_error_message(user_id, f"等待GPT响应超时: {str(e)}")
        except Exception as e:
            error_msg = f"处理失败: {str(e)}"
            self._log("error", error_msg, exc_info=True)
            await self._send_error_message(user_id, error_msg)

    async def process(self, callback: dingtalk_stream.CallbackMessage) -> Tuple[str, str]:
        incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        user_id = incoming_message.sender_staff_id
        
        if not incoming_message.text or not incoming_message.text.content:
            error_msg = "消息内容为空"
            self._log("warning", error_msg)
            access_token = await get_token(self.config)
            if access_token:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    send_robot_private_message,
                    access_token,
                    self.config,
                    [user_id],
                    error_msg,
                )
            return AckMessage.STATUS_OK, 'OK'
        
        message_text = incoming_message.text.content.strip()
        country, campaign_name, _ = self._parse_message(message_text)
        triggered = bool(country and campaign_name)
        
        message_key = self._get_message_key(callback, message_text, user_id)
        
        if self._is_message_processed(message_key, mark=True):
            self._log("warning", f"消息已处理过，跳过重复处理: {message_key[:50]}...")
            return AckMessage.STATUS_OK, 'OK'
        
        self._log("info", f"开始处理新消息: {message_text[:50]}... (key: {message_key[:50]}...)")

        _ensure_worker_started(self)
        try:
            _job_queue.put_nowait(Job(user_id=user_id, message_text=message_text, created_at=time.time()))
        except asyncio.QueueFull:
            self._log("warning", "队列已满，拒绝处理新消息")
            self._unmark_message(message_key)
            asyncio.create_task(self._send_info_message_async(user_id, "系统繁忙，请稍后再试"))
            return AckMessage.STATUS_OK, 'OK'

        # 记录调用日志到数据库
        user_name = getattr(incoming_message, 'sender_nick', None) or getattr(incoming_message, 'senderNick', None)
        asyncio.create_task(log_bot_call(user_id=user_id, user_name=user_name, message_text=message_text))

        if triggered:
            info_msg = "你的问题格式触发领星查询，正在查询，请稍等......"
        else:
            info_msg = "你的问题格式未触发领星查询，只会正常查询，请稍等......"
        asyncio.create_task(self._send_info_message_async(user_id, info_msg))
        position = _job_queue.qsize()
        if position > 1:
            asyncio.create_task(self._send_info_message_async(user_id, f"已排队，当前排队人数: {position}"))
        
        return AckMessage.STATUS_OK, 'OK'

    def _parse_message(self, message_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        pattern_with_sku = r'^(\S+)\s+(.+)\s+(\S+)$'
        match_with_sku = re.match(pattern_with_sku, message_text)
        if match_with_sku:
            country = match_with_sku.group(1)
            campaign_name = match_with_sku.group(2).strip()
            sku = match_with_sku.group(3)
            if campaign_name:
                return country, campaign_name, sku
        pattern_without_sku = r'^(\S+)\s+(.+)$'
        match_without_sku = re.match(pattern_without_sku, message_text)
        if match_without_sku:
            country = match_without_sku.group(1)
            campaign_name = match_without_sku.group(2).strip()
            if campaign_name:
                return country, campaign_name, None
        return None, None, None


    def _get_message_key(self, callback: dingtalk_stream.CallbackMessage, message_text: str, user_id: str) -> str:
        try:
            if hasattr(callback, 'data') and isinstance(callback.data, dict):
                msg_id = (
                    callback.data.get('msgId') or 
                    callback.data.get('msg_id') or 
                    callback.data.get('messageId') or
                    callback.data.get('id')
                )
                if msg_id:
                    return f"msg_id:{msg_id}"
        except:
            pass
        timestamp = int(time.time())
        content_hash = hashlib.md5(f"{user_id}:{message_text}".encode('utf-8')).hexdigest()
        return f"content:{content_hash}:{timestamp}"

    def _unmark_message(self, message_key: str) -> None:
        _processed_messages.pop(message_key, None)

    def _is_message_processed(self, message_key: str, mark: bool = True) -> bool:
        now = time.time()
        expired_keys = [
            key for key, timestamp in _processed_messages.items()
            if now - timestamp > _MESSAGE_DEDUP_EXPIRE_TIME
        ]
        for key in expired_keys:
            _processed_messages.pop(key, None)
        if message_key in _processed_messages:
            return True
        if mark:
            _processed_messages[message_key] = now
        return False
