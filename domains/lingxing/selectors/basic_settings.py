# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Basic selectors for LingXing login and language settings."""

from __future__ import annotations

BASIC_SELECTORS = {
    # ==================== 登录选择器 ====================
    "login_button": [
        '//button[@class="el-button loginBtn el-button--primary el-button--large is-round"]',
    ],
    "account_input": [
        '//input[@name="account"]',
    ],
    "password_input": [
        '//input[@name="pwd"]',
    ],
    # ==================== 语言选择 ====================
    "lang_trigger": [
        "//span[contains(@class,'lx-lang-title')]",
    ],
    "lang_option_cn": [
        "//span[contains(normalize-space(.),'简体中文')]",
    ],
}
