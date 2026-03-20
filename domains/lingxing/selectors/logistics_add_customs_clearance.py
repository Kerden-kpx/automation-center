# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Selectors for LingXing logistics add customs clearance."""

from __future__ import annotations

LOGISTICS_ADD_CUSTOMS_CLEARANCE_SELECTORS = {
    # 物流-添加清关资料-添加按钮（el-button--primary is-round）
    "customs_add_button": [
        '//button[contains(@class,"el-button--primary")][contains(@class,"is-round")][.//span[contains(text(),"添加")]]',
        '//button[contains(@class,"el-button--primary")][.//span[contains(text(),"添加")]]',
        '//*[contains(@class, "ak-footer-btn")]/button[2]',
    ],
    # 物流-添加清关资料-收货仓库信息区域（含名称/国家/省州/城市/邮编/详细地址等）
    "customs_receiver_section": [
        '//div[contains(@class,"col-item")][.//span[contains(normalize-space(.),"收货仓库")]]',
    ],
    # 物流-添加清关资料-收货仓库信息已加载（form-col-text）
    "customs_receiver_loaded": [
        '//div[contains(@class,"col-item")][.//span[contains(normalize-space(.),"收货仓库")]]//span[contains(@class,"form-col-text")]',
        '//span[contains(@class,"form-col-text")][contains(@class,"disable-bg")]',
    ],
}
