# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Browser client for SellerSprite UC/Selenium interactions."""

from __future__ import annotations

import time
from pathlib import Path

import yaml
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def _load_selectors() -> dict:
    selectors_path = Path(__file__).resolve().parents[1] / "selectors" / "sellersprite_ccp_selectors.yaml"
    if not selectors_path.exists():
        raise RuntimeError(f"Missing selectors YAML: {selectors_path}")
    with selectors_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid selectors YAML format: {selectors_path}")
    return data


class SellerSpriteBrowserClient:
    def __init__(self, driver, *, selectors: dict | None = None, logger=None) -> None:
        self.driver = driver
        self.selectors = selectors or _load_selectors()
        self.logger = logger or (lambda _message: None)

    def pause(self, min_s: float = 0.3, max_s: float = 0.9) -> None:
        import random

        time.sleep(random.uniform(min_s, max_s))

    def selector_xpaths(self, key: str) -> list[str]:
        raw = self.selectors.get(key, [])
        out: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.startswith("xpath="):
                out.append(item[len("xpath=") :])
        if not out:
            raise RuntimeError(f"选择器缺少 xpath 配置: {key}")
        return out

    def wait_first_interactable(self, xpaths: list[str], timeout: int = 20):
        wait = WebDriverWait(self.driver, timeout)

        def _probe(driver):
            for xp in xpaths:
                try:
                    elems = driver.find_elements(By.XPATH, xp)
                except Exception:
                    continue
                for elem in elems:
                    try:
                        if elem.is_displayed() and elem.is_enabled():
                            return elem
                    except Exception:
                        continue
            return False

        elem = wait.until(_probe)
        if not elem:
            raise RuntimeError("未找到可交互元素")
        return elem

    def first_present(self, xpaths: list[str], timeout: int = 20):
        wait = WebDriverWait(self.driver, timeout)
        last_exc: Exception | None = None
        for xp in xpaths:
            try:
                return wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            except Exception as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        raise RuntimeError("未找到可用选择器")

    def wait_present(self, key: str, timeout: int = 20):
        return self.first_present(self.selector_xpaths(key), timeout=timeout)

    def click(self, key: str, timeout: int = 20) -> None:
        elem = self.wait_first_interactable(self.selector_xpaths(key), timeout=timeout)
        self.pause()
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
        self.pause(0.1, 0.3)
        try:
            elem.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", elem)
        self.pause()

    def fill(self, key: str, value: str, timeout: int = 20) -> None:
        elem = self.wait_first_interactable(self.selector_xpaths(key), timeout=timeout)
        self.pause()
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
        try:
            elem.click()
        except Exception:
            self.driver.execute_script("arguments[0].focus();", elem)
        try:
            elem.send_keys(Keys.CONTROL, "a")
            elem.send_keys(Keys.DELETE)
            elem.send_keys(value)
        except Exception:
            self.driver.execute_script(
                """
                const el = arguments[0];
                const v = arguments[1];
                el.focus();
                el.value = '';
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.value = v;
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
                """,
                elem,
                value,
            )
        self.pause()

    def select_site(self, site: str, timeout: int = 20) -> None:
        site_code = (site or "US").strip().upper() or "US"
        site_label_map = {
            "US": "美国站",
            "JP": "日本站",
            "UK": "英国站",
            "GB": "英国站",
            "DE": "德国站",
            "FR": "法国站",
            "IT": "意大利",
            "ES": "西班牙",
            "CA": "加拿大",
            "IN": "印度站",
            "MX": "墨西哥",
        }
        site_label = site_label_map.get(site_code)
        if not site_label:
            raise RuntimeError(f"未配置 SellerSprite 站点映射: {site_code}")

        self.logger(f"UC 选择站点: {site_code} -> {site_label}")
        option_xpath = (
            "//ul[contains(@class,'el-select-dropdown__list')]"
            "//li[contains(@class,'el-select-dropdown__item')]"
            f"[.//span[contains(normalize-space(.), '{site_label}')]]"
        )

        option = None
        for attempt in range(3):
            try:
                self.click("site_select_input", timeout=10)
                option = self.wait_first_interactable([option_xpath], timeout=5)
                if option:
                    break
            except Exception:
                self.logger(f"UC 等待站点下拉框展开超时，重新点击 ({attempt + 1}/3)...")
                time.sleep(1.5)

        if not option:
            self.click("site_select_input", timeout=10)
            option = self.wait_first_interactable([option_xpath], timeout=timeout)

        self.pause(0.1, 0.3)
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", option)
        self.pause(0.1, 0.3)
        try:
            option.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", option)
        self.pause(0.5, 1.0)

    def has_any(self, key: str) -> bool:
        for xp in self.selector_xpaths(key):
            try:
                elems = self.driver.find_elements(By.XPATH, xp)
                for elem in elems:
                    try:
                        if elem.is_displayed():
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def has_interactable(self, key: str, timeout: int = 6) -> bool:
        try:
            self.wait_first_interactable(self.selector_xpaths(key), timeout=timeout)
            return True
        except Exception:
            return False

    def is_not_logged_in(self) -> bool:
        query_ready = self.has_interactable("competitor_query_input", timeout=5)
        if query_ready:
            return False

        cur = str(getattr(self.driver, "current_url", "") or "").lower()
        self.logger(f"UC 登录态检查: url={cur or '<empty>'}, query_ready={query_ready}")
        if "/user/login" in cur:
            return True

        return self.has_any("not_logged_in_badge")

    def read_user_name_text(self) -> str:
        try:
            elems = self.driver.find_elements(By.XPATH, "//div[contains(@class,'user-name')]")
        except Exception:
            return ""
        for elem in elems:
            try:
                if elem.is_displayed():
                    return str(elem.text or "").strip()
            except Exception:
                continue
        return ""

    def wait_login_ready(self, timeout_sec: int = 45) -> bool:
        deadline = time.time() + max(5, int(timeout_sec))
        while time.time() < deadline:
            if not self.is_not_logged_in():
                return True
            self.pause(0.8, 1.5)
        return False

    def wait_document_ready(self, timeout: int = 30) -> None:
        wait = WebDriverWait(self.driver, timeout)
        wait.until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))

    def safe_get(self, url: str, title: str = "", retries: int = 4, retry_delay: float = 3.0) -> None:
        target = (url or "").strip()
        if not target:
            raise RuntimeError("empty url")
        for attempt in range(1, max(1, retries) + 1):
            try:
                self.logger(f"UC 打开页面[{title or target}] 第 {attempt}/{retries} 次")
                self.driver.get(target)
                try:
                    self.wait_document_ready(timeout=15)
                except Exception:
                    pass

                cur = str(getattr(self.driver, "current_url", "")).lower()
                if "50x" in cur or "error" in cur:
                    self.logger(f"UC 页面被自动重定向到服务端 50x 错误页 ({cur})，休息 {retry_delay}s 重试...")
                    time.sleep(retry_delay)
                    continue

                try:
                    title_text = str(self.driver.title).lower()
                    if "502" in title_text or "503" in title_text or "gateway" in title_text:
                        self.logger(f"UC 检测到网页标题包含 50x 网关错误，休息 {retry_delay}s 重试...")
                        time.sleep(retry_delay)
                        continue
                except Exception:
                    pass

                return
            except TimeoutException:
                self.logger(f"UC 页面加载超时[{title or target}]，中断并重试 ({attempt}/{retries})")
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
                if attempt >= retries:
                    raise
                time.sleep(retry_delay)
