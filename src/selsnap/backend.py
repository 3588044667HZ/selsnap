from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any

from .actions import (
    CDP_KEY_DEFS,
    DOC_STATE_JS,
    MODIFIER_MASK,
    render_clear_ref_js,
    render_focus_ref_js,
    render_probe_js,
    render_scroll_by_js,
    render_scroll_ref_js,
    render_select_options_js,
    render_set_select_js,
    render_settle_js,
)
from .config import MODE_ORDER
from .errors import ToolError
from .snapshot import SNAPSHOT_JS, render_snapshot

CHALLENGE_JS = r"""
(() => {
  const body = document.body;
  const selectors = [
    "#challenge-form", ".cf-chl", ".cf-turnstile", "#cf-challenge-running",
    "iframe[src*='challenges.cloudflare.com']",
    "script[src*='challenge-platform']",
    "[id*='cf-challenge']", "[class*='cf-challenge']"
  ];
  const signals = [];
  for (const selector of selectors) {
    try { if (document.querySelector(selector)) signals.push(selector); } catch (error) {}
  }
  return {
    title: document.title || "",
    url: location.href,
    text: (body ? body.innerText : "").slice(0, 4000),
    signals: signals,
    ready: document.readyState
  };
})()
"""

POINT_JS = r"""
(() => {
  const X = __X_JSON__;
  const Y = __Y_JSON__;
  const vw = window.innerWidth || 0;
  const vh = window.innerHeight || 0;
  if (X < 0 || Y < 0 || X >= vw || Y >= vh) {
    return {in_viewport: false, x: X, y: Y, viewport_width: vw, viewport_height: vh};
  }
  const el = document.elementFromPoint(X, Y);
  if (!el) return {in_viewport: true, found: false, x: X, y: Y};
  return {
    in_viewport: true,
    found: true,
    x: X,
    y: Y,
    tag: el.tagName.toLowerCase(),
    ref: el.getAttribute("data-mcp-ref") || null,
    text: (el.innerText || "").slice(0, 80)
  };
})()
"""

REF_RECTS_JS = r"""
(() => {
  const REFS = __REFS_JSON__;
  const root = document.documentElement;
  const out = [];
  for (const ref of REFS) {
    const el = document.querySelector('[data-mcp-ref="' + ref + '"]');
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (rect.width <= 0 || rect.height <= 0) continue;
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") continue;
    out.push({ref: ref, x: rect.x, y: rect.y, width: rect.width, height: rect.height});
  }
  const body = document.body;
  return {
    refs: out,
    doc_id: root ? (root.getAttribute("data-mcp-doc") || null) : null,
    scroll_x: window.scrollX || 0,
    scroll_y: window.scrollY || 0,
    inner_width: window.innerWidth || 0,
    inner_height: window.innerHeight || 0,
    scroll_width: Math.max(root ? root.scrollWidth : 0, body ? body.scrollWidth : 0),
    scroll_height: Math.max(root ? root.scrollHeight : 0, body ? body.scrollHeight : 0),
    device_pixel_ratio: window.devicePixelRatio || 1
  };
})()
"""

CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "checking your browser",
    "checking if the site connection is secure",
    "verify you are human",
    "verify you are a human",
    "cf-chl",
    "challenge-platform",
    "请完成安全验证",
    "人机验证",
)

CHALLENGE_URL_MARKERS = ("__cf_chl", "/cdn-cgi/", "challenge")


def score_challenge(data: dict[str, Any], mode: str) -> dict[str, Any]:
    title = str(data.get("title") or "")
    url = str(data.get("url") or "")
    text = str(data.get("text") or "")
    haystack = f"{title}\n{text}".lower()
    matched: list[str] = []
    for marker in CHALLENGE_MARKERS:
        if marker in haystack:
            matched.append(marker)
    lowered_url = url.lower()
    for marker in CHALLENGE_URL_MARKERS:
        if marker in lowered_url:
            matched.append(f"url:{marker}")
    matched.extend(str(item) for item in (data.get("signals") or []))
    index = MODE_ORDER.index(mode) if mode in MODE_ORDER else -1
    suggested = MODE_ORDER[index + 1] if 0 <= index < len(MODE_ORDER) - 1 else None
    return {
        "detected": bool(matched),
        "title": title,
        "url": url,
        "signals": matched[:12],
        "suggested_mode": suggested,
    }


SELENIUM_KEYS: dict[str, Any] = {}


def _selenium_keys() -> dict[str, Any]:
    global SELENIUM_KEYS
    if not SELENIUM_KEYS:
        from selenium.webdriver.common.keys import Keys

        SELENIUM_KEYS = {
            "Enter": Keys.ENTER,
            "Tab": Keys.TAB,
            "Escape": Keys.ESCAPE,
            "Backspace": Keys.BACKSPACE,
            "Delete": Keys.DELETE,
            "Space": Keys.SPACE,
            "ArrowUp": Keys.ARROW_UP,
            "ArrowDown": Keys.ARROW_DOWN,
            "ArrowLeft": Keys.ARROW_LEFT,
            "ArrowRight": Keys.ARROW_RIGHT,
            "Home": Keys.HOME,
            "End": Keys.END,
            "PageUp": Keys.PAGE_UP,
            "PageDown": Keys.PAGE_DOWN,
            "Control": Keys.CONTROL,
            "Shift": Keys.SHIFT,
            "Alt": Keys.ALT,
            "Meta": Keys.META,
            **{f"F{index}": getattr(Keys, f"F{index}") for index in range(1, 13)},
        }
    return SELENIUM_KEYS


class BrowserBackend:
    def __init__(
        self,
        mode: str,
        browser_path: str,
        headless: bool,
        page_load_timeout: float = 30.0,
        profile_dir: str = "",
    ) -> None:
        self.mode = mode
        self.browser_path = browser_path
        self.headless = headless
        self.page_load_timeout = page_load_timeout
        self.profile_dir = profile_dir
        self.browser_version = ""
        self._driver = None
        self._cdp = None
        self._dialog_open = False
        self._dialog_info: dict[str, Any] | None = None

    def open(self) -> str:
        if self.browser_path and not Path(self.browser_path).exists():
            raise ToolError(
                "browser_launch_failed",
                f"浏览器路径不存在：{self.browser_path}",
                hint="检查 --browser 配置，或安装 Chrome for Testing",
            )
        if self.profile_dir:
            try:
                Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ToolError(
                    "browser_launch_failed",
                    f"无法创建会话 profile 目录：{self.profile_dir}",
                    details={"error": str(exc)},
                ) from exc
        try:
            if self.mode == "cdp":
                from seleniumbase import sb_cdp

                kwargs: dict[str, Any] = {"headless": self.headless}
                if self.browser_path:
                    kwargs["browser_executable_path"] = self.browser_path
                if self.profile_dir:
                    kwargs["user_data_dir"] = self.profile_dir
                self._cdp = sb_cdp.Chrome(**kwargs)
                self._install_cdp_dialog_handlers()
                self.browser_version = self._cdp_version()
            else:
                from seleniumbase import Driver

                kwargs = {"browser": "chrome", "headless": self.headless}
                if self.browser_path:
                    kwargs["binary_location"] = self.browser_path
                if self.profile_dir:
                    kwargs["user_data_dir"] = self.profile_dir
                if self.mode == "uc":
                    kwargs["uc"] = True
                self._driver = Driver(**kwargs)
                if self.page_load_timeout:
                    try:
                        self._driver.set_page_load_timeout(self.page_load_timeout)
                        self._driver.set_script_timeout(
                            max(10.0, self.page_load_timeout)
                        )
                    except Exception:
                        pass
                self.browser_version = str(
                    self._driver.capabilities.get("browserVersion") or ""
                )
        except ToolError:
            raise
        except Exception as exc:
            self.quit()
            raise ToolError(
                "browser_launch_failed",
                f"启动浏览器失败：{type(exc).__name__}: {exc}",
                hint="检查浏览器路径、driver 版本与 headless 配置",
            ) from exc
        return self.browser_version

    def _install_cdp_dialog_handlers(self) -> None:
        from mycdp import page as cdp_page

        def on_open(event) -> None:
            dtype = getattr(event.type_, "value", None) or str(event.type_)
            self._dialog_open = True
            self._dialog_info = {
                "type": dtype,
                "message": event.message,
                "default_prompt": event.default_prompt,
                "url": event.url,
            }

        def on_closed(event) -> None:
            self._dialog_open = False
            self._dialog_info = None

        self._cdp.add_handler(cdp_page.JavascriptDialogOpening, on_open)
        self._cdp.add_handler(cdp_page.JavascriptDialogClosed, on_closed)

    def _cdp_version(self) -> str:
        try:
            ua = self._cdp.get_user_agent()
        except Exception:
            ua = ""
        match = re.search(r"(?:Chrome|Edg)/([0-9.]+)", ua or "")
        return match.group(1) if match else (ua or "")

    def navigate(self, url: str) -> None:
        try:
            if self._cdp is not None:
                self._cdp.goto(url)
            else:
                self._driver.get(url)
        except Exception as exc:
            name = type(exc).__name__
            if "Timeout" in name:
                raise ToolError(
                    "nav_timeout",
                    f"页面加载超时（{self.page_load_timeout}s）：{url}",
                    hint="页面可能仍在加载，可稍后调用 snapshot 或 page_info",
                ) from exc
            raise ToolError(
                "navigation_failed",
                f"导航失败：{name}: {exc}",
                hint="检查 URL、网络与浏览器状态",
            ) from exc

    def execute_script(self, expression: str) -> Any:
        # CDP 的 execute_script 按表达式求值；WebDriver 需要显式 return。
        # 注意不能用 "return\n..."，换行会触发自动分号插入导致返回 None。
        if self._cdp is not None:
            return self._cdp.execute_script(expression)
        return self._driver.execute_script("return (" + expression.strip() + ")")

    def execute_async_script(self, expression: str) -> Any:
        if self._cdp is not None:
            return self._cdp.loop.run_until_complete(
                self._cdp.page.evaluate(expression.strip(), await_promise=True)
            )
        wrapper = (
            "const cb = arguments[arguments.length - 1];\n"
            "Promise.resolve(" + expression.strip() + ").then(\n"
            "  (value) => cb(value),\n"
            "  (error) => cb({__error__: String((error && error.message) || error)})\n"
            ");"
        )
        return self._driver.execute_async_script(wrapper)

    @property
    def current_url(self) -> str:
        if self._cdp is not None:
            return self._cdp.get_current_url()
        return self._driver.current_url

    @property
    def title(self) -> str:
        if self._cdp is not None:
            return self._cdp.get_title()
        return self._driver.title

    def doc_id(self) -> str | None:
        return self.execute_script(
            "(() => { const el = document.documentElement;"
            " return el ? (el.getAttribute('data-mcp-doc') || null) : null; })()"
        )

    def wait_document_ready(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        state: dict[str, Any] = {}
        while True:
            try:
                data = self.execute_script(DOC_STATE_JS)
                if isinstance(data, dict):
                    state = data
            except Exception:
                pass
            if state.get("ready") == "complete":
                return state
            if time.monotonic() >= deadline:
                return state
            time.sleep(0.1)

    def snapshot(
        self, max_nodes: int, max_chars: int, ref_base: int = 0
    ) -> dict[str, Any]:
        expression = SNAPSHOT_JS.replace("__MAX_NODES__", str(max_nodes)).replace(
            "__REF_BASE__", str(max(0, int(ref_base)))
        )
        try:
            data = self.execute_script(expression)
        except Exception as exc:
            raise ToolError(
                "snapshot_failed",
                f"页面快照失败：{type(exc).__name__}: {exc}",
                hint="页面可能已跳转或关闭；先调用 page_info 检查状态",
            ) from exc
        if not isinstance(data, dict):
            raise ToolError(
                "snapshot_failed",
                "快照脚本返回了非对象结果",
                details={"type": type(data).__name__},
            )
        text, render_stats = render_snapshot(data, max_chars=max_chars)
        stats = dict(data.get("stats") or {})
        stats.update(render_stats)
        return {
            "doc_id": data.get("doc_id"),
            "url": data.get("url") or self.current_url,
            "title": data.get("title") or self.title,
            "snapshot": text,
            "stats": stats,
            "tree": data.get("tree"),
        }

    def _ref_selector(self, ref: str) -> str:
        return f'[data-mcp-ref="{ref}"]'

    def _find_element(self, ref: str):
        from selenium.webdriver.common.by import By

        return self._driver.find_element(By.CSS_SELECTOR, self._ref_selector(ref))

    def probe_ref(self, ref: str) -> dict[str, Any]:
        try:
            data = self.execute_script(render_probe_js(ref))
        except Exception as exc:
            raise ToolError(
                "stale_ref",
                "无法读取元素状态，页面可能正在导航",
                hint="等待页面加载后重新调用 snapshot",
                details={"ref": ref, "cause": type(exc).__name__},
            ) from exc
        if not isinstance(data, dict):
            raise ToolError(
                "stale_ref",
                "元素探测返回了非对象结果",
                hint="重新调用 snapshot 获取最新 ref",
                details={"ref": ref},
            )
        return data

    def scroll_ref_into_view(self, ref: str) -> dict[str, Any]:
        try:
            data = self.execute_script(render_scroll_ref_js(ref))
        except Exception as exc:
            raise ToolError(
                "stale_ref",
                "无法滚动到元素，页面可能正在导航",
                hint="等待页面加载后重新调用 snapshot",
                details={"ref": ref, "cause": type(exc).__name__},
            ) from exc
        return data if isinstance(data, dict) else {"found": False}

    def focus_ref(self, ref: str) -> dict[str, Any]:
        data = self.execute_script(render_focus_ref_js(ref))
        return data if isinstance(data, dict) else {"found": False}

    def select_options(self, ref: str) -> dict[str, Any]:
        try:
            data = self.execute_script(render_select_options_js(ref))
        except Exception as exc:
            raise ToolError(
                "stale_ref",
                "无法读取下拉框选项，页面可能正在导航",
                hint="重新调用 snapshot 获取最新 ref",
                details={"ref": ref, "cause": type(exc).__name__},
            ) from exc
        return data if isinstance(data, dict) else {"found": False}

    def click_ref(self, ref: str, button: str = "left", count: int = 1) -> None:
        if self._cdp is not None:
            if button == "left" and count == 1:
                self._run_native(
                    ref, lambda: self._cdp.click(self._ref_selector(ref), timeout=2)
                )
                return

            def cdp_click() -> None:
                rect = self.probe_ref(ref).get("rect") or {}
                x = float(rect.get("x", 0)) + float(rect.get("width", 0)) / 2
                y = float(rect.get("y", 0)) + float(rect.get("height", 0)) / 2
                counts = (1, 2) if button == "left" and count == 2 else (1,)
                self._cdp_dispatch_mouse(x, y, button=button, counts=counts)

            self._run_native(ref, cdp_click)
            return

        def click() -> None:
            from selenium.webdriver.common.action_chains import ActionChains

            element = self._find_element(ref)
            if button == "left" and count == 1:
                element.click()
            elif button == "left" and count == 2:
                ActionChains(self._driver).double_click(element).perform()
            else:
                ActionChains(self._driver).context_click(element).perform()

        self._run_native(ref, click)

    def type_ref(
        self, ref: str, text: str, clear: bool = True, submit: bool = False
    ) -> None:
        if self._cdp is not None:
            def cdp_type() -> None:
                element = self._cdp.select(self._ref_selector(ref), timeout=2)
                if clear:
                    tag = str(getattr(element, "tag_name", "") or "").lower()
                    if tag in ("input", "textarea"):
                        try:
                            element.clear_input()
                        except Exception:
                            pass
                    else:
                        self.execute_script(render_clear_ref_js(ref))
                element.send_keys(text)
                if submit:
                    element.send_keys("\n")

            self._run_native(ref, cdp_type)
            return

        def type_text() -> None:
            from selenium.webdriver.common.keys import Keys

            element = self._find_element(ref)
            if clear:
                if element.tag_name.lower() in ("input", "textarea"):
                    element.clear()
                else:
                    self.execute_script(render_clear_ref_js(ref))
            element.send_keys(text)
            if submit:
                element.send_keys(Keys.ENTER)

        self._run_native(ref, type_text)

    def select_option(self, ref: str, index: int) -> dict[str, Any]:
        if self._cdp is not None:
            result: dict[str, Any] = {}

            def cdp_select() -> None:
                data = self.execute_script(render_set_select_js(ref, index))
                result.update(data if isinstance(data, dict) else {})

            self._run_native(ref, cdp_select)
            if not result.get("changed"):
                raise ToolError(
                    "action_failed",
                    f"选择选项失败：{result.get('reason') or 'unknown'}",
                    hint="重新调用 snapshot 检查下拉框状态",
                    details={"ref": ref, "index": index},
                )
            return result

        def native_select() -> None:
            from selenium.webdriver.support.ui import Select

            Select(self._find_element(ref)).select_by_index(index)

        self._run_native(ref, native_select)
        return {"changed": True}

    def hover_ref(self, ref: str) -> None:
        if self._cdp is not None:
            def cdp_hover() -> None:
                element = self._cdp.select(self._ref_selector(ref), timeout=2)
                element.mouse_move()

            self._run_native(ref, cdp_hover)
            return

        def hover() -> None:
            from selenium.webdriver.common.action_chains import ActionChains

            element = self._find_element(ref)
            ActionChains(self._driver).move_to_element(element).perform()

        self._run_native(ref, hover)

    def scroll_by(self, dy: int) -> dict[str, Any]:
        data = self.execute_script(render_scroll_by_js(dy))
        return data if isinstance(data, dict) else {}

    def press_keys(self, parsed: dict[str, Any], ref: str | None = None) -> None:
        if ref is not None:
            data = self.focus_ref(ref)
            if not data.get("found"):
                raise ToolError(
                    "stale_ref",
                    "元素已不存在，无法聚焦",
                    hint="重新调用 snapshot 获取最新 ref",
                    details={"ref": ref},
                )
        if self._cdp is not None:
            self._run_native(ref or "active", lambda: self._cdp_dispatch_keys(parsed))
            return

        def native_press() -> None:
            args: list[Any] = []
            keys = _selenium_keys()
            for modifier in parsed.get("modifiers") or []:
                args.append(keys[modifier])
            main = parsed.get("main") or {}
            if "char" in main:
                args.append(main["char"])
            else:
                name = main.get("name")
                args.append(keys.get(name, name))
            target = self._driver.switch_to.active_element
            target.send_keys(*args)

        self._run_native(ref or "active", native_press)

    def _cdp_dispatch_mouse(
        self, x: float, y: float, button: str = "left", counts: tuple[int, ...] = (1,)
    ) -> None:
        from mycdp import input_ as cdp_input

        mouse_button = cdp_input.MouseButton(button)
        buttons = {"left": 1, "right": 2, "middle": 4}[button]

        async def run() -> None:
            for count in counts:
                await self._cdp.page.send(
                    cdp_input.dispatch_mouse_event(
                        "mouseMoved", x=x, y=y, button=mouse_button, buttons=buttons
                    )
                )
                await self._cdp.page.send(
                    cdp_input.dispatch_mouse_event(
                        "mousePressed",
                        x=x,
                        y=y,
                        button=mouse_button,
                        buttons=buttons,
                        click_count=count,
                    )
                )
                await self._cdp.page.send(
                    cdp_input.dispatch_mouse_event(
                        "mouseReleased",
                        x=x,
                        y=y,
                        button=mouse_button,
                        buttons=buttons,
                        click_count=count,
                    )
                )

        self._cdp.loop.run_until_complete(run())

    def point_info(self, x: float, y: float) -> dict[str, Any]:
        expression = POINT_JS.replace("__X_JSON__", json.dumps(x)).replace(
            "__Y_JSON__", json.dumps(y)
        )
        data = self.execute_script(expression)
        return data if isinstance(data, dict) else {"in_viewport": False}

    def click_at(
        self, x: float, y: float, button: str = "left", count: int = 1
    ) -> None:
        counts = (1, 2) if count == 2 else (1,)
        if self._cdp is not None:
            self._run_native(
                "active", lambda: self._cdp_dispatch_mouse(x, y, button=button, counts=counts)
            )
            return

        def wd_click() -> None:
            buttons = {"left": 1, "right": 2, "middle": 4}[button]
            for click_count in counts:
                self._driver.execute_cdp_cmd(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseMoved",
                        "x": x,
                        "y": y,
                        "button": "none",
                        "buttons": 0,
                    },
                )
                self._driver.execute_cdp_cmd(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mousePressed",
                        "x": x,
                        "y": y,
                        "button": button,
                        "buttons": buttons,
                        "clickCount": click_count,
                    },
                )
                self._driver.execute_cdp_cmd(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseReleased",
                        "x": x,
                        "y": y,
                        "button": button,
                        "buttons": buttons,
                        "clickCount": click_count,
                    },
                )

        self._run_native("active", wd_click)

    def detect_challenge(self) -> dict[str, Any]:
        try:
            data = self.execute_script(CHALLENGE_JS)
        except Exception as exc:
            return {
                "detected": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            }
        if not isinstance(data, dict):
            return {"detected": False}
        return score_challenge(data, self.mode)

    def screenshot_png(self, full_page: bool = False) -> bytes:
        try:
            if self._cdp is not None:
                from mycdp import page as cdp_page

                data = self._cdp.loop.run_until_complete(
                    self._cdp.page.send(
                        cdp_page.capture_screenshot(
                            format_="png",
                            from_surface=True,
                            capture_beyond_viewport=bool(full_page),
                        )
                    )
                )
                return base64.b64decode(data)
            if full_page:
                result = self._driver.execute_cdp_cmd(
                    "Page.captureScreenshot",
                    {
                        "format": "png",
                        "fromSurface": True,
                        "captureBeyondViewport": True,
                    },
                )
                return base64.b64decode(result.get("data", ""))
            return self._driver.get_screenshot_as_png()
        except Exception as exc:
            raise ToolError(
                "screenshot_failed",
                f"截图失败：{type(exc).__name__}: {exc}",
                hint="确认浏览器仍在运行，或稍后重试",
            ) from exc

    def collect_ref_rects(self, refs: list[str]) -> dict[str, Any]:
        try:
            data = self.execute_script(
                REF_RECTS_JS.replace("__REFS_JSON__", json.dumps(refs))
            )
        except Exception:
            return {"refs": []}
        return data if isinstance(data, dict) else {"refs": []}

    def _cdp_dispatch_keys(self, parsed: dict[str, Any]) -> None:
        from mycdp import input_ as cdp_input

        modifiers = parsed.get("modifiers") or []
        mask = 0
        for modifier in modifiers:
            mask |= MODIFIER_MASK[modifier]
        main = parsed.get("main") or {}
        if "char" in main:
            char = main["char"]
            key = char
            text = char
            if char.isalpha():
                code = f"Key{char.upper()}"
                vk = ord(char.upper())
            elif char.isdigit():
                code = f"Digit{char}"
                vk = ord(char)
            else:
                code = ""
                vk = 0
        elif main.get("name") == "+":
            key, code, vk, text = "+", "Equal", 187, "+"
        else:
            name = main.get("name")
            key, code, vk, text = CDP_KEY_DEFS[name]

        async def run() -> None:
            for modifier in modifiers:
                mod_key, mod_code, mod_vk, _ = CDP_KEY_DEFS[modifier]
                await self._cdp.page.send(
                    cdp_input.dispatch_key_event(
                        type_="rawKeyDown",
                        modifiers=mask,
                        key=mod_key,
                        code=mod_code,
                        windows_virtual_key_code=mod_vk,
                        native_virtual_key_code=mod_vk,
                    )
                )
            await self._cdp.page.send(
                cdp_input.dispatch_key_event(
                    type_="keyDown",
                    modifiers=mask,
                    key=key,
                    code=code,
                    windows_virtual_key_code=vk,
                    native_virtual_key_code=vk,
                    text=text or None,
                )
            )
            await self._cdp.page.send(
                cdp_input.dispatch_key_event(
                    type_="keyUp",
                    modifiers=mask,
                    key=key,
                    code=code,
                    windows_virtual_key_code=vk,
                    native_virtual_key_code=vk,
                )
            )
            for modifier in reversed(modifiers):
                mod_key, mod_code, mod_vk, _ = CDP_KEY_DEFS[modifier]
                await self._cdp.page.send(
                    cdp_input.dispatch_key_event(
                        type_="keyUp",
                        modifiers=mask,
                        key=mod_key,
                        code=mod_code,
                        windows_virtual_key_code=mod_vk,
                        native_virtual_key_code=mod_vk,
                    )
                )

        self._cdp.loop.run_until_complete(run())

    def settle(self, timeout: float) -> dict[str, Any]:
        try:
            data = self.execute_async_script(render_settle_js(timeout))
        except Exception as exc:
            return {
                "settled": False,
                "reason": "context_destroyed",
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }
        if isinstance(data, dict):
            return data
        return {"settled": False, "reason": "invalid_result"}

    def has_dialog(self) -> bool:
        if self._driver is not None:
            try:
                self._driver.switch_to.alert
                return True
            except Exception:
                return False
        return self._dialog_open

    def dialog_info(self) -> dict[str, Any] | None:
        if self._driver is not None:
            try:
                alert = self._driver.switch_to.alert
                return {
                    "type": "native",
                    "message": alert.text,
                }
            except Exception:
                return None
        return dict(self._dialog_info) if self._dialog_info else None

    def handle_dialog(self, action: str, text: str | None = None) -> dict[str, Any]:
        if action not in ("accept", "dismiss"):
            raise ToolError(
                "invalid_argument", f"未知对话框动作：{action}", hint="accept / dismiss"
            )
        if self._driver is not None:
            try:
                alert = self._driver.switch_to.alert
            except Exception as exc:
                raise ToolError(
                    "dialog_not_open", "当前没有可处理的对话框"
                ) from exc
            info = {"type": "native", "message": alert.text}
            if action == "accept":
                if text is not None:
                    alert.send_keys(str(text))
                alert.accept()
            else:
                alert.dismiss()
            return info

        if self._cdp is not None:
            if not self._dialog_open:
                raise ToolError("dialog_not_open", "当前没有可处理的对话框")
            from mycdp import page as cdp_page

            info = dict(self._dialog_info or {})
            try:
                self._cdp.loop.run_until_complete(
                    self._cdp.page.send(
                        cdp_page.handle_java_script_dialog(
                            accept=(action == "accept"),
                            prompt_text=text,
                        )
                    )
                )
            finally:
                self._dialog_open = False
                self._dialog_info = None
            return info

        raise ToolError("dialog_not_open", "当前没有可处理的对话框")

    def _run_native(self, ref: str, fn) -> Any:
        try:
            return fn()
        except ToolError:
            raise
        except Exception as exc:
            raise self._translate_error(exc, ref) from exc

    def _translate_error(self, exc: Exception, ref: str) -> ToolError:
        name = type(exc).__name__
        message = str(exc)
        lowered = message.lower()
        if (
            name in ("StaleElementReferenceException", "NoSuchElementException")
            or "stale" in lowered
            or "no such element" in lowered
            or "not found" in lowered
            or "could not find" in lowered
        ):
            return ToolError(
                "stale_ref",
                f"元素已失效或不存在：{message[:200]}",
                hint="重新调用 snapshot 获取最新 ref",
                details={"ref": ref},
            )
        if (
            name
            in (
                "ElementClickInterceptedException",
                "ElementNotInteractableException",
                "InvalidElementStateException",
            )
            or "intercepted" in lowered
            or "not interactable" in lowered
            or "not clickable" in lowered
            or "not editable" in lowered
        ):
            reason = (
                "covered"
                if "intercepted" in lowered or "clickable" in lowered
                else "not_interactable"
            )
            return ToolError(
                "not_actionable",
                f"元素当前不可操作：{message[:200]}",
                hint="等待页面稳定或关闭遮挡层后重试",
                details={"ref": ref, "reason": reason},
            )
        if "alert" in lowered or "dialog" in lowered:
            return ToolError(
                "dialog_open",
                f"存在未处理的对话框：{message[:200]}",
                hint="使用 dialog 工具 accept/dismiss",
                details={"ref": ref},
            )
        if name == "TimeoutException" or "timeout" in lowered:
            return ToolError(
                "timeout",
                f"动作超时：{message[:200]}",
                hint="稍后重试或提高 command_timeout",
            )
        return ToolError(
            "action_failed",
            f"{name}: {message[:300]}",
            hint="页面可能已变化；重新调用 snapshot 后重试",
            details={"ref": ref},
        )

    def quit(self) -> None:
        self._dialog_open = False
        self._dialog_info = None
        if self._cdp is not None:
            try:
                self._cdp.quit()
            except Exception:
                pass
            self._cdp = None
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
