# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Centralized UI selectors for Agl automation."""

from __future__ import annotations

AGL_SELECTORS = {
    # 登录
    "login_account": [
        '//form//input[@type="email"]',
    ],
    # 密码
    "login_password": [
        '//form//input[@type="password"]',
    ],
    # 继续按钮
    "login_continue": [
        '//form//input[@id="continue"]',
    ],
    # 登录按钮
    "login_submit": [
        '//form//input[@id="signInSubmit"]'
    ],
    # 保持登录状态
    "login_keep_signed_in": [
        '//form//span[contains(@class, "a-label")]'
    ],
    # 选择账号按钮（如出现）
    "login_account_select": [
        '//kat-button[@class="full-page-account-switcher-button"]',
    ],
    # 语言选择
    "language_dropdown": [
        '//div[@class="css-bnlngw"]',
        '//div[@class="css-1h2ruwl"]',
    ],
    # 简体中文
    "language_option_zh_cn": [
        '//button/div[1][normalize-space(.)="简体中文"]',
    ],
    # 入库目的地
    "entry_destination_input": [
        'css=kat-dropdown[data-testid="destination-service-type-dropdown"] >> div[part="dropdown-header"]',
    ],
    # 亚马逊优享入仓(AMP)
    "entry_destination_option_amp": [
        'css=kat-dropdown[data-testid="destination-service-type-dropdown"] >> kat-option[part="dropdown-option1"]',
    ],
    # 总体积（m³）-箱子
    "volume_input": [
        '//kat-input[@data-testid="volume-input"]',
    ],
    # 总重量（kg）-箱子
    "weight_input": [
        '//kat-input[@data-testid="weight-input"]',
    ],
    # 货好日期
    "cargo_ready_date_input": [
        'css=kat-input[part="date-picker-input"] input[placeholder="YYYY/MM/DD"]',
    ],
    # 搜索
    "search_button": [
        '//kat-button[@data-testid="quotation-form-confirm-btn"]',
    ],
    # 配送方式页面结果卡片
    "booking_cards": [
        'css=kat-card.offering-tile',
        'xpath=//*[@id="root"]//kat-card[contains(@class,"offering-tile")]',
    ],
    # 卡片内预订按钮
    "booking_button_in_card": [
        'xpath=.//*[local-name()="kat-button"][normalize-space(.)="预订"]',
        'xpath=.//button[normalize-space(.)="预订"]',
    ],
    # 配送类型
    "delivery_type_in_card": [
        'xpath=.//div[contains(@class, "display-flex-vertical")]/*[local-name()="kat-label"][contains(@class,"kat-typography-heading-300")]'
    ],
    # 集装箱类型
    "container_type_in_card": [
        'xpath=.//div[contains(@class, "offering-tile")]//div[contains(@class,"kat-col-xs-3")][2]//kat-label[contains(@class,"kat-typography-heading-300")]'
    ],
    # 装货方法
    "loading_method_input": [
        'css=kat-dropdown[data-testid="loading-method-dropdown"] >> div[part="dropdown-header"]',
    ],
    # 亚马逊提货
    "loading_method_option_amazon_pickup": [
        'css=kat-dropdown[data-testid="loading-method-dropdown"] >> kat-option:has-text("亚马逊提货")',
    ],
    # 提货位置
    "pickup_location_input": [
        'css=kat-dropdown[placeholder="Select a location"] >> div[part="dropdown-header"]',
    ],
    # 杭州易达工具有限公司
    "pickup_location_option_yuhang": [
        'css=kat-dropdown[placeholder="Select a location"] >> kat-option:has-text("余杭本地仓-杭州易达工具有限公司")',
    ],
    # 位置
    "location_input": [
        'css=kat-dropdown[data-testid="pol-customs-dropdown"] >> div[part="dropdown-header"]',
    ],
    # 位于装货港
    "location_option_at_port": [
        'css=kat-dropdown[data-testid="pol-customs-dropdown"] >> kat-option:has-text("位于装货港")',
    ],
    # 立即输入海关入境申报单信息，稍后再提供 FBA 货件详情
    "customs_info_radio": [
        '//input[@aria-label="立即输入海关入境申报单信息，稍后再提供 FBA 货件详情"]',
    ],
    # 商品描述
    "goods_description_input": [
        'css=input[part="input"][placeholder="输入描述"]',
        'xpath=//input[@part="input" and @type="text" and contains(@placeholder,"输入描述")]',
    ],
    # 商品数量
    "goods_quantity_input": [
        'css=kat-input[data-testid="item-count-input"] >> input[part="input"]',
        'xpath=//kat-input[@data-testid="item-count-input"]//input[@part="input" and @type="number"]',
    ],
    # 包装箱数量
    "carton_quantity_input": [
        'css=kat-input[data-testid="box-count-input"] >> input[part="input"]',
        'xpath=//kat-input[@data-testid="box-count-input"]//input[@part="input" and @type="number"]',
    ],
    # 发货人
    "shipper_input": [
        'css=kat-dropdown[data-testid="CONSIGNER-dropdown"] >> div[part="dropdown-header"]',
    ],
    # Room 403-5, Building 9, Yunkong Chengfeng Zhizhu-Hangzhou Lumiya Technology Co., Ltd
    "shipper_option": [
        'css=kat-dropdown[data-testid="CONSIGNER-dropdown"] >> kat-option:has-text("Room 403-5, Building 9, Yunkong Chengfeng Zhizhu-Hangzhou Lumiya Technology Co., Ltd")'
    ],
    # 收货人
    "consignee_input": [
        'css=kat-dropdown[data-testid="CONSIGNEE-dropdown"] >> div[part="dropdown-header"]',
    ],
    # ONT2-Hangzhou Lumiya Technology Co., Ltd
    "consignee_option": [
        'css=kat-dropdown[data-testid="CONSIGNEE-dropdown"] >> kat-option:has-text("ONT2-Hangzhou Lumiya Technology Co., Ltd")',
    ],
    # 主要订舱联系人
    "main_contact_input": [
        'css=kat-dropdown[data-testid="CONTACT-dropdown"] >> div[part="dropdown-header"]',
    ],
    # Room 403-5, Building 9, Yunkong Chengfeng Zhizhu-Hangzhou Lumiya Technology Co., Ltd
    "main_contact_option": [
        'css=kat-dropdown[data-testid="CONTACT-dropdown"] >> kat-option:has-text("Room 403-5, Building 9, Yunkong Chengfeng Zhizhu-Hangzhou Lumiya Technology Co., Ltd")',
    ],
    # 通知方
    "notify_party_input": [
        'css=kat-dropdown[data-testid="NOTIFY-dropdown"] >> div[part="dropdown-header"]',
    ],
    # ONT2-Amazon.com Services, Inc.
    "notify_party_option": [
        'css=kat-dropdown[data-testid="NOTIFY-dropdown"] >> kat-option:has-text("ONT2-Amazon.com Services, Inc.")',
    ],
    # 进口文件提供商
    "import_doc_provider_input": [
        'css=kat-dropdown[data-testid="IMPORT_DOCUMENTS_PROVIDER-dropdown"] >> div[part="dropdown-header"]',
    ],
    # 发货人
    "import_doc_provider_option": [
        'css=kat-dropdown[data-testid="IMPORT_DOCUMENTS_PROVIDER-dropdown"] >> kat-option:has-text("发货人")',
    ],
    # 订舱方
    "booking_party_input": [
        'css=kat-dropdown[data-testid="BOOKING_PLACEMENT_PARTY-dropdown"] >> div[part="dropdown-header"]',
    ],
    # 发货人
    "booking_party_option": [
        'css=kat-dropdown[data-testid="BOOKING_PLACEMENT_PARTY-dropdown"] >> kat-option:has-text("发货人")',
    ],
    # 登记进口商
    "importer_of_record_input": [
        'css=kat-dropdown[data-testid="IMPORTER_OF_RECORD-dropdown"] >> div[part="dropdown-header"]',
    ],
    # Hangzhou Lumiya Technology Co., Ltd-Hangzhou Lumiya Technology Co., Ltd
    "importer_of_record_option": [
        'css=kat-dropdown[data-testid="IMPORTER_OF_RECORD-dropdown"] >> kat-option:has-text("Hangzhou Lumiya Technology Co., Ltd-Hangzhou Lumiya Technology Co., Ltd")',
    ],
    #  货件名称
    "shipment_name_input": [
        '//kat-input[@data-testid="shipment-name-input"]',
    ],
    # 提交
    "submit_button": [
        '//kat-button[@data-testid="submit-booking-button"]',
    ],
    # 订单管理搜索框
    "management_search_bar": [
        '//kat-input[@data-testid="search-bar"]',
        '//input[@placeholder="按名称、ID或位置搜索货件"]',
        '//kat-input//input[@part="input"]',
    ],
    # 订单管理搜索图标
    "management_search_icon": [
        '//kat-button[@class="search-icon"]',
        'kat-button.search-icon',
    ],
    # 预订单号链接
    "shipment_id_link": [
        'xpath=//span[@data-testid="booking-id-cell-booking-id"]//kat-link[contains(@href, "/freight-puma/shipment/AL0-")]',
        'xpath=//kat-link[contains(@href, "/freight-puma/shipment/AL0-")]',
    ],
}
