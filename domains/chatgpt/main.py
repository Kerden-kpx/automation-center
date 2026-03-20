#!/usr/bin/env python
"""钉钉机器人入口：初始化配置、注册回调并启动。"""

from dataclasses import dataclass
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import types
from urllib.parse import quote_plus

import dingtalk_stream
import websockets

if __package__:
    from .bot.handler import EchoTextHandler
    from .services.auto_sync import start_auto_sync_in_background
    from .utils.error_notifier import attach_error_notifier
    from .utils.formatting import setup_logger
else:
    # Allow running directly as a script: python main.py
    package_root = Path(__file__).resolve().parent
    repo_root = package_root.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    package_name = "dingtalk_gpt_bot"
    if package_name not in sys.modules:
        package_module = types.ModuleType(package_name)
        package_module.__path__ = [str(package_root)]  # type: ignore[attr-defined]
        package_module.__file__ = str(package_root / "__init__.py")
        sys.modules[package_name] = package_module
    from dingtalk_gpt_bot.bot.handler import EchoTextHandler
    from dingtalk_gpt_bot.services.auto_sync import start_auto_sync_in_background
    from dingtalk_gpt_bot.utils.error_notifier import attach_error_notifier
    from dingtalk_gpt_bot.utils.formatting import setup_logger


@dataclass
class Config:
    client_id: str
    client_secret: str
    robot_code: str
    tech_user_ids: list
    stream_ws_ping_interval: int
    stream_ws_ping_timeout: int


def _get_cdp_url() -> str:
    return os.getenv("CDP_URL", "").strip() or "http://127.0.0.1:9222"


def _get_gpt_url() -> str:
    gpt_url = os.getenv("GPT_URL", "").strip()
    if not gpt_url:
        raise RuntimeError("Missing required env var: GPT_URL")
    return gpt_url


def _ensure_browser_and_target_page(logger) -> None:
    try:
        from core.browser.base_driver import BrowserDriver
    except Exception as exc:
        # Script-mode fallback: ensure project root is on sys.path.
        project_root = Path(__file__).resolve().parents[2]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        try:
            from core.browser.base_driver import BrowserDriver
        except Exception as exc2:
            raise RuntimeError("Cannot import BrowserDriver from core.browser.base_driver") from exc2

    driver = BrowserDriver(
        headless=False,
        use_cdp=True,
        cdp_endpoint=_get_cdp_url(),
        cdp_timeout_sec=10,
    )
    opened = driver.ensure_cdp_and_target_page(_get_gpt_url(), startup_timeout_sec=20)
    if opened:
        logger.info("Opened target GPT page: %s", _get_gpt_url())
    else:
        logger.info("Target GPT page already opened: %s", _get_gpt_url())


def _load_config_from_env() -> Config:
    _load_env_files()
    client_id = os.getenv("DING_CLIENT_ID", "").strip()
    client_secret = os.getenv("DING_CLIENT_SECRET", "").strip()
    robot_code = os.getenv("DING_ROBOT_CODE", "").strip()
    stream_ws_ping_interval = _read_positive_int_env("DING_STREAM_WS_PING_INTERVAL", 30)
    stream_ws_ping_timeout = _read_positive_int_env("DING_STREAM_WS_PING_TIMEOUT", 120)
    tech_user_ids_raw = os.getenv("DING_TECH_USER_IDS", "").strip()
    tech_user_ids = [item for item in re.split(r"[,\s;]+", tech_user_ids_raw) if item]

    missing = []
    if not client_id:
        missing.append("DING_CLIENT_ID")
    if not client_secret:
        missing.append("DING_CLIENT_SECRET")
    if not robot_code:
        missing.append("DING_ROBOT_CODE")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    return Config(
        client_id=client_id,
        client_secret=client_secret,
        robot_code=robot_code,
        tech_user_ids=tech_user_ids,
        stream_ws_ping_interval=stream_ws_ping_interval,
        stream_ws_ping_timeout=stream_ws_ping_timeout,
    )


def _read_positive_int_env(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{key} must be a positive integer, got: {raw!r}") from exc
    if parsed <= 0:
        raise RuntimeError(f"{key} must be > 0, got: {raw!r}")
    return parsed


class ResilientDingTalkStreamClient(dingtalk_stream.DingTalkStreamClient):
    """Override websocket connect params to reduce false keepalive timeout disconnects."""

    def __init__(
        self,
        credential: dingtalk_stream.Credential,
        logger,
        ping_interval: int,
        ping_timeout: int,
    ):
        super().__init__(credential, logger=logger)
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout

    async def start(self):
        self.pre_start()

        while True:
            try:
                connection = self.open_connection()

                if not connection:
                    self.logger.error("open connection failed")
                    await asyncio.sleep(10)
                    continue
                self.logger.info("endpoint is %s", connection)

                uri = f'{connection["endpoint"]}?ticket={quote_plus(connection["ticket"])}'
                async with websockets.connect(
                    uri,
                    ping_interval=self._ping_interval,
                    ping_timeout=self._ping_timeout,
                    close_timeout=10,
                ) as websocket:
                    self.websocket = websocket
                    asyncio.create_task(self.keepalive(websocket))
                    async for raw_message in websocket:
                        json_message = json.loads(raw_message)
                        asyncio.create_task(self.background_task(json_message))
            except KeyboardInterrupt:
                break
            except (
                asyncio.exceptions.CancelledError,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            ) as exc:
                self.logger.warning("[start] stream disconnected, reconnecting in 10s: %s", exc)
                await asyncio.sleep(10)
                continue
            except Exception:
                self.logger.exception("unknown exception")
                await asyncio.sleep(3)
                continue


def _load_env_files() -> None:
    """Load .env from cwd and package directory without overriding existing env."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def main() -> None:
    logger = setup_logger()
    _load_env_files()
    _ensure_browser_and_target_page(logger)
    config = _load_config_from_env()
    attach_error_notifier(logger, config)
    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = ResilientDingTalkStreamClient(
        credential,
        logger=logger,
        ping_interval=config.stream_ws_ping_interval,
        ping_timeout=config.stream_ws_ping_timeout,
    )

    try:
        start_auto_sync_in_background()
        logger.info("auto_sync background task started")
    except Exception as exc:
        logger.warning("auto_sync background task failed to start: %s", exc)

    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        EchoTextHandler(logger, config),
    )
    client.start_forever()


if __name__ == "__main__":
    main()
