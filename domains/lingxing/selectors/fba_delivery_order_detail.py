# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Selectors for LingXing FBA delivery order detail."""

from __future__ import annotations

FBA_DELIVERY_ORDER_SELECTORS = {
    # FBA-发货单-发货单详情-编辑按钮
    "edit_button": [
        '//button[contains(@class,"el-button")][.//div[contains(translate(normalize-space(.), " ", ""), "编辑")]]',
        '//button[@class="el-button el-button--primary el-button--small is-round out-btn single-btn undefined "]',
        '//button[@data-auth="auth-button" and contains(@class,"el-button")]'
        '[contains(translate(normalize-space(.), " ", ""), "编辑")]',
        '//button[contains(@class,"el-button")]'
        '[contains(translate(normalize-space(.), " ", ""), "编辑")]',
    ],
    # FBA-发货单-发货单详情-编辑页面-确定按钮
    "confirm_button": [
        '//button[@class="el-button ak-width-100 el-button--primary el-button--small is-round"]',
    ],
    # FBA-发货单-发货单详情-上传按钮
    "upload_button": [
        '//button[@class="el-button el-button--text el-button--mini is-round is-icon"]',
    ],
    # 装箱信息选项卡
    "packing_info_tab": [
        '//*[@id="tab-装箱信息"]',
    ],
    # 获取货件装箱按钮 (通过按钮内文本定位)
    "get_shipment_packing_btn": [
        '//button[.//span[contains(text(),"获取货件装箱")]]',
        '//span[contains(text(),"获取货件装箱")]/parent::button',
        '//*[contains(@class, "packingInformation-formBox")]/button[4]',  # 备选
    ],
    # 获取货件装箱确定按钮 (primary 按钮 + 确定文本)
    "get_shipment_packing_confirm_btn": [
        '//button[contains(@class,"el-button--primary")][.//span[contains(text(),"确定")]]',
        '//button[.//span[contains(text(),"确定")]]',
        '//*[@id="undefined"]//div/div/div[3]/span/button[2]',  # 兜底
    ],
    # 获取货件装箱成功提示
    "get_shipment_packing_success_msg": [
        '//p[contains(@class,"el-message__content")][contains(normalize-space(.),"获取货件装箱数据成功")]',
        '//div[contains(@class,"el-message")]//p[contains(@class,"el-message__content")][contains(normalize-space(.),"获取货件装箱数据成功")]',
    ],
    # 下载装箱清单模板按钮
    "packing_template_download_button": [
        '//button[contains(@class,"el-button")][.//span[contains(normalize-space(.),"下载装箱清单模板")]]',
    ],
    # 装箱清单模板上传输入框
    "packing_template_upload_input": [
        '//button[contains(@class,"upload-btn")][.//span[contains(normalize-space(.),"上传")]]/following-sibling::input[@type="file"]',
        '//button[contains(@class,"el-button")][.//span[contains(normalize-space(.),"上传")]]/following-sibling::input[@type="file"]',
        '//div[contains(@class,"el-upload")]//input[@type="file"]',
    ],
    # 表格空态/行（用于等待加载完成）
    "vxe_table_rows": [
        '//table[contains(@class,"vxe-table--body")]//tr[contains(@class,"vxe-body--row")]',
    ],
    "vxe_table_empty": [
        '//div[contains(@class,"vxe-table--empty-block")]',
        '//*[contains(@class,"vxe-table--empty-text")][contains(normalize-space(.),"暂无数据")]',
    ],
    # 发货量 (class="total-num" 的 span，内容格式: 945 (945))
    "shipment_quantity": [
        '//span[contains(@class,"total-num")]',
        '//*[contains(@class, "ak-modal-table-sum")]/span[3]',  # 兜底
    ],
    # 物流信息选项卡
    "logistics_info_tab": [
        '//*[@id="tab-物流信息"]',
    ],
    # 物流商单号输入框 (maxlength="30", 在 el-tooltip 容器内)
    "logistics_number_input": [
        '//div[contains(@class, "el-form-item__content")]//input[@maxlength="30"]',
        '//div[contains(@class, "el-tooltip")]//input[@class="el-input__inner"][@maxlength="30"]',
        '//input[@class="el-input__inner"][@maxlength="30"]',
    ],
    # 查询单号输入框 (maxlength="255", 在 vxe-cell 容器内)
    "tracking_number_input": [
        '//*[@id="pane-物流信息"]//tr[contains(@class,"vxe-body--row")]//td[2]//input[@maxlength="255"]',
        '//td[contains(@class, "vxe-body--column")]//input[@class="el-input__inner"][@maxlength="255"]',
        '(//tr[contains(@class,"vxe-body--row")]//td[2]//input[@maxlength="255"])[1]',
    ],
    # 运输方式（readonly select 显示值）
    "transport_mode_value": [
        '//div[contains(@class,"el-form-item")][.//label[contains(normalize-space(.),"运输方式")] or .//div[contains(@class,"el-form-item__label")][contains(normalize-space(.),"运输方式")]]//span[contains(@class,"fake-placeholder-hidden") or contains(@class,"fake-select-label")]',
        '//div[contains(@class,"el-form-item")][.//label[contains(normalize-space(.),"运输方式")] or .//div[contains(@class,"el-form-item__label")][contains(normalize-space(.),"运输方式")]]//input[@readonly]',
    ],
    # 物流渠道（readonly select 显示值）
    "logistics_channel_value": [
        '//div[contains(@class,"el-form-item")][.//label[contains(normalize-space(.),"物流渠道")] or .//div[contains(@class,"el-form-item__label")][contains(normalize-space(.),"物流渠道")]]//span[contains(@class,"fake-placeholder-hidden") or contains(@class,"fake-select-label")]',
        '//div[contains(@class,"el-form-item")][.//label[contains(normalize-space(.),"物流渠道")] or .//div[contains(@class,"el-form-item__label")][contains(normalize-space(.),"物流渠道")]]//input[@readonly]',
    ],
    # 物流商（readonly select 显示值，排除“物流商单号”）
    "logistics_provider_value": [
        '//div[contains(@class,"el-form-item")][.//*[contains(@class,"el-form-item__label")][contains(normalize-space(.),"物流商") and not(contains(normalize-space(.),"单号"))] or .//label[contains(normalize-space(.),"物流商") and not(contains(normalize-space(.),"单号"))]]//span[contains(@class,"fake-placeholder-hidden") or contains(@class,"fake-select-label")]',
        '//div[contains(@class,"el-form-item")][.//*[contains(@class,"el-form-item__label")][contains(normalize-space(.),"物流商") and not(contains(normalize-space(.),"单号"))] or .//label[contains(normalize-space(.),"物流商") and not(contains(normalize-space(.),"单号"))]]//input[@readonly]',
    ],
    # 运输方式/物流渠道/物流商 选择框触发器
    "transport_mode_select": [
        '//div[contains(@class,"el-form-item")][.//label[contains(normalize-space(.),"运输方式")] or .//div[contains(@class,"el-form-item__label")][contains(normalize-space(.),"运输方式")]]//div[contains(@class,"el-select")]//input',
    ],
    "logistics_channel_select": [
        '//div[contains(@class,"el-form-item")][.//label[contains(normalize-space(.),"物流渠道")] or .//div[contains(@class,"el-form-item__label")][contains(normalize-space(.),"物流渠道")]]//div[contains(@class,"el-select")]//input',
    ],
    "logistics_provider_select": [
        '//div[contains(@class,"el-form-item")][.//*[contains(@class,"el-form-item__label")][contains(normalize-space(.),"物流商") and not(contains(normalize-space(.),"单号"))] or .//label[contains(normalize-space(.),"物流商") and not(contains(normalize-space(.),"单号"))]]//div[contains(@class,"el-select")]//input',
    ],

    # 装箱信息全选框
    "packing_select_all": [
        "//span[contains(@class,'vxe-cell--checkbox') and @title='全选/取消']",
        "//span[contains(@class,'vxe-cell--checkbox')][@title='全选/取消']/ancestor::span[contains(@class,'vxe-cell--title')]",
    ],
    # 更新箱子信息按钮
    "packing_update_box_button": [
        "//button[@data-auth='auth-button' and .//span[normalize-space(.)='更新箱子信息']]",
        "//span[normalize-space(.)='更新箱子信息']/ancestor::button",
    ],
    # 更新箱子信息确认按钮
    "packing_confirm_button": [
        "//button[@data-auth='auth-button' and contains(@class,'el-button--primary') and .//span[normalize-space(.)='确定']]",
        "//span[normalize-space(.)='确定']/ancestor::button[contains(@class,'el-button--primary')]",
    ],
    # 物流商选项（北京世纪卓越快递服务有限公司（龙舟））
    "logistics_provider_option": [
        "//li[contains(@class,'el-select-dropdown__item')][.//span[contains(normalize-space(.),'北京世纪卓越快递服务有限公司（龙舟）')]]",
        "//span[contains(normalize-space(.),'北京世纪卓越快递服务有限公司（龙舟）')]/ancestor::li[contains(@class,'el-select-dropdown__item')]",
    ],
    # 物流渠道选项（美国快船）
    "logistics_channel_option": [
        "//li[contains(@class,'el-select-dropdown__item')][.//span[contains(normalize-space(.),'美国快船')]]",
        "//span[contains(normalize-space(.),'美国快船')]/ancestor::li[contains(@class,'el-select-dropdown__item')]",
    ],
    # 运输方式“海派”选项
    "transport_type_option_sea": [
        "//li[contains(@class,'el-select-dropdown__item')][.//span[contains(normalize-space(.),'海派')]]",
        "//span[contains(normalize-space(.),'海派')]/ancestor::li[contains(@class,'el-select-dropdown__item')]",
    ],
    # 发货仓库选择框
    "shipment_warehouse_select": [
        "//span[contains(@class,'fake-placeholder-hidden')][contains(normalize-space(.),'余杭新仓库')]/ancestor::div[contains(@class,'el-input')]//input[@readonly]",
        "//div[contains(@class,'el-input') and contains(@class,'el-input--prefix')]//input[@readonly]",
    ],
    # 发货仓库选项（杭州虚拟仓）
    "shipment_warehouse_option_hz_virtual": [
        "//li[contains(@class,'el-select-dropdown__item')][.//span[contains(normalize-space(.),'杭州虚拟仓')]]",
        "//span[contains(normalize-space(.),'杭州虚拟仓')]/ancestor::li[contains(@class,'el-select-dropdown__item')]",
        "//p[contains(@class,'ak-align-center')][.//span[contains(normalize-space(.),'杭州虚拟仓')]]/ancestor::li[contains(@class,'el-select-dropdown__item')]",
    ],
}
