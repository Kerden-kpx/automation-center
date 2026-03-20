# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""SellerSprite authentication service."""

from __future__ import annotations

from core import config as web_config


def ensure_logged_in(browser, account: str, password: str, log) -> None:
    browser.safe_get(web_config.SELLERSPRITE_COMPETITOR_LOOKUP_URL, title="竞品反查")
    browser.wait_document_ready()
    browser.pause(0.6, 1.2)

    if browser.is_not_logged_in():
        log("UC 检测到未登录，开始登录")
        browser.safe_get(web_config.SELLERSPRITE_LOGIN_URL, title="登录页")
        browser.wait_document_ready()
        browser.pause(0.8, 1.4)
        if browser.is_not_logged_in():
            browser.click("account_login_tab", timeout=20)
            browser.fill("account_input", account, timeout=20)
            browser.fill("password_input", password, timeout=20)
            browser.click("login_submit_button", timeout=20)
            log("UC 已提交登录，等待登录状态生效")
            if not browser.wait_login_ready(timeout_sec=45):
                name_text = browser.read_user_name_text()
                raise RuntimeError(f"登录提交后仍未生效，user-name={name_text or '<empty>'}")
        else:
            log("UC 登录页自动跳转后已恢复登录，跳过手动登录")

    browser.safe_get(web_config.SELLERSPRITE_COMPETITOR_LOOKUP_URL, title="竞品反查")
    browser.wait_document_ready()
    browser.pause(0.8, 1.5)
    if browser.is_not_logged_in():
        name_text = browser.read_user_name_text()
        raise RuntimeError(f"登录后仍检测到未登录状态，user-name={name_text or '<empty>'}")
