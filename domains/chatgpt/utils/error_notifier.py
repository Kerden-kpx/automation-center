#!/usr/bin/env python
"""日志 ERROR 级别通知钉钉技术人员。"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import traceback
from typing import Iterable, Optional

from .dingtalk_api import get_token_sync, send_robot_private_message


class DingTalkErrorNotifier(logging.Handler):
    """将 ERROR 日志转发到钉钉单聊。"""

    def __init__(
        self,
        config,
        user_ids: Iterable[str],
        *,
        dedup_seconds: int = 60,
        max_message_len: int = 1500,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self.config = config
        self.user_ids = [uid for uid in user_ids if uid]
        self.dedup_seconds = max(0, int(dedup_seconds))
        self.max_message_len = max(200, int(max_message_len))
        self._lock = threading.Lock()
        self._last_sent = {}
        self._local = threading.local()
        self._queue: queue.Queue[str] = queue.Queue(maxsize=200)
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="dingtalk-error-notifier",
            daemon=True,
        )
        self._worker.start()

    def _should_skip(self) -> bool:
        return bool(getattr(self._local, "sending", False))

    def _build_message(self, record: logging.LogRecord) -> str:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        base = f"[{timestamp}] {record.levelname} {record.name}\n{record.getMessage()}"
        if record.pathname:
            base += f"\n{record.pathname}:{record.lineno}"
        if record.exc_info:
            exc_text = "".join(traceback.format_exception(*record.exc_info)).strip()
            if exc_text:
                base += f"\n{exc_text}"
        if len(base) > self.max_message_len:
            base = base[: self.max_message_len - 20] + "\n... (truncated)"
        return base

    def _allow_send(self, record: logging.LogRecord) -> bool:
        if self.dedup_seconds <= 0:
            return True
        key = f"{record.name}:{record.levelno}:{record.getMessage()}"
        now = time.time()
        with self._lock:
            last = self._last_sent.get(key, 0)
            if now - last < self.dedup_seconds:
                return False
            self._last_sent[key] = now
            if len(self._last_sent) > 2000:
                cutoff = now - max(self.dedup_seconds * 5, 300)
                stale_keys = [k for k, ts in self._last_sent.items() if ts < cutoff]
                for k in stale_keys:
                    self._last_sent.pop(k, None)
        return True

    def _worker_loop(self) -> None:
        while True:
            message = self._queue.get()
            try:
                self._local.sending = True
                token = get_token_sync(self.config)
                if not token:
                    continue
                send_robot_private_message(
                    token,
                    self.config,
                    self.user_ids,
                    message,
                    msg_title="Bot Error",
                )
            except Exception:
                pass
            finally:
                self._local.sending = False
                self._queue.task_done()

    def emit(self, record: logging.LogRecord) -> None:
        if not self.user_ids:
            return
        if record.levelno < logging.ERROR:
            return
        if self._should_skip():
            return
        if not self._allow_send(record):
            return
        message = self._build_message(record)
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                return
            try:
                self._queue.put_nowait(message)
            except queue.Full:
                return


def attach_error_notifier(logger: logging.Logger, config) -> Optional[DingTalkErrorNotifier]:
    """在 root logger 上挂载错误通知处理器。"""
    if config is None:
        return None
    user_ids = getattr(config, "tech_user_ids", None) or []
    if not user_ids:
        return None
    for handler in logger.handlers:
        if isinstance(handler, DingTalkErrorNotifier):
            return handler
    dedup_raw = os.getenv("DING_ERROR_NOTIFY_DEDUP_SECS", "60").strip()
    try:
        dedup_seconds = int(dedup_raw)
    except ValueError:
        dedup_seconds = 60
    notifier = DingTalkErrorNotifier(config, user_ids, dedup_seconds=dedup_seconds)
    logger.addHandler(notifier)
    return notifier
