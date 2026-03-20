# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SellerSprite automation flows."""

__all__ = [
    "SellerSpritePortal",
    "login_sellersprite_from_env",
    "login_and_query_sellersprite_from_env",
    "login_query_and_export_sellersprite_from_env",
]


def __getattr__(name: str):
    if name in __all__:
        from . import sellersprite_ccp as _ccp

        return getattr(_ccp, name)
    raise AttributeError(name)
