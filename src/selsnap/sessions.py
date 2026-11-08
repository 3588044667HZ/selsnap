from __future__ import annotations

import logging
import queue
import re
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .backend import BrowserBackend
from .config import MODE_ORDER, VALID_MODES, Settings
from .errors import ToolError
from .identity import AGENT_RE

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
GRANT_MODES = ("read", "write", "revoke")
MAX_SHARE_TTL = 30 * 24 * 3600


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class SessionActor:
    def __init__(
        self,
        name: str,
        mode: str,
        headless: bool,
        settings: Settings,
        owner: str = "local",
        auto_escalate: bool = False,
    ) -> None:
        self.name = name
        self.mode = mode
        self.headless = headless
        self.settings = settings
        self.owner = owner
        self.auto_escalate = bool(auto_escalate)
        self.profile_dir = str(Path(settings.profile_root) / name)
        self.backend = self._new_backend(mode)
        self.browser_version = ""
        self.created_at = utc_now()
        self.last_doc_id: str | None = None
        self.last_tree: dict[str, Any] | None = None
        self.last_snapshot_text = ""
        self.last_url = ""
        self.ref_counter = 0
        self.last_used = time.monotonic()
        self._grants: dict[str, dict[str, Any]] = {}
        self._acl_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name=f"selsnap-{name}", daemon=True
        )
        self._closed = False
        self._suspended = False
        self._resume_hook: Callable[[], None] | None = None

    def _new_backend(self, mode: str) -> BrowserBackend:
        return BrowserBackend(
            mode=mode,
            browser_path=self.settings.browser_path,
            headless=self.headless,
            page_load_timeout=self.settings.page_load_timeout,
            profile_dir=self.profile_dir,
        )

    @property
    def suspended(self) -> bool:
        return self._suspended

    @property
    def closed(self) -> bool:
        return self._closed

    def start(self) -> None:
        with self._lifecycle_lock:
            self._thread.start()
            self.browser_version = self._submit(
                self.backend.open, self.settings.command_timeout
            )
            self.last_used = time.monotonic()

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
        for _ in range(2):
            if self._suspended:
                if self._resume_hook is None:
                    raise ToolError(
                        "session_suspended",
                        f"会话 {self.name} 已因空闲挂起",
                        hint="调用 session_attach 以恢复会话",
                    )
                self._resume_hook()
            with self._lifecycle_lock:
                if self._closed:
                    raise ToolError("session_closed", f"会话 {self.name} 已关闭")
                if self._suspended:
                    continue
                try:
                    return self._submit(fn, timeout or self.settings.command_timeout)
                finally:
                    self.last_used = time.monotonic()
        raise ToolError(
            "session_suspended",
            f"会话 {self.name} 已因空闲挂起",
            hint="稍后重试，或调用 session_attach 恢复会话",
        )

    def can_read(self, agent: str) -> bool:
        return self._access(agent, "read")

    def can_write(self, agent: str) -> bool:
        return self._access(agent, "write")

    def _access(self, agent: str, required: str) -> bool:
        if agent == self.owner:
            return True
        with self._acl_lock:
            grant = self._grants.get(agent)
        if not grant:
            return False
        expires = grant.get("expires_at")
        if expires is not None and expires <= time.time():
            with self._acl_lock:
                self._grants.pop(agent, None)
            return False
        return grant.get("mode") == "write" or required == "read"

    def require_access(self, agent: str, required: str) -> None:
        if self._access(agent, required):
            return
        raise ToolError(
            "forbidden",
            f"agent {agent} 无权{required}访问会话 {self.name}",
            hint="会话默认私有；由 owner 调用 session_share 授权",
            details={"owner": self.owner, "required": required},
        )

    def share(self, agent: str, mode: str, ttl: float | None = None) -> dict[str, Any]:
        if not AGENT_RE.match(agent or ""):
            raise ToolError(
                "invalid_argument",
                "agent 名必须是 1-64 位字母、数字、点、下划线或短横线",
            )
        if mode not in GRANT_MODES:
            raise ToolError(
                "invalid_argument", f"未知共享模式：{mode}", hint="read / write / revoke"
            )
        if agent == self.owner:
            raise ToolError("invalid_argument", "owner 已拥有全部权限，无需共享")
        with self._acl_lock:
            if mode == "revoke":
                existed = self._grants.pop(agent, None) is not None
                return {"agent": agent, "mode": "revoke", "revoked": existed}
            if ttl is not None:
                if ttl <= 0 or ttl > MAX_SHARE_TTL:
                    raise ToolError(
                        "invalid_argument",
                        f"ttl 必须在 (0, {MAX_SHARE_TTL}] 秒之间",
                    )
            now = time.time()
            entry = {
                "mode": mode,
                "created_at": now,
                "expires_at": (now + ttl) if ttl else None,
            }
            self._grants[agent] = entry
            return {
                "agent": agent,
                "mode": mode,
                "expires_at": _iso(entry["expires_at"]),
            }

    def grants(self) -> list[dict[str, Any]]:
        now = time.time()
        result: list[dict[str, Any]] = []
        with self._acl_lock:
            for agent, entry in list(self._grants.items()):
                expires = entry.get("expires_at")
                if expires is not None and expires <= now:
                    self._grants.pop(agent, None)
                    continue
                result.append(
                    {
                        "agent": agent,
                        "mode": entry.get("mode"),
                        "expires_at": _iso(expires),
                    }
                )
        return sorted(result, key=lambda item: item["agent"])

    def info(self, agent: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "mode": self.mode,
            "headless": self.headless,
            "browser_version": self.browser_version,
            "created_at": self.created_at,
            "closed": self._closed,
            "suspended": self._suspended,
            "owner": self.owner,
            "auto_escalate": self.auto_escalate,
        }
        if agent is None or agent == self.owner:
            payload["shared_with"] = self.grants()
        return payload

    def record_snapshot(self, result: dict[str, Any]) -> None:
        # 只在 actor 线程内调用，避免跨线程读写快照状态
        self.last_doc_id = result.get("doc_id")
        self.last_tree = result.get("tree")
        self.last_snapshot_text = result.get("snapshot") or ""
        self.last_url = result.get("url") or ""
        stats = result.get("stats") or {}
        counter = stats.get("ref_counter")
        if isinstance(counter, int) and counter > self.ref_counter:
            self.ref_counter = counter

    @property
    def next_ref_base(self) -> int:
        # 新文档从上一文档的最大 ref 继续（refFor 会先自增，故直接用 ref_counter）
        return self.ref_counter

    def next_mode(self) -> str | None:
        try:
            index = MODE_ORDER.index(self.mode)
        except ValueError:
            return None
        if index + 1 >= len(MODE_ORDER):
            return None
        return MODE_ORDER[index + 1]

    def escalate_locked(self, target: str) -> dict[str, Any]:
        # 必须在 actor 线程内调用
        if self._closed:
            raise ToolError("session_closed", f"会话 {self.name} 已关闭")
        if self._suspended:
            raise ToolError("session_suspended", f"会话 {self.name} 已挂起")
        if target not in VALID_MODES:
            raise ToolError(
                "invalid_mode", f"未知模式：{target}", hint="standard / uc / cdp"
            )
        if target == self.mode:
            raise ToolError("invalid_argument", f"会话已处于 {target} 模式")
        try:
            url = self.backend.current_url
        except Exception:
            url = self.last_url
        self.backend.quit()
        self.backend = self._new_backend(target)
        self.mode = target
        try:
            self.browser_version = self.backend.open()
            if url and url != "about:blank":
                self.backend.navigate(url)
        except Exception:
            self.last_doc_id = None
            self.last_tree = None
            raise
        self.last_doc_id = None
        self.last_tree = None
        self.last_snapshot_text = ""
        self.last_url = url or ""
        self.last_used = time.monotonic()
        return {
            "mode": target,
            "browser_version": self.browser_version,
            "url": url,
        }

    def suspend(self, if_idle_for: float | None = None) -> bool:
        with self._lifecycle_lock:
            if self._closed or self._suspended:
                return False
            if (
                if_idle_for is not None
                and time.monotonic() - self.last_used < if_idle_for
            ):
                return False
            try:
                self.last_url = self.backend.current_url or self.last_url
            except Exception:
                pass
            try:
                self._submit(self.backend.quit, 15.0)
            except Exception:
                log.warning("挂起会话 %s 时关闭浏览器失败", self.name, exc_info=True)
            self._suspended = True
            self.last_doc_id = None
            self.last_tree = None
            log.info("会话 %s 因空闲挂起（profile 保留：%s）", self.name, self.profile_dir)
            return True

    def resume(self) -> bool:
        with self._lifecycle_lock:
            if self._closed or not self._suspended:
                return False
            try:
                self.browser_version = self._submit(
                    self.backend.open, self.settings.command_timeout
                )
                if self.last_url and self.last_url != "about:blank":
                    self.backend.navigate(self.last_url)
                try:
                    snap = self.backend.snapshot(
                        self.settings.snapshot_max_nodes,
                        self.settings.snapshot_max_chars,
                        ref_base=self.next_ref_base,
                    )
                    self.record_snapshot(snap)
                except ToolError:
                    log.warning("恢复会话 %s 后快照失败", self.name, exc_info=True)
            except Exception:
                try:
                    self._submit(self.backend.quit, 15.0)
                except Exception:
                    pass
                raise
            self._suspended = False
            self.last_used = time.monotonic()
            log.info("会话 %s 已恢复", self.name)
            return True

    def close(self) -> None:
        with self._lifecycle_lock:
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
        self._permit_held: dict[str, bool] = {}
        self._lifecycle_locks: dict[str, threading.Lock] = {}
        self._stop = threading.Event()
        self._sweeper: threading.Thread | None = None
        if self.settings.idle_timeout > 0:
            self._sweeper = threading.Thread(
                target=self._idle_loop, name="selsnap-idle", daemon=True
            )
            self._sweeper.start()

    def _validate_name(self, name: str) -> str:
        cleaned = (name or "").strip()
        if not NAME_RE.match(cleaned):
            raise ToolError(
                "invalid_argument",
                "会话名必须是 1-64 位字母、数字、点、下划线或短横线",
            )
        return cleaned

    def _actor_lock(self, name: str) -> threading.Lock:
        with self._lock:
            return self._lifecycle_locks.setdefault(name, threading.Lock())

    def open(
        self,
        name: str,
        mode: str = "standard",
        headless: bool | None = None,
        agent: str = "local",
        auto_escalate: bool = False,
    ) -> dict[str, Any]:
        name = self._validate_name(name)
        if mode not in VALID_MODES:
            raise ToolError(
                "invalid_mode",
                f"未知模式：{mode}",
                hint="可用模式：standard / uc / cdp",
            )
        if not AGENT_RE.match(agent or ""):
            raise ToolError("invalid_argument", "无效的 agent 名")
        if self._closed:
            raise ToolError("server_closed", "服务已关闭")
        headless = self.settings.headless if headless is None else bool(headless)

        with self._lock:
            existing = self._sessions.get(name)
        if existing is not None:
            existing.require_access(agent, "write")
            self._ensure_active(name, existing)
            info = existing.info(agent)
            info["reused"] = True
            return info

        if not self._pool.acquire(timeout=30):
            raise ToolError(
                "resource_busy",
                f"浏览器并发已达上限（{self.settings.pool_size}）",
                hint="关闭空闲会话后重试",
            )
        permit_owned = True

        actor: SessionActor | None = None
        started = False
        try:
            with self._lock:
                existing = self._sessions.get(name)
                if existing is not None:
                    self._pool.release()
                    permit_owned = False
                    existing.require_access(agent, "write")
                    self._ensure_active(name, existing)
                    info = existing.info(agent)
                    info["reused"] = True
                    return info
                actor = SessionActor(
                    name,
                    mode,
                    headless,
                    self.settings,
                    owner=agent,
                    auto_escalate=auto_escalate,
                )
                self._sessions[name] = actor
                self._permit_held[name] = True
                actor._resume_hook = lambda: self._ensure_active(name, actor)

            try:
                actor.start()
            except Exception as exc:
                with self._lock:
                    self._sessions.pop(name, None)
                    self._permit_held.pop(name, None)
                actor.close()
                if isinstance(exc, ToolError):
                    raise
                raise ToolError(
                    "browser_launch_failed",
                    f"会话 {name} 启动失败：{type(exc).__name__}: {exc}",
                ) from exc

            started = True
            info = actor.info(agent)
            info["reused"] = False
            return info
        finally:
            if not started and permit_owned:
                self._pool.release()

    def _ensure_active(self, name: str, actor: SessionActor) -> None:
        if not actor.suspended:
            return
        lock = self._actor_lock(name)
        with lock:
            if not actor.suspended:
                return
            if not self._pool.acquire(timeout=30):
                raise ToolError(
                    "resource_busy",
                    f"浏览器并发已达上限（{self.settings.pool_size}）",
                    hint="关闭空闲会话后重试",
                )
            try:
                actor.resume()
            except Exception:
                self._pool.release()
                raise
            with self._lock:
                self._permit_held[name] = True

    def get(self, name: str, agent: str = "local", access: str = "read") -> SessionActor:
        with self._lock:
            actor = self._sessions.get(name)
        if actor is None:
            raise ToolError(
                "session_not_found",
                f"会话不存在：{name}",
                hint="先调用 session_open，或 session_list 查看现有会话",
            )
        actor.require_access(agent, access)
        self._ensure_active(name, actor)
        return actor

    def peek(self, name: str) -> SessionActor | None:
        with self._lock:
            return self._sessions.get(name)

    def list(self, agent: str = "local") -> list[dict[str, Any]]:
        with self._lock:
            actors = list(self._sessions.values())
        return [
            actor.info(agent)
            for actor in sorted(actors, key=lambda item: item.name)
            if actor.can_read(agent)
        ]

    def close(self, name: str, agent: str = "local") -> dict[str, Any]:
        with self._lock:
            actor = self._sessions.pop(name, None)
            held = self._permit_held.pop(name, False)
        if actor is None:
            raise ToolError(
                "session_not_found",
                f"会话不存在：{name}",
                hint="session_list 可查看现有会话",
            )
        if agent != actor.owner:
            # 放回会话，避免误删；只有 owner 可以关闭
            with self._lock:
                self._sessions[name] = actor
                self._permit_held[name] = held
            raise ToolError(
                "forbidden",
                f"只有 owner 可以关闭会话 {name}",
                details={"owner": actor.owner},
            )
        info = actor.info(agent)
        with self._actor_lock(name):
            actor.close()
        if held:
            self._pool.release()
        info["closed"] = True
        return info

    def share(
        self,
        name: str,
        requester: str,
        agent: str,
        mode: str = "read",
        ttl: float | None = None,
    ) -> dict[str, Any]:
        actor = self.peek(name)
        if actor is None:
            raise ToolError(
                "session_not_found",
                f"会话不存在：{name}",
                hint="session_list 可查看现有会话",
            )
        if requester != actor.owner:
            raise ToolError(
                "forbidden",
                f"只有 owner 可以共享会话 {name}",
                details={"owner": actor.owner},
            )
        result = actor.share(agent, mode, ttl)
        return {"session": name, **result}

    def _idle_loop(self) -> None:
        timeout = self.settings.idle_timeout
        interval = self.settings.idle_check_interval
        interval = max(0.2, min(interval, max(0.5, timeout / 4)))
        while not self._stop.wait(interval):
            try:
                self._sweep_idle()
            except Exception:
                log.warning("空闲回收扫描失败", exc_info=True)

    def _sweep_idle(self) -> None:
        if self._closed:
            return
        now = time.monotonic()
        with self._lock:
            candidates = [
                actor
                for actor in self._sessions.values()
                if not actor.closed
                and not actor.suspended
                and now - actor.last_used >= self.settings.idle_timeout
            ]
        for actor in candidates:
            with self._actor_lock(actor.name):
                if (
                    actor.closed
                    or actor.suspended
                    or time.monotonic() - actor.last_used < self.settings.idle_timeout
                ):
                    continue
                try:
                    suspended = actor.suspend(
                        if_idle_for=self.settings.idle_timeout
                    )
                except Exception:
                    log.warning("空闲挂起会话 %s 失败", actor.name, exc_info=True)
                    continue
                if not suspended:
                    continue
                with self._lock:
                    if self._permit_held.get(actor.name):
                        self._permit_held[actor.name] = False
                        self._pool.release()

    def close_all(self) -> None:
        self._closed = True
        self._stop.set()
        with self._lock:
            actors = list(self._sessions.values())
            self._sessions.clear()
            self._permit_held.clear()
        for actor in actors:
            try:
                actor.close()
            except Exception:
                log.warning("关闭会话 %s 失败", actor.name, exc_info=True)
