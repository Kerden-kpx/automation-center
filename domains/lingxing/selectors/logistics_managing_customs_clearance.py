# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Selectors for LingXing logistics customs clearance management."""

from __future__ import annotations

LOGISTICS_CUSTOMS_MANAGEMENT_SELECTORS = {
    # 物流-清关管理-筛选条件下拉框（搜索栏前置的"清关资料编号"下拉框，在 el-input-group__prepend 内）
    "customs_filter_select": [
        '//div[contains(@class,"el-input-group__prepend")]//div[contains(@class,"el-select")]//input[@readonly]',
        '//div[contains(@class,"el-input-group__prepend")]//span[contains(@class,"fake-placeholder-hidden")]',
        '//div[@id="advanced-input"]//div[contains(@class,"el-select")]//input[@readonly]',
    ],
    # 物流-清关管理-筛选项-关联单号
    "customs_filter_option_related": [
        '//li[contains(@class,"el-select-dropdown__item")][.//span[contains(text(),"关联单号")]]',
        '//li[contains(@class,"el-select-dropdown__item")][contains(.,"关联单号")]',
        '//span[contains(text(),"关联单号")]/ancestor::li[contains(@class,"el-select-dropdown__item")]',
    ],
    # 物流-清关管理-搜索输入框（el-input-group 内的非只读输入框）
    "customs_search_input": [
        '//div[contains(@class,"el-input-group--prepend")]//input[contains(@class,"el-input__inner")][not(@readonly)]',
        '//div[contains(@class,"search-input")]//input[contains(@class,"el-input__inner")][not(@readonly)]',
        '//div[@id="advanced-input"]//input[not(@readonly)]',
    ],
    # 物流-清关管理-查询按钮（放大镜图标）

    "customs_search_button": [
        '//i[@class="iconfont lx_combo_search"]',
        '//button[contains(@class,"el-button")][.//i[contains(@class,"lx_combo_search")]]',
    ],
    # 物流-清关管理-全选复选框（表头区域内的 vxe-cell--checkbox）
    "customs_select_all": [
        '//div[contains(@class,"vxe-table--header")]//span[contains(@class,"vxe-cell--checkbox")]',
        '//th[contains(@class,"vxe-header--column")]//span[contains(@class,"vxe-cell--checkbox")]',
        '//span[@title="全选/取消"]',
        '//div[contains(@class,"vxe-cell")]//span[contains(@class,"vxe-cell--checkbox")]',
    ],

    # 物流-清关管理-下载按钮
    "customs_download_button": [
        '//button[contains(@class,"el-button--default")][.//span[contains(text(),"下载")]]',
        '//*[contains(@class, "ak-operate-wrapper")]/button[2]',
        '//button[contains(@class,"is-round")][.//span[contains(text(),"下载")]]',
    ],
    # 物流-清关管理-批量下载-打印模板选择框
    "customs_download_template_select": [
        '//div[@aria-label="批量下载"]//div[contains(@class,"el-select")]//input[@readonly]',
        '//div[@aria-label="批量下载"]//div[contains(@class,"el-input")]//input[@readonly]',
        '//div[contains(@class,"el-dialog")][.//span[contains(normalize-space(.),"批量下载")]]//input[@readonly]',
    ],
    # 物流-清关管理-批量下载-模板选项-平谊国际下单模板
    "customs_download_template_option_pingyi": [
        '//li[contains(@class,"el-select-dropdown__item")][.//span[contains(text(),"平谊国际下单模板")]]',
        '//li[contains(@class,"el-select-dropdown__item")][contains(.,"平谊国际下单模板")]',
        '//span[contains(text(),"平谊国际下单模板")]/ancestor::li[contains(@class,"el-select-dropdown__item")]',
    ],
    # 物流-清关管理-确认下载按钮
    "customs_download_confirm": [
        '//div[@aria-label="批量下载"]//button[contains(@class,"el-button--primary")][.//span[contains(text(),"下载")]]',
        '//button[contains(@class,"el-button--primary")][contains(@class,"is-round")]',
        '//div[@aria-label="批量下载"]//button[contains(@class,"el-button--primary")]',
    ],
    # 物流-清关管理-下载弹窗关闭按钮
    "customs_download_close": [
        '//div[@aria-label="批量下载"]//button[@aria-label="Close"]',
        '//div[@aria-label="批量下载"]//button[contains(@class,"el-dialog__headerbtn")]',
        '//button[contains(@class,"el-dialog__headerbtn")][.//i[contains(@class,"lx_close")]]',
    ],
    # 调整按钮 (用于刷新发货仓库店铺和FNSKU)
    "adjust_button": [
        '//th[@colid="col_240"]//button[.//span[contains(text(), "调整")]]',
        '//th[@colid="col_240"]//span[contains(text(), "调整")]',
        '//th[@colid="col_226"]//button[.//span[contains(text(), "调整")]]',
        '//th[@colid="col_226"]//span[contains(text(), "调整")]',
        '//th[.//span[contains(normalize-space(.), "发货仓库店铺")]]//button[.//span[contains(normalize-space(.), "调整")]]',
        '//button[.//span[contains(text(), "调整")]]',
    ],
    # 发货仓库店铺单元格 (增加对 col_240/col_226 的支持)
    "warehouse_shop_cells": [
        '//td[@colid="col_240"]',
        '//td[@colid="col_226"]',
        '//tr[contains(@class,"vxe-body--row")]//td[@colid="col_14"]',
        '//td[@colid="col_14"]',
    ],
    # 发货仓库FNSKU单元格 (增加对 col_241/col_227 的支持)
    "warehouse_fnsku_cells": [
        '//td[@colid="col_241"]',
        '//td[@colid="col_227"]',
        '//tr[contains(@class,"vxe-body--row")]//td[@colid="col_15"]',
        '//td[@colid="col_15"]',
    ],
    # 发货仓库店铺下拉选项 (通常第一个就是 EZARC NA-US)
    "warehouse_shop_dropdown_options": [
        '//div[not(contains(@style,"display: none"))][contains(@class, "el-select-dropdown")]//li[contains(@class, "el-select-dropdown__item")][string-length(normalize-space(.)) > 0]',
        '//div[not(contains(@style,"display: none"))][contains(@class, "el-select-dropdown")]//li[contains(@class, "el-select-dropdown__item")]',
    ],
    # 发货仓库FNSKU下拉选项 (通常第一个是空，第二个才是 B08FR158NR，所以强制要求内容非空)
    "warehouse_fnsku_dropdown_options": [
        '//div[not(contains(@style,"display: none"))][contains(@class, "el-select-dropdown")]//li[contains(@class, "el-select-dropdown__item")][string-length(normalize-space(.)) > 0]',
        '//div[not(contains(@style,"display: none"))][contains(@class, "el-select-dropdown")]//li[contains(@class, "el-select-dropdown__item")][2]', # 也可以直接选第二个
    ],

    # 物流-清关管理-数据行
    "customs_manage_table_row": [
        '//table[contains(@class,"vxe-table--body")]//tr[contains(@class,"vxe-body--row")]',
        '//tr[contains(@class,"vxe-body--row")]',
    ],
}
