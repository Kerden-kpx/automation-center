#!/usr/bin/env python
"""钉钉 API 辅助：获取 access_token 和发送私聊消息，已抽取到 Utils 包避免循环导入。"""
from typing import Optional, Tuple
import asyncio
import json
import time
from alibabacloud_dingtalk.oauth2_1_0.client import Client as dingtalkoauth2_1_0Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dingtalk.oauth2_1_0 import models as dingtalkoauth_2__1__0_models
from alibabacloud_dingtalk.robot_1_0.client import Client as dingtalkrobot_1_0Client
from alibabacloud_dingtalk.robot_1_0 import models as dingtalkrobot__1__0_models
from alibabacloud_tea_util import models as util_models


def _fetch_token_sync(config) -> Tuple[Optional[str], int]:
    api_config = open_api_models.Config()
    api_config.protocol = 'https'
    api_config.region_id = 'central'
    client = dingtalkoauth2_1_0Client(api_config)
    get_access_token_request = dingtalkoauth_2__1__0_models.GetAccessTokenRequest(
        app_key=config.client_id,
        app_secret=config.client_secret
    )
    response = client.get_access_token(get_access_token_request)
    token = getattr(response.body, "access_token", None)
    expire_in = getattr(response.body, "expires_in", None) or getattr(response.body, "expire_in", 7200)
    return token, int(expire_in) if expire_in else 7200


async def get_token(config=None) -> Optional[str]:
    """获取 DingTalk access_token，带本地缓存。"""
    if not hasattr(get_token, "_token_cache"):
        get_token._token_cache = {"token": None, "expire": 0}
    now = time.time()
    if get_token._token_cache["token"] and now < get_token._token_cache["expire"]:
        return get_token._token_cache["token"]

    if config is None:
        print("获取token失败: 缺少 DingTalk 配置")
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop:
            token, expire_in = await loop.run_in_executor(None, _fetch_token_sync, config)
        else:
            token, expire_in = _fetch_token_sync(config)
    except Exception as err:
        print(f"获取token失败: {err}")
        return None

    if token:
        get_token._token_cache["token"] = token
        get_token._token_cache["expire"] = now + max(expire_in - 200, 60)
    return token


def get_token_sync(config=None) -> Optional[str]:
    """同步获取 DingTalk access_token，带本地缓存。"""
    if not hasattr(get_token_sync, "_token_cache"):
        get_token_sync._token_cache = {"token": None, "expire": 0}
    now = time.time()
    if get_token_sync._token_cache["token"] and now < get_token_sync._token_cache["expire"]:
        return get_token_sync._token_cache["token"]
    if config is None:
        print("获取token失败: 缺少 DingTalk 配置")
        return None
    try:
        token, expire_in = _fetch_token_sync(config)
    except Exception as err:
        print(f"获取token失败: {err}")
        return None
    if token:
        get_token_sync._token_cache["token"] = token
        get_token_sync._token_cache["expire"] = now + max(expire_in - 200, 60)
    return token


def send_robot_private_message(
    access_token: str,
    config,
    user_ids: list,
    message: str,
    *,
    msg_title: str = "消息",
    use_markdown: bool = False,
) -> Optional[object]:
    """发送机器人私聊消息。"""
    api_config = open_api_models.Config()
    api_config.protocol = 'https'
    api_config.region_id = 'central'
    client = dingtalkrobot_1_0Client(api_config)

    batch_send_otoheaders = dingtalkrobot__1__0_models.BatchSendOTOHeaders()
    batch_send_otoheaders.x_acs_dingtalk_access_token = access_token
    if use_markdown:
        msg_key = 'sampleMarkdown'
        msg_param = json.dumps({"title": msg_title, "text": message}, ensure_ascii=False)
    else:
        msg_key = 'sampleText'
        msg_param = json.dumps({"content": message}, ensure_ascii=False)

    batch_send_otorequest = dingtalkrobot__1__0_models.BatchSendOTORequest(
        robot_code=config.robot_code,
        user_ids=user_ids,
        msg_key=msg_key,
        msg_param=msg_param
    )
    try:
        return client.batch_send_otowith_options(
            batch_send_otorequest,
            batch_send_otoheaders,
            util_models.RuntimeOptions()
        )
    except Exception as err:
        print(f"发送单聊消息失败: {err}")
        return None


