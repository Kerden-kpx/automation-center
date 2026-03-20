#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Common API Library Configuration.

Centralized configuration for shared API clients (e.g., LingXing).
"""

from __future__ import annotations

import os
from pathlib import Path
from core.settings import load_env_files

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_APP_ENV = _PROJECT_ROOT / "apps" / "scheduler" / "backend" / ".env"
_ROOT_ENV = _PROJECT_ROOT / ".env"
load_env_files([_APP_ENV, _ROOT_ENV], override=False)

# ==================== LingXing OpenAPI Configuration ====================
LINGXING_API_HOST = os.getenv('LINGXING_API_HOST', 'http://121.41.4.126:3188')
LINGXING_API_KEY = os.getenv('LINGXING_API_KEY', '')
LINGXING_API_SECRET = os.getenv('LINGXING_API_SECRET', '')
LINGXING_TOKEN_URL = os.getenv('LINGXING_TOKEN_URL', 'http://121.41.4.126:3721/token')
LINGXING_TOKEN_REQUEST_KEY = os.getenv('LINGXING_TOKEN_REQUEST_KEY', '') or LINGXING_API_KEY
LINGXING_SSL_VERIFY = os.getenv('LINGXING_SSL_VERIFY', 'false').lower() == 'true'

# Web Login
LINGXING_USERNAME = os.getenv('LINGXING_USERNAME', '')
LINGXING_PASSWORD = os.getenv('LINGXING_PASSWORD', '')

# ==================== DingTalk Configuration ====================
DINGTALK_API_BASE_URL = os.getenv("DINGTALK_API_BASE_URL", "https://api.dingtalk.com")
# Allow fallback to existing env names for compatibility.
DINGTALK_APP_KEY = os.getenv("DINGTALK_APP_KEY") or os.getenv("CLIENT_ID", "")
DINGTALK_APP_SECRET = os.getenv("DINGTALK_APP_SECRET") or os.getenv("CLIENT_SECRET", "")
DINGTALK_ROBOT_CODE = os.getenv("DINGTALK_ROBOT_CODE") or os.getenv("ROBOT_CODE", "")
DINGTALK_GROUP_WEBHOOK = os.getenv("DINGTALK_GROUP_WEBHOOK", "")
DINGTALK_GROUP_SECRET = os.getenv("DINGTALK_GROUP_SECRET", "")
