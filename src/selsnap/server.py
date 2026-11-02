from __future__ import annotations

import logging
from typing import Any, Callable
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer

from .config import Settings, load_settings
from .errors import ToolError
from .sessions import SessionRegistry, SessionActor

log = logging.getLogger(__name__)

mcp = MCPServer("selsnap", version="0.1.0")

_settings: Settings | None = None
_registry: SessionRegistry | None = None


def _get_settings() -> Settings:
    if _settings is None:
        raise ToolError("server_not_ready", "服务尚未初始化")
    return _settings


def _get_registry() -> SessionRegistry:
    if _registry is None:
        raise ToolError("server_not_ready", "服务尚未初始化")
    return _registry


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


def _snapshot_payload(session: str, actor: SessionActor, settings: Settings) -> dict[str, Any]:
    result = actor.call(
        lambda: actor.backend.snapshot(
            settings.snapshot_max_nodes, settings.snapshot_max_chars
        )
    )
    return {"ok": True, "session": session, **result}


@mcp.tool()
def session_open(
    name: str,
    mode: str = "standard",
    headless: bool | None = None,
) -> dict:
    """打开（或复用）一个浏览器会话。

    Args:
        name: 会话名，1-64 位字母、数字、点、下划线或短横线
        mode: standard（默认）、uc（反检测）或 cdp（纯 CDP）
        headless: 是否无头；缺省使用服务配置
    """
    return _guarded(lambda: {"ok": True, **_get_registry().open(name, mode, headless)})


@mcp.tool()
def session_attach(name: str) -> dict:
    """附加到已存在的浏览器会话，返回会话信息。

    Args:
        name: 会话名
    """
    return _guarded(lambda: {"ok": True, **_get_registry().get(name).info()})


@mcp.tool()
def session_list() -> dict:
    """列出当前服务持有的全部浏览器会话。"""
    return _guarded(lambda: {"ok": True, "sessions": _get_registry().list()})


@mcp.tool()
def session_close(name: str) -> dict:
    """关闭浏览器会话并释放浏览器进程。

    Args:
        name: 会话名
    """
    return _guarded(lambda: {"ok": True, "closed": _get_registry().close(name)})


@mcp.tool()
def session_share(name: str, agent: str, mode: str = "read") -> dict:
    """预留：会话共享（M0 尚未实现）。"""
    return ToolError(
        "not_implemented",
        "会话共享将在 M2 实现",
        hint="当前所有会话归本机默认 agent 所有",
    ).to_payload()


@mcp.tool()
def navigate(session: str, url: str) -> dict:
    """导航到 URL，并在加载完成后返回页面快照。

    Args:
        session: 会话名
        url: http/https 地址（无 scheme 时按 https 处理）
    """
    def run() -> dict[str, Any]:
        settings = _get_settings()
        actor = _get_registry().get(session)
        target = _normalize_url(url)

        def op() -> dict[str, Any]:
            actor.backend.navigate(target)
            return actor.backend.snapshot(
                settings.snapshot_max_nodes, settings.snapshot_max_chars
            )

        snap = actor.call(op)
        return {"ok": True, "session": session, **snap}

    return _guarded(run)


@mcp.tool()
def snapshot(session: str) -> dict:
    """返回当前页面快照（稳定 ref + 语义文本）。

    Args:
        session: 会话名
    """
    return _guarded(
        lambda: _snapshot_payload(session, _get_registry().get(session), _get_settings())
    )


@mcp.tool()
def page_info(session: str) -> dict:
    """返回当前页面的 URL、标题、doc_id 与 readyState。

    Args:
        session: 会话名
    """
    def run() -> dict[str, Any]:
        actor = _get_registry().get(session)

        def op() -> dict[str, Any]:
            return {
                "url": actor.backend.current_url,
                "title": actor.backend.title,
                "doc_id": actor.backend.doc_id(),
                "ready_state": actor.backend.execute_script(
                    "(() => document.readyState)()"
                ),
            }

        return {"ok": True, "session": session, **actor.call(op)}

    return _guarded(run)


def main(argv: list[str] | None = None) -> None:
    global _settings, _registry

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _settings = load_settings(argv)
    if _settings.token:
        log.warning("SELSNAP_TOKEN 已配置，但 Bearer 鉴权尚未实现（计划 M2）")
    if not _settings.browser_path:
        log.warning("未找到项目内 Chrome，SeleniumBase 将自动发现浏览器（可能不稳定）")
    _registry = SessionRegistry(_settings)
    log.info(
        "selsnap 启动：http://%s:%s%s（pool=%s, headless=%s）",
        _settings.host,
        _settings.port,
        _settings.path,
        _settings.pool_size,
        _settings.headless,
    )
    try:
        mcp.run(
            transport="streamable-http",
            host=_settings.host,
            port=_settings.port,
            streamable_http_path=_settings.path,
        )
    finally:
        _registry.close_all()


if __name__ == "__main__":
    main()
