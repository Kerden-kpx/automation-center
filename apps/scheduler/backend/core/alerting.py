from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from urllib.request import Request, urlopen


class SchedulerAlertNotifier:
    def __init__(
        self,
        *,
        enabled: bool,
        mode: str,
        user_ids: list[str],
        webhook_url: str,
        dedup_secs: int,
        timeout_sec: int,
    ) -> None:
        self._enabled = enabled
        self._mode = mode
        self._user_ids = [uid for uid in user_ids if uid]
        self._webhook_url = webhook_url
        self._dedup_secs = max(0, int(dedup_secs))
        self._timeout_sec = max(2, int(timeout_sec))
        self._lock = threading.Lock()
        self._last_sent: dict[str, float] = {}

    @classmethod
    def from_env(cls) -> "SchedulerAlertNotifier":
        enabled = os.getenv("SCHEDULER_ALERT_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
        mode = (os.getenv("SCHEDULER_ALERT_MODE", "dingtalk_user").strip().lower() or "dingtalk_user")
        user_ids = [
            item.strip()
            for item in os.getenv("SCHEDULER_ALERT_USER_IDS", "").replace(";", ",").split(",")
            if item.strip()
        ]
        webhook_url = os.getenv("SCHEDULER_ALERT_WEBHOOK", "").strip()
        dedup_secs = int(os.getenv("SCHEDULER_ALERT_DEDUP_SECS", "120") or 120)
        timeout_sec = int(os.getenv("SCHEDULER_ALERT_TIMEOUT_SEC", "5") or 5)

        if mode == "dingtalk_user":
            real_enabled = enabled and bool(user_ids)
        elif mode == "webhook":
            real_enabled = enabled and bool(webhook_url)
        else:
            real_enabled = False

        return cls(
            enabled=real_enabled,
            mode=mode,
            user_ids=user_ids,
            webhook_url=webhook_url,
            dedup_secs=dedup_secs,
            timeout_sec=timeout_sec,
        )

    def notify_failure(
        self,
        *,
        task_id: str,
        run_id: str,
        status: str,
        error_message: str,
        trigger_type: str,
        attempt: int,
    ) -> None:
        if not self._enabled:
            return
        dedup_key = f"{task_id}:{status}:{error_message[:120]}"
        now = time.time()
        with self._lock:
            prev = self._last_sent.get(dedup_key)
            if prev is not None and (now - prev) < self._dedup_secs:
                return
            self._last_sent[dedup_key] = now

        content = "\n".join(
            [
                "[Scheduler Alert] Task failed",
                f"time={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"task_id={task_id}",
                f"run_id={run_id}",
                f"status={status}",
                f"trigger={trigger_type}",
                f"attempt={attempt}",
                f"error={error_message or 'unknown'}",
            ]
        )

        if self._mode == "dingtalk_user":
            self._send_dingtalk_user_text(content)
            return
        if self._mode == "webhook":
            self._post_webhook(content)

    def _send_dingtalk_user_text(self, content: str) -> None:
        try:
            from core.integrations.dingtalk_client import send_user_text
        except Exception:
            return

        for user_id in self._user_ids:
            try:
                send_user_text(user_id=user_id, text=content)
            except Exception:
                continue

    def _post_webhook(self, content: str) -> None:
        try:
            payload = {
                "msgtype": "text",
                "text": {"content": content},
            }
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = Request(
                self._webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=self._timeout_sec):  # noqa: S310
                pass
        except Exception:
            return
