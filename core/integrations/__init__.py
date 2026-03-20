# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Common API Library for automation projects."""

from .lingxing_client import LingXingClient
from .dingtalk_client import (
    DingTalkNotifier,
    download_file_by_code,
    send_group_text,
    send_user_file,
    send_user_text,
)

__all__ = [
    "LingXingClient",
    "DingTalkNotifier",
    "send_user_text",
    "send_user_file",
    "send_group_text",
    "download_file_by_code",
]

