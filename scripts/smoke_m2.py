from __future__ import annotations

import asyncio
import base64
import functools
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var"
HOST = "127.0.0.1"
PORT = 8797
URL = f"http://{HOST}:{PORT}/mcp"
IDLE_PORT = 8791
IDLE_URL = f"http://{HOST}:{IDLE_PORT}/mcp"
FIXTURE_PORT = 8796
FIXTURE_BASE = f"http://{HOST}:{FIXTURE_PORT}"
AUDIT_DIR = VAR / "m2-smoke-audit"
ARTIFACT_DIR = VAR / "m2-smoke-artifacts"
PROFILE_DIR = VAR / "m2-smoke-profiles"
IDLE_PROFILE_DIR = VAR / "m2-smoke-idle-profiles"

TOKENS = {"tok-a": "agent-a", "tok-b": "agent-b"}

PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>M2 Fixture</title>
<style>
body { margin: 0; font-family: sans-serif; }
#target { position: absolute; left: 20px; top: 20px; width: 220px; height: 60px; }
#dlg { position: absolute; left: 20px; top: 100px; width: 220px; height: 40px; }
#secret { position: absolute; left: 20px; top: 160px; width: 220px; height: 30px; }
#tall { height: 4000px; background: linear-gradient(#eef, #99f); }
#bottom { position: absolute; top: 3900px; left: 20px; width: 220px; height: 40px; }
</style></head><body>
<button id="target" onclick="this.textContent='Target clicked'">Target</button>
<button id="dlg" onclick="if (confirm('ok?')) { this.textContent='Dialog accepted' } else { this.textContent='Dialog dismissed' }">Open dialog</button>
<input id="secret" type="text">
<div id="tall"></div>
<button id="bottom" onclick="this.textContent='Bottom clicked'">Bottom</button>
</body></html>
"""

CHALLENGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Just a moment...</title></head>
<body><h1>Checking your browser before accessing the site</h1>
<div id="challenge-form"></div></body></html>
"""


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


def wait_port(port: int, timeout: float, proc: subprocess.Popen | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
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


def ref_of(pattern: str, snapshot: str) -> str | None:
    match = re.search(pattern, snapshot or "", re.M)
    return match.group(1) if match else None


def updated_text(data: dict) -> str:
    return "\n".join((data.get("diff") or {}).get("updated") or [])


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


class QuietServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        return


def start_fixture_server(directory: Path) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(QuietHandler, directory=str(directory))
    httpd = QuietServer((HOST, FIXTURE_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def write_fixtures() -> None:
    directory = VAR / "m2-smoke-fixtures"
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    (directory / "page.html").write_text(PAGE_HTML, encoding="utf-8")
    (directory / "challenge.html").write_text(CHALLENGE_HTML, encoding="utf-8")


def start_server(port: int, extra_env: dict | None = None) -> tuple[subprocess.Popen, list[Path]]:
    stdout_log = VAR / f"smoke_m2_{port}.stdout.log"
    stderr_log = VAR / f"smoke_m2_{port}.stderr.log"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
    stdout_file = open(stdout_log, "w", encoding="utf-8")
    stderr_file = open(stderr_log, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "selsnap.server", "--port", str(port)],
        cwd=str(ROOT),
        env=env,
        stdout=stdout_file,
        stderr=stderr_file,
    )
    proc._selsnap_files = (stdout_file, stderr_file)  # type: ignore[attr-defined]
    if not wait_port(port, 30.0, proc):
        raise RuntimeError(f"服务 {port} 未在 30 秒内监听端口")
    return proc, [stdout_log, stderr_log]


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    files = getattr(proc, "_selsnap_files", ())
    for handle in files:
        try:
            handle.close()
        except Exception:
            pass


def client_for(token: str | None) -> httpx2.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(
        headers=headers, timeout=httpx2.Timeout(30.0, read=240.0)
    )


async def call(session: ClientSession, tool: str, args: dict) -> dict:
    return payload(await session.call_tool(tool, args))


def image_data(result) -> bytes | None:
    for block in result.content:
        if getattr(block, "type", None) == "image":
            return base64.b64decode(block.data)
    return None


async def run_main_checks(checks: list[dict], info: dict) -> None:
    http_a = client_for("tok-a")
    http_b = client_for("tok-b")
    try:
        async with streamable_http_client(URL, http_client=http_a) as (read, write):
            async with ClientSession(read, write) as a:
                await a.initialize()
                names = {tool.name for tool in (await a.list_tools()).tools}
                expected = {
                    "session_open",
                    "session_share",
                    "session_escalate",
                    "screenshot",
                    "click_at",
                    "dialog",
                    "snapshot",
                    "click",
                    "type",
                    "select",
                    "press",
                    "hover",
                    "scroll",
                }
                check(checks, "工具面包含 M2 工具", expected <= names, sorted(names))

                opened = await call(
                    a, "session_open", {"name": "m2", "mode": "standard"}
                )
                info["open"] = opened
                check(
                    checks,
                    "agent-a 打开会话",
                    opened.get("ok") is True and opened.get("owner") == "agent-a",
                    opened,
                )
                nav = await call(
                    a, "navigate", {"session": "m2", "url": f"{FIXTURE_BASE}/page.html"}
                )
                snap = nav.get("snapshot") or ""
                target = ref_of(r'^\s*- button "Target" \[(e\d+)\]', snap)
                dlg = ref_of(r'^\s*- button "Open dialog" \[(e\d+)\]', snap)
                secret = ref_of(r'^\s*- textbox \[(e\d+)\] type="text"$', snap)
                info["refs"] = {"target": target, "dlg": dlg, "secret": secret}
                check(
                    checks,
                    "导航 fixture 并解析 ref",
                    nav.get("ok") is True
                    and bool(target and dlg and secret)
                    and nav.get("challenge", {}).get("detected") is False,
                    {"nav": {k: nav.get(k) for k in ("ok", "doc_id", "challenge")}, "refs": info["refs"]},
                )

                typed = await call(
                    a,
                    "type",
                    {
                        "session": "m2",
                        "ref": secret,
                        "text": "hunter2-super-secret",
                    },
                )
                check(
                    checks,
                    "type 动作正常",
                    typed.get("ok") is True
                    and 'hunter2-super-secret' in updated_text(typed),
                    typed,
                )

                shot_view = await a.call_tool(
                    "screenshot", {"session": "m2"}
                )
                meta_view = payload(shot_view)
                png_view = image_data(shot_view)
                path_view = Path(meta_view.get("path") or "")
                info["screenshot_view"] = {
                    k: meta_view.get(k)
                    for k in ("scope", "width", "height", "bytes", "annotated")
                }
                check(
                    checks,
                    "视口截图返回 PNG 图像与元数据",
                    meta_view.get("ok") is True
                    and meta_view.get("scope") == "viewport"
                    and png_view is not None
                    and png_view[:8] == b"\x89PNG\r\n\x1a\n"
                    and meta_view.get("bytes") == len(png_view)
                    and path_view.exists(),
                    info["screenshot_view"],
                )

                shot_full = await a.call_tool(
                    "screenshot", {"session": "m2", "full_page": True, "annotate": True}
                )
                meta_full = payload(shot_full)
                png_full = image_data(shot_full)
                info["screenshot_full"] = {
                    k: meta_full.get(k)
                    for k in ("scope", "width", "height", "bytes", "annotated")
                }
                check(
                    checks,
                    "整页截图带 ref 标注",
                    meta_full.get("ok") is True
                    and meta_full.get("scope") == "full_page"
                    and meta_full.get("annotated") is True
                    and meta_full.get("height", 0) > meta_view.get("height", 0)
                    and png_full is not None
                    and len(png_full) > 0,
                    info["screenshot_full"],
                )

                shot_element = await a.call_tool(
                    "screenshot", {"session": "m2", "ref": target}
                )
                meta_element = payload(shot_element)
                info["screenshot_element"] = {
                    k: meta_element.get(k)
                    for k in ("scope", "ref", "width", "height")
                }
                check(
                    checks,
                    "元素截图裁剪尺寸正确",
                    meta_element.get("ok") is True
                    and meta_element.get("scope") == "element"
                    and meta_element.get("ref") == target
                    and abs(int(meta_element.get("width", 0)) - 220) <= 2
                    and abs(int(meta_element.get("height", 0)) - 60) <= 2,
                    meta_element,
                )

                clicked = await call(
                    a, "click_at", {"session": "m2", "x": 130, "y": 50}
                )
                info["click_at"] = clicked
                check(
                    checks,
                    "click_at 命中按钮",
                    clicked.get("ok") is True
                    and "Target clicked" in updated_text(clicked),
                    clicked,
                )

                dialog_click = await call(a, "click", {"session": "m2", "ref": dlg})
                dialog_info = await call(a, "dialog", {"session": "m2", "action": "accept"})
                info["dialog"] = {"click": dialog_click, "accept": dialog_info}
                check(
                    checks,
                    "dialog 工具处理 confirm",
                    dialog_click.get("ok") is False
                    and (dialog_click.get("error") or {}).get("code") == "dialog_open"
                    and dialog_info.get("ok") is True
                    and "Dialog accepted" in updated_text(dialog_info),
                    info["dialog"],
                )

                missing_auth = await httpx2.AsyncClient().get(
                    URL, headers={"Accept": "text/event-stream"}
                )
                bad_auth = await httpx2.AsyncClient().get(
                    URL,
                    headers={
                        "Accept": "text/event-stream",
                        "Authorization": "Bearer wrong",
                    },
                )
                check(
                    checks,
                    "缺少或错误 token 返回 401",
                    missing_auth.status_code == 401 and bad_auth.status_code == 401,
                    {
                        "missing": missing_auth.status_code,
                        "wrong": bad_auth.status_code,
                    },
                )

                share_read = await call(
                    a,
                    "session_share",
                    {"name": "m2", "agent": "agent-b", "mode": "read"},
                )

                async with streamable_http_client(URL, http_client=http_b) as (rb, wb):
                    async with ClientSession(rb, wb) as b:
                        await b.initialize()
                        b_list = await call(b, "session_list", {})
                        b_snapshot = await call(b, "snapshot", {"session": "m2"})
                        b_navigate = await call(
                            b,
                            "navigate",
                            {"session": "m2", "url": f"{FIXTURE_BASE}/page.html"},
                        )
                        b_open = await call(b, "session_open", {"name": "m2"})
                        b_close = await call(b, "session_close", {"name": "m2"})
                        info["b_read"] = {
                            "list": b_list,
                            "snapshot_ok": b_snapshot.get("ok"),
                            "navigate_error": (b_navigate.get("error") or {}).get("code"),
                            "open_error": (b_open.get("error") or {}).get("code"),
                            "close_error": (b_close.get("error") or {}).get("code"),
                        }
                        check(
                            checks,
                            "agent-b 只读共享：可读不可写",
                            share_read.get("ok") is True
                            and [item["name"] for item in b_list.get("sessions") or []] == ["m2"]
                            and b_snapshot.get("ok") is True
                            and (b_navigate.get("error") or {}).get("code") == "forbidden"
                            and (b_open.get("error") or {}).get("code") == "forbidden"
                            and (b_close.get("error") or {}).get("code") == "forbidden",
                            info["b_read"],
                        )

                        share_write = await call(
                            a,
                            "session_share",
                            {"name": "m2", "agent": "agent-b", "mode": "write"},
                        )
                        b_type = await call(
                            b,
                            "type",
                            {"session": "m2", "ref": secret, "text": "from-agent-b"},
                        )
                        info["b_write"] = {
                            "share": share_write,
                            "type_ok": b_type.get("ok"),
                            "changed": b_type.get("changed"),
                        }
                        check(
                            checks,
                            "agent-b 写共享后可执行动作",
                            share_write.get("ok") is True
                            and b_type.get("ok") is True
                            and 'from-agent-b' in updated_text(b_type),
                            info["b_write"],
                        )

                        share_ttl = await call(
                            a,
                            "session_share",
                            {"name": "m2", "agent": "agent-b", "mode": "read", "ttl": 1},
                        )
                        time.sleep(1.4)
                        b_expired = await call(b, "snapshot", {"session": "m2"})
                        info["ttl"] = {
                            "share": share_ttl,
                            "error": (b_expired.get("error") or {}).get("code"),
                        }
                        check(
                            checks,
                            "共享 TTL 到期后拒绝访问",
                            (b_expired.get("error") or {}).get("code") == "forbidden",
                            info["ttl"],
                        )

                        revoke = await call(
                            a,
                            "session_share",
                            {"name": "m2", "agent": "agent-b", "mode": "revoke"},
                        )
                        b_list_after = await call(b, "session_list", {})
                        check(
                            checks,
                            "revoke 后 agent-b 不再看到会话",
                            b_list_after.get("sessions") == [],
                            {"revoke": revoke, "list": b_list_after},
                        )

                escalated = await call(
                    a, "session_escalate", {"session": "m2", "mode": "uc"}
                )
                info["escalate"] = escalated
                attach = await call(a, "session_attach", {"name": "m2"})
                check(
                    checks,
                    "session_escalate 切换到 uc 并保留页面",
                    escalated.get("ok") is True
                    and escalated.get("target_mode") == "uc"
                    and bool(escalated.get("snapshot"))
                    and f"{FIXTURE_BASE}/page.html" in (escalated.get("url") or "")
                    and attach.get("mode") == "uc",
                    {"escalate": escalated, "attach": attach},
                )

                escalated_snap = escalated.get("snapshot") or ""
                target2 = ref_of(r'^\s*- button "Target" \[(e\d+)\]', escalated_snap)
                shot_uc = await a.call_tool(
                    "screenshot", {"session": "m2", "ref": target2}
                )
                meta_uc = payload(shot_uc)
                check(
                    checks,
                    "uc 模式下元素截图",
                    meta_uc.get("ok") is True
                    and meta_uc.get("scope") == "element"
                    and image_data(shot_uc) is not None,
                    meta_uc,
                )

                closed = await call(a, "session_close", {"name": "m2"})
                check(checks, "owner 关闭会话", closed.get("ok") is True, closed)

                auto_open = await call(
                    a,
                    "session_open",
                    {"name": "auto", "mode": "standard", "auto_escalate": True},
                )
                auto_nav = await call(
                    a,
                    "navigate",
                    {"session": "auto", "url": f"{FIXTURE_BASE}/challenge.html"},
                )
                auto_info = await call(a, "session_attach", {"name": "auto"})
                auto_close = await call(a, "session_close", {"name": "auto"})
                info["auto_escalate"] = {
                    "open": auto_open.get("ok"),
                    "detected": (auto_nav.get("challenge") or {}).get("detected"),
                    "escalated_to": auto_nav.get("escalated_to"),
                    "mode": auto_info.get("mode"),
                }
                check(
                    checks,
                    "auto_escalate 在挑战页自动升级到 uc",
                    auto_open.get("ok") is True
                    and (auto_nav.get("challenge") or {}).get("detected") is True
                    and auto_nav.get("escalated_to") == "uc"
                    and auto_info.get("mode") == "uc"
                    and auto_close.get("ok") is True,
                    info["auto_escalate"],
                )
    finally:
        await http_a.aclose()
        await http_b.aclose()


async def run_idle_checks(checks: list[dict], info: dict) -> None:
    http = client_for(None)
    try:
        async with streamable_http_client(IDLE_URL, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                opened = await call(
                    session, "session_open", {"name": "idle", "mode": "standard"}
                )
                nav = await call(
                    session,
                    "navigate",
                    {"session": "idle", "url": f"{FIXTURE_BASE}/page.html"},
                )
                suspended = False
                listed = {}
                for _ in range(20):
                    await asyncio.sleep(0.3)
                    listed = await call(session, "session_list", {})
                    suspended = any(
                        item.get("name") == "idle" and item.get("suspended")
                        for item in listed.get("sessions") or []
                    )
                    if suspended:
                        break
                snapshot = await call(session, "snapshot", {"session": "idle"})
                listed_after = await call(session, "session_list", {})
                resumed = any(
                    item.get("name") == "idle" and not item.get("suspended")
                    for item in listed_after.get("sessions") or []
                )
                closed = await call(session, "session_close", {"name": "idle"})
                info["idle"] = {
                    "open": opened.get("ok"),
                    "nav": nav.get("ok"),
                    "suspended": suspended,
                    "snapshot_ok": snapshot.get("ok"),
                    "resumed": resumed,
                }
                check(
                    checks,
                    "空闲会话自动挂起并可恢复",
                    opened.get("ok") is True
                    and nav.get("ok") is True
                    and suspended is True
                    and snapshot.get("ok") is True
                    and resumed is True
                    and closed.get("ok") is True,
                    info["idle"],
                )
    finally:
        await http.aclose()


def check_audit(checks: list[dict], info: dict) -> None:
    files = sorted(AUDIT_DIR.glob("audit-*.jsonl"))
    entries = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    raw = "\n".join(path.read_text(encoding="utf-8") for path in files)
    type_entries = [
        item
        for item in entries
        if item.get("tool") == "type"
        and item.get("agent") == "agent-a"
        and (item.get("args") or {}).get("text")
    ]
    b_entries = [
        item
        for item in entries
        if item.get("agent") == "agent-b"
        and item.get("owner") == "agent-a"
        and item.get("tool") == "snapshot"
        and item.get("ok") is True
    ]
    tools = {item.get("tool") for item in entries}
    info["audit"] = {
        "entries": len(entries),
        "tools": sorted(tools),
        "hashed_type": bool(type_entries),
        "b_owner": bool(b_entries),
        "secret_leaked": "hunter2-super-secret" in raw,
    }
    check(
        checks,
        "审计 JSONL 记录身份/owner/工具且脱敏",
        bool(files)
        and bool(type_entries)
        and bool(b_entries)
        and {"session_share", "session_escalate", "screenshot", "click_at", "dialog"}
        <= tools
        and "hunter2-super-secret" not in raw,
        info["audit"],
    )


def main() -> int:
    VAR.mkdir(exist_ok=True)
    for path in (AUDIT_DIR, ARTIFACT_DIR, PROFILE_DIR, IDLE_PROFILE_DIR):
        shutil.rmtree(path, ignore_errors=True)
    write_fixtures()

    result: dict = {"checks": [], "info": {}}
    servers: list[subprocess.Popen] = []
    fixture = None
    try:
        if not port_is_free(FIXTURE_PORT):
            raise RuntimeError(f"fixture 端口 {FIXTURE_PORT} 被占用")
        fixture = start_fixture_server(VAR / "m2-smoke-fixtures")
        main_env = {
            "SELSNAP_TOKENS": json.dumps(TOKENS),
            "SELSNAP_AUDIT_DIR": str(AUDIT_DIR),
            "SELSNAP_ARTIFACT_DIR": str(ARTIFACT_DIR),
            "SELSNAP_PROFILE_ROOT": str(PROFILE_DIR),
        }
        proc, _ = start_server(PORT, main_env)
        servers.append(proc)
        asyncio.run(run_main_checks(result["checks"], result["info"]))
        check_audit(result["checks"], result["info"])
        stop_server(proc)

        idle_env = {
            "SELSNAP_IDLE_TIMEOUT": "1",
            "SELSNAP_IDLE_CHECK_INTERVAL": "0.2",
            "SELSNAP_PROFILE_ROOT": str(IDLE_PROFILE_DIR),
            "SELSNAP_AUDIT": "0",
            "SELSNAP_ARTIFACT_DIR": str(ARTIFACT_DIR),
        }
        idle_proc, _ = start_server(IDLE_PORT, idle_env)
        servers.append(idle_proc)
        asyncio.run(run_idle_checks(result["checks"], result["info"]))
        stop_server(idle_proc)
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for proc in servers:
            stop_server(proc)
        if fixture is not None:
            fixture.shutdown()
            fixture.server_close()
        result["port_released"] = wait_port_closed(PORT, 15.0) and wait_port_closed(
            IDLE_PORT, 15.0
        )
        result["stderr_tail"] = [
            line
            for port in (PORT, IDLE_PORT)
            for line in (
                (VAR / f"smoke_m2_{port}.stderr.log").read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()[-10:]
                if (VAR / f"smoke_m2_{port}.stderr.log").exists()
                else []
            )
        ]
        (VAR / "smoke_m2.json").write_text(
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
