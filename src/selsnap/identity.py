from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

AGENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_current_agent: ContextVar[str | None] = ContextVar("selsnap_agent", default=None)


def current_agent(default: str = "local") -> str:
    return _current_agent.get() or default


def set_current_agent(agent: str):
    return _current_agent.set(agent)


def reset_current_agent(token) -> None:
    _current_agent.reset(token)


def build_token_map(
    single_token: str | None, tokens_json: str | None, default_agent: str
) -> dict[str, str]:
    if not AGENT_RE.match(default_agent):
        raise ValueError(
            "默认 agent 名必须是 1-64 位字母、数字、点、下划线或短横线"
        )
    mapping: dict[str, str] = {}
    if tokens_json:
        try:
            data = json.loads(tokens_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"SELSNAP_TOKENS 不是合法 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("SELSNAP_TOKENS 必须是 {token: agent} 形式的 JSON 对象")
        for token, agent in data.items():
            if not isinstance(token, str) or not token.strip():
                raise ValueError("SELSNAP_TOKENS 中存在空 token")
            if not isinstance(agent, str) or not AGENT_RE.match(agent):
                raise ValueError(
                    f"SELSNAP_TOKENS 中 token 对应的 agent 名不合法：{agent!r}"
                )
            mapping[token] = agent
    if single_token:
        mapping[single_token] = default_agent
    return mapping


def _unauthorized_body() -> bytes:
    return json.dumps(
        {
            "ok": False,
            "error": {
                "code": "unauthorized",
                "message": "缺少或无效的 Bearer token",
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


async def _send_unauthorized(send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    body = _unauthorized_body()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


class BearerAuthMiddleware:
    """纯 ASGI 中间件：校验所有 HTTP 请求的 Bearer token 并注入 agent 身份。"""

    def __init__(self, app, token_map: dict[str, str], default_agent: str) -> None:
        self.app = app
        self.token_map = token_map
        self.default_agent = default_agent

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or not self.token_map:
            token = set_current_agent(self.default_agent)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_current_agent(token)
            return

        headers = {key.lower(): value for key, value in scope.get("headers") or []}
        raw = headers.get(b"authorization", b"").decode("latin-1").strip()
        bearer = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
        agent = self.token_map.get(bearer)
        if agent is None:
            await _send_unauthorized(send)
            return

        token = set_current_agent(agent)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_agent(token)
