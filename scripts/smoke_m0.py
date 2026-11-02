from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"
HOST = "127.0.0.1"
PORT = 8799
PATH = "/mcp"
URL = f"http://{HOST}:{PORT}{PATH}"
DEMO = "https://seleniumbase.io/demo_page"


def port_is_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.5)
        sock.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def wait_port(port: int, timeout: float, proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if not port_is_free(port):
            return True
        time.sleep(0.15)
    return False


def wait_port_closed(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_free(port):
            return True
        time.sleep(0.15)
    return False


def payload(result) -> dict:
    structured = result.structured_content
    if isinstance(structured, dict):
        if set(structured.keys()) == {"result"}:
            value = structured["result"]
            return value if isinstance(value, dict) else {"result": value}
        return structured
    texts = []
    for block in result.content:
        if getattr(block, "type", None) == "text":
            texts.append(block.text)
    try:
        return json.loads("\n".join(texts))
    except Exception:
        return {"text": "\n".join(texts)}


def check(checks: list[dict], name: str, ok: bool, detail=None) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


async def run_checks() -> dict:
    checks: list[dict] = []
    info: dict = {}
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(30.0, read=180.0)) as http_client:
        async with streamable_http_client(URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                info["protocol_version"] = init.protocol_version
                tools = (await session.list_tools()).tools
                names = {tool.name for tool in tools}
                expected = {
                    "session_open",
                    "session_attach",
                    "session_list",
                    "session_close",
                    "navigate",
                    "snapshot",
                    "page_info",
                }
                check(checks, "工具面包含 M0 工具", expected <= names, sorted(names))

                opened = payload(
                    await session.call_tool(
                        "session_open", {"name": "smoke", "mode": "standard"}
                    )
                )
                info["open"] = opened
                check(
                    checks,
                    "standard 会话打开",
                    opened.get("ok") is True and opened.get("browser_version"),
                    opened,
                )

                nav = payload(
                    await session.call_tool(
                        "navigate", {"session": "smoke", "url": DEMO}
                    )
                )
                info["navigate"] = {
                    "ok": nav.get("ok"),
                    "url": nav.get("url"),
                    "title": nav.get("title"),
                    "doc_id": nav.get("doc_id"),
                    "stats": nav.get("stats"),
                    "chars": len(nav.get("snapshot") or ""),
                }
                check(
                    checks,
                    "导航并返回快照",
                    nav.get("ok") is True
                    and bool(nav.get("doc_id"))
                    and len(nav.get("snapshot") or "") > 0,
                    info["navigate"],
                )

                refs1 = set(re.findall(r"\[(e\d+)\]", nav.get("snapshot") or ""))
                snap2 = payload(
                    await session.call_tool("snapshot", {"session": "smoke"})
                )
                refs2 = set(re.findall(r"\[(e\d+)\]", snap2.get("snapshot") or ""))
                info["refs"] = {"first": len(refs1), "second": len(refs2)}
                check(
                    checks,
                    "快照 ref 稳定",
                    bool(refs1) and refs1 <= refs2 and snap2.get("doc_id") == nav.get("doc_id"),
                    info["refs"],
                )

                page = payload(
                    await session.call_tool("page_info", {"session": "smoke"})
                )
                info["page"] = page
                check(
                    checks,
                    "page_info 正确",
                    page.get("ok") is True
                    and DEMO in (page.get("url") or "")
                    and page.get("ready_state") in ("interactive", "complete"),
                    page,
                )

                cdp_open = payload(
                    await session.call_tool(
                        "session_open", {"name": "smoke-cdp", "mode": "cdp"}
                    )
                )
                cdp_nav = payload(
                    await session.call_tool(
                        "navigate", {"session": "smoke-cdp", "url": DEMO}
                    )
                )
                info["cdp"] = {
                    "open": cdp_open,
                    "navigate_ok": cdp_nav.get("ok"),
                    "chars": len(cdp_nav.get("snapshot") or ""),
                }
                check(
                    checks,
                    "cdp 会话导航并返回快照",
                    cdp_open.get("ok") is True
                    and cdp_nav.get("ok") is True
                    and len(cdp_nav.get("snapshot") or "") > 0,
                    info["cdp"],
                )

                listed = payload(
                    await session.call_tool("session_list", {})
                )
                check(
                    checks,
                    "session_list 返回两个会话",
                    len(listed.get("sessions") or []) == 2,
                    listed,
                )

                closed = payload(
                    await session.call_tool("session_close", {"name": "smoke"})
                )
                closed_cdp = payload(
                    await session.call_tool("session_close", {"name": "smoke-cdp"})
                )
                listed_after = payload(
                    await session.call_tool("session_list", {})
                )
                check(
                    checks,
                    "会话关闭后列表为空",
                    closed.get("ok") is True
                    and closed_cdp.get("ok") is True
                    and listed_after.get("sessions") == [],
                    {"closed": closed, "closed_cdp": closed_cdp, "after": listed_after},
                )
    return {"checks": checks, "info": info}


def main() -> int:
    VAR.mkdir(exist_ok=True)
    stdout_log = VAR / "smoke_m0.stdout.log"
    stderr_log = VAR / "smoke_m0.stderr.log"
    result: dict = {"checks": [], "info": {}}
    proc = None
    stdout_file = None
    stderr_file = None
    try:
        if not port_is_free(PORT):
            raise RuntimeError(f"端口 {PORT} 被占用")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        stdout_file = open(stdout_log, "w", encoding="utf-8")
        stderr_file = open(stderr_log, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "selsnap.server", "--port", str(PORT)],
            cwd=str(ROOT),
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
        )
        if not wait_port(PORT, 30.0, proc):
            raise RuntimeError("服务未在 30 秒内监听端口")
        result = asyncio.run(run_checks())
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if stdout_file is not None:
            stdout_file.close()
        if stderr_file is not None:
            stderr_file.close()
        result["port_released"] = wait_port_closed(PORT, 10.0)
        result["server_exit_code"] = None if proc is None else proc.returncode
        result["stderr_tail"] = (
            stderr_log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
            if stderr_log.exists()
            else []
        )
        (VAR / "smoke_m0.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    failed = [item for item in result.get("checks", []) if not item["ok"]]
    summary = {
        "checks": len(result.get("checks", [])),
        "failed": [item["name"] for item in failed],
        "fatal_error": result.get("fatal_error"),
        "port_released": result.get("port_released"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failed and not result.get("fatal_error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
