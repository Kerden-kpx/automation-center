from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from core.settings import configure_logging, env_int, env_truthy, load_env_files, validate_required_env

logger = logging.getLogger(__name__)


def _load_runtime_env() -> None:
    project_root = Path(__file__).resolve().parents[3]
    app_env = Path(__file__).resolve().parent / ".env"
    root_env = project_root / ".env"
    load_env_files([app_env, root_env], override=False)


def _validate_boot_env() -> None:
    validate_required_env(["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"])


def run() -> None:
    configure_logging()
    _load_runtime_env()
    _validate_boot_env()
    host = os.getenv("SCHEDULER_HOST", "0.0.0.0")
    port = env_int("SCHEDULER_PORT", 27643, minimum=1)
    reload_flag = env_truthy("SCHEDULER_RELOAD", "0")
    logger.info("Starting scheduler backend host=%s port=%s reload=%s", host, port, reload_flag)
    uvicorn.run(
        "apps.scheduler.backend.api:app",
        host=host,
        port=port,
        reload=reload_flag,
    )


if __name__ == "__main__":
    run()
