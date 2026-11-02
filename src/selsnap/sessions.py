from __future__ import annotations

import logging
import queue
import re
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .backend import BrowserBackend
from .config import VALID_MODES, Settings
from .errors import ToolError

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionActor:
    def __init__(
        self,
        name: str,
        mode: str,
        headless: bool,
        settings: Settings,
    ) -> None:
        self.name = name
        self.mode = mode
        self.headless = headless
        self.settings = settings
        self.backend = BrowserBackend(
            mode=mode,
            browser_path=settings.browser_path,
            headless=headless,
            page_load_timeout=settings.page_load_timeout,
        )
        self.browser_version = ""
        self.created_at = utc_now()
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name=f"selsnap-{name}", daemon=True
        )
        self._closed = False

    def start(self) -> None:
        self._thread.start()
        self.browser_version = self._submit(
            self.backend.open, self.settings.command_timeout
        )

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            future, fn = item
            if future.cancelled():
                continue
            try:
                result = fn()
            except BaseException as exc:
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)

    def _submit(self, fn: Callable[[], Any], timeout: float) -> Any:
        future: Future = Future()
        self._queue.put((future, fn))
        try:
            return future.result(timeout=timeout)
        except FutureTimeout as exc:
            raise ToolError(
                "timeout",
                f"会话 {self.name} 操作超时（{timeout}s）",
                hint="浏览器可能仍在加载；稍后重试或提高 command_timeout",
            ) from exc

    def call(self, fn: Callable[[], Any], timeout: float | None = None) -> Any:
        if self._closed:
            raise ToolError("session_closed", f"会话 {self.name} 已关闭")
        return self._submit(fn, timeout or self.settings.command_timeout)

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "headless": self.headless,
            "browser_version": self.browser_version,
            "created_at": self.created_at,
            "closed": self._closed,
        }

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._submit(self.backend.quit, 15.0)
        except Exception:
            log.warning("关闭会话 %s 时 backend.quit 失败", self.name, exc_info=True)
        self._closed = True
        self._queue.put(None)
        self._thread.join(timeout=10)


@dataclass
class SessionRegistry:
    settings: Settings

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionActor] = {}
        self._pool = threading.BoundedSemaphore(self.settings.pool_size)
        self._closed = False

    def open(
        self,
        name: str,
        mode: str = "standard",
        headless: bool | None = None,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not NAME_RE.match(name):
            raise ToolError(
                "invalid_argument",
                "会话名必须是 1-64 位字母、数字、点、下划线或短横线",
            )
        if mode not in VALID_MODES:
            raise ToolError(
                "invalid_mode",
                f"未知模式：{mode}",
                hint="可用模式：standard / uc / cdp",
            )
        if self._closed:
            raise ToolError("server_closed", "服务已关闭")
        headless = self.settings.headless if headless is None else bool(headless)

        if not self._pool.acquire(timeout=30):
            raise ToolError(
                "resource_busy",
                f"浏览器并发已达上限（{self.settings.pool_size}）",
                hint="关闭空闲会话后重试",
            )

        started = False
        try:
            with self._lock:
                existing = self._sessions.get(name)
                if existing is not None:
                    info = existing.info()
                    info["reused"] = True
                    return info
                actor = SessionActor(name, mode, headless, self.settings)
                self._sessions[name] = actor

            try:
                actor.start()
            except Exception as exc:
                with self._lock:
                    self._sessions.pop(name, None)
                actor.close()
                if isinstance(exc, ToolError):
                    raise
                raise ToolError(
                    "browser_launch_failed",
                    f"会话 {name} 启动失败：{type(exc).__name__}: {exc}",
                ) from exc

            started = True
            info = actor.info()
            info["reused"] = False
            return info
        finally:
            if not started:
                self._pool.release()

    def get(self, name: str) -> SessionActor:
        with self._lock:
            actor = self._sessions.get(name)
        if actor is None:
            raise ToolError(
                "session_not_found",
                f"会话不存在：{name}",
                hint="先调用 session_open，或 session_list 查看现有会话",
            )
        return actor

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            actors = list(self._sessions.values())
        return [actor.info() for actor in sorted(actors, key=lambda item: item.name)]

    def close(self, name: str) -> dict[str, Any]:
        with self._lock:
            actor = self._sessions.pop(name, None)
        if actor is None:
            raise ToolError(
                "session_not_found",
                f"会话不存在：{name}",
                hint="session_list 可查看现有会话",
            )
        info = actor.info()
        actor.close()
        self._pool.release()
        info["closed"] = True
        return info

    def close_all(self) -> None:
        self._closed = True
        with self._lock:
            actors = list(self._sessions.values())
            self._sessions.clear()
        for actor in actors:
            actor.close()
