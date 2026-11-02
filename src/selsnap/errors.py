from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolError(Exception):
    code: str
    message: str
    hint: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {"code": self.code, "message": self.message},
        }
        if self.hint:
            payload["error"]["hint"] = self.hint
        if self.details:
            payload["error"]["details"] = self.details
        return payload
