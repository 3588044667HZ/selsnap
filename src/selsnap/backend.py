from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import ToolError
from .snapshot import SNAPSHOT_JS, render_snapshot


class BrowserBackend:
    def __init__(
        self,
        mode: str,
        browser_path: str,
        headless: bool,
        page_load_timeout: float = 30.0,
    ) -> None:
        self.mode = mode
        self.browser_path = browser_path
        self.headless = headless
        self.page_load_timeout = page_load_timeout
        self.browser_version = ""
        self._driver = None
        self._cdp = None

    def open(self) -> str:
        if self.browser_path and not Path(self.browser_path).exists():
            raise ToolError(
                "browser_launch_failed",
                f"浏览器路径不存在：{self.browser_path}",
                hint="检查 --browser 配置，或安装 Chrome for Testing",
            )
        try:
            if self.mode == "cdp":
                from seleniumbase import sb_cdp

                kwargs: dict[str, Any] = {"headless": self.headless}
                if self.browser_path:
                    kwargs["browser_executable_path"] = self.browser_path
                self._cdp = sb_cdp.Chrome(**kwargs)
                self.browser_version = self._cdp_version()
            else:
                from seleniumbase import Driver

                kwargs = {"browser": "chrome", "headless": self.headless}
                if self.browser_path:
                    kwargs["binary_location"] = self.browser_path
                if self.mode == "uc":
                    kwargs["uc"] = True
                self._driver = Driver(**kwargs)
                if self.page_load_timeout:
                    try:
                        self._driver.set_page_load_timeout(self.page_load_timeout)
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

    def snapshot(self, max_nodes: int, max_chars: int) -> dict[str, Any]:
        expression = SNAPSHOT_JS.replace("__MAX_NODES__", str(max_nodes))
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
        }

    def quit(self) -> None:
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
