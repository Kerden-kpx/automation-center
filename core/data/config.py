from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from core.settings import load_env_files


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_APP_ENV = _PROJECT_ROOT / "apps" / "scheduler" / "backend" / ".env"
_ROOT_ENV = _PROJECT_ROOT / ".env"
load_env_files([_APP_ENV, _ROOT_ENV], override=False)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def get_required_env(name: str) -> str:
    value = get_env(name)
    if value is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return value
