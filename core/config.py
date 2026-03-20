# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Centralized configuration for Web_Library.

All platform URLs and common settings should be defined here.
"""

from __future__ import annotations

# ==================== 平台网址配置 ====================
# 领星 ERP
LINGXING_URL = "https://erp.lingxing.com/erp/home"
LINGXING_DELIVERY_URL = "https://erp.lingxing.com/erp/msupply/DeliveryOrderDetail?order_sn={order_no}&tag_name=deliveryOrderDetail"
LINGXING_DELIVERY_EDIT_URL = "https://erp.lingxing.com/erp/msupply/DeliveryOrderEdit?order_sn={order_no}&tag_name=deliveryOrderEdit"
LINGXING_CUSTOMS_CLEAR_URL = "https://erp.lingxing.com/erp/customsClearAdd?businessType=1&businessSns="
LINGXING_CUSTOMS_MANAGE_URL = "https://erp.lingxing.com/erp/customsClearManage"
LINGXING_SHIPMENT_PLAN_URL = "https://erp.lingxing.com/erp/msupply/shipmentPlan"

# Agl 物流平台
AGL_URL = "https://freight.amazon.com"

# 卖家精灵
SELLERSPRITE_COMPETITOR_LOOKUP_URL = "https://www.sellersprite.com/v3/competitor-lookup"
SELLERSPRITE_LOGIN_URL = "https://www.sellersprite.com/cn/w/user/login"

# ==================== 浏览器配置 ====================
# Chrome 调试端口
CDP_ENDPOINT = "http://127.0.0.1:9222"
CDP_TIMEOUT_SEC = 10

# 是否在连接失败时尝试自动启动 Chrome (仅限 Windows)
AUTO_START_CDP = True
CDP_START_TIMEOUT_SEC = 15
CHROME_USER_DATA_DIR = r"D:\Yida_project\automation-center\web\shared\chrome-user-data"

# ==================== 超时配置 ====================
# 页面加载超时 (毫秒)
PAGE_LOAD_TIMEOUT_MS = 30000
# 网络空闲等待超时 (毫秒)
NETWORK_IDLE_TIMEOUT_MS = 8000
