#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Amazon flows shared SellerSprite login helper."""

from __future__ import annotations

import os
import tempfile
import time
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import yaml
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from core.browser import click_first_visible, human_pause, wait_for_stability


def _load_sellersprite_login_selectors() -> Dict[str, List[str]]:
    selectors_path = (
        Path(__file__).resolve().parents[2]
        / "sellersprite"
        / "selectors"
        / "sellersprite_ccp_selectors.yaml"
    )
    if not selectors_path.exists():
        raise RuntimeError(f"Missing selectors YAML: {selectors_path}")
    with selectors_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid selectors YAML format: {selectors_path}")

    required_keys = [
        "account_login_tab",
        "account_input",
        "password_input",
        "login_submit_button",
        "asin_count_ready",
    ]
    out: Dict[str, List[str]] = {}
    for key in required_keys:
        value = data.get(key) or []
        if not isinstance(value, list):
            value = []
        out[key] = [str(item) for item in value if str(item).strip()]
    return out


SELLERSPRITE_LOGIN_SELECTORS = _load_sellersprite_login_selectors()


def _iter_contexts(page) -> List[Tuple[str, Any]]:
    contexts: List[Tuple[str, Any]] = [("page", page)]
    try:
        main_frame = page.main_frame
        for idx, frame in enumerate(page.frames):
            if frame == main_frame:
                continue
            frame_name = frame.name or f"frame_{idx}"
            contexts.append((f"frame:{frame_name}", frame))
    except Exception:
        pass
    return contexts


def _wait_for_any_selector_across_contexts(
    page, selectors: List[str], timeout_ms: int = 10000, visible_only: bool = False
) -> bool:
    deadline = time.time() + max(0.2, timeout_ms / 1000.0)
    while time.time() < deadline:
        for _, ctx in _iter_contexts(page):
            for selector in selectors:
                try:
                    locator = ctx.locator(selector)
                    count = locator.count()
                    if count <= 0:
                        continue
                    if not visible_only:
                        return True
                    for i in range(count):
                        try:
                            if locator.nth(i).is_visible():
                                return True
                        except Exception:
                            continue
                except Exception:
                    continue
        try:
            page.wait_for_timeout(250)
        except Exception:
            time.sleep(0.25)
    return False


def _click_first_visible_across_contexts(page, selectors: List[str], timeout_ms: int = 3000) -> bool:
    for _, ctx in _iter_contexts(page):
        try:
            if click_first_visible(ctx, selectors, timeout_ms=timeout_ms):
                human_pause(350, 700)
                return True
        except Exception:
            continue
    return False


def _click_account_login_tab_across_contexts(page, selectors: List[str], timeout_ms: int = 4500) -> bool:
    if _click_first_visible_across_contexts(page, selectors, timeout_ms=timeout_ms):
        return True

    for _, ctx in _iter_contexts(page):
        for selector in selectors:
            try:
                locator = ctx.locator(selector)
                count = locator.count()
                for i in range(count):
                    target = locator.nth(i)
                    try:
                        if not target.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        target.scroll_into_view_if_needed(timeout=1500)
                    except Exception:
                        pass
                    try:
                        target.click(timeout=2500, force=True)
                        human_pause(350, 700)
                        return True
                    except Exception:
                        try:
                            target.evaluate("el => el.click()")
                            human_pause(350, 700)
                            return True
                        except Exception:
                            continue
            except Exception:
                continue

    js_click = """
    () => {
      const candidates = Array.from(document.querySelectorAll('a,button,div,span,li'));
      for (const el of candidates) {
        const txt = (el.textContent || '').trim();
        if (!txt || !txt.includes('账号登录')) continue;
        const style = window.getComputedStyle(el);
        const hidden = style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0';
        const rect = el.getBoundingClientRect();
        if (hidden || rect.width <= 0 || rect.height <= 0) continue;
        try { el.scrollIntoView({block:'center'}); } catch(e) {}
        try { el.click(); return true; } catch(e) {}
      }
      return false;
    }
    """
    for _, ctx in _iter_contexts(page):
        try:
            if bool(ctx.evaluate(js_click)):
                human_pause(350, 700)
                return True
        except Exception:
            continue
    return False


def _fill_first_visible_across_contexts(
    page, selectors: List[str], value: str, log: Callable[[str], None], field_tag: str
) -> bool:
    last_err = ""
    for _, ctx in _iter_contexts(page):
        for selector in selectors:
            try:
                locator = ctx.locator(selector)
                count = locator.count()
                if count <= 0:
                    continue
                for i in range(count):
                    target = locator.nth(i)
                    if not target.is_visible():
                        continue
                    try:
                        target.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    try:
                        target.focus(timeout=2000)
                    except Exception:
                        pass
                    try:
                        target.click(timeout=2000)
                    except Exception:
                        pass
                    human_pause(180, 360)
                    try:
                        target.fill("")
                    except Exception:
                        pass
                    try:
                        target.fill(value, timeout=3000)
                        human_pause(500, 900)
                        return True
                    except Exception as exc:
                        last_err = f"{type(exc).__name__}: {exc}"
                        try:
                            target.press("Control+A", timeout=1200)
                            target.press("Backspace", timeout=1200)
                            target.type(value, delay=120, timeout=5000)
                            human_pause(500, 900)
                            return True
                        except Exception as exc2:
                            last_err = f"{type(exc2).__name__}: {exc2}"
                            try:
                                target.evaluate(
                                    """(el, v) => {
                                        el.removeAttribute('readonly');
                                        el.removeAttribute('disabled');
                                        el.focus();
                                        el.value = '';
                                        el.dispatchEvent(new Event('input', { bubbles: true }));
                                        el.value = v;
                                        el.dispatchEvent(new Event('input', { bubbles: true }));
                                        el.dispatchEvent(new Event('change', { bubbles: true }));
                                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                                    }""",
                                    value,
                                )
                                current = (target.input_value(timeout=1200) or "").strip()
                                if current:
                                    human_pause(500, 900)
                                    return True
                            except Exception as exc3:
                                last_err = f"{type(exc3).__name__}: {exc3}"
                                continue
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                continue
    if last_err:
        log(f"[调试][{field_tag}] 输入失败: {last_err}")
    else:
        log(f"[调试][{field_tag}] 输入失败: 未找到可见可编辑元素")
    return False


def _debug_selector_counts(page, selectors: List[str], tag: str, log: Callable[[str], None]) -> None:
    rows = []
    for ctx_name, ctx in _iter_contexts(page):
        for selector in selectors:
            try:
                count = ctx.locator(selector).count()
                if count > 0:
                    rows.append(f"{ctx_name} | {selector} | count={count}")
            except Exception:
                continue
    if rows:
        log(f"[调试][{tag}] 选择器命中如下:")
        for row in rows:
            log(f"[调试][{tag}] {row}")
    else:
        log(f"[调试][{tag}] 选择器命中: 无")


def _read_first_visible_text_across_contexts(page, selectors: List[str]) -> str:
    for _, ctx in _iter_contexts(page):
        for selector in selectors:
            try:
                locator = ctx.locator(selector)
                count = locator.count()
                if count <= 0:
                    continue
                for i in range(count):
                    target = locator.nth(i)
                    try:
                        if not target.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        text = (target.text_content(timeout=1000) or "").strip()
                    except Exception:
                        text = ""
                    if text:
                        return text
            except Exception:
                continue
    return ""


def _ensure_jimu_logged_in(page, log: Callable[[str], None]) -> None:
    jimu_login_button_selectors = [
        "button.ant-btn.ant-btn-primary.ant-btn-sm:has-text('登录')",
        "xpath=//button[contains(@class,'ant-btn-primary') and contains(@class,'ant-btn-sm') and .//span[normalize-space(.)='登录']]",
    ]
    jimu_mobile_tab_selectors = [
        "#rc-tabs-1-tab-mobile",
        "div.ant-tabs-tab-btn:has-text('手机登录')",
        "xpath=//div[@role='tab' and contains(normalize-space(.), '手机登录')]",
    ]
    jimu_account_input_selectors = [
        "input#mobile[placeholder='请输入手机号']",
        "xpath=//input[@id='mobile' and contains(@placeholder,'请输入手机号')]",
    ]
    jimu_password_input_selectors = [
        "input#pwd[placeholder='请输入密码']",
        "xpath=//input[@id='pwd' and contains(@placeholder,'请输入密码')]",
    ]
    jimu_submit_selectors = [
        ".ant-modal-root button.ant-btn.ant-btn-primary:has-text('登录')",
        "xpath=//div[contains(@class,'ant-modal-root')]//button[contains(@class,'ant-btn-primary') and .//span[normalize-space(.)='登录']]",
    ]

    if not _wait_for_any_selector_across_contexts(
        page, jimu_login_button_selectors, timeout_ms=3000, visible_only=True
    ):
        log("[初始化][J1] 未检测到极目登录按钮，跳过极目登录检查")
        return

    log("[初始化][J1] 检测到极目登录按钮，开始极目登录")
    if not _click_first_visible_across_contexts(page, jimu_login_button_selectors, timeout_ms=4000):
        _debug_selector_counts(page, jimu_login_button_selectors, "jimu_login_button", log)
        raise RuntimeError("点击极目登录按钮失败")

    if not _wait_for_any_selector_across_contexts(
        page, jimu_mobile_tab_selectors, timeout_ms=8000, visible_only=True
    ):
        _debug_selector_counts(page, jimu_mobile_tab_selectors, "jimu_mobile_tab", log)
        raise RuntimeError("极目登录弹窗未出现“手机登录”Tab")

    if not _click_first_visible_across_contexts(page, jimu_mobile_tab_selectors, timeout_ms=4000):
        raise RuntimeError("点击极目“手机登录”Tab失败")

    account = str(os.getenv("JIMU_ACCOUNT") or "").strip()
    password = str(os.getenv("JIMU_PASSWORD") or "").strip()
    if not account or not password:
        raise RuntimeError("缺少环境变量：JIMU_ACCOUNT / JIMU_PASSWORD")

    if not _fill_first_visible_across_contexts(
        page, jimu_account_input_selectors, account, log=log, field_tag="jimu_account_input"
    ):
        _debug_selector_counts(page, jimu_account_input_selectors, "jimu_account_input", log)
        raise RuntimeError("极目账号输入失败")

    if not _fill_first_visible_across_contexts(
        page, jimu_password_input_selectors, password, log=log, field_tag="jimu_password_input"
    ):
        _debug_selector_counts(page, jimu_password_input_selectors, "jimu_password_input", log)
        raise RuntimeError("极目密码输入失败")

    if not _click_first_visible_across_contexts(page, jimu_submit_selectors, timeout_ms=4000):
        _debug_selector_counts(page, jimu_submit_selectors, "jimu_submit_button", log)
        raise RuntimeError("点击极目登录提交按钮失败")
    human_pause(800, 1500)
    log("[初始化][J1][完成] 极目登录已提交")


def _notify_xiyou_qr_to_dingtalk(image_path: Path, log: Callable[[str], None]) -> None:
    try:
        from core.integrations.dingtalk_client import send_user_file, send_user_text
    except Exception as exc:
        log(f"[初始化][X1] 钉钉通知模块加载失败: {exc}")
        return

    raw_user_ids = (
        os.getenv("XIYOU_NOTIFY_USER_IDS", "").strip()
        or os.getenv("SCHEDULER_ALERT_USER_IDS", "").strip()
    )
    user_ids = [item.strip() for item in raw_user_ids.replace(";", ",").split(",") if item.strip()]
    if not user_ids:
        log("[初始化][X1] 未配置 XIYOU_NOTIFY_USER_IDS/SCHEDULER_ALERT_USER_IDS，跳过钉钉发送")
        return

    text = (
        "西柚找词检测到未登录，已发送登录二维码截图。"
        "请尽快扫码登录，脚本会等待登录完成后继续。"
    )
    for user_id in user_ids:
        try:
            send_user_text(user_id=user_id, text=text)
        except Exception as exc:
            log(f"[初始化][X1] 钉钉文本发送失败 user_id={user_id}: {exc}")
        try:
            send_user_file(user_id=user_id, file_path=str(image_path))
        except Exception as exc:
            log(f"[初始化][X1] 钉钉文件发送失败 user_id={user_id}: {exc}")


def _ensure_xiyou_logged_in(page, log: Callable[[str], None]) -> None:
    login_entry_selectors = [
        "span:has-text('点击登录')",
        "xpath=//span[contains(normalize-space(.), '点击登录')]",
    ]
    mobile_tab_selectors = [
        "#rc-tabs-1-tab-mobile",
        "div.ant-tabs-tab-btn:has-text('手机登录')",
        "xpath=//div[@role='tab' and contains(normalize-space(.), '手机登录')]",
    ]
    dialog_selectors = [
        ".ant-modal-root",
        ".ant-modal-content",
        "xpath=//div[contains(@class,'ant-modal-root') or contains(@class,'ant-modal-content')]",
    ]
    qr_selectors = [
        ".ant-modal-root .ant-qrcode canvas",
        ".ant-modal-root .ant-qrcode img",
        ".ant-modal-root img[src*='qr']",
        ".ant-modal-root img[src*='showqrcode']",
        ".ant-modal-root canvas",
    ]
    def _capture_and_notify_qr(prefix: str) -> bool:
        screenshot_path = Path(tempfile.gettempdir()) / f"{prefix}_{int(time.time())}.png"
        shot_ok = False
        for _, ctx in _iter_contexts(page):
            for selector in qr_selectors:
                try:
                    locator = ctx.locator(selector)
                    count = locator.count()
                    if count <= 0:
                        continue
                    target = locator.first
                    if not target.is_visible():
                        continue
                    target.screenshot(path=str(screenshot_path))
                    shot_ok = True
                    break
                except Exception:
                    continue
            if shot_ok:
                break
        if not shot_ok:
            for _, ctx in _iter_contexts(page):
                for selector in dialog_selectors:
                    try:
                        locator = ctx.locator(selector)
                        if locator.count() <= 0:
                            continue
                        target = locator.first
                        if not target.is_visible():
                            continue
                        target.screenshot(path=str(screenshot_path))
                        shot_ok = True
                        break
                    except Exception:
                        continue
                if shot_ok:
                    break
        if shot_ok and screenshot_path.exists():
            log(f"[初始化][X1] 西柚登录二维码已截图: {screenshot_path}")
            _notify_xiyou_qr_to_dingtalk(screenshot_path, log)
            return True
        log("[初始化][X1] 未能截图西柚登录二维码，跳过钉钉发送")
        return False

    if not _wait_for_any_selector_across_contexts(
        page, login_entry_selectors, timeout_ms=3000, visible_only=True
    ):
        log("[初始化][X1] 未检测到西柚找词“点击登录”，视为已登录")
        return

    log("[初始化][X1] 检测到西柚找词未登录，打开登录弹窗")
    if not _click_first_visible_across_contexts(page, login_entry_selectors, timeout_ms=4000):
        _debug_selector_counts(page, login_entry_selectors, "xiyou_login_entry", log)
        raise RuntimeError("点击西柚找词“点击登录”失败")

    if not _wait_for_any_selector_across_contexts(page, dialog_selectors, timeout_ms=10000, visible_only=True):
        _debug_selector_counts(page, dialog_selectors, "xiyou_login_dialog", log)
        raise RuntimeError("西柚找词登录弹窗未出现")

    if _wait_for_any_selector_across_contexts(page, mobile_tab_selectors, timeout_ms=5000, visible_only=True):
        _click_first_visible_across_contexts(page, mobile_tab_selectors, timeout_ms=4000)
        human_pause(300, 700)

    _capture_and_notify_qr("xiyou_login_qr")
    watch_since_ts = time.time()

    wait_sec = max(30, int(os.getenv("XIYOU_LOGIN_WAIT_SEC", "300") or "300"))
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if not _wait_for_any_selector_across_contexts(
            page, login_entry_selectors, timeout_ms=1200, visible_only=True
        ):
            log("[初始化][X1][完成] 西柚找词登录已生效")
            return
        backend_base = (
            os.getenv("SCHEDULER_BACKEND_API_BASE", "").strip()
            or "http://127.0.0.1:27643"
        ).rstrip("/")
        consume_url = f"{backend_base}/integrations/dingtalk/commands/consume"
        try:
            req_body = json.dumps(
                {"command_key": "xiyou_login", "since_ts": watch_since_ts},
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib.request.Request(
                consume_url,
                data=req_body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw) if raw else {}
            cmd = (data or {}).get("command") if isinstance(data, dict) else None
            if cmd:
                who = str((cmd or {}).get("user_id") or "").strip() or "unknown"
                log(f"[初始化][X1][完成] 收到钉钉指令“已登录”，来自: {who}")
                return
        except urllib.error.URLError:
            # backend unavailable: keep waiting for page-state login success
            pass
        except Exception as exc:
            log(f"[初始化][X1] 读取钉钉登录指令失败: {exc}")
        human_pause(2.0, 3.5)
    raise RuntimeError(f"等待西柚找词登录超时（{wait_sec}s）")


def _goto_with_fallback(page, url: str, timeout_ms: int) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        page.goto(url, wait_until="commit", timeout=max(timeout_ms, 60000))


def ensure_sellersprite_logged_in(
    page,
    *,
    first_url: str,
    log: Callable[[str], None],
    enabled: bool = True,
    ready_timeout_ms: int = 60000,
) -> None:
    if not enabled:
        return

    account = str(os.getenv("SELLERSPRITE_ACCOUNT") or "").strip()
    password = str(os.getenv("SELLERSPRITE_PASSWORD") or "").strip()
    if not account or not password:
        raise RuntimeError("缺少环境变量：SELLERSPRITE_ACCOUNT / SELLERSPRITE_PASSWORD")

    timeout_ms = int(page.timeout) if hasattr(page, "timeout") else 45000
    log("[初始化][S0] 打开首个目标页")
    _goto_with_fallback(page, first_url, timeout_ms=max(10000, timeout_ms))
    wait_for_stability(page)
    human_pause(600, 1200)
    log("[初始化][S0][完成] 首个目标页已打开")

    launcher_selectors = [
        "div.ss-name:has-text('卖家精灵')",
        "text=卖家精灵",
        "xpath=//div[contains(@class,'ss-name') and contains(normalize-space(.), '卖家精灵')]",
    ]
    log("[初始化][S1] 首个页面: 打开卖家精灵悬浮入口")
    if not _wait_for_any_selector_across_contexts(page, launcher_selectors, timeout_ms=15000):
        _debug_selector_counts(page, launcher_selectors, "sellersprite_launcher", log)
        log("[初始化][S1][警告] 未找到卖家精灵入口，跳过登录检查并继续")
        return
    if not _click_first_visible_across_contexts(page, launcher_selectors, timeout_ms=4000):
        _debug_selector_counts(page, launcher_selectors, "sellersprite_launcher", log)
        log("[初始化][S1][警告] 点击卖家精灵入口失败，跳过登录检查并继续")
        return
    log("[初始化][S1][完成] 已点击卖家精灵入口")
    human_pause(500, 900)

    tab_selectors = list(SELLERSPRITE_LOGIN_SELECTORS.get("account_login_tab", []))
    tab_selectors.extend(
        [
            "text=账号登录",
            "xpath=//div[contains(normalize-space(.), '账号登录')]",
            "xpath=//*[contains(@class,'tab') and contains(normalize-space(.), '账号登录')]",
        ]
    )
    account_selectors = SELLERSPRITE_LOGIN_SELECTORS.get("account_input", [])
    password_selectors = SELLERSPRITE_LOGIN_SELECTORS.get("password_input", [])
    submit_selectors = SELLERSPRITE_LOGIN_SELECTORS.get("login_submit_button", [])
    asin_count_ready_selectors = SELLERSPRITE_LOGIN_SELECTORS.get("asin_count_ready", [])
    user_name_selectors = [
        "span.hide-nickname-more",
        "xpath=//span[contains(@class,'hide-nickname-more')]",
    ]

    log("[初始化][S2] 检查登录面板/账号输入框")
    user_name = _read_first_visible_text_across_contexts(page, user_name_selectors)
    if user_name and user_name not in {"未登录"}:
        log(f"[初始化][S2] 检测到已登录用户名: {user_name}")
        assume_logged_in = True
        account_ready = False
    else:
        account_ready = _wait_for_any_selector_across_contexts(
            page, account_selectors, timeout_ms=3500, visible_only=True
        )
        assume_logged_in = False
    if not account_ready:
        if not assume_logged_in:
            log("[初始化][S2] 暂未看到账号输入框，尝试点击“账号登录”Tab")
            if not _wait_for_any_selector_across_contexts(page, tab_selectors, timeout_ms=15000, visible_only=True):
                log("[初始化][S2] 未出现“账号登录”Tab，判定当前已登录，跳过登录流程")
                _debug_selector_counts(page, tab_selectors, "account_login_tab", log)
                assume_logged_in = True
        clicked_tab = False
        if not assume_logged_in:
            for i in range(2):
                log(f"[初始化][S2] 点击“账号登录”Tab，第 {i + 1}/2 次")
                if _click_account_login_tab_across_contexts(page, tab_selectors, timeout_ms=4500):
                    clicked_tab = True
                    human_pause(700, 1200)
                    if _wait_for_any_selector_across_contexts(
                        page, account_selectors, timeout_ms=3000, visible_only=True
                    ):
                        account_ready = True
                        log("[初始化][S2][完成] 点击 Tab 后账号输入框已出现")
                        break
                    log("[初始化][S2] Tab 已点击，但账号输入框仍未出现")
                else:
                    log("[初始化][S2] Tab 点击未命中可见元素")
                human_pause(450, 850)
        if not clicked_tab:
            _debug_selector_counts(page, tab_selectors, "account_login_tab", log)
    else:
        log("[初始化][S2][完成] 账号输入框已可见")

    if assume_logged_in:
        log("[初始化][S3] 已登录判定成立，跳过账号密码输入")
    elif not account_ready and not _wait_for_any_selector_across_contexts(
        page, account_selectors, timeout_ms=5000, visible_only=True
    ):
        log("[初始化][S3] 未发现账号输入框，判定为已登录")
    else:
        log("[初始化][S3] 填写账号密码并提交登录")
        if not _fill_first_visible_across_contexts(
            page, account_selectors, account, log=log, field_tag="account_input"
        ):
            _debug_selector_counts(page, account_selectors, "account_input", log)
            raise RuntimeError("账号输入失败")
        log("[初始化][S3][完成] 账号已填写")
        human_pause(400, 800)

        if not _fill_first_visible_across_contexts(
            page, password_selectors, password, log=log, field_tag="password_input"
        ):
            _debug_selector_counts(page, password_selectors, "password_input", log)
            raise RuntimeError("密码输入失败")
        log("[初始化][S3][完成] 密码已填写")
        human_pause(500, 900)

        if not _click_first_visible_across_contexts(page, submit_selectors, timeout_ms=4000):
            _debug_selector_counts(page, submit_selectors, "login_submit_button", log)
            raise RuntimeError("点击登录按钮失败")
        log("[初始化][S3][完成] 已点击登录按钮")

        log("[初始化][S3] 登录后等待“ASIN数量”元素出现")
        if not _wait_for_any_selector_across_contexts(
            page, asin_count_ready_selectors, timeout_ms=max(5000, int(ready_timeout_ms)), visible_only=True
        ):
            _debug_selector_counts(page, asin_count_ready_selectors, "asin_count_ready", log)
            raise RuntimeError("登录后等待 ASIN数量 元素超时")
        log("[初始化][S3][完成] 已检测到“ASIN数量”元素")

    log("[初始化][S4] 卖家精灵登录步骤结束，重新打开首个页面")
    try:
        _goto_with_fallback(page, first_url, timeout_ms=max(10000, timeout_ms))
        wait_for_stability(page)
        human_pause(800, 1500)
        log("[初始化][S4][完成] 首个页面已重新打开")
    except Exception as exc:
        log(f"[初始化][S4][警告] 重新打开首个页面失败，继续后续流程: {exc}")

    _ensure_jimu_logged_in(page, log)
    # Temporarily disable Xiyou login check; keep code for easy re-enable.
    # _ensure_xiyou_logged_in(page, log)
