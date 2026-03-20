# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""LingXing shipment plan automation (生成发货单)."""

from __future__ import annotations

import re
from typing import Dict, Iterable, Optional
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import Page

from core.browser.interaction import (
    click_first_visible,
    fill_first,
    human_pause,
    wait_for_any_selector,
    wait_for_stability,
)
from ..selectors.fba_shipment_plan import FBA_SHIPMENT_PLAN_SELECTORS
from ..selectors.fba_delivery_order_detail import FBA_DELIVERY_ORDER_SELECTORS
from ... import config


class LingXingShipmentPlanPortal:
    def __init__(self, page: Page, selectors: Optional[Dict[str, Iterable[str]]] = None):
        self.page = page
        self.selectors = selectors or FBA_SHIPMENT_PLAN_SELECTORS

    def _require(self, key: str) -> list[str]:
        value = self.selectors.get(key) or []
        if not value:
            raise RuntimeError(f"领星发货计划页面缺少选择器: {key}")
        return list(value)

    def goto_plan_page(self) -> None:
        self.page.goto(config.LINGXING_SHIPMENT_PLAN_URL, wait_until="domcontentloaded", timeout=30000)
        wait_for_stability(self.page)

    def filter_by_plan_no(self, plan_no: str | list[str]) -> None:
        if isinstance(plan_no, (list, tuple)):
            plan_nos = [str(item).strip() for item in plan_no if str(item).strip()]
            plan_text = "\n".join(plan_nos)
        else:
            plan_text = str(plan_no).strip()
        if not plan_text:
            raise ValueError("缺少发货计划单号。")
        click_first_visible(self.page, self._require("plan_filter_select_input"))
        human_pause(200, 500)
        if "plan_filter_option_plan_no" in self.selectors:
            click_first_visible(self.page, self._require("plan_filter_option_plan_no"))
            human_pause(200, 500)
        click_first_visible(self.page, self._require("plan_multi_search_button"))
        human_pause(200, 500)
        fill_first(self.page, self._require("plan_multi_search_input"), plan_text)
        human_pause(200, 500)
        click_first_visible(self.page, self._require("plan_search_button"))
        wait_for_stability(self.page, timeout_ms=15000)

    def select_all_results(self) -> None:
        click_first_visible(self.page, self._require("plan_select_all_checkbox"))
        human_pause(300, 600)

    def generate_shipment(self) -> None:
        click_first_visible(self.page, self._require("plan_generate_button"))
        human_pause(300, 600)
        click_first_visible(self.page, self._require("plan_generate_delivery_button"))
        wait_for_stability(self.page, timeout_ms=15000)

    def open_packing_tab(self) -> None:
        selectors = FBA_DELIVERY_ORDER_SELECTORS.get("packing_info_tab", [])
        if not selectors:
            raise RuntimeError("缺少装箱信息 Tab 选择器。")
        click_first_visible(self.page, selectors)
        wait_for_stability(self.page)

    def update_box_info(self) -> None:
        selectors = FBA_DELIVERY_ORDER_SELECTORS.get("packing_select_all", [])
        if not selectors:
            raise RuntimeError("缺少装箱信息全选框选择器。")
        click_first_visible(self.page, selectors)
        human_pause(200, 400)
        selectors = FBA_DELIVERY_ORDER_SELECTORS.get("packing_update_box_button", [])
        if not selectors:
            raise RuntimeError("缺少更新箱子信息按钮选择器。")
        click_first_visible(self.page, selectors)
        human_pause(200, 400)
        selectors = FBA_DELIVERY_ORDER_SELECTORS.get("packing_confirm_button", [])
        if not selectors:
            raise RuntimeError("缺少更新箱子信息确认按钮选择器。")
        click_first_visible(self.page, selectors)
        wait_for_stability(self.page, timeout_ms=15000)

    def open_logistics_tab(self) -> None:
        selectors = FBA_DELIVERY_ORDER_SELECTORS.get("logistics_info_tab", [])
        if not selectors:
            raise RuntimeError("缺少物流信息 Tab 选择器。")
        click_first_visible(self.page, selectors)
        wait_for_stability(self.page)

    def set_logistics_for_sea_type(self, sea_type: str) -> None:
        if sea_type == "海卡":
            selectors = FBA_DELIVERY_ORDER_SELECTORS.get("logistics_provider_select", [])
            if not selectors:
                raise RuntimeError("缺少物流商选择框选择器。")
            click_first_visible(self.page, selectors)
            human_pause(200, 400)
            selectors = FBA_DELIVERY_ORDER_SELECTORS.get("logistics_provider_option", [])
            if not selectors:
                raise RuntimeError("缺少物流商选项选择器。")
            click_first_visible(self.page, selectors)
            human_pause(200, 400)
            selectors = FBA_DELIVERY_ORDER_SELECTORS.get("logistics_channel_select", [])
            if not selectors:
                raise RuntimeError("缺少物流渠道选择框选择器。")
            click_first_visible(self.page, selectors)
            human_pause(200, 400)
            selectors = FBA_DELIVERY_ORDER_SELECTORS.get("logistics_channel_option", [])
            if not selectors:
                raise RuntimeError("缺少物流渠道选项选择器。")
            click_first_visible(self.page, selectors)
        elif sea_type == "海派":
            selectors = FBA_DELIVERY_ORDER_SELECTORS.get("transport_mode_select", [])
            if not selectors:
                raise RuntimeError("缺少运输方式选择框选择器。")
            click_first_visible(self.page, selectors)
            human_pause(200, 400)
            selectors = FBA_DELIVERY_ORDER_SELECTORS.get("transport_type_option_sea", [])
            if not selectors:
                raise RuntimeError("缺少运输方式海派选项选择器。")
            click_first_visible(self.page, selectors)
        else:
            raise ValueError(f"未知运输方式: {sea_type}")

        human_pause(300, 600)
        selectors = FBA_DELIVERY_ORDER_SELECTORS.get("confirm_button", [])
        if not selectors:
            raise RuntimeError("缺少确认按钮选择器。")
        click_first_visible(self.page, selectors)
        wait_for_stability(self.page, timeout_ms=15000)

    def get_order_sn_from_url(self) -> str | None:
        url = self.page.url or ""
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if "order_sn" in query and query["order_sn"]:
            return query["order_sn"][0]
        match = re.search(r"order_sn=([A-Za-z0-9]+)", url)
        if match:
            return match.group(1)
        return None

    def wait_for_order_sn_from_url(self, timeout_ms: int = 20000) -> str:
        try:
            self.page.wait_for_url(
                lambda url: "DeliveryOrderDetail" in url and "order_sn=" in url,
                timeout=timeout_ms,
            )
        except Exception:
            pass
        wait_for_stability(self.page, timeout_ms=15000)
        order_sn = self.get_order_sn_from_url()
        if not order_sn:
            raise RuntimeError(f"未从URL获取到发货单号: {self.page.url}")
        return order_sn
