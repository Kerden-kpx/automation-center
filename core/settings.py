from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level_env: str = "LOG_LEVEL", default_level: str = "INFO") -> None:
    level_name = (os.getenv(level_env, default_level) or default_level).strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=_LOG_FORMAT)


def load_env_files(paths: Iterable[Path], *, override: bool = False) -> list[Path]:
    loaded: list[Path] = []
    for path in paths:
        if path.exists() and path.is_file():
            load_dotenv(path, override=override)
            loaded.append(path)
    return loaded


def env_truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or default).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else int(default)
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    return value


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def validate_required_env(names: Iterable[str]) -> None:
    missing = [name for name in names if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
