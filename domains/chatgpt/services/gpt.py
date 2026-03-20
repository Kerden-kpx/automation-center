#!/usr/bin/python3
"""GPT 网页自动化（Playwright）模块 - 已搬迁至 Services 包。"""

import asyncio
import base64
import os
from playwright.async_api import async_playwright, Page, Locator

# ========== 常量定义 ==========
MAX_WAIT_FOR_RESPONSE = 120  # 最多等待响应时间（秒）
CHECK_INTERVAL = 0.5  # 检查间隔（秒）
INPUT_CHECK_INTERVAL = 2  # 输入框检查间隔（秒）
STOP_BUTTON_WAIT_TIMEOUT = 10000  # 等待停止按钮出现的超时时间（毫秒）
INPUT_BOX_WAIT_TIMEOUT = 10000  # 等待输入框出现的超时时间（毫秒）
SEND_BUTTON_WAIT_TIMEOUT = 5000  # 等待发送按钮出现的超时时间（毫秒）
RESPONSE_LOCATOR_WAIT_TIMEOUT = 10000  # 等待响应定位器的超时时间（毫秒）

# XPath 选择器
INPUT_XPATH = '//div[@id="prompt-textarea"]'
SEND_BUTTON_XPATH = '//form//button[@data-testid="send-button"]'
STOP_BUTTON_XPATH = '//form//button[@data-testid="stop-button"]'
RESPONSE_XPATH = '(//article[starts-with(@data-testid, "conversation-turn")]//div[contains(@class, "text-message")][@data-message-author-role="assistant"]/div)[last()]'
ALL_ARTICLES_XPATH = '//article[starts-with(@data-testid, "conversation-turn")]'
MESSAGE_XPATH = './/div[contains(@class, "text-message")][@data-message-author-role="assistant"]/div'

# 备选响应选择器
FALLBACK_RESPONSE_SELECTORS = [
    '[data-message-author-role="assistant"]:last-child',
    '.markdown:last-child',
    '[class*="message"]:last-child',
]
# 输入框备选选择器（优先保留标准 id）
INPUT_CANDIDATE_SELECTORS = [
    ("css", "#prompt-textarea"),
    ("xpath", INPUT_XPATH),
    ("css", '[data-testid="prompt-textarea"]'),
    ("css", 'textarea[data-testid="prompt-textarea"]'),
    ("css", 'div[contenteditable="true"][data-testid="prompt-textarea"]'),
    ("css", 'div[contenteditable="true"]#prompt-textarea'),
    ("css", 'div.ProseMirror[contenteditable="true"]'),
    ("css", 'div.ProseMirror#prompt-textarea'),
    ("css", 'div#prompt-textarea[data-virtualkeyboard="true"]'),
]
# ==============================


def _get_gpt_url() -> str:
    url = os.getenv("GPT_URL", "").strip()
    return url or "https://chatgpt.com"


async def _find_prompt_locator(gpt_page: Page, timeout_total: float = 15.0) -> Locator:
    """Try multiple selectors to find the GPT prompt input box."""
    deadline = asyncio.get_event_loop().time() + timeout_total
    last_err = None
    while asyncio.get_event_loop().time() < deadline:
        for kind, selector in INPUT_CANDIDATE_SELECTORS:
            locator = gpt_page.locator(f'xpath={selector}') if kind == "xpath" else gpt_page.locator(selector)
            try:
                target = locator.first
                await target.wait_for(state="visible", timeout=1500)
                try:
                    if await target.is_editable():
                        return target
                except Exception:
                    return target
            except Exception as exc:
                last_err = exc
                continue
        await asyncio.sleep(0.5)
    raise RuntimeError(f"无法找到GPT输入框，请确认已登录并停留在聊天页面: {last_err}")


async def _ensure_prompt_locator(gpt_page: Page, input_locator: Locator) -> Locator:
    try:
        await input_locator.wait_for(state="visible", timeout=1500)
        return input_locator
    except Exception:
        return await _find_prompt_locator(gpt_page, timeout_total=6.0)


def _normalize_prompt_text(text: str) -> str:
    if not text:
        return ""
    cleaned = (
        text.replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\ufeff", "")
        .strip()
    )
    if cleaned in {"询问任何问题", "Ask anything"}:
        return ""
    return cleaned


async def _get_prompt_text(gpt_page: Page, input_locator: Locator) -> str:
    text = ""
    try:
        text = await input_locator.inner_text()
    except Exception:
        text = ""
    if not text:
        try:
            text = await input_locator.evaluate("el => el.textContent || ''")
        except Exception:
            text = ""
    if not text:
        try:
            text = await gpt_page.evaluate(
                """() => {
                    const el = document.querySelector("#prompt-textarea");
                    if (!el) return "";
                    return el.textContent || "";
                }"""
            )
        except Exception:
            text = ""
    return _normalize_prompt_text(text)


async def _focus_prompt(gpt_page: Page, input_locator: Locator) -> Locator:
    input_locator = await _ensure_prompt_locator(gpt_page, input_locator)
    try:
        await input_locator.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        await input_locator.click(timeout=2000)
    except Exception:
        pass
    try:
        await input_locator.evaluate("el => el.focus()")
    except Exception:
        try:
            input_locator = await _ensure_prompt_locator(gpt_page, input_locator)
            await input_locator.evaluate("el => el.focus()")
        except Exception:
            pass
    return input_locator


async def _clear_prompt(gpt_page: Page, input_locator: Locator) -> Locator:
    for _ in range(3):
        input_locator = await _focus_prompt(gpt_page, input_locator)
        for combo in ("Control+A", "Meta+A"):
            try:
                await gpt_page.keyboard.press(combo)
                await gpt_page.keyboard.press("Backspace")
                break
            except Exception:
                continue
        try:
            await input_locator.evaluate(
                """el => {
                    el.innerHTML = "";
                    const p = document.createElement("p");
                    const br = document.createElement("br");
                    p.appendChild(br);
                    el.appendChild(p);
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                }"""
            )
        except Exception:
            try:
                input_locator = await _ensure_prompt_locator(gpt_page, input_locator)
                await input_locator.evaluate(
                    """el => {
                        el.innerHTML = "";
                        const p = document.createElement("p");
                        const br = document.createElement("br");
                        p.appendChild(br);
                        el.appendChild(p);
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                    }"""
                )
            except Exception:
                pass
        await asyncio.sleep(0.1)
        if not await _get_prompt_text(gpt_page, input_locator):
            return input_locator
    return input_locator


async def _wait_for_response_completion(
    stop_button_locator: Locator,
    input_locator: Locator,
    content: str,
    max_wait: float = MAX_WAIT_FOR_RESPONSE,
    check_interval: float = CHECK_INTERVAL,
) -> float:
    """等待GPT响应完成（停止按钮消失）。"""
    waited = 0.0
    last_input_check = 0.0
    try:
        is_visible = await stop_button_locator.is_visible()
        if is_visible:
            while waited < max_wait:
                try:
                    is_visible = await stop_button_locator.is_visible()
                    if not is_visible:
                        break
                    if waited - last_input_check >= INPUT_CHECK_INTERVAL:
                        try:
                            current_input = await input_locator.inner_text()
                            if current_input.strip() == content.strip() and is_visible:
                                await input_locator.evaluate('el => el.innerText = ""')
                        except:
                            pass
                        last_input_check = waited
                except:
                    break
                await asyncio.sleep(check_interval)
                waited += check_interval
        else:
            await asyncio.sleep(2)
            try:
                is_visible = await stop_button_locator.is_visible()
                if is_visible:
                    while waited < max_wait:
                        try:
                            is_visible = await stop_button_locator.is_visible()
                            if not is_visible:
                                break
                        except:
                            break
                        await asyncio.sleep(check_interval)
                        waited += check_interval
            except:
                await asyncio.sleep(3)
    except:
        await asyncio.sleep(5)
    return waited


async def _extract_response_text(gpt_page: Page) -> str:
    """从GPT页面提取最后一个助手消息的文本。"""
    response_text = ""
    try:
        response_locator = gpt_page.locator(f'xpath={RESPONSE_XPATH}')
        await response_locator.wait_for(state='visible', timeout=RESPONSE_LOCATOR_WAIT_TIMEOUT)
        response_text = await response_locator.inner_text()
    except Exception:
        try:
            articles = await gpt_page.query_selector_all(f'xpath={ALL_ARTICLES_XPATH}')
            if articles:
                last_article = articles[-1]
                message_elements = await last_article.query_selector_all(f'xpath={MESSAGE_XPATH}')
                if message_elements:
                    response_text = await message_elements[-1].inner_text()
        except:
            pass
        if not response_text.strip():
            for selector in FALLBACK_RESPONSE_SELECTORS:
                try:
                    elements = await gpt_page.query_selector_all(selector)
                    if elements:
                        response_text = await elements[-1].inner_text()
                        if response_text.strip():
                            break
                except:
                    continue
    if not response_text.strip():
        raise RuntimeError(f"无法提取GPT响应内容。尝试的选择器: {RESPONSE_XPATH}")
    return response_text.strip()


async def _wait_for_gpt_ready(stop_button_locator: Locator, max_wait: float = MAX_WAIT_FOR_RESPONSE) -> None:
    try:
        is_responding = await stop_button_locator.is_visible()
        if is_responding:
            check_interval = CHECK_INTERVAL
            waited = 0.0
            while waited < max_wait:
                try:
                    is_responding = await stop_button_locator.is_visible()
                    if not is_responding:
                        await asyncio.sleep(1)
                        break
                except:
                    await asyncio.sleep(1)
                    break
                await asyncio.sleep(check_interval)
                waited += check_interval
            if waited >= max_wait:
                raise RuntimeError("GPT正在响应中，等待超时。请稍后再试。")
    except RuntimeError:
        raise
    except:
        pass


async def _set_input_content(gpt_page: Page, input_locator: Locator, content: str) -> Locator:
    """Set content into the GPT prompt box, preserving formatting when possible."""
    input_locator = await _clear_prompt(gpt_page, input_locator)
    input_locator = await _focus_prompt(gpt_page, input_locator)

    inserted = False
    try:
        await gpt_page.keyboard.insertText(content)
        inserted = True
    except Exception:
        pass

    if not inserted:
        try:
            await input_locator.fill(content, timeout=3000, force=True)
            inserted = True
        except Exception:
            pass

    if not inserted:
        try:
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if line:
                    await gpt_page.keyboard.insertText(line)
                if idx < len(lines) - 1:
                    await gpt_page.keyboard.press("Shift+Enter")
            inserted = True
        except Exception:
            pass

    if not inserted:
        try:
            input_locator = await _ensure_prompt_locator(gpt_page, input_locator)
            await input_locator.evaluate(
                """(el, value) => {
                    el.focus();
                    el.innerHTML = "";
                    const parts = value.split("\\n");
                    parts.forEach((part, i) => {
                        el.appendChild(document.createTextNode(part));
                        if (i < parts.length - 1) {
                            el.appendChild(document.createElement("br"));
                        }
                    });
                    el.dispatchEvent(new Event("input", { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                }""",
                content,
                timeout=5000,
            )
        except Exception as exc:
            # Final fallback: query DOM directly without waiting on a locator.
            try:
                wrote = await gpt_page.evaluate(
                    """(value) => {
                        const el =
                            document.querySelector("#prompt-textarea") ||
                            document.querySelector('[data-testid="prompt-textarea"]') ||
                            document.querySelector('div[contenteditable="true"]');
                        if (!el) return false;
                        el.focus();
                        el.innerHTML = "";
                        const parts = value.split("\\n");
                        parts.forEach((part, i) => {
                            el.appendChild(document.createTextNode(part));
                            if (i < parts.length - 1) {
                                el.appendChild(document.createElement("br"));
                            }
                        });
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                        return true;
                    }""",
                    content,
                )
                if not wrote:
                    raise RuntimeError("找不到可写入的GPT输入框")
            except Exception as exc2:
                raise RuntimeError(f"无法写入GPT输入框: {exc}") from exc2
    return input_locator


async def _send_message_to_gpt(
    gpt_page: Page,
    input_locator: Locator,
    content: str,
) -> bool:
    """向GPT发送消息。"""
    input_locator = await _set_input_content(gpt_page, input_locator, content)
    await asyncio.sleep(0.3)
    try:
        send_button = gpt_page.locator(f'xpath={SEND_BUTTON_XPATH}')
        await send_button.wait_for(state='visible', timeout=SEND_BUTTON_WAIT_TIMEOUT)
        is_enabled = await send_button.is_enabled()
        if is_enabled:
            await send_button.click()
            await asyncio.sleep(0.5)
            return True
        else:
            raise RuntimeError("发送按钮被禁用，GPT可能正在响应中")
    except Exception as e:
        if "发送按钮被禁用" in str(e):
            raise
        try:
            is_disabled = await input_locator.is_disabled()
            if is_disabled:
                raise RuntimeError("输入框被禁用，GPT可能正在响应中，不应发送新消息")
        except RuntimeError:
            raise
        except Exception:
            pass
        await input_locator.press("Enter")
        await asyncio.sleep(0.5)
        return True


async def send_to_gpt_and_get_response(
    content: str, cdp_url: str = "http://localhost:9222"
) -> tuple[str, str | None]:
    """连接到已打开的Chrome浏览器，发送内容到GPT并获取响应。"""
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
    except Exception as e:
        raise ConnectionError(
            f"无法连接到Chrome浏览器 ({cdp_url})。请确保Chrome以调试模式启动：chrome --remote-debugging-port=9222"
        ) from e

    try:
        gpt_url = _get_gpt_url()
        gpt_page = None
        contexts = browser.contexts
        if contexts:
            for ctx in contexts:
                for page in ctx.pages:
                    page_url = page.url or ""
                    if gpt_url and gpt_url in page_url:
                        gpt_page = page
                        break
                    if ("chat.openai.com" in page_url) or ("chatgpt.com" in page_url):
                        gpt_page = page
                        break
                if gpt_page:
                    break
        target_ctx = contexts[0] if contexts else await browser.new_context()
        input_locator = None
        if gpt_page:
            try:
                await gpt_page.bring_to_front()
            except Exception:
                pass
            try:
                input_locator = await _find_prompt_locator(gpt_page, timeout_total=3.0)
            except Exception:
                input_locator = None
        if not gpt_page or input_locator is None:
            gpt_page = await target_ctx.new_page()
            await gpt_page.goto(gpt_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            try:
                input_locator = await _find_prompt_locator(
                    gpt_page, timeout_total=INPUT_BOX_WAIT_TIMEOUT / 1000
                )
            except Exception as e:
                current_url = ""
                try:
                    current_url = gpt_page.url
                except Exception:
                    pass
                raise RuntimeError(f"无法找到GPT输入框: {e}. 当前URL: {current_url}")
        stop_button_locator = gpt_page.locator(f'xpath={STOP_BUTTON_XPATH}')
        await _wait_for_gpt_ready(stop_button_locator)
        await _send_message_to_gpt(gpt_page, input_locator, content)
        try:
            await stop_button_locator.wait_for(state='visible', timeout=STOP_BUTTON_WAIT_TIMEOUT)
        except:
            try:
                is_disabled = await input_locator.is_disabled()
                if not is_disabled:
                    current_content = await input_locator.inner_text()
                    if current_content.strip() == content.strip():
                        raise RuntimeError("消息可能未成功发送，但为避免重复发送，停止处理")
            except RuntimeError:
                raise
            except:
                pass
        waited = await _wait_for_response_completion(
            stop_button_locator, input_locator, content
        )
        if waited >= MAX_WAIT_FOR_RESPONSE:
            raise TimeoutError("等待GPT响应超时")
        await asyncio.sleep(1)
        response_text = await _extract_response_text(gpt_page)
        screenshot_b64 = None
        try:
            response_locator = gpt_page.locator(f'xpath={RESPONSE_XPATH}')
            png_bytes = await response_locator.screenshot(type="png")
            screenshot_b64 = base64.b64encode(png_bytes).decode("utf-8")
        except:
            pass
        return response_text, screenshot_b64
    finally:
        await browser.close()
        await playwright.stop()


