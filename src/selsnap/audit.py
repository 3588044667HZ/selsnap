from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SENSITIVE_KEYS = ("token", "password", "secret", "authorization", "api_key", "apikey")
MAX_ARG_TEXT = 2000


def _digest(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8", "replace")
    return {
        "len": len(value),
        "sha256": hashlib.sha256(encoded).hexdigest()[:16],
    }


def sanitize_arguments(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in arguments.items():
        lowered = key.lower()
        if any(name in lowered for name in SENSITIVE_KEYS):
            sanitized[key] = "***"
            continue
        if tool == "type" and key == "text":
            sanitized[key] = _digest("" if value is None else str(value))
            continue
        if isinstance(value, str) and len(value) > MAX_ARG_TEXT:
            sanitized[key] = value[:MAX_ARG_TEXT] + "…"
        else:
            sanitized[key] = value
    return sanitized


class AuditLogger:
    def __init__(self, directory: str, enabled: bool = True) -> None:
        self.directory = Path(directory)
        self.enabled = enabled
        self._lock = threading.Lock()
        self._warned = False
        if self.enabled:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
            except OSError:
                log.warning("无法创建审计目录 %s，审计将降级为仅日志", self.directory)
                self.enabled = False

    def record(self, entry: dict[str, Any]) -> None:
        if not self.enabled:
            return
        now = datetime.now(timezone.utc)
        payload = {"ts": now.isoformat(), **entry}
        line = json.dumps(payload, ensure_ascii=False, default=str)
        path = self.directory / f"audit-{now.strftime('%Y-%m-%d')}.jsonl"
        try:
            with self._lock:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError as exc:
            if not self._warned:
                log.warning("写入审计日志失败：%s", exc)
                self._warned = True
