# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Selectors for LingXing FBA shipment plan page."""

from __future__ import annotations

FBA_SHIPMENT_PLAN_SELECTORS = {
    # 筛选项选择框（当前显示“创建批次号”）
    "plan_filter_select_input": [
        "//div[contains(@class,'el-input') and contains(@class,'el-input--prefix') and .//span[contains(@class,'fake-placeholder-hidden')][contains(normalize-space(.),'创建批次号')]]//input[@readonly]",
        "//span[contains(@class,'fake-placeholder-hidden')][contains(normalize-space(.),'创建批次号')]/ancestor::div[contains(@class,'el-input')]//input[@readonly]",
    ],
    # 筛选项下拉选项：发货计划单号
    "plan_filter_option_plan_no": [
        "//li[contains(@class,'el-select-dropdown__item')][.//span[contains(normalize-space(.),'发货计划单号')]]",
        "//li[contains(@class,'el-select-dropdown__item') and contains(normalize-space(.),'发货计划单号')]",
    ],
    # 多项精确搜索按钮
    "plan_multi_search_button": [
        "//span[contains(@class,'advanced-input-icon')]/ancestor::span[contains(@class,'wrapper-icon')]",
        "//span[contains(@class,'wrapper-icon')]//i[contains(@class,'lx_combo_filter')]/ancestor::span[contains(@class,'wrapper-icon')]",
        "//i[contains(@class,'lx_combo_filter')]/ancestor::span[contains(@class,'wrapper-icon')]",
    ],
    # 多项精确搜索输入框
    "plan_multi_search_input": [
        "//div[contains(@class,'popover-textarea')]//textarea[contains(@class,'el-textarea__inner') and contains(@placeholder,'精确搜索')]",
        "//textarea[contains(@class,'el-textarea__inner') and contains(@placeholder,'精确搜索')]",
    ],
    # 搜索按钮
    "plan_search_button": [
        "//button[contains(@class,'el-button') and contains(@class,'el-button--primary') and .//span[normalize-space(.)='搜索']]",
        "//button[@data-auth='auth-button' and .//span[normalize-space(.)='搜索']]",
        "//span[normalize-space(.)='搜索']/ancestor::button[contains(@class,'el-button')]",
    ],
    # 结果表全选框
    "plan_select_all_checkbox": [
        "//div[contains(@class,'vxe-cell')]//span[contains(@class,'vxe-cell--checkbox') and @title='全选/取消']",
        "//span[contains(@class,'vxe-cell--checkbox') and @title='全选/取消']",
    ],
    # 生成单据按钮
    "plan_generate_button": [
        "//div[contains(@class,'ak-drop-button')]//button[contains(@class,'el-button')][.//span[contains(normalize-space(.),'生成单据')]]",
        "//button[@data-auth='auth-button' and .//span[contains(normalize-space(.),'生成单据')]]",
        "//span[contains(normalize-space(.),'生成单据')]/ancestor::button",
    ],
    # 生成发货单按钮
    "plan_generate_delivery_button": [
        "//li[contains(@class,'ak-dropdown-item') and @data-auth='auth-item'][.//span[normalize-space(.)='生成发货单']]",
        "//span[normalize-space(.)='生成发货单']/ancestor::li[contains(@class,'ak-dropdown-item')]",
    ],
}
