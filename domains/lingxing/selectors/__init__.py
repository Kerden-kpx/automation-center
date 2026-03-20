# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""LingXing selectors package."""

from .basic_settings import BASIC_SELECTORS
from .fba_delivery_order_detail import FBA_DELIVERY_ORDER_SELECTORS
from .logistics_add_customs_clearance import LOGISTICS_ADD_CUSTOMS_CLEARANCE_SELECTORS
from .logistics_managing_customs_clearance import LOGISTICS_CUSTOMS_MANAGEMENT_SELECTORS

__all__ = [
    "BASIC_SELECTORS",
    "FBA_DELIVERY_ORDER_SELECTORS",
    "LOGISTICS_ADD_CUSTOMS_CLEARANCE_SELECTORS",
    "LOGISTICS_CUSTOMS_MANAGEMENT_SELECTORS",
]
