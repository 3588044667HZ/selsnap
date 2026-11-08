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
PORT = 8798
PATH = "/mcp"
URL = f"http://{HOST}:{PORT}{PATH}"
DEMO = "https://seleniumbase.io/demo_page"

BUTTON_GREEN = re.compile(r'^\s*- button "Click Me \(Green\)" \[(?P<ref>e\d+)\]', re.M)
TEXTBOX = re.compile(r'^\s*- textbox \[(?P<ref>e\d+)\] type="text"$', re.M)
SELECT = re.compile(r'^\s*- combobox "selectName" \[(?P<ref>e\d+)\]', re.M)
LINK = re.compile(r'^\s*- link "[^"]+" \[(?P<ref>e\d+)\]', re.M)
DEMO_LINK = re.compile(r'^\s*- link "SeleniumBase Demo Page" \[(?P<ref>e\d+)\]', re.M)


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


def ref_of(pattern: re.Pattern, snapshot: str) -> str | None:
    match = pattern.search(snapshot or "")
    return match.group("ref") if match else None


def updated_text(data: dict) -> str:
    diff = data.get("diff") or {}
    return "\n".join(diff.get("updated") or [])


async def call(session: ClientSession, tool: str, args: dict) -> dict:
    return payload(await session.call_tool(tool, args))


async def run_checks() -> dict:
    checks: list[dict] = []
    info: dict = {}
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(30.0, read=240.0)) as http_client:
        async with streamable_http_client(URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                info["protocol_version"] = init.protocol_version
                names = {tool.name for tool in (await session.list_tools()).tools}
                expected = {
                    "session_open",
                    "session_attach",
                    "session_list",
                    "session_close",
                    "navigate",
                    "snapshot",
                    "page_info",
                    "click",
                    "type",
                    "select",
                    "press",
                    "hover",
                    "scroll",
                }
                check(checks, "工具面包含 M1 动作工具", expected <= names, sorted(names))

                opened = await call(session, "session_open", {"name": "m1-std", "mode": "standard"})
                check(
                    checks,
                    "standard 会话打开",
                    opened.get("ok") is True and bool(opened.get("browser_version")),
                    opened,
                )
                nav = await call(session, "navigate", {"session": "m1-std", "url": DEMO})
                snapshot = nav.get("snapshot") or ""
                info["std_nav"] = {
                    "ok": nav.get("ok"),
                    "doc_id": nav.get("doc_id"),
                    "chars": len(snapshot),
                }
                check(
                    checks,
                    "standard 导航并返回快照",
                    nav.get("ok") is True and bool(nav.get("doc_id")) and bool(snapshot),
                    info["std_nav"],
                )

                button = ref_of(BUTTON_GREEN, snapshot)
                textbox = ref_of(TEXTBOX, snapshot)
                select_ref = ref_of(SELECT, snapshot)
                link = ref_of(LINK, snapshot)
                demo_link = ref_of(DEMO_LINK, snapshot)
                info["std_refs"] = {
                    "button": button,
                    "textbox": textbox,
                    "select": select_ref,
                    "link": link,
                    "demo_link": demo_link,
                }
                check(
                    checks,
                    "从快照解析出动作 ref",
                    all((button, textbox, select_ref, link, demo_link)),
                    info["std_refs"],
                )

                started = time.perf_counter()
                click1 = await call(session, "click", {"session": "m1-std", "ref": button})
                info["std_click_ms"] = round((time.perf_counter() - started) * 1000)
                info["std_click1"] = click1
                check(
                    checks,
                    "standard 点击按钮并返回 diff",
                    click1.get("ok") is True
                    and click1.get("changed") is True
                    and "Click Me (Purple)" in updated_text(click1),
                    click1,
                )

                click2 = await call(session, "click", {"session": "m1-std", "ref": button})
                check(
                    checks,
                    "standard 再次点击恢复状态",
                    click2.get("ok") is True
                    and "Click Me (Green)" in updated_text(click2),
                    click2,
                )

                started = time.perf_counter()
                typed = await call(
                    session,
                    "type",
                    {"session": "m1-std", "ref": textbox, "text": "hello selsnap"},
                )
                info["std_type_ms"] = round((time.perf_counter() - started) * 1000)
                info["std_type"] = typed
                check(
                    checks,
                    "standard 输入文本并返回 diff",
                    typed.get("ok") is True
                    and typed.get("changed") is True
                    and 'value="hello selsnap"' in updated_text(typed),
                    typed,
                )

                pressed = await call(
                    session, "press", {"session": "m1-std", "keys": "Enter", "ref": textbox}
                )
                check(
                    checks,
                    "standard press Enter",
                    pressed.get("ok") is True
                    and (pressed.get("settle") or {}).get("settled") is True,
                    pressed,
                )

                started = time.perf_counter()
                selected = await call(
                    session,
                    "select",
                    {"session": "m1-std", "ref": select_ref, "option": "Set to 75%"},
                )
                info["std_select_ms"] = round((time.perf_counter() - started) * 1000)
                info["std_select"] = selected
                check(
                    checks,
                    "standard 选择下拉选项并返回 diff",
                    selected.get("ok") is True
                    and 'value="Set to 75%"' in updated_text(selected),
                    selected,
                )

                hov = await call(session, "hover", {"session": "m1-std", "ref": link})
                check(
                    checks,
                    "standard 悬停元素",
                    hov.get("ok") is True,
                    hov,
                )

                scrolled = await call(session, "scroll", {"session": "m1-std", "dy": 400})
                check(
                    checks,
                    "standard 滚动页面",
                    scrolled.get("ok") is True
                    and (scrolled.get("settle") or {}).get("settled") is True,
                    scrolled,
                )

                navigated = await call(
                    session, "click", {"session": "m1-std", "ref": demo_link}
                )
                info["std_navigated_click"] = {
                    "ok": navigated.get("ok"),
                    "navigated": navigated.get("navigated"),
                    "reason": navigated.get("full_snapshot_reason"),
                    "snapshot_chars": len(navigated.get("snapshot") or ""),
                    "doc_id": navigated.get("doc_id"),
                }
                check(
                    checks,
                    "点击链接导航并返回完整快照",
                    navigated.get("ok") is True
                    and navigated.get("navigated") is True
                    and len(navigated.get("snapshot") or "") > 0,
                    info["std_navigated_click"],
                )

                stale = await call(session, "click", {"session": "m1-std", "ref": button})
                error = stale.get("error") or {}
                details = error.get("details") or {}
                info["std_stale"] = {
                    "ok": stale.get("ok"),
                    "code": error.get("code"),
                    "detail_keys": sorted(details.keys()),
                    "snapshot_chars": len(details.get("snapshot") or ""),
                }
                check(
                    checks,
                    "旧文档 ref 返回 stale_ref 并附最新快照",
                    stale.get("ok") is False
                    and error.get("code") == "stale_ref"
                    and bool(details.get("doc_id"))
                    and len(details.get("snapshot") or "") > 0,
                    info["std_stale"],
                )

                uc_open = await call(session, "session_open", {"name": "m1-uc", "mode": "uc"})
                uc_nav = await call(session, "navigate", {"session": "m1-uc", "url": DEMO})
                uc_snapshot = uc_nav.get("snapshot") or ""
                uc_button = ref_of(BUTTON_GREEN, uc_snapshot)
                uc_textbox = ref_of(TEXTBOX, uc_snapshot)
                uc_click = await call(
                    session, "click", {"session": "m1-uc", "ref": uc_button}
                )
                uc_type = await call(
                    session,
                    "type",
                    {"session": "m1-uc", "ref": uc_textbox, "text": "uc mode"},
                )
                info["uc"] = {"open": uc_open, "click": uc_click, "type": uc_type}
                check(
                    checks,
                    "uc 会话点击与输入",
                    uc_open.get("ok") is True
                    and uc_nav.get("ok") is True
                    and uc_click.get("ok") is True
                    and "Click Me (Purple)" in updated_text(uc_click)
                    and uc_type.get("ok") is True
                    and 'value="uc mode"' in updated_text(uc_type),
                    info["uc"],
                )

                cdp_open = await call(session, "session_open", {"name": "m1-cdp", "mode": "cdp"})
                cdp_nav = await call(session, "navigate", {"session": "m1-cdp", "url": DEMO})
                cdp_snapshot = cdp_nav.get("snapshot") or ""
                cdp_button = ref_of(BUTTON_GREEN, cdp_snapshot)
                cdp_textbox = ref_of(TEXTBOX, cdp_snapshot)
                cdp_click = await call(
                    session, "click", {"session": "m1-cdp", "ref": cdp_button}
                )
                cdp_type = await call(
                    session,
                    "type",
                    {"session": "m1-cdp", "ref": cdp_textbox, "text": "cdp mode"},
                )
                info["cdp"] = {"open": cdp_open, "click": cdp_click, "type": cdp_type}
                check(
                    checks,
                    "cdp 会话点击与输入",
                    cdp_open.get("ok") is True
                    and cdp_nav.get("ok") is True
                    and cdp_click.get("ok") is True
                    and "Click Me (Purple)" in updated_text(cdp_click)
                    and cdp_type.get("ok") is True
                    and 'value="cdp mode"' in updated_text(cdp_type),
                    info["cdp"],
                )

                for name in ("m1-std", "m1-uc", "m1-cdp"):
                    await call(session, "session_close", {"name": name})
                listed = await call(session, "session_list", {})
                check(
                    checks,
                    "会话关闭后列表为空",
                    listed.get("sessions") == [],
                    listed,
                )
    return {"checks": checks, "info": info}


def main() -> int:
    VAR.mkdir(exist_ok=True)
    stdout_log = VAR / "smoke_m1.stdout.log"
    stderr_log = VAR / "smoke_m1.stderr.log"
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
        (VAR / "smoke_m1.json").write_text(
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
