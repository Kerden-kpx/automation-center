# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Browser driver management - Playwright startup, CDP connection, environment initialization.

Usage:
    from core.browser import BrowserDriver

    driver = BrowserDriver(headless=False, use_cdp=True)
    with driver.session() as page:
        page.goto("https://example.com")
        # ... automation logic
"""

from __future__ import annotations

import os
import json
import socket
import sys
import time
from contextlib import contextmanager
from typing import Generator, Optional
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


class BrowserDriver:
    """Unified browser session management with CDP and headless support."""

    def __init__(
        self,
        headless: bool = False,
        use_cdp: bool = True,
        cdp_endpoint: str = "http://127.0.0.1:9222",
        cdp_timeout_sec: int = 10,
    ):
        """
        Initialize the browser driver.

        Args:
            headless: Run browser in headless mode (no visible window).
            use_cdp: Connect to existing Chrome via CDP instead of launching new browser.
            cdp_endpoint: Chrome DevTools Protocol endpoint URL.
            cdp_timeout_sec: Timeout for waiting CDP connection to be ready.
        """
        self.headless = headless
        self.use_cdp = use_cdp
        self.cdp_endpoint = cdp_endpoint
        self.cdp_timeout_sec = cdp_timeout_sec

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._is_cdp_session = False

    def _wait_for_cdp_ready(self) -> bool:
        """Wait for CDP endpoint to become available."""
        host, port = self._get_cdp_host_port()
        deadline = time.time() + max(1, self.cdp_timeout_sec)
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=1):
                    return True
            except OSError:
                time.sleep(0.5)
        return False

    def _get_cdp_host_port(self) -> tuple[str, int]:
        """Parse host/port from CDP endpoint."""
        parsed = urlparse(self.cdp_endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9222
        return host, port

    def _cdp_http_base(self) -> str:
        parsed = urlparse(self.cdp_endpoint)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9222
        return f"{scheme}://{host}:{port}"

    def _find_chrome_path(self) -> Optional[str]:
        """Find Chrome/Chromium executable for current OS."""
        import shutil

        if os.name == "nt":
            candidates = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata:
                candidates.append(
                    os.path.join(local_appdata, "Google", "Chrome", "Application", "chrome.exe")
                )
            commands = ("chrome.exe", "chrome")
        elif sys.platform == "darwin":
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
            commands = ("google-chrome", "chromium")
        else:
            candidates = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/snap/bin/chromium",
            ]
            commands = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")

        for path in candidates:
            if os.path.exists(path):
                return path
        for cmd in commands:
            found = shutil.which(cmd)
            if found:
                return found
        return None

    def _start_chrome_debug(self) -> bool:
        """Start Chrome with remote debugging enabled."""
        import subprocess
        from .. import config

        chrome_path = self._find_chrome_path()
        if not chrome_path:
            return False

        user_data_dir = config.CHROME_USER_DATA_DIR
        os.makedirs(user_data_dir, exist_ok=True)
        _, port = self._get_cdp_host_port()

        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-automation",
        ]
        if os.name != "nt":
            args.append("--remote-debugging-address=127.0.0.1")
        try:
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception:
            return False

    def _connect_browser(self, playwright):
        """Connect to existing Chrome via CDP or launch a new Chromium."""
        from .. import config
        
        if self.use_cdp and not self.headless:
            try:
                # Try connecting first
                if not self._wait_for_cdp_ready():
                    if config.AUTO_START_CDP:
                        # Try to start chrome if connecting failed
                        if self._start_chrome_debug():
                            # Wait again for the newly started browser
                            if self._wait_for_cdp_ready():
                                browser = playwright.chromium.connect_over_cdp(self.cdp_endpoint)
                                return browser, True
                    
                    raise RuntimeError(
                        f"CDP 端点不可用: {self.cdp_endpoint}。"
                        "请先运行 Chrome 调试模式（chrome.exe --remote-debugging-port=9222）。"
                    )
                
                browser = playwright.chromium.connect_over_cdp(self.cdp_endpoint)
                return browser, True
            except Exception as exc:
                if "CDP 端点不可用" in str(exc):
                    raise exc
                # Fallback to launch if connection failed for other reasons
                pass

        browser = playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        return browser, False

    def ensure_cdp_and_target_page(
        self,
        target_url: str,
        *,
        startup_timeout_sec: int = 20,
    ) -> bool:
        """Ensure CDP browser is ready and target URL tab is present.

        Returns True if a new tab was opened, False if target tab already existed.
        """
        from .. import config

        if not self.use_cdp or self.headless:
            return False

        if not self._wait_for_cdp_ready():
            if config.AUTO_START_CDP and self._start_chrome_debug():
                deadline = time.time() + max(1, int(startup_timeout_sec))
                while time.time() < deadline:
                    if self._wait_for_cdp_ready():
                        break
                    time.sleep(0.5)
            if not self._wait_for_cdp_ready():
                raise RuntimeError(f"CDP endpoint unavailable: {self.cdp_endpoint}")

        try:
            with urlopen(f"{self._cdp_http_base()}/json/list", timeout=5) as resp:  # noqa: S310
                tabs = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if not isinstance(tabs, list):
                    tabs = []
        except Exception:
            tabs = []

        target_norm = (target_url or "").strip().lower()
        for tab in tabs:
            tab_url = str((tab or {}).get("url") or "").lower()
            if target_norm and target_norm in tab_url:
                return False
            if ("chatgpt.com" in tab_url) or ("chat.openai.com" in tab_url):
                return False

        open_url = f"{self._cdp_http_base()}/json/new?{quote(target_url, safe='')}"
        try:
            with urlopen(open_url, timeout=6):  # noqa: S310
                pass
        except Exception:
            req = Request(open_url, method="PUT")
            with urlopen(req, timeout=6):  # noqa: S310
                pass
        return True

    def _get_context(self, use_cdp: bool) -> BrowserContext:
        """Get or create browser context."""
        if use_cdp and self._browser.contexts:
            ctx = self._browser.contexts[0]
        else:
            ctx = self._browser.new_context(viewport=None)
        self._apply_stealth(ctx)
        return ctx

    @staticmethod
    def _apply_stealth(context: BrowserContext) -> None:
        """Apply stealth evasions via playwright-stealth or local fallback."""
        try:
            from playwright_stealth import Stealth
            Stealth(init_scripts_only=True).apply_stealth_sync(context)
            return
        except ImportError:
            pass
        except Exception:
            pass
        context.add_init_script(
            """
            // === 1. Core webdriver property ===
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            // Delete the property entirely from the prototype
            delete Object.getPrototypeOf(navigator).webdriver;

            // === 2. Languages & platform ===
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'platform', { get: () => 'Linux x86_64' });
            Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });

            // === 3. Plugins - mimic real Chrome plugins ===
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const arr = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
                    ];
                    arr.refresh = () => {};
                    Object.defineProperty(arr, 'length', { get: () => 3 });
                    return arr;
                }
            });
            Object.defineProperty(navigator, 'mimeTypes', {
                get: () => {
                    const arr = [
                        { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format', enabledPlugin: { name: 'Chrome PDF Plugin' } },
                    ];
                    arr.refresh = () => {};
                    Object.defineProperty(arr, 'length', { get: () => 1 });
                    return arr;
                }
            });

            // === 4. Chrome runtime object ===
            window.chrome = {
                app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
                runtime: { OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' }, OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' }, PlatformArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }, PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }, PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' }, RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }, connect: function() {}, sendMessage: function() {} },
                csi: function() { return {}; },
                loadTimes: function() { return {}; },
            };

            // === 5. Permissions API ===
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters)
            );

            // === 6. iframe contentWindow detection ===
            // Prevent detection via accessing contentWindow of dynamically created iframes
            try {
                const elementDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'contentWindow');
                // Only patch if not already patched
            } catch(e) {}

            // === 7. toString detection bypass ===
            // Make overridden functions look native
            const nativeToStringFunctionString = Error.toString().replace(/Error/g, 'toString');
            const originalFunctionToString = Function.prototype.toString;
            Object.defineProperty(Function.prototype, 'toString', {
                value: function() {
                    if (this === window.navigator.permissions.query) return 'function query() { [native code] }';
                    if (this === Function.prototype.toString) return 'function toString() { [native code] }';
                    return originalFunctionToString.call(this);
                }
            });

            // === 8. WebGL vendor/renderer ===
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Google Inc. (NVIDIA)';
                if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 6GB Direct3D11 vs_5_0 ps_5_0, D3D11)';
                return getParameter.call(this, parameter);
            };

            // === 9. Connection / hardware concurrency ===
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
            if (navigator.connection) {
                Object.defineProperty(navigator.connection, 'rtt', { get: () => 50 });
            }
            """
        )

    @staticmethod
    def _apply_stealth_page(page: Page) -> None:
        """Apply stealth evasions directly on a Page.

        This is called after new_page() to ensure CDP-attached pages are also
        patched — context-level init_scripts may not apply to pre-existing contexts.
        """
        try:
            from playwright_stealth import Stealth
            Stealth(init_scripts_only=True).apply_stealth_sync(page)
            return
        except ImportError:
            pass
        except Exception:
            pass
        # Minimal fallback: at least remove the webdriver flag
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            "try { delete Object.getPrototypeOf(navigator).webdriver; } catch(e) {}"
        )

    @contextmanager
    def session(self) -> Generator[Page, None, None]:
        """
        Context manager for a browser session.

        Yields:
            Playwright Page object for automation.
        """
        # Build the playwright context manager, optionally wrapped by Stealth.
        _stealth = None
        try:
            from playwright_stealth import Stealth
            _stealth = Stealth(init_scripts_only=True)
        except Exception:
            pass

        pw_ctx = sync_playwright()
        if _stealth is not None:
            try:
                pw_ctx = _stealth.use_sync(pw_ctx)
            except Exception:
                pass

        # Use __enter__/__exit__ so both plain SyncPlaywrightContextManager
        # and stealth's SyncWrappingContextManager (which has no .start()) work.
        self._playwright = pw_ctx.__enter__()
        page: Optional[Page] = None
        page_is_new = False
        try:
            self._browser, is_cdp = self._connect_browser(self._playwright)
            self._is_cdp_session = bool(is_cdp)
            self._context = self._get_context(is_cdp)

            if is_cdp:
                # Default to creating a dedicated visible tab in CDP mode.
                # Reusing an existing tab can make navigation look like "not opened"
                # when automation is running on a background tab.
                reuse_existing = (os.getenv("BROWSER_REUSE_CDP_TAB", "0") or "0").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
                if reuse_existing:
                    existing = [p for p in self._context.pages if not p.is_closed()]
                    if existing:
                        blank = [p for p in existing if p.url in ("about:blank", "chrome://newtab/", "")]
                        page = blank[0] if blank else existing[0]
                        page_is_new = False
                    else:
                        page = self._context.new_page()
                        page_is_new = True
                else:
                    page = self._context.new_page()
                    page_is_new = True
            else:
                page = self._context.new_page()
                page_is_new = True

            try:
                page.bring_to_front()
            except Exception:
                pass

            # Apply stealth directly on page to cover CDP-attached contexts.
            self._apply_stealth_page(page)
            yield page
        finally:
            # Only close the tab if we created it; never close human-opened tabs.
            if page_is_new:
                try:
                    if page is not None and not page.is_closed():
                        page.close()
                except Exception:
                    pass

            try:
                # In CDP mode we may be attached to a shared persistent context.
                # Closing it can terminate user tabs/extensions unexpectedly.
                if self._context and not self._is_cdp_session:
                    self._context.close()
            except Exception:
                pass
            try:
                # Same rule for the browser process: only close browsers we launched.
                if self._browser and not self._is_cdp_session:
                    self._browser.close()
            except Exception:
                pass
            try:
                pw_ctx.__exit__(None, None, None)
            except Exception:
                pass


    def maximize_window(self, page: Page) -> None:
        """Best-effort maximize for headed Chromium."""
        try:
            cdp = page.context.new_cdp_session(page)
            window_info = cdp.send("Browser.getWindowForTarget")
            window_id = window_info.get("windowId")
            if window_id is None:
                return
            cdp.send(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": {"windowState": "maximized"}},
            )
            page.wait_for_timeout(300)
        except Exception:
            pass
