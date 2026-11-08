from __future__ import annotations

import base64
import functools
import inspect
import json
import logging
import time
from typing import Any, Callable
from urllib.parse import urlparse

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent

from .actions import ActionRunner
from .audit import AuditLogger, sanitize_arguments
from .config import Settings, load_settings
from .errors import ToolError
from .identity import (
    BearerAuthMiddleware,
    build_token_map,
    current_agent,
)
from .maintenance import cleanup_orphans
from .screenshots import capture_screenshot
from .sessions import SessionActor, SessionRegistry

log = logging.getLogger(__name__)

mcp = MCPServer("selsnap", version="0.2.0")

_settings: Settings | None = None
_registry: SessionRegistry | None = None
_audit: AuditLogger | None = None


def _get_settings() -> Settings:
    if _settings is None:
        raise ToolError("server_not_ready", "服务尚未初始化")
    return _settings


def _get_registry() -> SessionRegistry:
    if _registry is None:
        raise ToolError("server_not_ready", "服务尚未初始化")
    return _registry


def _agent() -> str:
    default = _settings.default_agent if _settings else "local"
    return current_agent(default)


def _get_actor(session: str, access: str = "read") -> SessionActor:
    return _get_registry().get(session, _agent(), access)


def _guarded(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except ToolError as exc:
        return exc.to_payload()
    except Exception as exc:
        log.exception("工具执行失败")
        return ToolError(
            "internal_error",
            f"{type(exc).__name__}: {exc}",
            hint="查看服务端日志",
        ).to_payload()


def _record_audit(
    tool_name: str,
    arguments: dict[str, Any],
    agent: str,
    started: float,
    result: Any,
    error: BaseException | None,
) -> None:
    if _audit is None or not _audit.enabled:
        return
    session_name = arguments.get("session") or arguments.get("name")
    owner = None
    if session_name and _registry is not None:
        try:
            actor = _registry.peek(str(session_name))
            owner = actor.owner if actor else None
        except Exception:
            owner = None

    ok = True
    code = None
    url = None
    doc_id = None
    if error is not None:
        ok = False
        code = getattr(error, "code", None) or type(error).__name__
    elif isinstance(result, CallToolResult):
        ok = not result.is_error
        structured = result.structured_content
        if isinstance(structured, dict):
            code = (structured.get("error") or {}).get("code")
            url = structured.get("url")
            doc_id = structured.get("doc_id")
    elif isinstance(result, dict):
        ok = bool(result.get("ok", True))
        code = (result.get("error") or {}).get("code")
        url = result.get("url")
        doc_id = result.get("doc_id")

    try:
        _audit.record(
            {
                "agent": agent,
                "owner": owner,
                "tool": tool_name,
                "session": session_name,
                "args": sanitize_arguments(tool_name, arguments),
                "ok": ok,
                "error_code": code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "url": url,
                "doc_id": doc_id,
            }
        )
    except Exception:
        log.warning("审计记录失败", exc_info=True)


def _tool(name: str | None = None, *, structured_output: bool | None = None):
    def decorator(fn):
        signature = inspect.signature(fn)
        tool_name = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            agent = _agent()
            try:
                bound = signature.bind_partial(*args, **kwargs)
                arguments = dict(bound.arguments)
            except TypeError:
                arguments = dict(kwargs)
            result: Any = None
            error: BaseException | None = None
            try:
                result = fn(*args, **kwargs)
                return result
            except BaseException as exc:
                error = exc
                raise
            finally:
                _record_audit(tool_name, arguments, agent, started, result, error)

        wrapper.__signature__ = signature
        return mcp.tool(name=name, structured_output=structured_output)(wrapper)

    return decorator


BLOCKED_SCHEMES = {
    "file",
    "javascript",
    "data",
    "about",
    "chrome",
    "view-source",
    "ftp",
    "mailto",
    "tel",
    "blob",
    "ws",
    "wss",
}


def _normalize_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ToolError("invalid_argument", "url 不能为空")
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.scheme.lower() in ("http", "https") and "://" in value:
        pass
    elif parsed.scheme.lower() in BLOCKED_SCHEMES:
        raise ToolError(
            "policy_blocked",
            f"不允许的 URL scheme：{parsed.scheme}",
            hint="只允许 http / https",
        )
    else:
        value = "https://" + value
        parsed = urlparse(value)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ToolError(
            "policy_blocked",
            f"不允许的 URL scheme：{parsed.scheme}",
            hint="只允许 http / https",
        )
    if not parsed.netloc:
        raise ToolError("invalid_argument", f"URL 缺少主机名：{value}")
    if parsed.username or parsed.password:
        raise ToolError("policy_blocked", "URL 中不允许包含用户名或密码")
    return value


def _capture_snapshot(actor: SessionActor, settings: Settings) -> dict[str, Any]:
    result = actor.backend.snapshot(
        settings.snapshot_max_nodes,
        settings.snapshot_max_chars,
        ref_base=actor.next_ref_base,
    )
    actor.record_snapshot(result)
    return result


def _public_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "tree"}


def _snapshot_payload(session: str, actor: SessionActor, settings: Settings) -> dict[str, Any]:
    result = actor.call(lambda: _capture_snapshot(actor, settings))
    return {"ok": True, "session": session, **_public_snapshot(result)}


def _attach_error_snapshot(session: str, exc: ToolError) -> None:
    if exc.code != "stale_ref":
        return
    try:
        settings = _get_settings()
        actor = _get_registry().get(session, _agent(), "read")
    except ToolError:
        return
    try:
        result = actor.call(lambda: _capture_snapshot(actor, settings))
    except Exception:
        return
    exc.details.setdefault("snapshot", result.get("snapshot") or "")
    exc.details.setdefault("doc_id", result.get("doc_id"))
    exc.details.setdefault("url", result.get("url"))


def _action(
    session: str, run: Callable[[ActionRunner], dict[str, Any]]
) -> dict[str, Any]:
    try:
        actor = _get_actor(session, "write")

        def execute() -> dict[str, Any]:
            runner = ActionRunner(actor, _get_settings())
            return run(runner)

        result = actor.call(execute)
        return {"ok": True, "session": session, **result}
    except ToolError as exc:
        _attach_error_snapshot(session, exc)
        return exc.to_payload()
    except Exception as exc:
        log.exception("动作执行失败")
        return ToolError(
            "internal_error",
            f"{type(exc).__name__}: {exc}",
            hint="查看服务端日志",
        ).to_payload()


@_tool()
def session_open(
    name: str,
    mode: str = "standard",
    headless: bool | None = None,
    auto_escalate: bool = False,
) -> dict:
    """打开（或复用）一个浏览器会话。

    Args:
        name: 会话名，1-64 位字母、数字、点、下划线或短横线
        mode: standard（默认）、uc（反检测）或 cdp（纯 CDP）
        headless: 是否无头；缺省使用服务配置
        auto_escalate: 导航遇到挑战页时是否自动升级到更强模式
    """
    return _guarded(
        lambda: {
            "ok": True,
            **_get_registry().open(
                name,
                mode,
                headless,
                agent=_agent(),
                auto_escalate=auto_escalate,
            ),
        }
    )


@_tool()
def session_attach(name: str) -> dict:
    """附加到已存在的浏览器会话，返回会话信息（挂起会话会自动恢复）。

    Args:
        name: 会话名
    """
    return _guarded(lambda: {"ok": True, **_get_registry().get(name, _agent(), "read").info(_agent())})


@_tool()
def session_list() -> dict:
    """列出当前 agent 可见的浏览器会话（自己的与被共享的）。"""
    return _guarded(lambda: {"ok": True, "sessions": _get_registry().list(_agent())})


@_tool()
def session_close(name: str) -> dict:
    """关闭浏览器会话并释放浏览器进程（仅 owner）。

    Args:
        name: 会话名
    """
    return _guarded(lambda: {"ok": True, "closed": _get_registry().close(name, _agent())})


@_tool()
def session_share(
    name: str,
    agent: str,
    mode: str = "read",
    ttl: float | None = None,
) -> dict:
    """将会话共享给另一个 agent（仅 owner）。

    Args:
        name: 会话名
        agent: 被授权 agent 名
        mode: read / write / revoke
        ttl: 可选授权有效期（秒），最长 30 天；缺省不过期
    """
    return _guarded(
        lambda: {
            "ok": True,
            **_get_registry().share(
                name, _agent(), agent, mode=mode, ttl=ttl
            ),
        }
    )


@_tool()
def session_escalate(session: str, mode: str | None = None) -> dict:
    """将会话重启到更强的浏览器模式（standard → uc → cdp），保留 profile。

    Args:
        session: 会话名
        mode: 目标模式；缺省升级到下一档
    """
    def run() -> dict[str, Any]:
        settings = _get_settings()
        actor = _get_actor(session, "write")

        def op() -> dict[str, Any]:
            target = mode or actor.next_mode()
            if target is None:
                raise ToolError(
                    "invalid_mode",
                    "会话已处于最强模式 cdp，无法继续升级",
                )
            info = actor.escalate_locked(target)
            snap = _capture_snapshot(actor, settings)
            return {
                "target_mode": info["mode"],
                "browser_version": info["browser_version"],
                "previous_url": info["url"],
                "challenge": actor.backend.detect_challenge(),
                **_public_snapshot(snap),
            }

        return {"ok": True, "session": session, **actor.call(op)}

    return _guarded(run)


@_tool()
def navigate(session: str, url: str) -> dict:
    """导航到 URL，并在加载完成后返回页面快照。

    Args:
        session: 会话名
        url: http/https 地址（无 scheme 时按 https 处理）
    """
    def run() -> dict[str, Any]:
        settings = _get_settings()
        actor = _get_actor(session, "write")
        target = _normalize_url(url)

        def op() -> dict[str, Any]:
            actor.backend.navigate(target)
            snap = _capture_snapshot(actor, settings)
            challenge = actor.backend.detect_challenge()
            escalated_to = None
            if challenge.get("detected") and actor.auto_escalate and actor.mode != "cdp":
                next_mode = actor.next_mode()
                if next_mode:
                    info = actor.escalate_locked(next_mode)
                    snap = _capture_snapshot(actor, settings)
                    challenge = actor.backend.detect_challenge()
                    escalated_to = info["mode"]
            return {
                **_public_snapshot(snap),
                "challenge": challenge,
                "escalated_to": escalated_to,
            }

        return {"ok": True, "session": session, **actor.call(op)}

    return _guarded(run)


@_tool()
def snapshot(session: str) -> dict:
    """返回当前页面快照（稳定 ref + 语义文本）。

    Args:
        session: 会话名
    """
    return _guarded(
        lambda: _snapshot_payload(session, _get_actor(session, "read"), _get_settings())
    )


@_tool()
def page_info(session: str) -> dict:
    """返回当前页面的 URL、标题、doc_id、readyState 与挑战检测结果。

    Args:
        session: 会话名
    """
    def run() -> dict[str, Any]:
        actor = _get_actor(session, "read")

        def op() -> dict[str, Any]:
            return {
                "url": actor.backend.current_url,
                "title": actor.backend.title,
                "doc_id": actor.backend.doc_id(),
                "ready_state": actor.backend.execute_script(
                    "(() => document.readyState)()"
                ),
                "challenge": actor.backend.detect_challenge(),
            }

        return {"ok": True, "session": session, **actor.call(op)}

    return _guarded(run)


@_tool(structured_output=False)
def screenshot(
    session: str,
    ref: str | None = None,
    full_page: bool = False,
    annotate: bool = False,
) -> CallToolResult:
    """截图并返回 PNG 图像内容；可截取视口、整页或单个元素。

    Args:
        session: 会话名
        ref: 可选；元素 ref，给出时返回元素截图
        full_page: 是否截取整页（ref 存在时自动整页再裁剪）
        annotate: 是否在截图上叠加 ref 标注气泡
    """
    try:
        settings = _get_settings()
        actor = _get_actor(session, "read")

        def op() -> tuple[bytes, dict[str, Any]]:
            started = time.perf_counter()
            data, meta = capture_screenshot(
                actor,
                settings,
                ref=ref,
                full_page=full_page,
                annotate=annotate,
            )
            meta["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return data, meta

        data, meta = actor.call(op)
        encoded = base64.b64encode(data).decode("ascii")
        return CallToolResult(
            content=[
                ImageContent(type="image", data=encoded, mimeType="image/png"),
                TextContent(
                    type="text", text=json.dumps(meta, ensure_ascii=False)
                ),
            ],
            structured_content=meta,
        )
    except ToolError as exc:
        _attach_error_snapshot(session, exc)
        payload = exc.to_payload()
        return CallToolResult(
            content=[
                TextContent(
                    type="text", text=json.dumps(payload, ensure_ascii=False)
                )
            ],
            structured_content=payload,
            is_error=True,
        )
    except Exception as exc:
        log.exception("截图失败")
        payload = ToolError(
            "internal_error",
            f"{type(exc).__name__}: {exc}",
            hint="查看服务端日志",
        ).to_payload()
        return CallToolResult(
            content=[
                TextContent(
                    type="text", text=json.dumps(payload, ensure_ascii=False)
                )
            ],
            structured_content=payload,
            is_error=True,
        )


@_tool()
def click(
    session: str,
    ref: str,
    button: str = "left",
    count: int = 1,
    full: bool = False,
) -> dict:
    """点击快照中的元素。

    Args:
        session: 会话名
        ref: 快照中的元素引用，如 e12
        button: 鼠标键，left（默认）或 right
        count: 点击次数，1（默认）或 2（双击）
        full: 强制返回动作后的完整快照（默认仅返回 diff）
    """
    return _action(
        session,
        lambda runner: runner.click(ref, button=button, count=count, full=full),
    )


@_tool("type")
def type_text(
    session: str,
    ref: str,
    text: str,
    clear: bool = True,
    submit: bool = False,
    full: bool = False,
) -> dict:
    """向输入元素输入文本。

    Args:
        session: 会话名
        ref: 快照中的元素引用，如 e12
        text: 要输入的文本
        clear: 输入前清空现有内容（默认 True）
        submit: 输入后按 Enter（默认 False）
        full: 强制返回动作后的完整快照（默认仅返回 diff）
    """
    return _action(
        session,
        lambda runner: runner.type_text(
            ref, text, clear=clear, submit=submit, full=full
        ),
    )


@_tool("select")
def select_option(session: str, ref: str, option: str, full: bool = False) -> dict:
    """选择原生下拉框中的选项。

    Args:
        session: 会话名
        ref: 快照中的下拉框引用
        option: 选项的 value 或可见文本（大小写不敏感）
        full: 强制返回动作后的完整快照（默认仅返回 diff）
    """
    return _action(session, lambda runner: runner.select(ref, option, full=full))


@_tool()
def press(session: str, keys: str, ref: str | None = None, full: bool = False) -> dict:
    """向当前焦点或指定元素发送按键。

    Args:
        session: 会话名
        keys: 按键或组合，如 Enter、Tab、Control+a、Shift+Tab
        ref: 可选；给出时先聚焦该元素
        full: 强制返回动作后的完整快照（默认仅返回 diff）
    """
    return _action(session, lambda runner: runner.press(keys, ref=ref, full=full))


@_tool()
def hover(session: str, ref: str, full: bool = False) -> dict:
    """将鼠标悬停到元素上。

    Args:
        session: 会话名
        ref: 快照中的元素引用
        full: 强制返回动作后的完整快照（默认仅返回 diff）
    """
    return _action(session, lambda runner: runner.hover(ref, full=full))


@_tool()
def scroll(
    session: str,
    ref: str | None = None,
    dy: int = 600,
    full: bool = False,
) -> dict:
    """滚动页面；给出 ref 时将该元素滚动到视口中央。

    Args:
        session: 会话名
        ref: 可选；为目标元素引用
        dy: 无 ref 时的垂直滚动像素（正数向下）
        full: 强制返回动作后的完整快照（默认仅返回 diff）
    """
    return _action(
        session, lambda runner: runner.scroll(ref=ref, dy=dy, full=full)
    )


@_tool()
def click_at(
    session: str,
    x: float,
    y: float,
    button: str = "left",
    count: int = 1,
    full: bool = False,
) -> dict:
    """按视口坐标点击（用于 canvas 或没有 ref 的区域）。

    Args:
        session: 会话名
        x: 视口内 x 坐标（CSS 像素）
        y: 视口内 y 坐标（CSS 像素）
        button: 鼠标键，left / right
        count: 点击次数，1 / 2
        full: 强制返回动作后的完整快照（默认仅返回 diff）
    """
    return _action(
        session,
        lambda runner: runner.click_at(x, y, button=button, count=count, full=full),
    )


@_tool()
def dialog(
    session: str,
    action: str = "accept",
    text: str | None = None,
    full: bool = False,
) -> dict:
    """处理原生 alert/confirm/prompt 对话框。

    Args:
        session: 会话名
        action: accept（确认）或 dismiss（取消）
        text: prompt 对话框要输入的文本
        full: 强制返回动作后的完整快照（默认仅返回 diff）
    """
    return _action(
        session, lambda runner: runner.dialog(action, text=text, full=full)
    )


def _build_app(settings: Settings):
    app = mcp.streamable_http_app(
        streamable_http_path=settings.path,
        host=settings.host,
    )
    token_map = build_token_map(
        settings.token, settings.tokens_json, settings.default_agent
    )
    app.add_middleware(
        BearerAuthMiddleware,
        token_map=token_map,
        default_agent=settings.default_agent,
    )
    return app, token_map


def main(argv: list[str] | None = None) -> None:
    global _settings, _registry, _audit

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _settings = load_settings(argv)
    try:
        _audit = AuditLogger(_settings.audit_dir, _settings.audit_enabled)
        app, token_map = _build_app(_settings)
    except ValueError as exc:
        raise SystemExit(f"配置错误：{exc}") from exc

    cleanup_orphans(_settings.profile_root)
    if not _settings.browser_path:
        log.warning("未找到项目内 Chrome，SeleniumBase 将自动发现浏览器（可能不稳定）")
    _registry = SessionRegistry(_settings)
    log.info(
        "selsnap 启动：http://%s:%s%s（pool=%s, headless=%s, auth=%s）",
        _settings.host,
        _settings.port,
        _settings.path,
        _settings.pool_size,
        _settings.headless,
        "on" if token_map else "off",
    )
    try:
        uvicorn.run(
            app,
            host=_settings.host,
            port=_settings.port,
            log_level="info",
        )
    finally:
        _registry.close_all()


if __name__ == "__main__":
    main()
