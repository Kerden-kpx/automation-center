"""Synchronize utilities (legacy script module)."""

import asyncio
import base64
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Callable, Tuple
from collections import OrderedDict
import aiohttp
import aiomysql
import pydantic as pyd


# orjson 可选；未安装或无二进制轮子时回退到 json
try:  # pragma: no cover
    import orjson  # type: ignore

    def _dumps(obj, sort: bool = False) -> str:
        opt = orjson.OPT_SORT_KEYS if sort else 0
        return orjson.dumps(obj, option=opt).decode()

    def _dumps_bytes(obj, sort: bool = False) -> bytes:
        opt = orjson.OPT_SORT_KEYS if sort else 0
        return orjson.dumps(obj, option=opt)

except Exception:  # pragma: no cover
    import json

    print("[warn] orjson 未安装或不可用，已回退到内置 json，性能略低")

    def _dumps(obj, sort: bool = False) -> str:
        return json.dumps(obj, ensure_ascii=False, sort_keys=sort)

    def _dumps_bytes(obj, sort: bool = False) -> bytes:
        return _dumps(obj, sort).encode("utf-8")

BaseModel = pyd.BaseModel
PYD_VERSION = getattr(pyd, "VERSION", getattr(pyd, "__version__", "1"))

_PYD_MAJOR = int(PYD_VERSION.split(".")[0]) if PYD_VERSION else 1

try:  # Pydantic v1 API
    from pydantic import root_validator  # type: ignore
except Exception:  # pragma: no cover
    root_validator = None

try:  # Pydantic v2 API
    from pydantic import model_validator
except Exception:  # pragma: no cover
    model_validator = None


# =============== 加密与签名 ===============
BLOCK_SIZE = 16


def _do_pad(text: str) -> str:
    """PKCS7 padding: 如果文本长度正好是16的倍数，需要填充16个字符"""
    pad_len = BLOCK_SIZE - (len(text) % BLOCK_SIZE)
    return text + chr(pad_len) * pad_len


def _aes_encrypt(key: str, data: str) -> str:
    from Crypto.Cipher import AES  # 延迟导入，避免未安装时报错过早

    cipher = AES.new(key.encode("utf-8"), AES.MODE_ECB)
    result = cipher.encrypt(_do_pad(data).encode())
    return base64.b64encode(result).decode("utf-8")


def _md5(text: str) -> str:
    md = hashlib.md5()
    md.update(text.encode("utf-8"))
    return md.hexdigest()


class SignBase:
    @classmethod
    def generate_sign(cls, encrypt_key: str, request_params: dict) -> str:
        canonical = cls.format_params(request_params)
        return _aes_encrypt(encrypt_key, _md5(canonical).upper())

    @classmethod
    def format_params(cls, request_params: Optional[dict]) -> str:
        if not request_params:
            return ""
        parts = []
        for k in sorted(request_params.keys()):
            v = request_params[k]
            if v == "":
                continue
            if isinstance(v, (dict, list)):
                parts.append(f"{k}={_dumps(v, sort=True)}")
            else:
                parts.append(f"{k}={v}")
        return "&".join(parts)


# =============== 数据模型 ===============

Row = List[Any]
Rows = List[Row]

CAMPAIGN_REPORT_ROUTES: Dict[str, str] = {
    "/pb/openapi/newad/spCampaignReports": "sp",
    "/pb/openapi/newad/hsaCampaignReports": "sb",
}

SP_PRODUCT_ADS_ROUTE = "/pb/openapi/newad/spProductAdReports"
SP_PRODUCT_ADS_ROUTE2 = "/pb/openapi/newad/spProductAds"
SP_KEYWORD_REPORTS_ROUTE = "/pb/openapi/newad/spKeywordReports"
SB_TARGET_REPORT_ROUTE = "/pb/openapi/newad/listHsaTargetingReport"
SB_TARGETING_ROUTE = "/pb/openapi/newad/sbTargeting"
SP_TARGET_HOUR_ROUTE = "/pb/openapi/newad/spTargetHourData"

QUERY_WORD_ROUTES: Dict[str, str] = {
    "/pb/openapi/newad/queryWordReports": "sp",
    "/pb/openapi/newad/hsaQueryWordReports": "sb",
}

CAMPAIGN_NAME_ROUTES: Dict[str, str] = {
    "/pb/openapi/newad/spCampaigns": "sp",
    "/pb/openapi/newad/hsaCampaigns": "sb",
}

AD_GROUP_ROUTES: Dict[str, str] = {
    "/pb/openapi/newad/spAdGroups": "sp",
    "/pb/openapi/newad/hsaAdGroups": "sb",
}

# 可选：手动指定 access_token
# 默认值填入用户提供的 token，可按需修改。
MANUAL_ACCESS_TOKEN = os.getenv(
    "MANUAL_ACCESS_TOKEN",
    "",
).strip()
TOKEN_URL = os.getenv("TOKEN_URL", "").strip()
TOKEN_REQUEST_KEY = os.getenv("TOKEN_REQUEST_KEY", "").strip()


def _is_asin_query(query: Optional[str]) -> int:
    """判断搜索词是否形似 ASIN（10 位字母数字）。"""
    if not query:
        return 0
    return 1 if re.fullmatch(r"[A-Za-z0-9]{10}", query.strip()) else 0


def _reset_msg_and_trace_id(cls, values: dict):
    values["message"] = values.get("message") or values.get("msg", "")
    values["request_id"] = values.get("request_id") or values.get("traceId", "")
    return values


class ResponseResult(BaseModel):
    code: Optional[int]
    message: Optional[str]
    data: Any
    error_details: Optional[Any] = None
    request_id: Optional[str] = None
    response_time: Optional[str] = None
    total: Optional[int] = None

    if _PYD_MAJOR >= 2 and model_validator:
        @model_validator(mode="before")  # type: ignore
        @classmethod
        def _reset(cls, values):
            return _reset_msg_and_trace_id(cls, values)
    elif root_validator:  # fallback for v1
        _reset = root_validator(pre=True)(_reset_msg_and_trace_id)  # type: ignore


class AccessTokenDto(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


_HTTP_SESSIONS: Dict[asyncio.AbstractEventLoop, aiohttp.ClientSession] = {}

# =============== 请求缓存 ===============
# 简单的 LRU 缓存实现（用于请求缓存）
_REQUEST_CACHE: OrderedDict = OrderedDict()
_CACHE_MAX_SIZE = 1000  # 最大缓存条目数
_CACHE_LOCK = asyncio.Lock()


def _make_cache_key(route: str, payload: dict) -> str:
    """生成缓存键（基于路由和请求体）"""
    import json
    # 排序 payload 以确保相同内容生成相同键
    sorted_payload = json.dumps(payload, sort_keys=True) if payload else ""
    return f"{route}:{sorted_payload}"


async def _get_cached_response(cache_key: str, cache_ttl: int) -> Optional[ResponseResult]:
    """从缓存获取响应（如果未过期）"""
    async with _CACHE_LOCK:
        if cache_key in _REQUEST_CACHE:
            cached_data, cached_time = _REQUEST_CACHE[cache_key]
            if time.time() - cached_time < cache_ttl:
                # 移动到末尾（LRU）
                _REQUEST_CACHE.move_to_end(cache_key)
                return cached_data
            else:
                # 过期，删除
                del _REQUEST_CACHE[cache_key]
    return None


async def _set_cached_response(cache_key: str, response: ResponseResult):
    """将响应存入缓存"""
    async with _CACHE_LOCK:
        if cache_key in _REQUEST_CACHE:
            _REQUEST_CACHE.move_to_end(cache_key)
        else:
            if len(_REQUEST_CACHE) >= _CACHE_MAX_SIZE:
                # 删除最旧的条目（LRU）
                _REQUEST_CACHE.popitem(last=False)
            _REQUEST_CACHE[cache_key] = (response, time.time())


def _clear_request_cache():
    """清空请求缓存（用于测试或手动清理）"""
    global _REQUEST_CACHE
    _REQUEST_CACHE.clear()


def _get_current_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.get_event_loop()


async def _get_http_session() -> aiohttp.ClientSession:
    """获取当前事件循环复用的 aiohttp 会话；如已关闭则重建。"""
    loop = _get_current_loop()
    session = _HTTP_SESSIONS.get(loop)
    if session is None or session.closed:
        # HTTP 连接优化配置
        connector = aiohttp.TCPConnector(
            limit=100,              # 总连接数限制
            limit_per_host=30,      # 每个主机连接数限制
            ttl_dns_cache=300,      # DNS 缓存时间（秒）
            enable_cleanup_closed=True,  # 启用清理已关闭的连接
            force_close=False,      # 不强制关闭连接，支持连接复用
        )
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60, connect=10),  # 总超时60秒，连接超时10秒
            connector=connector,
            headers={"Connection": "keep-alive"}  # 保持连接
        )
        _HTTP_SESSIONS[loop] = session
    return session


async def _close_http_session():
    loop = _get_current_loop()
    session = _HTTP_SESSIONS.pop(loop, None)
    if session is not None and not session.closed:
        await session.close()


# =============== HTTP 封装 ===============
class HttpBase:
    def __init__(self, default_timeout: int = 30):
        self.default_timeout = default_timeout

    async def request(self, method: str, req_url: str, params: Optional[dict] = None,
                      json: Optional[dict] = None, headers: Optional[dict] = None, **kwargs) -> ResponseResult:
        timeout = kwargs.pop("timeout", self.default_timeout)
        data = _dumps_bytes(json, sort=True) if json else None
        session = await _get_http_session()
        async with session.request(method=method, url=req_url, params=params, data=data,
                                   timeout=timeout, headers=headers, **kwargs) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}: {await resp.text()}")
            return ResponseResult(**await resp.json())


# =============== OpenAPI 封装 ===============
class OpenApiBase:
    def __init__(self, host: str, app_id: str, app_secret: str, enable_cache: bool = True, cache_ttl: int = 300,
                 enable_prefetch: bool = True, prefetch_pages: int = 2):
        self.host = host.rstrip("/")
        self.app_id = app_id
        self.app_secret = app_secret
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        self.enable_prefetch = enable_prefetch
        self.prefetch_pages = prefetch_pages

    async def generate_access_token(self) -> AccessTokenDto:
        path = "/api/auth-server/oauth/access-token"
        params = {"appId": self.app_id, "appSecret": self.app_secret}
        result = await HttpBase().request("POST", self.host + path, params=params)
        if result.code != 200:
            raise ValueError(f"generate_access_token failed: {result.message}")
        return AccessTokenDto(**result.data)

    async def request(self, access_token: str, route_name: str, method: str,
                      req_params: Optional[dict] = None, req_body: Optional[dict] = None,
                      use_cache: Optional[bool] = None, **kwargs) -> ResponseResult:
        """发送 API 请求，支持缓存。

        Args:
            use_cache: 是否使用缓存（None 时使用 self.enable_cache，POST 请求默认不使用缓存）
        """
        # 对于 GET 请求，尝试从缓存获取（POST 请求通常包含 timestamp，不适合缓存）
        use_cache = use_cache if use_cache is not None else (self.enable_cache and method == "GET")
        if use_cache:
            # 创建缓存键（不包含 timestamp 和 sign，因为这些每次都会变化）
            cache_payload = {**(req_body or {}), **(req_params or {})}
            # 移除签名相关字段
            cache_payload.pop("timestamp", None)
            cache_payload.pop("sign", None)
            cache_payload.pop("app_key", None)
            cache_payload.pop("access_token", None)
            cache_key = _make_cache_key(route_name, cache_payload)
            cached = await _get_cached_response(cache_key, self.cache_ttl)
            if cached is not None:
                return cached

        req_url = self.host + route_name
        headers = kwargs.pop("headers", {})

        req_params = req_params or {}
        sign_params = {"app_key": self.app_id, "access_token": access_token, "timestamp": str(int(time.time()))}
        merged_for_sign = {**(req_body or {}), **req_params, **sign_params}
        sign_params["sign"] = SignBase.generate_sign(self.app_id, merged_for_sign)
        req_params.update(sign_params)

        if req_body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        result = await HttpBase().request(method, req_url, params=req_params, json=req_body, headers=headers, **kwargs)

        # 缓存成功的 GET 请求结果
        if use_cache and result.code in (0, 200):
            cache_payload = {**(req_body or {}), **(req_params or {})}
            cache_payload.pop("timestamp", None)
            cache_payload.pop("sign", None)
            cache_payload.pop("app_key", None)
            cache_payload.pop("access_token", None)
            cache_key = _make_cache_key(route_name, cache_payload)
            await _set_cached_response(cache_key, result)

        return result


# =============== 业务示例 ===============
# 尝试从 .env 加载环境变量（简易实现，避免额外依赖）


def _load_env_file(path: str = ".env"):
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 兼容 KEY=VAL 与 KEY: VAL 两种写法
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


_load_env_file()


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val not in ("0", "false", "False")


TIMING_ENABLED = _env_bool("ENABLE_TIMING", True)
_TIMING_STATS: Dict[str, Dict[str, float]] = {}


def _timing_log(label: str, start_ts: float):
    """记录并打印耗时（由 ENABLE_TIMING 控制）。"""
    if not TIMING_ENABLED:
        return
    duration = time.perf_counter() - start_ts
    stats = _TIMING_STATS.get(label)
    if stats is None:
        _TIMING_STATS[label] = {"total": duration, "count": 1.0, "max": duration}
    else:
        stats["total"] += duration
        stats["count"] += 1.0
        stats["max"] = max(stats["max"], duration)
    print(f"[timing] {label}: {duration:.2f}s")


def _print_timing_summary():
    if not TIMING_ENABLED or not _TIMING_STATS:
        return
    print("\n[timing] Summary (total desc):")
    items = sorted(_TIMING_STATS.items(), key=lambda x: x[1]["total"], reverse=True)
    for label, stats in items:
        count = int(stats["count"])
        avg = stats["total"] / stats["count"]
        print(
            f"[timing] {label}: total {stats['total']:.2f}s, count {count}, avg {avg:.2f}s, max {stats['max']:.2f}s"
        )


@dataclass
class Settings:
    host: str = field(default_factory=lambda: os.getenv("HOST", "https://openapi.lingxing.com"))
    app_id: Optional[str] = field(default_factory=lambda: os.getenv("APP_ID"))
    app_secret: Optional[str] = field(default_factory=lambda: os.getenv("APP_SECRET"))
    # 若提供则优先使用手动 token，不再请求新 token；可通过环境变量 MANUAL_ACCESS_TOKEN 覆盖
    manual_access_token: Optional[str] = field(default_factory=lambda: MANUAL_ACCESS_TOKEN or None)
    token_url: Optional[str] = field(default_factory=lambda: TOKEN_URL or None)
    token_request_key: Optional[str] = field(default_factory=lambda: TOKEN_REQUEST_KEY or None)
    db_config: Dict[str, Any] = field(default_factory=lambda: {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", ""),
        "password": os.getenv("DB_PASSWORD", ""),
        "db": os.getenv("DB_NAME", ""),
        "charset": "utf8mb4",
        "autocommit": True,
        # 连接池优化配置
        "minsize": int(os.getenv("DB_POOL_MINSIZE", "5")),  # 最小连接数
        "maxsize": int(os.getenv("DB_POOL_MAXSIZE", "20")),  # 最大连接数
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "3600")),  # 连接回收时间（秒）
    })
    # 独立开关：活动报表、商品报表、名称/广告组同步
    run_campaign_reports: bool = True
    run_queryword_reports: bool = True
    # ---------------------------------
    run_sp_keyword_reports: bool = False
    run_sp_target_hour_reports: bool = False
    run_sb_target_reports: bool = False
    # ---------------------------------
    run_names: bool = True
    run_ad_groups: bool = True
    run_sb_creativity: bool = True
    run_sp_product_ads: bool = True
    # ---------------------------------
    run_sb_targeting_dim: bool = False
    # ---------------------------------
    date_list_override: List[str] = field(default_factory=list)
    # 默认使用手动指定的起止日期；可按需修改
    report_start_date: str = "2025-12-13"
    report_end_date: str = "2026-01-13"

    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "24"))  # 从 8 提升到 24
    # 拉取接口分页大小（可通过环境变量 PAGE_SIZE 覆盖；默认 50000）
    page_size: int = int(os.getenv("PAGE_SIZE", "50000"))
    queryword_target_type: str = field(default_factory=lambda: os.getenv("QUERYWORD_TARGET_TYPE", "target"))
    queryword_target_type_extra: str = field(default_factory=lambda: os.getenv("QUERYWORD_TARGET_TYPE_EXTRA", "keyword"))
    retries: int = int(os.getenv("RETRY_TIMES", "3"))
    retry_on_empty: bool = True  # 若某日全部为空，是否再重试一次
    slow_retry_on_empty: bool = True  # 二次为空时是否再降并发慢速重试
    slow_retry_concurrency: int = 1
    slow_retry_retries: int = 5
    slow_retry_delay: float = 3.0
    date_concurrency: int = int(os.getenv("DATE_CONCURRENCY", "6"))  # 从 2 提升到 6
    # 数据库写入并发数（新增）
    db_write_concurrency: int = int(os.getenv("DB_WRITE_CONCURRENCY", "4"))
    # 数据库批量写入大小（可通过环境变量 DB_BATCH_SIZE 覆盖；默认 1000）
    db_batch_size: int = int(os.getenv("DB_BATCH_SIZE", "1000"))
    # 分页预取配置（新增）
    enable_page_prefetch: bool = _env_bool("ENABLE_PAGE_PREFETCH", True)  # 是否启用分页预取
    prefetch_pages: int = int(os.getenv("PREFETCH_PAGES", "2"))  # 预取页数（默认2页）
    # 请求缓存配置（新增）
    enable_request_cache: bool = _env_bool("ENABLE_REQUEST_CACHE", True)  # 是否启用请求缓存
    cache_ttl: int = int(os.getenv("CACHE_TTL", "300"))  # 缓存时间（秒，默认5分钟）

    @property
    def date_list(self) -> List[str]:
        if self.date_list_override:
            return self.date_list_override
        day_seconds = 24 * 3600
        start_ts = int(time.mktime(time.strptime(self.report_start_date, "%Y-%m-%d")))
        end_ts = int(time.mktime(time.strptime(self.report_end_date, "%Y-%m-%d")))
        return [time.strftime("%Y-%m-%d", time.localtime(ts)) for ts in range(start_ts, end_ts + 1, day_seconds)]


async def _create_pool_with_retry(db_config: Dict[str, Any], attempts: int = 3, base_delay: float = 0.5):
    """创建 MySQL 连接池，带重试。失败返回 None。"""
    for i in range(1, attempts + 1):
        try:
            return await aiomysql.create_pool(**db_config)
        except Exception as exc:
            if i == attempts:
                print(f"[error] 创建 MySQL 连接池失败（{i}/{attempts}）: {exc}")
                return None
            delay = base_delay * i
            print(f"[warn] 创建 MySQL 连接池失败（{i}/{attempts}），{delay:.1f}s 后重试: {exc}")


async def _fetch_custom_access_token(token_url: str, token_request_key: str) -> Optional[str]:
    if not token_url or not token_request_key:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json={"api_key": token_request_key}) as resp:
                token_resp = await resp.json()
    except Exception as exc:
        print(f"[warn] 自定义 token 获取失败: {exc}")
        return None
    if isinstance(token_resp, dict):
        token = token_resp.get("access_token")
        if token:
            return token
        data = token_resp.get("data")
        if isinstance(data, dict):
            return data.get("access_token")
    return None


async def get_lingxing_access_token(settings: Settings, op_api: OpenApiBase) -> str:
    if settings.manual_access_token:
        return settings.manual_access_token
    if settings.token_url and settings.token_request_key:
        token = await _fetch_custom_access_token(settings.token_url, settings.token_request_key)
        if token:
            return token
        print("[warn] 自定义 token 为空，回退到 APP_ID/APP_SECRET 获取")
    token_resp = await op_api.generate_access_token()
    return token_resp.access_token


_DB_POOLS: Dict[asyncio.AbstractEventLoop, aiomysql.Pool] = {}


async def _get_db_pool(db_config: Dict[str, Any]) -> Optional[aiomysql.Pool]:
    """获取当前事件循环复用的 MySQL 连接池，如未创建则按配置初始化。"""
    loop = _get_current_loop()
    pool = _DB_POOLS.get(loop)
    if pool is None or pool.closed:
        pool = await _create_pool_with_retry(db_config)
        if pool is not None:
            _DB_POOLS[loop] = pool
    return pool


async def _close_db_pool():
    """关闭当前事件循环的 MySQL 连接池。"""
    loop = _get_current_loop()
    pool = _DB_POOLS.pop(loop, None)
    if pool is not None and not pool.closed:
        pool.close()
        await pool.wait_closed()


async def _prepare_db_pool(db_config: Dict[str, Any], label: str) -> Optional[aiomysql.Pool]:
    """校验 DB_NAME 并返回连接池，缺失时给出统一提示。"""
    db_name = db_config.get("db") or ""
    if not db_name:
        print(f"[warn] 未设置 DB_NAME（数据库名），跳过{label}写库。请设置后重试。")
        return None
    return await _get_db_pool(db_config)


def _chunked(seq: Iterable[Row], size: int) -> Iterable[List[Row]]:
    """将序列按固定 batch 切块。"""
    buf: List[Row] = []
    for item in seq:
        buf.append(item)
        if len(buf) == size:
            yield buf
            buf = []
    if buf:
        yield buf


async def _execute_multi_values(cur, rows: Rows, insert_prefix: str, update_clause: str,
                                column_count: int, batch_size: int) -> int:
    """以多值 INSERT 批量写入，返回影响行数。"""
    affected = 0
    for chunk in _chunked(rows, batch_size):
        valid_chunk = [r for r in chunk if len(r) >= column_count]
        if not valid_chunk:
            continue
        values_placeholder = ", ".join(
            ["(" + ",".join(["%s"] * column_count) + ")"] * len(valid_chunk)
        )
        sql = insert_prefix + values_placeholder + update_clause
        flat_values: List[Any] = []
        for r in valid_chunk:
            flat_values.extend(r[:column_count])
        await cur.execute(sql, flat_values)
        affected += cur.rowcount
    return affected


async def fetch_campaign_reports(op_api: OpenApiBase, access_token: str, route: str,
                                 payload: dict, tag: str, sid: int, seller_name: str,
                                 sem: asyncio.Semaphore, page_size: int, retries: int,
                                 country: Optional[str] = None) -> List[list]:
    def _process(item: dict, rows: List[list]):
        rows.append([
            sid,
            seller_name,
            tag,
            country,
            item.get("campaign_id"),
            item.get("impressions"),
            item.get("clicks"),
            item.get("cost"),
            item.get("sales"),
            item.get("orders"),
            item.get("units"),
            item.get("report_date"),
        ])

    return await _fetch_with_pagination(
        op_api,
        access_token,
        route,
        payload,
        page_size,
        sem,
        retries,
        _process,
        seller_id=sid,
        seller_name=seller_name,
        tag=tag,
    )


async def fetch_product_ads(op_api: OpenApiBase, access_token: str, payload: dict, report_date: str,
                            sid: int, seller_name: str, sem: asyncio.Semaphore, page_size: int,
                            retries: int, country: Optional[str] = None) -> List[list]:
    """获取商品级广告报表（spProductAdReports），返回行列表；参数与 spCampaignReports 保持一致。"""

    def _process(item: dict, rows: List[list]):
        asin_value = item.get("asin") or item.get("sku") or item.get("msku") or ""
        sku_value = item.get("sku") or item.get("msku") or item.get("asin") or ""
        rows.append([
            sid,
            seller_name,
            "sp",  # 仅拉取 SP 商品广告
            country,
            item.get("campaign_id"),
            item.get("ad_id"),
            asin_value,
            sku_value,
            item.get("impressions"),
            item.get("clicks"),
            item.get("cost"),
            item.get("sales"),
            item.get("orders"),
            item.get("units"),
            report_date,
        ])

    return await _fetch_with_pagination(
        op_api,
        access_token,
        SP_PRODUCT_ADS_ROUTE,
        payload,
        page_size,
        sem,
        retries,
        _process,
        seller_id=sid,
        seller_name=seller_name,
        tag="sp",
    )


async def fetch_sp_product_ads(op_api: OpenApiBase, access_token: str, payload: dict,
                                sid: int, seller_name: str, sem: asyncio.Semaphore,
                                page_size: int, retries: int) -> List[list]:
    """获取 SP 商品广告（spProductAds），返回行列表；过滤掉 state='archived' 的数据。

    注意：该接口支持一次性拉取大量数据，使用较大的 page_size 以提高效率。
    """

    def _process(item: dict, rows: List[list]):
        # 过滤掉 archived 状态的数据
        state = item.get("state") or ""
        if state.lower() == "archived":
            return

        campaign_id = item.get("campaign_id") or ""
        sku = item.get("sku") or ""
        asin = item.get("asin") or ""
        # 尝试提取 ad_id（兼容不同命名与嵌套）
        ad_id = item.get("ad_id") or item.get("adId") or (item.get("data") or {}).get("ad_id") or ""

        # 确保必要字段存在
        if not campaign_id or not sku or not asin:
            return

        # 现在包含 ad_id；位置：campaign_type, campaign_id, ad_id, sid, state, asin, sku
        rows.append([
            "sp",  # campaign_type
            campaign_id,
            ad_id,
            str(sid),  # sid
            state,
            asin,
            sku,
        ])

    # spProductAds 接口支持一次性拉取大量数据，使用更大的 page_size
    # 根据测试，该接口可以处理 length=100000 的请求
    # 这里使用 50000 作为 page_size，如果数据量更大，会自动分页
    effective_page_size = max(page_size, 50000)

    return await _fetch_with_pagination(
        op_api,
        access_token,
        SP_PRODUCT_ADS_ROUTE2,
        payload,
        effective_page_size,
        sem,
        retries,
        _process,
        seller_id=sid,
        seller_name=seller_name,
        tag="sp_product_ads",
    )


async def fetch_sp_keyword_reports(op_api: OpenApiBase, access_token: str, payload: dict, report_date: str,
                                   sid: int, seller_name: str, sem: asyncio.Semaphore, page_size: int,
                                   retries: int) -> Rows:
    """获取 SP 关键词报表，返回写库所需行列表。"""

    def _process(item: dict, rows: Rows):
        keyword_id = item.get("keyword_id") or ""
        keyword_text = item.get("keyword_text") or ""
        campaign_id = item.get("campaign_id")
        if not keyword_id or not campaign_id:
            return
        ad_group_id = item.get("ad_group_id") or item.get("adgroup_id") or ""
        rows.append([
            "sp",  # campaign_type
            keyword_id,
            keyword_text,
            str(ad_group_id),
            str(campaign_id),
            int(item.get("clicks") or 0),
            int(item.get("orders") or 0),
            item.get("report_date") or report_date,
        ])

    return await _fetch_with_pagination(
        op_api,
        access_token,
        SP_KEYWORD_REPORTS_ROUTE,
        payload,
        page_size,
        sem,
        retries,
        _process,
        seller_id=sid,
        seller_name=seller_name,
        tag="sp_keyword",
    )


async def fetch_sb_target_reports(op_api: OpenApiBase, access_token: str, payload: dict, report_date: str,
                                  sid: int, seller_name: str, sem: asyncio.Semaphore, page_size: int,
                                  retries: int) -> Rows:
    """获取 SB 定向报表（listHsaTargetingReport），返回写库所需行列表。"""

    def _process(item: dict, rows: Rows):
        campaign_id = item.get("campaign_id")
        ad_group_id = item.get("ad_group_id") or item.get("adgroup_id") or ""
        keyword_id = item.get("keyword_id")
        target_id = item.get("target_id")
        if not campaign_id or (not keyword_id and not target_id):
            return
        if keyword_id:
            target_type = "keyword"
            entity_id = keyword_id
        else:
            target_type = "producttarget"
            entity_id = target_id
        rows.append([
            str(ad_group_id),
            str(campaign_id),
            target_type,
            str(entity_id),
            int(item.get("clicks") or 0),
            int(item.get("orders") or 0),
            item.get("report_date") or report_date,
        ])

    return await _fetch_with_pagination(
        op_api,
        access_token,
        SB_TARGET_REPORT_ROUTE,
        payload,
        page_size,
        sem,
        retries,
        _process,
        seller_id=sid,
        seller_name=seller_name,
        tag="sb_target",
    )


async def fetch_query_word_reports(op_api: OpenApiBase, access_token: str, payload: dict, report_date: str,
                                   sid: int, seller_name: str, target_type: str,
                                   sem: asyncio.Semaphore, page_size: int, retries: int,
                                   country: Optional[str], route: str, campaign_type: str) -> Rows:
    """获取用户搜索词报表（SP/SB），返回写库所需行列表。"""

    def _process(item: dict, rows: Rows):
        query = item.get("query") or ""
        campaign_id = item.get("campaign_id")
        target_text = item.get("target_text") or ""
        if not query or not campaign_id or not target_text:
            return
        ad_group_id = item.get("ad_group_id") or item.get("adgroup_id") or ""
        rows.append([
            campaign_type,
            query,
            target_text,
            _is_asin_query(query),
            target_type,
            str(ad_group_id),
            str(campaign_id),
            int(item.get("clicks") or 0),
            int(item.get("orders") or 0),
            item.get("report_date") or report_date,
        ])

    return await _fetch_with_pagination(
        op_api,
        access_token,
        route,
        payload,
        page_size,
        sem,
        retries,
        _process,
        seller_id=sid,
        seller_name=seller_name,
        tag="queryword",
    )


async def fetch_seller_lists(op_api: OpenApiBase, access_token: str) -> List[dict]:
    """获取店铺列表（含 sid 等信息）"""
    resp = await op_api.request(access_token, "/erp/sc/data/seller/lists", "GET")
    # 返回列表，元素形如 {'sid': 123, ...}
    return resp.data if isinstance(resp.data, list) else []


async def _fetch_with_pagination(op_api: OpenApiBase, access_token: str, route: str, base_payload: dict,
                                 page_size: int, sem: asyncio.Semaphore, retries: int,
                                 process_item: Callable[[dict, List[list]], None], *,
                                 seller_id: Optional[int] = None, seller_name: str = "",
                                 tag: str = "", enable_prefetch: Optional[bool] = None,
                                 prefetch_pages: Optional[int] = None) -> List[list]:
    """分页获取数据，支持预取功能。

    Args:
        enable_prefetch: 是否启用分页预取（None 时从 op_api 读取）
        prefetch_pages: 预取页数（None 时从 op_api 读取）
    """
    # 从 op_api 读取配置（如果未指定）
    enable_prefetch = enable_prefetch if enable_prefetch is not None else op_api.enable_prefetch
    prefetch_pages = prefetch_pages if prefetch_pages is not None else op_api.prefetch_pages

    rows: List[list] = []
    offset = 0
    prefetch_tasks: Dict[int, asyncio.Task] = {}  # offset -> task

    async def _fetch_page(offset_val: int) -> Tuple[int, Optional[ResponseResult], Optional[Exception]]:
        """获取单页数据，返回 (offset, response, exception)"""
        page_payload = {**base_payload, "offset": offset_val, "length": page_size}
        for attempt in range(1, retries + 1):
            try:
                async with sem:
                    resp = await op_api.request(access_token, route, "POST", req_body=page_payload, use_cache=False)
            except Exception as exc:
                if attempt == retries:
                    return offset_val, None, exc
                delay = min(2 ** attempt, 30)
                await asyncio.sleep(delay)
                continue

            if resp.code in (3001008,):  # 频控
                if attempt == retries:
                    return offset_val, None, ValueError(f"频控限制")
                delay = min(2 ** attempt * 2, 60)
                await asyncio.sleep(delay)
                continue

            if resp.code not in (0, 200):
                if attempt == retries:
                    return offset_val, None, ValueError(f"code={resp.code} msg={resp.message}")
                delay = min(2 ** attempt, 15)
                await asyncio.sleep(delay)
                continue

            return offset_val, resp, None

        return offset_val, None, ValueError("重试次数用尽")

    while True:
        # 如果启用预取，提前发起后续页的请求
        if enable_prefetch:
            for prefetch_offset in range(offset + page_size, offset + page_size * (prefetch_pages + 1), page_size):
                if prefetch_offset not in prefetch_tasks:
                    prefetch_tasks[prefetch_offset] = asyncio.create_task(_fetch_page(prefetch_offset))

        # 获取当前页数据（如果已预取则直接使用，否则发起请求）
        if offset in prefetch_tasks:
            task = prefetch_tasks.pop(offset)
            offset_val, resp, exc = await task
        else:
            offset_val, resp, exc = await _fetch_page(offset)

        if exc is not None:
            print(f"[error] route {route} sid={seller_id} name={seller_name} off={offset} exception={exc}")
            # 取消所有预取任务
            for task in prefetch_tasks.values():
                task.cancel()
            return rows

        if resp is None:
            # 取消所有预取任务
            for task in prefetch_tasks.values():
                task.cancel()
            return rows

        data_list = resp.data
        if data_list is None:
            # 取消所有预取任务
            for task in prefetch_tasks.values():
                task.cancel()
            return rows
        if isinstance(data_list, dict):
            data_list = [data_list]
        if not isinstance(data_list, list):
            # 取消所有预取任务
            for task in prefetch_tasks.values():
                task.cancel()
            return rows

        for item in data_list:
            process_item(item, rows)

        current_page_size = len(data_list)
        total_fetched = len(rows)

        # 减少调试日志输出，只在最后一页或每10页打印一次
        has_identifier = seller_id is not None or (seller_name and seller_name != "")
        if has_identifier and (current_page_size < page_size or offset % (page_size * 10) == 0):
            identifier = f"sid={seller_id}" if seller_id else f"name={seller_name}"
            print(f"[debug] {tag} {identifier} offset={offset} page_size={current_page_size} total_fetched={total_fetched}")

        # 判断是否还有下一页
        if current_page_size < page_size:
            # 当前页数据量不足，说明是最后一页
            # 取消所有预取任务
            for task in prefetch_tasks.values():
                task.cancel()
            if has_identifier:
                identifier = f"sid={seller_id}" if seller_id else f"name={seller_name}"
            print(f"[info] {tag} {identifier} 最后一页，共获取 {total_fetched} 条数据")
            return rows

        # 检查是否有 total 字段可用（用于验证）
        if hasattr(resp, 'total') and resp.total is not None:
            if total_fetched >= resp.total:
                # 取消所有预取任务
                for task in prefetch_tasks.values():
                    task.cancel()
                if has_identifier:
                    identifier = f"sid={seller_id}" if seller_id else f"name={seller_name}"
                    print(f"[info] {tag} {identifier} 已获取全部数据（total={resp.total}），共 {total_fetched} 条")
                return rows

        # 继续请求下一页
        offset += page_size


def filter_active_sellers(sellers: List[dict]) -> List[dict]:
    """筛选 status == 1 且国家在白名单内的店铺，仅保留 sid/name/country。"""
    allowed_countries = {"美国", "加拿大", "英国", "德国", "法国", "意大利", "西班牙", "日本"}
    return [
        {"sid": s.get("sid"), "name": s.get("name"), "country": s.get("country")}
        for s in sellers
        if s.get("status") == 1 and s.get("country") in allowed_countries
    ]


async def get_campaign_data_for_seller(op_api: OpenApiBase, access_token: str,
                                       seller: dict, report_date: str,
                                       sem: asyncio.Semaphore, page_size: int, retries: int) -> List[list]:
    """抓取单个店铺的 campaign 报表（sp/sb/sd）。"""
    sid = seller.get("sid")
    seller_name = seller.get("name", "")
    seller_country = seller.get("country")
    if not sid:
        return []

    base_payload = {"sid": sid, "report_date": report_date}

    tasks = [
        fetch_campaign_reports(op_api, access_token, route, base_payload, tag, sid, seller_name, sem, page_size, retries, seller_country)
        for route, tag in CAMPAIGN_REPORT_ROUTES.items()
    ]
    results = await asyncio.gather(*tasks)
    return [row for group in results for row in group]


async def get_product_data_for_seller(op_api: OpenApiBase, access_token: str,
                                      seller: dict, report_date: str,
                                      sem: asyncio.Semaphore, page_size: int, retries: int) -> List[list]:
    """抓取单个店铺的商品级报表（当前仅 sp）。"""
    sid = seller.get("sid")
    seller_name = seller.get("name", "")
    seller_country = seller.get("country")
    if not sid:
        return []

    # 请求参数与 spCampaignReports 保持一致
    base_payload = {"sid": sid, "report_date": report_date}

    return await fetch_product_ads(
        op_api,
        access_token,
        base_payload,
        report_date,
        sid,
        seller_name,
        sem,
        page_size,
        retries,
        seller_country,
    )


async def get_sp_product_ads_for_seller(op_api: OpenApiBase, access_token: str,
                                         seller: dict, sem: asyncio.Semaphore,
                                         page_size: int, retries: int) -> List[list]:
    """抓取单个店铺的 SP 商品广告数据。"""
    sid = seller.get("sid")
    seller_name = seller.get("name", "")
    if not sid:
        return []

    base_payload = {"sid": sid}

    return await fetch_sp_product_ads(
        op_api,
        access_token,
        base_payload,
        sid,
        seller_name,
        sem,
        page_size,
        retries,
    )


async def get_sp_keyword_data_for_seller(op_api: OpenApiBase, access_token: str,
                                         seller: dict, report_date: str,
                                         sem: asyncio.Semaphore, page_size: int, retries: int) -> Rows:
    """抓取单个店铺的 SP 关键词报表，返回写库元组。"""

    sid = seller.get("sid")
    seller_name = seller.get("name", "")
    if not sid:
        return []

    base_payload = {"sid": sid, "report_date": report_date}

    return await fetch_sp_keyword_reports(
        op_api,
        access_token,
        base_payload,
        report_date,
        sid,
        seller_name,
        sem,
        page_size,
        retries,
    )


async def get_sb_target_data_for_seller(op_api: OpenApiBase, access_token: str,
                                        seller: dict, report_date: str,
                                        sem: asyncio.Semaphore, page_size: int, retries: int) -> Rows:
    """抓取单个店铺的 SB 定向报表，返回写库元组。"""

    sid = seller.get("sid")
    seller_name = seller.get("name", "")
    if not sid:
        return []

    # 按需求使用 sponsored_type = ALL, target_type = keyword
    base_payload = {
        "sid": sid,
        "report_date": report_date,
        "sponsored_type": "ALL",
        "target_type": "ALL",
    }

    return await fetch_sb_target_reports(
        op_api,
        access_token,
        base_payload,
        report_date,
        sid,
        seller_name,
        sem,
        page_size,
        retries,
    )


async def get_query_word_data_for_seller(op_api: OpenApiBase, access_token: str,
                                         seller: dict, report_date: str, target_type: str,
                                         sem: asyncio.Semaphore, page_size: int, retries: int,
                                         route: str, campaign_type: str) -> Rows:
    """抓取单个店铺的搜索词报表（SP/SB），返回写库元组。"""

    sid = seller.get("sid")
    seller_name = seller.get("name", "")
    seller_country = seller.get("country")
    if not sid:
        return []

    base_payload = {"sid": sid, "report_date": report_date, "target_type": target_type}

    return await fetch_query_word_reports(
        op_api,
        access_token,
        base_payload,
        report_date,
        sid,
        seller_name,
        target_type,
        sem,
        page_size,
        retries,
        seller_country,
        route,
        campaign_type,
    )


async def fetch_campaign_names(op_api: OpenApiBase, access_token: str, seller: dict,
                               sem: asyncio.Semaphore, page_size: int, retries: int) -> List[list]:
    """查询广告名称，返回 [sid, seller_name, tag, campaign_id, name, state, targeting_type] 列表"""
    sid = seller.get("sid")
    seller_name = seller.get("name", "")
    if not sid:
        return []

    base_payload = {"sid": sid}

    async def _fetch(route: str, tag: str) -> List[list]:
        def _process(item: dict, rows: List[list]):
            # 过滤掉 archived 状态
            if (item.get("state") or "").lower() == "archived":
                return
            rows.append([
                sid,
                seller_name,
                tag,
                item.get("campaign_id"),
                item.get("name"),
                item.get("state"),
                item.get("targeting_type"),
            ])

        return await _fetch_with_pagination(
            op_api,
            access_token,
            route,
            base_payload,
            page_size,
            sem,
            retries,
            _process,
            seller_id=sid,
            seller_name=seller_name,
            tag=tag,
        )

    tasks = [_fetch(route, tag) for route, tag in CAMPAIGN_NAME_ROUTES.items()]
    results = await asyncio.gather(*tasks)
    return [row for group in results for row in group]


async def fetch_ad_groups(op_api: OpenApiBase, access_token: str, seller: dict,
                          sem: asyncio.Semaphore, page_size: int, retries: int) -> List[list]:
    """查询广告组名称，返回 [sid, seller_name, tag, ad_group_id, name] 列表"""
    sid = seller.get("sid")
    seller_name = seller.get("name", "")
    if not sid:
        return []

    base_payload = {"sid": sid, "state": "enabled"}

    async def _fetch(route: str, tag: str) -> List[list]:
        def _process(item: dict, rows: List[list]):
            # 兼容不同接口返回的 campaign_id 字段位置（直接字段或嵌套在 data 中）
            campaign_id = (
                item.get("campaign_id")
                or item.get("campaignId")
                or (item.get("data") or {}).get("campaign_id")
                or (item.get("data") or {}).get("campaignId")
                or None
            )
            rows.append([
                sid,
                seller_name,
                tag,
                item.get("ad_group_id"),
                item.get("name"),
                campaign_id,
            ])

        return await _fetch_with_pagination(
            op_api,
            access_token,
            route,
            base_payload,
            page_size,
            sem,
            retries,
            _process,
            seller_id=sid,
            seller_name=seller_name,
            tag=tag,
        )

    tasks = [_fetch(route, tag) for route, tag in AD_GROUP_ROUTES.items()]
    results = await asyncio.gather(*tasks)
    return [row for group in results for row in group]


async def fetch_sb_creativity(op_api: OpenApiBase, access_token: str, seller: dict,
                              sem: asyncio.Semaphore, page_size: int, retries: int) -> List[list]:
    """查询 SB 创意（/pb/openapi/newad/hsaProductAds），返回 [sid, campaign_id, asin] 列表，仅 state=enabled。"""
    sid = seller.get("sid")
    if not sid:
        return []

    base_payload = {"sid": sid, "state": "enabled"}

    def _process(item: dict, rows: List[list]):
        if (item.get("state") or "").lower() != "enabled":
            return
        campaign_id = item.get("campaign_id") or (item.get("data") or {}).get("campaign_id")
        ad_group_id = item.get("ad_group_id")
        if ad_group_id is None:
            ad_group_id = (item.get("data") or {}).get("ad_group_id")
        # ad_creative_id 可能在顶层或嵌套在 data 中
        ad_creative_id = item.get("ad_creative_id")
        if ad_creative_id is None:
            ad_creative_id = (item.get("data") or {}).get("ad_creative_id")
        if ad_creative_id is None:
            ad_creative_id = item.get("adCreativeId")
        if ad_creative_id is None or ad_creative_id == "":
            # 无 ad_creative_id 跳过（表定义要求非空并为主键一部分）
            return
        if ad_group_id is None or ad_group_id == "":
            # 无 ad_group_id 跳过（表定义要求非空并为主键一部分）
            return
        asin_field = item.get("asin")
        # 如果 asin 是列表，遍历每个 asin 并为每个 asin 生成一行
        if isinstance(asin_field, list):
            for a in asin_field:
                if a is None or (isinstance(a, str) and not a):
                    continue
                rows.append([
                    sid,
                    campaign_id,
                    str(ad_group_id),
                    str(ad_creative_id) if ad_creative_id is not None else None,
                    str(a),
                ])
        # 如果 asin 是字符串，直接使用
        elif isinstance(asin_field, str) and asin_field:
            rows.append([
                sid,
                campaign_id,
                str(ad_group_id),
                str(ad_creative_id) if ad_creative_id is not None else None,
                asin_field,
            ])
        # 否则不添加行（避免插入空 asin）

    return await _fetch_with_pagination(
        op_api,
        access_token,
        "/pb/openapi/newad/hsaProductAds",
        base_payload,
        page_size,
        sem,
        retries,
        _process,
        seller_id=sid,
        seller_name=seller.get("name", ""),
        tag="sb_creativity",
    )


async def fetch_sb_targeting_keywords(op_api: OpenApiBase, access_token: str, seller: dict,
                                      sem: asyncio.Semaphore, page_size: int, retries: int) -> List[list]:
    """查询 SB 定向关键词（/pb/openapi/newad/sbTargeting），返回 [sid, campaign_id, keyword_id, keyword_text, keyword_state]。

    请求参数示例：
      {"sid": 109, "ads_type": "ALL", "targeting_type": "keyword", "offset": 0, "length": 10}
    """
    sid = seller.get("sid")
    if not sid:
        return []

    base_payload = {"sid": sid, "ads_type": "ALL", "targeting_type": "keyword"}

    def _process(item: dict, rows: List[list]):
        campaign_id = item.get("campaign_id")
        keyword_id = item.get("keyword_id")
        if not campaign_id or not keyword_id:
            return
        rows.append([
            str(sid),
            str(campaign_id),
            str(keyword_id),
            item.get("keyword_text"),
            item.get("keyword_state"),
        ])

    return await _fetch_with_pagination(
        op_api,
        access_token,
        SB_TARGETING_ROUTE,
        base_payload,
        page_size,
        sem,
        retries,
        _process,
        seller_id=sid,
        seller_name=seller.get("name", ""),
        tag="sb_targeting",
    )


async def fetch_sp_target_hour_data(op_api: OpenApiBase, access_token: str, campaign_id: str, report_date: str,
                                    sem: asyncio.Semaphore, page_size: int, retries: int) -> List[dict]:
    """获取 SP Target 小时报表（spTargetHourData），返回原始行列表（用于后续按天汇总）。"""

    base_payload = {
        "campaign_id": campaign_id,
        "report_date": report_date,
        "agg_dimension": "both_ad_target",
    }

    def _process(item: dict, rows: List[dict]):
        rows.append({
            "campaign_id": item.get("campaign_id"),
            "report_date": item.get("report_date") or report_date,
            "clicks": item.get("clicks"),
            "orders": item.get("orders"),
            "group_id": item.get("group_id"),
            "targeting_id": item.get("targeting_id"),
            "targeting": item.get("targeting"),
        })

    # 使用 campaign_id 作为标识符，以便输出日志
    # 尝试将 campaign_id 转换为整数，如果失败则使用 None（但 seller_name 仍会显示）
    try:
        seller_id_for_log = int(campaign_id) if campaign_id else None
    except (ValueError, TypeError):
        seller_id_for_log = None

    return await _fetch_with_pagination(
        op_api,
        access_token,
        SP_TARGET_HOUR_ROUTE,
        base_payload,
        page_size,
        sem,
        retries,
        _process,
        seller_id=seller_id_for_log,
        seller_name=f"campaign_{campaign_id}",
        tag="sp_target_hour",
    )


async def fetch_enabled_campaign_ids(db_config: Dict[str, Any], target_sellers: Optional[List[dict]] = None) -> List[str]:
    """从 dim_amazon_campaign 获取 enabled 的 campaign_id 列表，可选按 sid 过滤。"""
    pool = await _prepare_db_pool(db_config, "campaign_id")
    if not pool:
        return []

    sids = [s.get("sid") for s in (target_sellers or []) if s.get("sid")]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if sids:
                placeholders = ",".join(["%s"] * len(sids))
                sql = (
                    "SELECT DISTINCT campaign_id FROM dim_amazon_campaign "
                    f"WHERE state='enabled' AND sid IN ({placeholders})"
                )
                await cur.execute(sql, sids)
            else:
                sql = "SELECT DISTINCT campaign_id FROM dim_amazon_campaign WHERE state='enabled'"
                await cur.execute(sql)
            rows = await cur.fetchall()
            return [str(r[0]) for r in rows if r and r[0] is not None]


async def _save_rows_with_batch(insert_prefix: str, update_clause: str, column_count: int,
                                rows: Rows, db_config: Dict[str, Any], label: str,
                                batch_size: int = 10000):
    """通用批量写库，带 UPSERT；label 用于日志。"""
    if not rows:
        print(f"[info] 无{label}数据可写入数据库，已跳过")
        return
    pool = await _prepare_db_pool(db_config, label)
    if not pool:
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            affected = 0
            try:
                affected = await _execute_multi_values(
                    cur,
                    rows,
                    insert_prefix,
                    update_clause,
                    column_count,
                    batch_size,
                )
                await conn.commit()
                print(f"[info] {label}写入 MySQL 完成，影响行数: {affected}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] {label}写入 MySQL 失败: {exc}")


async def save_campaign_reports_to_db(rows: Rows, db_config: Dict[str, Any], delete_dates: Iterable[str],
                                      batch_size: int = 10000):
    """先按指定日期集合清理旧数据，再批量写入广告报表。"""

    if not rows:
        print("[info] 无广告报表数据可写入数据库，已跳过")
        return

    pool = await _prepare_db_pool(db_config, "广告报表")
    if not pool:
        return

    # 使用别名避免 MySQL 8.0 对 VALUES() 的弃用警告
    # 使用多值 INSERT 以减少网络往返
    insert_prefix = (
        "INSERT INTO amazon_campaign_reports (campaign_type, sid, name, country, campaign_id, "
        "impressions, clicks, cost, sales, orders, units, createtime) VALUES "
    )
    update_clause = (
        " AS new_data ON DUPLICATE KEY UPDATE "
        "impressions=new_data.impressions, clicks=new_data.clicks, cost=new_data.cost, "
        "sales=new_data.sales, orders=new_data.orders, units=new_data.units, "
        "sid=new_data.sid, name=new_data.name, country=new_data.country"
    )

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await conn.begin()
                # 删除指定日期的旧数据，确保当天全量刷新
                date_list = list({d for d in delete_dates if d})
                if date_list:
                    placeholders = ",".join(["%s"] * len(date_list))
                    delete_sql = f"DELETE FROM amazon_campaign_reports WHERE createtime IN ({placeholders})"
                    delete_start = time.perf_counter()
                    await cur.execute(delete_sql, date_list)
                    _timing_log(f"campaign_reports delete({len(date_list)}d)", delete_start)

                affected = 0
                insert_start = time.perf_counter()
                for chunk in _chunked(rows, batch_size):
                    valid_chunk = [r for r in chunk if len(r) >= 12]
                    if not valid_chunk:
                        continue
                    values_placeholder = ", ".join(["(" + ",".join(["%s"] * 12) + ")"] * len(valid_chunk))
                    sql = insert_prefix + values_placeholder + update_clause
                    flat_values: List[Any] = []
                    for r in valid_chunk:
                        flat_values.extend(r[:12])
                    await cur.execute(sql, flat_values)
                    affected += cur.rowcount
                _timing_log(f"campaign_reports insert({len(rows)}r)", insert_start)
                commit_start = time.perf_counter()
                await conn.commit()
                _timing_log("campaign_reports commit", commit_start)
                print(f"[info] 广告报表刷新完成，清空日期 {date_list} 后插入行数: {affected}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] 广告报表写入失败: {exc}")


async def save_product_reports_to_db(rows: Rows, db_config: Dict[str, Any]):
    """将商品级广告报表写入 dim_amazon_product（包含 ad_id，主键为 campaign_id+ad_id+sku）。"""
    insert_prefix = (
        "INSERT INTO dim_amazon_product (campaign_type, campaign_id, ad_id, sid, state, asin, sku, createtime) VALUES "
    )
    update_clause = (
        " AS new_data ON DUPLICATE KEY UPDATE asin=new_data.asin, sku=new_data.sku, createtime=new_data.createtime, "
        "sid=new_data.sid, state=new_data.state"
    )
    await _save_rows_with_batch(insert_prefix, update_clause, 8, rows, db_config, "商品报表")


async def save_queryword_reports_to_db(rows: Rows, db_config: Dict[str, Any], delete_dates: Iterable[str],
                                       batch_size: int = 10000):
    """刷新 amazon_queryword_reports：先删指定日期，再 upsert 写入。"""

    if not rows:
        print("[info] 无搜索词报表数据可写入数据库，已跳过")
        return

    pool = await _prepare_db_pool(db_config, "搜索词报表")
    if not pool:
        return

    insert_prefix = (
        "INSERT INTO amazon_queryword_reports (campaign_type, query, target_text, is_asin, target_type, ad_group_id, "
        "campaign_id, clicks, orders, createtime) VALUES "
    )
    update_clause = (
        " AS new_data ON DUPLICATE KEY UPDATE "
        "campaign_type=new_data.campaign_type, is_asin=new_data.is_asin, target_type=new_data.target_type, "
        "ad_group_id=new_data.ad_group_id, clicks=new_data.clicks, orders=new_data.orders"
    )

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                date_list = list({d for d in delete_dates if d})
                if date_list:
                    placeholders = ",".join(["%s"] * len(date_list))
                    delete_sql = f"DELETE FROM amazon_queryword_reports WHERE createtime IN ({placeholders})"
                    await cur.execute(delete_sql, date_list)

                affected = await _execute_multi_values(
                    cur,
                    rows,
                    insert_prefix,
                    update_clause,
                    10,
                    batch_size,
                )
                await conn.commit()
                print(f"[info] 搜索词报表刷新完成，清空日期 {date_list} 后插入行数: {affected}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] 搜索词报表写入失败: {exc}")


async def save_sb_target_reports_to_db(rows: Rows, db_config: Dict[str, Any], delete_dates: Iterable[str],
                                       batch_size: int = 10000):
    """刷新 amazon_sb_target_reports：先删指定日期，再 upsert 写入。"""

    if not rows:
        print("[info] 无 SB 定向报表数据可写入数据库，已跳过")
        return

    pool = await _prepare_db_pool(db_config, "SB 定向报表")
    if not pool:
        return

    insert_prefix = (
        "INSERT INTO amazon_sb_target_reports (ad_group_id, campaign_id, target_type, id, "
        "clicks, orders, createtime) VALUES "
    )
    update_clause = (
        " AS new_data ON DUPLICATE KEY UPDATE "
        "ad_group_id=new_data.ad_group_id, target_type=new_data.target_type, "
        "clicks=new_data.clicks, orders=new_data.orders"
    )

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                date_list = list({d for d in delete_dates if d})
                if date_list:
                    placeholders = ",".join(["%s"] * len(date_list))
                    delete_sql = f"DELETE FROM amazon_sb_target_reports WHERE createtime IN ({placeholders})"
                    await cur.execute(delete_sql, date_list)

                affected = await _execute_multi_values(
                    cur,
                    rows,
                    insert_prefix,
                    update_clause,
                    7,
                    batch_size,
                )
                await conn.commit()
                print(f"[info] SB 定向报表刷新完成，清空日期 {date_list} 后插入行数: {affected}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] SB 定向报表写入失败: {exc}")


async def save_sp_keyword_reports_to_db(rows: Rows, db_config: Dict[str, Any], delete_dates: Iterable[str],
                                        batch_size: int = 10000):
    """刷新 amazon_sp_keyword_reports：先删指定日期，再 upsert 写入。"""

    if not rows:
        print("[info] 无 SP 关键词报表数据可写入数据库，已跳过")
        return

    pool = await _prepare_db_pool(db_config, "SP 关键词报表")
    if not pool:
        return

    insert_prefix = (
        "INSERT INTO amazon_sp_keyword_reports (keyword_id, keyword_text, ad_group_id, "
        "campaign_id, clicks, orders, createtime) VALUES "
    )
    update_clause = (
        " AS new_data ON DUPLICATE KEY UPDATE "
        "keyword_text=new_data.keyword_text, ad_group_id=new_data.ad_group_id, "
        "clicks=new_data.clicks, orders=new_data.orders"
    )

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                date_list = list({d for d in delete_dates if d})
                if date_list:
                    placeholders = ",".join(["%s"] * len(date_list))
                    delete_sql = f"DELETE FROM amazon_sp_keyword_reports WHERE createtime IN ({placeholders})"
                    await cur.execute(delete_sql, date_list)

                # rows 结构: [campaign_type, keyword_id, keyword_text, ad_group_id,
                #            campaign_id, clicks, orders, report_date]
                values = [
                    (
                        r[1],  # keyword_id
                        r[2],  # keyword_text
                        r[3],  # ad_group_id
                        r[4],  # campaign_id
                        r[5],  # clicks
                        r[6],  # orders
                        r[7],  # createtime
                    )
                    for r in rows
                    if len(r) >= 8
                ]
                affected = await _execute_multi_values(
                    cur,
                    values,
                    insert_prefix,
                    update_clause,
                    7,
                    batch_size,
                )
                await conn.commit()
                print(f"[info] SP 关键词报表刷新完成，清空日期 {date_list} 后插入行数: {affected}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] SP 关键词报表写入失败: {exc}")


async def save_sp_target_reports_to_db(rows: Rows, db_config: Dict[str, Any], delete_dates: Iterable[str],
                                       batch_size: int = 10000):
    """刷新 amazon_sp_target_reports：先删指定日期，再 upsert 写入。"""

    if not rows:
        print("[info] 无 SP 定向报表数据可写入数据库，已跳过")
        return

    pool = await _prepare_db_pool(db_config, "SP 定向报表")
    if not pool:
        return

    insert_prefix = (
        "INSERT INTO amazon_sp_target_reports (ad_group_id, campaign_id, targeting_id, targeting, "
        "clicks, orders, createtime) VALUES "
    )
    update_clause = (
        " AS new_data ON DUPLICATE KEY UPDATE "
        "ad_group_id=new_data.ad_group_id, targeting=new_data.targeting, "
        "clicks=new_data.clicks, orders=new_data.orders"
    )

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                date_list = list({d for d in delete_dates if d})
                if date_list:
                    placeholders = ",".join(["%s"] * len(date_list))
                    delete_sql = f"DELETE FROM amazon_sp_target_reports WHERE createtime IN ({placeholders})"
                    await cur.execute(delete_sql, date_list)

                affected = await _execute_multi_values(
                    cur,
                    rows,
                    insert_prefix,
                    update_clause,
                    7,
                    batch_size,
                )
                await conn.commit()
                print(f"[info] SP 定向报表刷新完成，清空日期 {date_list} 后插入行数: {affected}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] SP 定向报表写入失败: {exc}")


async def save_campaign_names_to_db(rows: Rows, db_config: Dict[str, Any], batch_size: int = 10000):
    """全量刷新 dim_amazon_campaign：先清空表，再批量插入最新名称。"""

    pool = await _prepare_db_pool(db_config, "广告名称")
    if not pool:
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("TRUNCATE TABLE dim_amazon_campaign")
                inserted = 0
                if rows:
                    insert_prefix = (
                        "INSERT INTO dim_amazon_campaign (campaign_type, sid, campaign_id, name, state, targeting_type, createtime) VALUES "
                    )
                    inserted = await _execute_multi_values(
                        cur,
                        rows,
                        insert_prefix,
                        "",
                        7,
                        batch_size,
                    )
                await conn.commit()
                print(f"[info] 广告名称全量刷新完成，清空后插入行数: {inserted}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] 广告名称全量刷新失败: {exc}")
    # 连接池统一在主流程结束时关闭


async def save_ad_groups_to_db(rows: Rows, db_config: Dict[str, Any], batch_size: int = 10000):
    """全量刷新 dim_amazon_campaign_groups：先清空表，再批量插入最新广告组。"""

    pool = await _prepare_db_pool(db_config, "广告组")
    if not pool:
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("TRUNCATE TABLE dim_amazon_campaign_groups")
                inserted = 0
                if rows:
                    insert_prefix = (
                        "INSERT INTO dim_amazon_campaign_groups (campaign_type, sid, ad_group_id, name, campaign_id, createtime) VALUES "
                    )
                    inserted = await _execute_multi_values(
                        cur,
                        rows,
                        insert_prefix,
                        "",
                        6,
                        batch_size,
                    )
                await conn.commit()
                print(f"[info] 广告组全量刷新完成，清空后插入行数: {inserted}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] 广告组全量刷新失败: {exc}")

    # 连接池统一在主流程结束时关闭


async def save_sb_creativity_to_db(rows: Rows, db_config: Dict[str, Any], batch_size: int = 10000):
    """刷新 dim_amazon_sb_creativity：全量删除后按主键 campaign_id upsert 写入。"""

    pool = await _prepare_db_pool(db_config, "SB 创意")
    if not pool:
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("TRUNCATE TABLE dim_amazon_sb_creativity")
                inserted = 0
                if rows:
                    insert_prefix = (
                        "INSERT INTO dim_amazon_sb_creativity (sid, campaign_id, ad_group_id, ad_creative_id, asin, createtime) VALUES "
                    )
                    inserted = await _execute_multi_values(
                        cur,
                        rows,
                        insert_prefix,
                        "",
                        6,
                        batch_size,
                    )
                await conn.commit()
                print(f"[info] SB 创意全量刷新完成，清空后插入行数: {inserted}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] SB 创意刷新失败: {exc}")


async def save_sb_targeting_dim_to_db(rows: Rows, db_config: Dict[str, Any], batch_size: int = 10000):
    """全量刷新 dim_amazon_sb_target：SB 定向关键词（campaign_id+keyword_id 主键）。"""

    pool = await _prepare_db_pool(db_config, "SB 定向关键词")
    if not pool:
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("TRUNCATE TABLE dim_amazon_sb_target")
                inserted = 0
                if rows:
                    insert_prefix = (
                        "INSERT INTO dim_amazon_sb_target (sid, campaign_id, keyword_id, keyword_text, keyword_state, createtime) VALUES "
                    )
                    inserted = await _execute_multi_values(
                        cur,
                        rows,
                        insert_prefix,
                        "",
                        6,
                        batch_size,
                    )
                await conn.commit()
                print(f"[info] SB 定向关键词全量刷新完成，清空后插入行数: {inserted}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] SB 定向关键词刷新失败: {exc}")


async def save_sp_product_ads_to_db(rows: Rows, db_config: Dict[str, Any], batch_size: int = 10000):
    """全量刷新 dim_amazon_product：先清空表，再批量插入最新数据。"""

    pool = await _prepare_db_pool(db_config, "SP 商品广告")
    if not pool:
        return

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("TRUNCATE TABLE dim_amazon_product")
                inserted = 0
                if rows:
                    insert_prefix = (
                        "INSERT INTO dim_amazon_product (campaign_type, campaign_id, ad_id, sid, state, asin, sku, createtime) VALUES "
                    )
                    inserted = await _execute_multi_values(
                        cur,
                        rows,
                        insert_prefix,
                        "",
                        8,
                        batch_size,
                    )
                await conn.commit()
                print(f"[info] SP 商品广告全量刷新完成，清空后插入行数: {inserted}")
            except Exception as exc:  # pragma: no cover
                await conn.rollback()
                print(f"[error] SP 商品广告刷新失败: {exc}")


async def _run_reports(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                       date_list: List[str], sem: asyncio.Semaphore, page_size: int,
                       db_config: Dict[str, Any], retries: int, retry_on_empty: bool,
                       slow_retry: bool, slow_sem_size: int, slow_retries: int, slow_delay: float,
                       fetch_campaign: bool = True, fetch_product: bool = True,
                       date_concurrency: int = 1) -> List[str]:
    """拉取并写入 campaign + product 报表，返回失败日期列表。可独立控制两类报表。支持日期层面的有限并行。"""
    total_campaign_rows = 0
    total_product_rows = 0
    failed_dates: List[str] = []

    if not fetch_campaign and not fetch_product:
        print("[info] fetch_campaign 和 fetch_product 都为 False，已跳过报表拉取。")
        return failed_dates
    date_concurrency = max(1, date_concurrency)

    async def _process_single_date(report_date: str) -> Tuple[int, int, Optional[str]]:
        total_start = time.perf_counter()
        async def collect(current_sem: asyncio.Semaphore, retry_times: int) -> Tuple[List[list], List[list]]:
            tasks = []
            if fetch_campaign:
                tasks.append(asyncio.gather(*[
                    get_campaign_data_for_seller(op_api, access_token, s, report_date, current_sem, page_size, retry_times)
                    for s in target_sellers
                ]))
            if fetch_product:
                tasks.append(asyncio.gather(*[
                    get_product_data_for_seller(op_api, access_token, s, report_date, current_sem, page_size, retry_times)
                    for s in target_sellers
                ]))

            results = await asyncio.gather(*tasks) if tasks else []
            idx = 0
            campaign_rows = [row for group in results[idx] for row in group] if fetch_campaign else []
            if fetch_campaign:
                idx += 1
            product_rows = [row for group in results[idx] for row in group] if fetch_product else []
            return campaign_rows, product_rows

        collect_start = time.perf_counter()
        day_campaign_rows, day_product_rows = await collect(sem, retries)
        _timing_log(f"{report_date} collect(main)", collect_start)

        def _has_data() -> bool:
            has_campaign = fetch_campaign and bool(day_campaign_rows)
            has_product = fetch_product and bool(day_product_rows)
            return has_campaign or has_product

        if not _has_data() and retry_on_empty:
            print(f"[warn] {report_date} 首次抓取 0 行（按当前开关），准备重试一次...")
            await asyncio.sleep(1.0)
            retry_start = time.perf_counter()
            day_campaign_rows, day_product_rows = await collect(sem, retries)
            _timing_log(f"{report_date} collect(retry)", retry_start)

        msg_parts = []
        if fetch_campaign:
            msg_parts.append(f"campaign rows: {len(day_campaign_rows)}")
        if fetch_product:
            msg_parts.append(f"product rows: {len(day_product_rows)}")
        print("\n" + report_date + (" " + "; ".join(msg_parts) if msg_parts else ""))

        if not _has_data():
            if slow_retry:
                print(f"[warn] {report_date} 重试后仍 0 行，降并发再次尝试 (concurrency={slow_sem_size}, retries={slow_retries}) ...")
                await asyncio.sleep(slow_delay)
                slow_sem = asyncio.Semaphore(slow_sem_size)
                slow_start = time.perf_counter()
                day_campaign_rows, day_product_rows = await collect(slow_sem, slow_retries)
                _timing_log(f"{report_date} collect(slow)", slow_start)
                retry_parts = []
                if fetch_campaign:
                    retry_parts.append(f"campaign {len(day_campaign_rows)}")
                if fetch_product:
                    retry_parts.append(f"product {len(day_product_rows)}")
                print(f"[info] {report_date} 慢速重试结果: {', '.join(retry_parts) if retry_parts else '无任务'}")

        if not _has_data():
            print(f"[warn] {report_date} 仍然 0 行，已跳过写库")
            return len(day_campaign_rows), len(day_product_rows), report_date

        # 数据库写入并行化：campaign 和 product 写入不同表，可以并行执行
        write_tasks = []
        if day_campaign_rows:
            write_tasks.append(save_campaign_reports_to_db([
                (
                    r[2],  # campaign_type
                    r[0],  # sid
                    r[1],  # name
                    r[3],  # country
                    r[4],  # campaign_id
                    r[5],  # impressions
                    r[6],  # clicks
                    r[7],  # cost
                    r[8],  # sales
                    r[9],  # orders
                    r[10],  # units
                    r[11],  # createtime
                )
                for r in day_campaign_rows
                if len(r) >= 12
            ], db_config, [report_date]))

        if day_product_rows:
            # 在写库前在 Python 端按 (campaign_id, sku, createtime) 去重，避免批量插入时主键冲突
            prod_seen = set()
            prod_unique: List[tuple] = []
            prod_duplicates = 0
            prod_duplicate_samples: List[tuple] = []
            for r in day_product_rows:
                # day_product_rows layout (from fetch_product_ads):
                # [sid, seller_name, campaign_type, country, campaign_id, ad_id, asin, sku, impressions, clicks, cost, sales, orders, units, report_date]
                if len(r) < 15:
                    continue
                campaign_raw = r[4]
                ad_id_val = r[5]
                asin_val = r[6]
                sku_raw = r[7]
                createtime_val = r[14]
                campaign_type_val = r[2] if len(r) > 2 else None
                sid_val = r[0]
                # 归一化：campaign 去两端空白，sku 去空白并小写以避免大小写/空格导致的重复
                campaign_norm = str(campaign_raw).strip()
                ad_id_norm = str(ad_id_val).strip()
                sku_norm = str(sku_raw).strip().lower()
                key = (campaign_norm, ad_id_norm, sku_norm)
                if key in prod_seen:
                    prod_duplicates += 1
                    if len(prod_duplicate_samples) < 10:
                        prod_duplicate_samples.append((campaign_raw, ad_id_val, sku_raw, createtime_val))
                    continue
                prod_seen.add(key)
                # Append in order matching save_product_reports_to_db insert_sql:
                # (campaign_type, campaign_id, ad_id, sid, state, asin, sku, createtime)
                prod_unique.append((campaign_type_val, campaign_raw, ad_id_val, sid_val, None, asin_val, sku_raw, createtime_val))

            if prod_duplicates:
                print(f"[info] 产品表去重：原始 {len(day_product_rows)} 行 -> 去重后 {len(prod_unique)} 行，去重掉 {prod_duplicates} 行")
                print(f"[debug] 产品去重示例（最多10）：{prod_duplicate_samples}")
            else:
                print(f"[info] 产品表去重：共 {len(prod_unique)} 行（无重复）")

            write_tasks.append(save_product_reports_to_db(prod_unique, db_config))

        # 并行执行所有写库任务
        if write_tasks:
            write_start = time.perf_counter()
            await asyncio.gather(*write_tasks)
            _timing_log(f"{report_date} write_db", write_start)

        # 移除固定延迟，只在遇到频控时延迟
        _timing_log(f"{report_date} total", total_start)
        return len(day_campaign_rows), len(day_product_rows), None

    for i in range(0, len(date_list), date_concurrency):
        chunk = date_list[i:i + date_concurrency]
        results = await asyncio.gather(*[_process_single_date(d) for d in chunk])
        for camp_cnt, prod_cnt, fail_date in results:
            total_campaign_rows += camp_cnt
            total_product_rows += prod_cnt
            if fail_date:
                failed_dates.append(fail_date)

    print(f"\nTotal campaign rows in range: {total_campaign_rows}")
    print(f"Total product rows in range: {total_product_rows}")
    if failed_dates:
        print(f"[warn] 以下日期仍未抓到数据（请留意频控/权限/数据缺失）：{', '.join(failed_dates)}")
    return failed_dates


async def _run_queryword_reports(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                                 date_list: List[str], sem: asyncio.Semaphore, page_size: int,
                                 db_config: Dict[str, Any], retries: int, retry_on_empty: bool,
                                 slow_retry: bool, slow_sem_size: int, slow_retries: int, slow_delay: float,
                                 queryword_configs: List[Tuple[str, str, str]], date_concurrency: int = 1) -> List[str]:
    """拉取并写入搜索词报表，返回失败日期列表。queryword_configs: (route, campaign_type, target_type)。支持日期层面的有限并行。"""

    total_rows = 0
    failed_dates: List[str] = []

    date_concurrency = max(1, date_concurrency)

    async def _process_single_date(report_date: str) -> Tuple[int, Optional[str]]:
        total_start = time.perf_counter()
        async def collect(current_sem: asyncio.Semaphore, retry_times: int) -> Rows:
            tasks = []
            for route, campaign_type, target_type in queryword_configs:
                tasks.extend([
                    get_query_word_data_for_seller(
                        op_api,
                        access_token,
                        s,
                        report_date,
                        target_type,
                        current_sem,
                        page_size,
                        retry_times,
                        route,
                        campaign_type,
                    )
                    for s in target_sellers
                ])
            results = await asyncio.gather(*tasks) if tasks else []
            return [row for group in results for row in group]

        collect_start = time.perf_counter()
        day_rows = await collect(sem, retries)
        _timing_log(f"{report_date} queryword collect", collect_start)

        print(f"\n{report_date} queryword rows: {len(day_rows)}")

        if not day_rows:
            print(f"[info] {report_date} 搜索词报表 0 行（过滤后），跳过重试与写库")
            return 0, None

        write_start = time.perf_counter()
        await save_queryword_reports_to_db(day_rows, db_config, [report_date])
        _timing_log(f"{report_date} queryword write_db", write_start)
        # 移除固定延迟，只在遇到频控时延迟
        _timing_log(f"{report_date} queryword total", total_start)
        return len(day_rows), None

    for i in range(0, len(date_list), date_concurrency):
        chunk = date_list[i:i + date_concurrency]
        results = await asyncio.gather(*[_process_single_date(d) for d in chunk])
        for rows_cnt, fail_date in results:
            total_rows += rows_cnt
            if fail_date:
                failed_dates.append(fail_date)

    print(f"\nTotal queryword rows in range: {total_rows}")
    if failed_dates:
        print(f"[warn] 搜索词报表未成功的日期：{', '.join(failed_dates)}")
    return failed_dates


async def _run_sp_keyword_reports(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                                  date_list: List[str], sem: asyncio.Semaphore, page_size: int,
                                  db_config: Dict[str, Any], retries: int, retry_on_empty: bool,
                                  slow_retry: bool, slow_sem_size: int, slow_retries: int, slow_delay: float,
                                  date_concurrency: int = 1) -> List[str]:
    """拉取并写入 SP 关键词报表，返回失败日期列表。支持日期层面的有限并行。"""

    total_rows = 0
    failed_dates: List[str] = []

    date_concurrency = max(1, date_concurrency)

    async def _process_single_date(report_date: str) -> Tuple[int, Optional[str]]:
        total_start = time.perf_counter()
        async def collect(current_sem: asyncio.Semaphore, retry_times: int) -> Rows:
            tasks = [
                get_sp_keyword_data_for_seller(
                    op_api,
                    access_token,
                    s,
                    report_date,
                    current_sem,
                    page_size,
                    retry_times,
                )
                for s in target_sellers
            ]
            results = await asyncio.gather(*tasks) if tasks else []
            return [row for group in results for row in group]

        collect_start = time.perf_counter()
        day_rows = await collect(sem, retries)
        _timing_log(f"{report_date} sp_keyword collect", collect_start)

        print(f"\n{report_date} sp_keyword rows: {len(day_rows)}")

        if not day_rows:
            print(f"[info] {report_date} SP 关键词报表 0 行（过滤后），跳过重试与写库")
            return 0, None

        write_start = time.perf_counter()
        await save_sp_keyword_reports_to_db(day_rows, db_config, [report_date])
        _timing_log(f"{report_date} sp_keyword write_db", write_start)
        _timing_log(f"{report_date} sp_keyword total", total_start)
        return len(day_rows), None

    for i in range(0, len(date_list), date_concurrency):
        chunk = date_list[i:i + date_concurrency]
        results = await asyncio.gather(*[_process_single_date(d) for d in chunk])
        for rows_cnt, fail_date in results:
            total_rows += rows_cnt
            if fail_date:
                failed_dates.append(fail_date)

    print(f"\nTotal sp_keyword rows in range: {total_rows}")
    if failed_dates:
        print(f"[warn] SP 关键词报表未成功的日期：{', '.join(failed_dates)}")
    return failed_dates


async def _run_sb_target_reports(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                                 date_list: List[str], sem: asyncio.Semaphore, page_size: int,
                                 db_config: Dict[str, Any], retries: int, retry_on_empty: bool,
                                 slow_retry: bool, slow_sem_size: int, slow_retries: int, slow_delay: float,
                                 date_concurrency: int = 1) -> List[str]:
    """拉取并写入 SB 定向报表，返回失败日期列表。支持日期层面的有限并行。"""

    total_rows = 0
    failed_dates: List[str] = []

    date_concurrency = max(1, date_concurrency)

    async def _process_single_date(report_date: str) -> Tuple[int, Optional[str]]:
        total_start = time.perf_counter()
        async def collect(current_sem: asyncio.Semaphore, retry_times: int) -> Rows:
            tasks = [
                get_sb_target_data_for_seller(
                    op_api,
                    access_token,
                    s,
                    report_date,
                    current_sem,
                    page_size,
                    retry_times,
                )
                for s in target_sellers
            ]
            results = await asyncio.gather(*tasks) if tasks else []
            return [row for group in results for row in group]

        collect_start = time.perf_counter()
        day_rows = await collect(sem, retries)
        _timing_log(f"{report_date} sb_target collect", collect_start)

        print(f"\n{report_date} sb_target rows: {len(day_rows)}")

        if not day_rows:
            print(f"[info] {report_date} SB 定向报表 0 行（过滤后），跳过重试与写库")
            return 0, None

        write_start = time.perf_counter()
        await save_sb_target_reports_to_db(day_rows, db_config, [report_date])
        _timing_log(f"{report_date} sb_target write_db", write_start)
        _timing_log(f"{report_date} sb_target total", total_start)
        return len(day_rows), None

    for i in range(0, len(date_list), date_concurrency):
        chunk = date_list[i:i + date_concurrency]
        results = await asyncio.gather(*[_process_single_date(d) for d in chunk])
        for rows_cnt, fail_date in results:
            total_rows += rows_cnt
            if fail_date:
                failed_dates.append(fail_date)

    print(f"\nTotal sb_target rows in range: {total_rows}")
    if failed_dates:
        print(f"[warn] SB 定向报表未成功的日期：{', '.join(failed_dates)}")
    return failed_dates


async def _run_sp_target_hour_reports(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                                      date_list: List[str], sem: asyncio.Semaphore, page_size: int,
                                      db_config: Dict[str, Any], retries: int, date_concurrency: int = 1) -> List[str]:
    """拉取 SP Target 小时报表并按天汇总后写库，返回失败日期列表。"""

    total_rows = 0
    failed_dates: List[str] = []

    print(f"\n[info] 开始获取 SP Target 小时报表，日期范围: {date_list[0] if date_list else 'N/A'} ~ {date_list[-1] if date_list else 'N/A'}，共 {len(date_list)} 天")

    campaign_ids = await fetch_enabled_campaign_ids(db_config, target_sellers)
    if not campaign_ids:
        print("[warn] 未找到 enabled 的 campaign_id，跳过 SP Target 小时报表")
        return failed_dates

    print(f"[info] 找到 {len(campaign_ids)} 个 enabled 的 campaign_id")

    date_concurrency = max(1, date_concurrency)

    async def _process_single_date(report_date: str) -> Tuple[int, Optional[str]]:
        total_start = time.perf_counter()
        print(f"\n[info] 开始处理日期: {report_date}，campaign 数量: {len(campaign_ids)}")

        async def collect(current_sem: asyncio.Semaphore, retry_times: int) -> List[dict]:
            completed = 0
            total_campaigns = len(campaign_ids)

            async def fetch_with_progress(campaign_id: str) -> List[dict]:
                nonlocal completed
                try:
                    result = await fetch_sp_target_hour_data(
                        op_api,
                        access_token,
                        campaign_id,
                        report_date,
                        current_sem,
                        page_size,
                        retry_times,
                    )
                    completed += 1
                    if completed % max(1, total_campaigns // 10) == 0 or completed == total_campaigns:
                        print(f"[progress] {report_date} 已完成 {completed}/{total_campaigns} 个 campaign")
                    return result
                except Exception as e:
                    completed += 1
                    print(f"[warn] {report_date} campaign_id={campaign_id} 获取失败: {e}")
                    return []

            tasks = [
                fetch_with_progress(campaign_id)
                for campaign_id in campaign_ids
            ]
            results = await asyncio.gather(*tasks) if tasks else []
            return [row for group in results for row in group]

        collect_start = time.perf_counter()
        raw_rows = await collect(sem, retries)
        _timing_log(f"{report_date} sp_target_hour collect", collect_start)
        print(f"[info] {report_date} 原始小时数据行数: {len(raw_rows)}")

        if not raw_rows:
            print(f"[info] {report_date} SP Target 小时报表 0 行，跳过写库")
            return 0, None

        # 按天汇总：key=(campaign_id, targeting_id, report_date)
        # 使用并行化汇总（大数据量时提升性能）
        print(f"[info] {report_date} 开始汇总数据（并行处理）...")

        async def _aggregate_chunk(chunk: List[dict]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
            """并行汇总数据块"""
            chunk_aggregated: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
            for item in chunk:
                campaign_id = str(item.get("campaign_id") or "")
                targeting_id = str(item.get("targeting_id") or "")
                if not campaign_id or not targeting_id:
                    continue
                createtime = str(item.get("report_date") or report_date)
                key = (campaign_id, targeting_id, createtime)
                entry = chunk_aggregated.get(key)
                if entry is None:
                    entry = {
                        "ad_group_id": str(item.get("group_id") or ""),
                        "campaign_id": campaign_id,
                        "targeting_id": targeting_id,
                        "targeting": item.get("targeting"),
                        "clicks": 0,
                        "orders": 0,
                        "createtime": createtime,
                    }
                    chunk_aggregated[key] = entry
                entry["clicks"] += int(item.get("clicks") or 0)
                entry["orders"] += int(item.get("orders") or 0)
                if not entry.get("ad_group_id") and item.get("group_id"):
                    entry["ad_group_id"] = str(item.get("group_id"))
                if not entry.get("targeting") and item.get("targeting"):
                    entry["targeting"] = item.get("targeting")
            return chunk_aggregated

        # 将数据分块并行处理（每块 10000 条）
        chunk_size = 10000
        chunks = [raw_rows[i:i + chunk_size] for i in range(0, len(raw_rows), chunk_size)]

        # 并行汇总各块数据
        agg_start = time.perf_counter()
        chunk_results = await asyncio.gather(*[_aggregate_chunk(chunk) for chunk in chunks])
        _timing_log(f"{report_date} sp_target_hour aggregate", agg_start)

        # 合并所有块的结果
        aggregated: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for chunk_agg in chunk_results:
            for key, entry in chunk_agg.items():
                if key in aggregated:
                    aggregated[key]["clicks"] += entry["clicks"]
                    aggregated[key]["orders"] += entry["orders"]
                    if not aggregated[key].get("ad_group_id") and entry.get("ad_group_id"):
                        aggregated[key]["ad_group_id"] = entry["ad_group_id"]
                    if not aggregated[key].get("targeting") and entry.get("targeting"):
                        aggregated[key]["targeting"] = entry["targeting"]
                else:
                    aggregated[key] = entry

        rows = [
            (
                v["ad_group_id"],
                v["campaign_id"],
                v["targeting_id"],
                v["targeting"],
                v["clicks"],
                v["orders"],
                v["createtime"],
            )
            for v in aggregated.values()
        ]

        print(f"[info] {report_date} 汇总完成: 原始 {len(raw_rows)} 行 -> 汇总后 {len(rows)} 行")
        if not rows:
            print(f"[info] {report_date} 汇总后 0 行，跳过写库")
            return 0, None

        print(f"[info] {report_date} 开始写入数据库...")
        write_start = time.perf_counter()
        await save_sp_target_reports_to_db(rows, db_config, [report_date])
        _timing_log(f"{report_date} sp_target_hour write_db", write_start)
        print(f"[info] {report_date} 完成，写入 {len(rows)} 行")
        _timing_log(f"{report_date} sp_target_hour total", total_start)
        return len(rows), None

    print(f"[info] 开始处理 {len(date_list)} 个日期，并发度: {date_concurrency}")
    for i in range(0, len(date_list), date_concurrency):
        chunk = date_list[i:i + date_concurrency]
        chunk_num = i // date_concurrency + 1
        total_chunks = (len(date_list) + date_concurrency - 1) // date_concurrency
        print(f"\n[progress] 处理日期批次 {chunk_num}/{total_chunks}: {', '.join(chunk)}")
        results = await asyncio.gather(*[_process_single_date(d) for d in chunk])
        for rows_cnt, fail_date in results:
            total_rows += rows_cnt
            if fail_date:
                failed_dates.append(fail_date)

    print(f"\n[info] SP Target 小时报表处理完成，总行数: {total_rows}")
    if failed_dates:
        print(f"[warn] SP Target 报表未成功的日期：{', '.join(failed_dates)}")
    else:
        print(f"[info] 所有日期处理成功")
    return failed_dates


async def _run_campaign_names(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                              sem: asyncio.Semaphore, page_size: int, db_config: Dict[str, Any], retries: int,
                              run_names: bool, run_ad_groups: bool) -> None:
    if not run_names and not run_ad_groups:
        return

    name_results: List[List[list]] = []
    group_results: List[List[list]] = []

    if run_names:
        name_tasks = [fetch_campaign_names(op_api, access_token, s, sem, page_size, retries)
                      for s in target_sellers]
        name_results = await asyncio.gather(*name_tasks)

    if run_ad_groups:
        group_tasks = [fetch_ad_groups(op_api, access_token, s, sem, page_size, retries)
                       for s in target_sellers]
        group_results = await asyncio.gather(*group_tasks)

    all_name_rows = [row for group in name_results for row in group] if run_names else []
    all_group_rows = [row for group in group_results for row in group] if run_ad_groups else []

    if run_names:
        print(f"\nCampaign names total: {len(all_name_rows)}")
        for seller, rows in zip(target_sellers, name_results):
            print(f"  seller sid={seller.get('sid')} name={seller.get('name')} rows={len(rows)}")

    if run_ad_groups:
        print(f"Ad group names total: {len(all_group_rows)}")
        for seller, rows in zip(target_sellers, group_results):
            print(f"  seller sid={seller.get('sid')} name={seller.get('name')} ad_groups={len(rows)}")

    today_str = date.today().strftime("%Y-%m-%d")

    # 数据库写入并行化：names 和 ad_groups 写入不同表，可以并行执行
    write_tasks = []
    if run_names and all_name_rows:
        name_values = [
            (
                r[2],  # campaign_type
                r[0],  # sid
                r[3],  # campaign_id
                r[4],  # name
                r[5] if len(r) > 5 else None,  # state
                r[6] if len(r) > 6 else None,  # targeting_type
                today_str,
            )
            for r in all_name_rows
            if len(r) >= 5
        ]
        write_tasks.append(save_campaign_names_to_db(name_values, db_config))

    if run_ad_groups and all_group_rows:
        group_values = [
            (
                r[2],  # campaign_type
                r[0],  # sid
                r[3],  # ad_group_id
                r[4],  # name
                r[5] if len(r) > 5 else None,  # campaign_id
                today_str,
            )
            for r in all_group_rows
            if len(r) >= 5
        ]
        write_tasks.append(save_ad_groups_to_db(group_values, db_config))

    # 并行执行所有写库任务
    if write_tasks:
        await asyncio.gather(*write_tasks)


async def _run_sb_creativity(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                             sem: asyncio.Semaphore, page_size: int, db_config: Dict[str, Any],
                             retries: int, run_flag: bool):
    """全量刷新 dim_amazon_sb_creativity（SB 创意，仅 state=enabled）。"""
    if not run_flag:
        return

    tasks = [fetch_sb_creativity(op_api, access_token, s, sem, page_size, retries) for s in target_sellers]
    results = await asyncio.gather(*tasks)

    all_rows = [row for group in results for row in group]
    print(f"\nSB creativity total: {len(all_rows)}")
    for seller, rows in zip(target_sellers, results):
        print(f"  seller sid={seller.get('sid')} name={seller.get('name')} rows={len(rows)}")

    if not all_rows:
        print("[info] SB 创意无数据，跳过写库")
        return

    today_str = date.today().strftime("%Y-%m-%d")
    # 构造插入值并在 Python 端去重，避免批量插入时出现主键重复错误
    seen = set()
    unique_values: List[tuple] = []
    duplicates = 0
    duplicate_samples: List[tuple] = []
    for r in all_rows:
        if len(r) < 4:
            continue
        sid_val = r[0]
        campaign_val = r[1]
        # 现在 rows 结构为 [sid, campaign_id, ad_group_id, ad_creative_id, asin]
        ad_group_val = r[2]
        ad_creative_val = r[3]
        asin_val = r[4] if len(r) > 4 else None
        if not campaign_val or not asin_val or ad_creative_val is None or ad_creative_val == "":
            continue
        # 使用表主键：按 (campaign_id, ad_creative_id, ad_group_id, asin) 去重（不包含 sid）
        key = (str(campaign_val), str(ad_creative_val), str(ad_group_val), str(asin_val))
        if key in seen:
            duplicates += 1
            if len(duplicate_samples) < 20:
                duplicate_samples.append((sid_val, campaign_val, ad_group_val, asin_val, ad_creative_val))
            continue
        seen.add(key)
        unique_values.append((sid_val, campaign_val, ad_group_val, ad_creative_val, asin_val, today_str))

    if duplicates:
        print(f"[info] SB 创意去重：原始 {len(all_rows)} 行 -> 去重后 {len(unique_values)} 行，去重掉 {duplicates} 行")
        if duplicate_samples:
            print(f"[debug] SB 创意重复样例（最多20）：{duplicate_samples}")
    else:
        print(f"[info] SB 创意去重：共 {len(unique_values)} 行（无重复）")

    await save_sb_creativity_to_db(unique_values, db_config)


async def _run_sb_targeting_dim(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                                sem: asyncio.Semaphore, page_size: int, db_config: Dict[str, Any],
                                retries: int, run_flag: bool):
    """全量刷新 dim_amazon_sb_target（SB 定向关键词，targeting_type=keyword）。"""
    if not run_flag:
        return

    tasks = [fetch_sb_targeting_keywords(op_api, access_token, s, sem, page_size, retries) for s in target_sellers]
    results = await asyncio.gather(*tasks)

    all_rows = [row for group in results for row in group]
    print(f"\nSB targeting keywords total: {len(all_rows)}")
    for seller, rows in zip(target_sellers, results):
        print(f"  seller sid={seller.get('sid')} name={seller.get('name')} rows={len(rows)}")

    if not all_rows:
        print("[info] SB 定向关键词无数据，跳过写库")
        return

    today_str = date.today().strftime("%Y-%m-%d")
    values = [
        (
            r[0],  # sid
            r[1],  # campaign_id
            r[2],  # keyword_id
            r[3] if len(r) > 3 else None,  # keyword_text
            r[4] if len(r) > 4 else None,  # keyword_state
            today_str,
        )
        for r in all_rows
        if len(r) >= 3
    ]
    await save_sb_targeting_dim_to_db(values, db_config)


async def _run_sp_product_ads(op_api: OpenApiBase, access_token: str, target_sellers: List[dict],
                               sem: asyncio.Semaphore, page_size: int, db_config: Dict[str, Any],
                               retries: int, run_flag: bool):
    """全量刷新 dim_amazon_product（SP 商品广告，过滤 archived 状态）。"""
    if not run_flag:
        return

    tasks = [get_sp_product_ads_for_seller(op_api, access_token, s, sem, page_size, retries) for s in target_sellers]
    results = await asyncio.gather(*tasks)

    all_rows = [row for group in results for row in group]
    print(f"\nSP product ads total: {len(all_rows)}")
    for seller, rows in zip(target_sellers, results):
        print(f"  seller sid={seller.get('sid')} name={seller.get('name')} rows={len(rows)}")

    if not all_rows:
        print("[info] SP 商品广告无数据，跳过写库")
        return

    today_str = date.today().strftime("%Y-%m-%d")
    # 直接写入 SP 商品广告，不进行去重
    values: List[tuple] = []
    for r in all_rows:
        # expected r layout after fetch_sp_product_ads:
        # [campaign_type, campaign_id, ad_id, sid, state, asin, sku]
        if len(r) < 7:
            continue
        values.append((r[0], r[1], r[2], r[3], r[4], r[5], r[6], today_str))

    print(f"[info] SP 商品广告写入行数: {len(values)}")
    await save_sp_product_ads_to_db(values, db_config)


async def main():
    settings = Settings()

    try:
        # 固定自动选择活跃店铺列表中的首个 sid，不再从环境变量读取
        sid_env = 0
        max_concurrency = settings.max_concurrency
        page_size = settings.page_size
        queryword_target_type = settings.queryword_target_type
        queryword_target_type_extra = settings.queryword_target_type_extra

        date_list = settings.date_list

        if not settings.app_id or not settings.app_secret:
            print("缺少凭据：请设置环境变量 APP_ID、APP_SECRET（可选 HOST）后重试")
            return

        op_api = OpenApiBase(
            settings.host,
            settings.app_id,
            settings.app_secret,
            enable_cache=settings.enable_request_cache,
            cache_ttl=settings.cache_ttl,
            enable_prefetch=settings.enable_page_prefetch,
            prefetch_pages=settings.prefetch_pages
        )
        token_start = time.perf_counter()
        access_token = await get_lingxing_access_token(settings, op_api)
        _timing_log("get_access_token", token_start)
        if settings.manual_access_token:
            print("[info] 使用手动提供的 access_token（未调用获取接口），可通过环境变量 MANUAL_ACCESS_TOKEN 覆盖")
        sellers_start = time.perf_counter()
        sellers = await fetch_seller_lists(op_api, access_token)
        _timing_log("fetch_sellers", sellers_start)
        filter_start = time.perf_counter()
        active_sellers = filter_active_sellers(sellers)
        _timing_log("filter_sellers", filter_start)
        print(f"Filter sellers: {len(active_sellers)} / total {len(sellers)}")

        target_sellers = active_sellers if sid_env == 0 else [s for s in active_sellers if s.get("sid") == sid_env]
        if sid_env and not target_sellers:
            print(f"未找到 sid={sid_env} 的活跃店铺，跳过")
            return
        if not target_sellers:
            return

        sem = asyncio.Semaphore(max_concurrency)

        # 目前仅按开关抓取 campaign 报表；商品级报表已在其他流程中处理
        if settings.run_campaign_reports:
            run_start = time.perf_counter()
            failed_dates = await _run_reports(
                op_api,
                access_token,
                target_sellers,
                date_list,
                sem,
                page_size,
                settings.db_config,
                settings.retries,
                settings.retry_on_empty,
                settings.slow_retry_on_empty,
                settings.slow_retry_concurrency,
                settings.slow_retry_retries,
                settings.slow_retry_delay,
                fetch_campaign=settings.run_campaign_reports,
                fetch_product=False,
                date_concurrency=settings.date_concurrency,
            )
            _timing_log("run_campaign_reports", run_start)
            if failed_dates:
                print(f"\n[info] 首轮完成，有 {len(failed_dates)} 天未成功，开始补采...")
                slow_sem = asyncio.Semaphore(settings.slow_retry_concurrency)
                run_retry_start = time.perf_counter()
                second_failed = await _run_reports(
                    op_api,
                    access_token,
                    target_sellers,
                    failed_dates,
                    slow_sem,
                    page_size,
                    settings.db_config,
                    settings.slow_retry_retries,
                    True,  # retry_on_empty
                    False,  # slow_retry，补采不再嵌套
                    settings.slow_retry_concurrency,
                    settings.slow_retry_retries,
                    settings.slow_retry_delay,
                    fetch_campaign=settings.run_campaign_reports,
                    fetch_product=False,
                    date_concurrency=settings.date_concurrency,
                )
                _timing_log("run_campaign_reports_retry", run_retry_start)
                if second_failed:
                    print(f"[warn] 补采后仍失败的日期: {', '.join(second_failed)}")
                else:
                    print("[info] 补采完成，所有日期已成功")

        if settings.run_queryword_reports:
            run_start = time.perf_counter()
            queryword_configs: List[Tuple[str, str, str]] = [
                ("/pb/openapi/newad/queryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/queryWordReports"], queryword_target_type),
                ("/pb/openapi/newad/queryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/queryWordReports"], queryword_target_type_extra),
                ("/pb/openapi/newad/hsaQueryWordReports", QUERY_WORD_ROUTES["/pb/openapi/newad/hsaQueryWordReports"], queryword_target_type_extra),
            ]
            qw_failed = await _run_queryword_reports(
                op_api,
                access_token,
                target_sellers,
                date_list,
                sem,
                page_size,
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
            _timing_log("run_queryword_reports", run_start)
            if qw_failed:
                print(f"[warn] 搜索词报表失败日期: {', '.join(qw_failed)}")
            else:
                print("[info] 搜索词报表完成")

        if settings.run_names or settings.run_ad_groups:
            run_start = time.perf_counter()
            await _run_campaign_names(
                op_api,
                access_token,
                target_sellers,
                sem,
                page_size,
                settings.db_config,
                settings.retries,
                settings.run_names,
                settings.run_ad_groups,
            )
            _timing_log("run_campaign_names/ad_groups", run_start)
        if settings.run_sb_creativity:
            run_start = time.perf_counter()
            await _run_sb_creativity(
                op_api,
                access_token,
                target_sellers,
                sem,
                page_size,
                settings.db_config,
                settings.retries,
                settings.run_sb_creativity,
            )
            _timing_log("run_sb_creativity", run_start)
        if settings.run_sb_targeting_dim:
            run_start = time.perf_counter()
            await _run_sb_targeting_dim(
                op_api,
                access_token,
                target_sellers,
                sem,
                page_size,
                settings.db_config,
                settings.retries,
                settings.run_sb_targeting_dim,
            )
            _timing_log("run_sb_targeting_dim", run_start)
        if settings.run_sp_product_ads:
            run_start = time.perf_counter()
            await _run_sp_product_ads(
                op_api,
                access_token,
                target_sellers,
                sem,
                page_size,
                settings.db_config,
                settings.retries,
                settings.run_sp_product_ads,
            )
            _timing_log("run_sp_product_ads", run_start)
        if settings.run_sp_keyword_reports:
            run_start = time.perf_counter()
            kw_failed = await _run_sp_keyword_reports(
                op_api,
                access_token,
                target_sellers,
                date_list,
                sem,
                page_size,
                settings.db_config,
                settings.retries,
                settings.retry_on_empty,
                settings.slow_retry_on_empty,
                settings.slow_retry_concurrency,
                settings.slow_retry_retries,
                settings.slow_retry_delay,
                date_concurrency=settings.date_concurrency,
            )
            _timing_log("run_sp_keyword_reports", run_start)
            if kw_failed:
                print(f"[warn] SP 关键词报表失败日期: {', '.join(kw_failed)}")
            else:
                print("[info] SP 关键词报表完成")
        if settings.run_sb_target_reports:
            run_start = time.perf_counter()
            sbt_failed = await _run_sb_target_reports(
                op_api,
                access_token,
                target_sellers,
                date_list,
                sem,
                page_size,
                settings.db_config,
                settings.retries,
                settings.retry_on_empty,
                settings.slow_retry_on_empty,
                settings.slow_retry_concurrency,
                settings.slow_retry_retries,
                settings.slow_retry_delay,
                date_concurrency=settings.date_concurrency,
            )
            _timing_log("run_sb_target_reports", run_start)
            if sbt_failed:
                print(f"[warn] SB 定向报表失败日期: {', '.join(sbt_failed)}")
            else:
                print("[info] SB 定向报表完成")
        if settings.run_sp_target_hour_reports:
            run_start = time.perf_counter()
            spt_failed = await _run_sp_target_hour_reports(
                op_api,
                access_token,
                target_sellers,
                date_list,
                sem,
                page_size,
                settings.db_config,
                settings.retries,
                date_concurrency=settings.date_concurrency,
            )
            _timing_log("run_sp_target_hour_reports", run_start)
            if spt_failed:
                print(f"[warn] SP Target 小时报表失败日期: {', '.join(spt_failed)}")
            else:
                print("[info] SP Target 小时报表完成")
    finally:
        await _close_http_session()
        await _close_db_pool()
        _print_timing_summary()


if __name__ == "__main__":
    asyncio.run(main())
