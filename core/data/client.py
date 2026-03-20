from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, TypeVar
from urllib.parse import quote_plus

import pymysql
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from .config import env_int, get_required_env

_ENGINE: Optional[Engine] = None
_ENGINE_LOCK = threading.Lock()
_RETRYABLE_MYSQL_ERRNOS = {2006, 2013}
_T = TypeVar("_T")


class _DictCursorConnection:
    def __init__(self, raw_conn):
        self._raw_conn = raw_conn

    def cursor(self, *args, **kwargs):
        if not args and not kwargs:
            return self._raw_conn.cursor(pymysql.cursors.DictCursor)
        return self._raw_conn.cursor(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._raw_conn, item)


def _build_db_url() -> str:
    user = quote_plus(get_required_env("DB_USER"))
    password = quote_plus(get_required_env("DB_PASSWORD"))
    host = get_required_env("DB_HOST")
    port = env_int("DB_PORT", 3306)
    database = quote_plus(get_required_env("DB_NAME"))
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


def _get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        _ENGINE = create_engine(
            _build_db_url(),
            pool_size=env_int("DB_POOL_SIZE", 5),
            max_overflow=env_int("DB_MAX_OVERFLOW", 10),
            pool_timeout=env_int("DB_POOL_TIMEOUT", 30),
            pool_recycle=env_int("DB_POOL_RECYCLE", 1800),
            pool_pre_ping=True,
        )
    return _ENGINE


@contextmanager
def get_connection():
    raw_conn = _get_engine().raw_connection()
    conn = _DictCursorConnection(raw_conn)
    try:
        yield conn
    except Exception:
        try:
            raw_conn.rollback()
        except pymysql.err.InterfaceError:
            # Connection is already dead; nothing left to roll back.
            pass
        raise
    finally:
        raw_conn.close()


QueryParams = Optional[Sequence[Any]]


def _normalize_params(params: QueryParams) -> Sequence[Any]:
    return params if params is not None else ()


def _is_retryable_mysql_error(exc: Exception) -> bool:
    if not isinstance(exc, pymysql.MySQLError):
        return False
    errno = int(exc.args[0]) if exc.args else 0
    return errno in _RETRYABLE_MYSQL_ERRNOS


def _run_with_reconnect_retry(action: Callable[[], _T]) -> _T:
    attempts = 2
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_retryable_mysql_error(exc):
                raise
            global _ENGINE
            with _ENGINE_LOCK:
                if _ENGINE is not None:
                    try:
                        _ENGINE.dispose()
                    except Exception:
                        pass
                    _ENGINE = None
    assert last_exc is not None
    raise last_exc


def fetch_all(sql: str, params: QueryParams = None) -> List[Dict[str, Any]]:
    normalized = _normalize_params(params)

    def _action() -> List[Dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, normalized)
                return cursor.fetchall()

    return _run_with_reconnect_retry(_action)


def execute(sql: str, params: QueryParams = None) -> int:
    normalized = _normalize_params(params)

    def _action() -> int:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, normalized)
                affected = cursor.rowcount
            conn.commit()
        return affected

    return _run_with_reconnect_retry(_action)


def execute_many(sql: str, param_sets: Iterable[Sequence[Any]]) -> int:
    batched_params = list(param_sets)

    def _action() -> int:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                affected = cursor.executemany(sql, batched_params)
            conn.commit()
        return affected

    return _run_with_reconnect_retry(_action)
