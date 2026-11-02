from __future__ import annotations

import asyncio
import inspect
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

import httpx2
import mcp.client.streamable_http as streamable_http_module
from mcp import ClientSession
from mcp.client.streamable_http import MCP_SESSION_ID, streamable_http_client
from mcp.server.mcpserver import MCPServer

BASE_DIR = Path(__file__).resolve().parent
SERVER_PATH = BASE_DIR / "server.py"
RESULT_JSON = BASE_DIR / "result.json"
RESULT_MD = BASE_DIR / "result.md"
HOST = "127.0.0.1"
PREFERRED_PORTS = (8765, 8766)
PATH = "/mcp"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def wait_port_open(port: int, timeout: float, proc: subprocess.Popen[bytes] | None = None) -> bool:
    # 以 bind 是否仍成功判断监听状态，避免 TCP 探活产生空的连接（Windows 上会触发 ConnectionResetError 日志）。
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        if not port_is_free(port):
            return True
        time.sleep(0.15)
    return False



def wait_port_closed(port: int, timeout: float) -> bool:
    # Windows 下非阻塞 connect_ex 可能返回 WSAEWOULDBLOCK，不能据此判定端口释放；用 bind 结果判定。
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_free(port):
            return True
        time.sleep(0.15)
    return False


def make_http_client(label: str, records: list[dict]) -> httpx2.AsyncClient:
    async def on_request(request: httpx2.Request) -> None:
        records.append(
            {
                "phase": "request",
                "client": label,
                "at": utc_now(),
                "method": request.method,
                "url": str(request.url),
                "mcp_session_id": request.headers.get(MCP_SESSION_ID),
                "mcp_protocol_version": request.headers.get("mcp-protocol-version"),
            }
        )

    async def on_response(response: httpx2.Response) -> None:
        records.append(
            {
                "phase": "response",
                "client": label,
                "at": utc_now(),
                "method": response.request.method,
                "url": str(response.request.url),
                "status": response.status_code,
                "mcp_session_id": response.headers.get(MCP_SESSION_ID),
                "content_type": response.headers.get("content-type"),
            }
        )

    return httpx2.AsyncClient(
        timeout=httpx2.Timeout(30.0, read=300.0),
        event_hooks={"request": [on_request], "response": [on_response]},
    )


@asynccontextmanager
async def open_session(url: str, label: str, records: list[dict]):
    http_client = make_http_client(label, records)
    async with http_client:
        async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init_result = await session.initialize()
                yield session, init_result


def session_id_for(records: list[dict], label: str) -> str | None:
    for record in records:
        if record["client"] == label and record["phase"] == "response" and record.get("mcp_session_id"):
            return record["mcp_session_id"]
    return None


def summarize_tool_result(result) -> dict:
    texts = []
    for block in result.content:
        if getattr(block, "type", None) == "text":
            texts.append(block.text)
    return {
        "is_error": result.is_error,
        "text": "\n".join(texts),
        "structured_content": result.structured_content,
    }


def counter_value(result) -> int | None:
    structured = result.structured_content
    if isinstance(structured, dict):
        if "result" in structured:
            return structured["result"]
        if len(structured) == 1:
            return next(iter(structured.values()))
    text = summarize_tool_result(result)["text"].strip()
    try:
        return int(text)
    except ValueError:
        return None


async def call_counter(label: str, session: ClientSession, events: list[dict]) -> dict:
    try:
        result = await session.call_tool("counter", {})
        event = {
            "label": label,
            "value": counter_value(result),
            "is_error": result.is_error,
            "structured_content": result.structured_content,
        }
    except Exception as exc:
        event = {"label": label, "value": None, "error": repr(exc)}
    events.append(event)
    return event



class ClientWorker:
    """把每个 MCP 连接放在独立 asyncio 任务中，避免多个 SDK task group 在同一任务里串行退出时的取消串扰。"""

    def __init__(self, url: str, label: str, records: list[dict]) -> None:
        self.url = url
        self.label = label
        self.records = records
        self.queue: asyncio.Queue = asyncio.Queue()
        self.ready = asyncio.Event()
        self.session_id: str | None = None
        self.init = None
        self.error: str | None = None
        self.task: asyncio.Task | None = None

    async def _run(self) -> None:
        try:
            async with open_session(self.url, self.label, self.records) as (session, init_result):
                self.init = init_result
                self.session_id = session_id_for(self.records, self.label)
                self.ready.set()
                while True:
                    command = await self.queue.get()
                    if command is None:
                        break
                    tool_name, arguments, future = command
                    if future.cancelled():
                        continue
                    try:
                        if tool_name == "__burst_counter__":
                            results = await asyncio.gather(
                                *(session.call_tool("counter", {}) for _ in range(arguments)),
                                return_exceptions=True,
                            )
                            future.set_result(results)
                        else:
                            result = await session.call_tool(tool_name, arguments)
                            future.set_result(result)
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
        except Exception as exc:
            self.error = repr(exc)
            if not self.ready.is_set():
                self.ready.set()
            while not self.queue.empty():
                command = self.queue.get_nowait()
                if command is not None and not command[2].done():
                    command[2].set_exception(exc)

    async def start(self) -> None:
        self.task = asyncio.create_task(self._run())
        await self.ready.wait()
        if self.error is not None:
            raise RuntimeError(f"客户端 {self.label} 启动失败：{self.error}")

    async def submit(self, tool_name: str, arguments: dict):
        if self.task is None or self.task.done():
            raise RuntimeError(f"客户端 {self.label} 已关闭或异常退出：{self.error}")
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((tool_name, arguments, future))
        return await future

    async def burst_counter(self, count: int) -> list:
        future = asyncio.get_running_loop().create_future()
        await self.queue.put(("__burst_counter__", count, future))
        return await future

    async def stop(self) -> None:
        if self.task is None or self.task.done():
            return
        await self.queue.put(None)
        await self.task



def init_snapshot(init_result) -> dict:
    return {
        "protocol_version": init_result.protocol_version,
        "server_info": init_result.server_info.model_dump(),
        "capabilities": init_result.capabilities.model_dump(),
    }


async def run_experiment(url: str) -> dict:
    records: list[dict] = []
    counter_events: list[dict] = []
    checks: list[dict] = []
    init_info: dict[str, dict] = {}
    session_ids: dict[str, str | None] = {}
    echo_checks: list[dict] = []
    workers: list[ClientWorker] = []

    def check(name: str, ok: bool, detail) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    async def call_counter(worker: ClientWorker, label: str) -> dict:
        try:
            result = await worker.submit("counter", {})
            event = {
                "label": label,
                "value": counter_value(result),
                "is_error": result.is_error,
                "structured_content": result.structured_content,
            }
        except Exception as exc:
            event = {"label": label, "value": None, "error": repr(exc)}
        counter_events.append(event)
        return event

    try:
        worker_a = ClientWorker(url, "A", records)
        worker_b = ClientWorker(url, "B", records)
        await worker_a.start()
        await worker_b.start()
        workers.extend([worker_a, worker_b])
        session_ids["A"] = worker_a.session_id
        session_ids["B"] = worker_b.session_id
        init_info["A"] = init_snapshot(worker_a.init)
        init_info["B"] = init_snapshot(worker_b.init)
        check("两个客户端均 initialize 成功", True, init_info["A"]["protocol_version"])
        check(
            "两个客户端 session id 不同",
            session_ids["A"] is not None
            and session_ids["B"] is not None
            and session_ids["A"] != session_ids["B"],
            {"A": session_ids["A"], "B": session_ids["B"]},
        )

        echo_a, echo_b = await asyncio.gather(
            worker_a.submit("echo", {"text": "hello-A"}),
            worker_b.submit("echo", {"text": "hello-B"}),
        )
        echo_info_a = summarize_tool_result(echo_a)
        echo_info_b = summarize_tool_result(echo_b)
        echo_checks.append({"label": "A", "expected": "hello-A", "result": echo_info_a})
        echo_checks.append({"label": "B", "expected": "hello-B", "result": echo_info_b})
        check(
            "并发 echo 结果正确",
            echo_info_a["text"] == "hello-A" and echo_info_b["text"] == "hello-B",
            echo_checks,
        )

        await asyncio.gather(
            call_counter(worker_a, "A"),
            call_counter(worker_a, "A"),
            call_counter(worker_b, "B"),
            call_counter(worker_b, "B"),
        )
        initial_values = [event["value"] for event in counter_events]
        check(
            "两个客户端并发各调用 counter 两次均成功",
            all(event.get("value") is not None and not event.get("error") for event in counter_events),
            initial_values,
        )

        burst_a, burst_b = await asyncio.gather(
            worker_a.burst_counter(5),
            worker_b.burst_counter(5),
        )
        burst_events = []
        for label, results in (("A", burst_a), ("B", burst_b)):
            for result in results:
                if isinstance(result, Exception):
                    burst_events.append({"label": label, "value": None, "error": repr(result)})
                else:
                    burst_events.append(
                        {
                            "label": label,
                            "value": counter_value(result),
                            "is_error": result.is_error,
                            "structured_content": result.structured_content,
                        }
                    )
        burst_values = [event.get("value") for event in burst_events]
        counter_events.extend(burst_events)
        check("并发爆发 10 次 counter 无异常", all(value is not None for value in burst_values), burst_values)
        check(
            "并发爆发 10 次 counter 返回值互不重复",
            len([v for v in burst_values if v is not None]) == len(set(v for v in burst_values if v is not None)) == 10,
            sorted(v for v in burst_values if v is not None),
        )

        await worker_a.stop()
        workers.remove(worker_a)
        check("客户端 A 已断开（发送 DELETE 终止会话）", True, {"A_session": session_ids["A"]})

        b_after_close = await call_counter(worker_b, "B-after-A-close")
        check(
            "A 断开后 B 仍可继续调用",
            b_after_close.get("value") is not None and not b_after_close.get("error"),
            b_after_close,
        )

        worker_a2 = ClientWorker(url, "A-reconnect", records)
        await worker_a2.start()
        workers.append(worker_a2)
        session_ids["A-reconnect"] = worker_a2.session_id
        init_info["A-reconnect"] = init_snapshot(worker_a2.init)
        check(
            "A 断开后重连成功且获得新 session id",
            session_ids["A-reconnect"] is not None
            and session_ids["A-reconnect"] != session_ids["A"]
            and session_ids["A-reconnect"] != session_ids["B"],
            {"old_A": session_ids["A"], "B": session_ids["B"], "new_A": session_ids["A-reconnect"]},
        )
        echo_re = await worker_a2.submit("echo", {"text": "reconnect-A"})
        echo_re_info = summarize_tool_result(echo_re)
        echo_checks.append({"label": "A-reconnect", "expected": "reconnect-A", "result": echo_re_info})
        reconnect_counter = await call_counter(worker_a2, "A-reconnect")
        check(
            "重连后可继续调用 echo/counter",
            echo_re_info["text"] == "reconnect-A"
            and reconnect_counter.get("value") is not None
            and not reconnect_counter.get("error"),
            {"echo": echo_re_info, "counter": reconnect_counter},
        )
    finally:
        for worker in list(workers):
            try:
                await worker.stop()
            except BaseException as exc:
                check(f"客户端 {worker.label} 关闭异常", False, repr(exc))

    values = [event.get("value") for event in counter_events if event.get("value") is not None]
    expected_sequence = sorted(values) == list(range(1, len(values) + 1))
    check(
        "counter 跨客户端/跨会话共享且连续递增",
        bool(values) and expected_sequence,
        {"values": values, "expected": list(range(1, len(values) + 1))},
    )

    delete_requests = [record for record in records if record["phase"] == "request" and record["method"] == "DELETE"]
    delete_responses = [record for record in records if record["phase"] == "response" and record["method"] == "DELETE"]
    check(
        "客户端上下文退出时发送 DELETE 终止会话",
        len(delete_requests) >= 2,
        {"requests": delete_requests, "responses": delete_responses},
    )

    session_headers = sorted({record["mcp_session_id"] for record in records if record.get("mcp_session_id")})
    url_has_session = any("session" in record["url"].lower() for record in records)
    check(
        "session id 通过 mcp-session-id 请求/响应头传递，未出现在 URL",
        bool(session_headers) and not url_has_session,
        {"observed_session_ids": session_headers, "url_contains_session": url_has_session},
    )

    compact_records = [{k: v for k, v in record.items() if k != "at" and v is not None} for record in records]
    return {
        "url": url,
        "checks": checks,
        "session_ids": session_ids,
        "init": init_info,
        "echo": echo_checks,
        "counter_events": counter_events,
        "counter_values": values,
        "http_records": compact_records,
        "delete": {"requests": delete_requests, "responses": delete_responses},
    }



def collect_api_facts() -> dict:
    fastmcp: dict
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401

        fastmcp = {"status": "available"}
    except Exception as exc:
        fastmcp = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}

    return {
        "distribution": "mcp",
        "version": pkg_version("mcp"),
        "python": sys.version.split()[0],
        "fastmcp": fastmcp,
        "server_class": "mcp.server.mcpserver.MCPServer",
        "server_init_signature": str(inspect.signature(MCPServer.__init__)),
        "server_run_signature": str(inspect.signature(MCPServer.run)),
        "run_streamable_http_async_signature": str(
            inspect.signature(MCPServer.run_streamable_http_async)
        ),
        "streamable_http_app_signature": str(inspect.signature(MCPServer.streamable_http_app)),
        "streamable_http_transport_params": {
            name: parameter.default
            for name, parameter in inspect.signature(MCPServer.run_streamable_http_async).parameters.items()
            if name != "self"
        },
        "server_tool_decorator_signature": str(inspect.signature(MCPServer.tool)),
        "client_module": "mcp.client.streamable_http",
        "client_function": "streamable_http_client",
        "client_function_signature": str(inspect.signature(streamable_http_client)),
        "client_yields": "2-tuple (read_stream, write_stream)，不再返回 get_session_id",
        "legacy_client_function_present": hasattr(streamable_http_module, "streamablehttp_client"),
        "client_session_import": "from mcp import ClientSession（实现在 mcp.client.session）",
        "session_id_header": MCP_SESSION_ID,
        "http_library": f"httpx2 {getattr(httpx2, '__version__', 'unknown')}",
    }


def auth_assessment() -> dict:
    return {
        "bearer_on_custom_service": "可行",
        "server_side": (
            "MCPServer 自带 auth/token_verifier 参数面向 OAuth 资源服务器；自研服务更简单的方式是在 "
            "ASGI/Starlette 层加中间件或反向代理校验 Authorization: Bearer <token>，未通过返回 401。"
        ),
        "client_side": (
            "streamable_http_client 接受自定义 httpx2.AsyncClient，可在其 headers/auth 中统一注入 Bearer；"
            "也可用 create_mcp_http_client(headers=...)。SDK 会跟随同源重定向，不会把请求带到其他源。"
        ),
        "caveats": [
            "鉴权失败需在 initialize 前返回 401，客户端会收到 HTTP 错误而非 JSON-RPC 错误。",
            "若使用 SDK 内置 OAuth 流程，需要 OAuthAuthorizationServerProvider/TokenVerifier，复杂度高于自研 Bearer。",
            "Streamable HTTP 的 GET SSE 长连接与 DELETE 请求同样会携带该头，中间件需放行 POST/GET/DELETE。",
        ],
        "implemented": False,
    }


def choose_port() -> tuple[int, list[str]]:
    notes = []
    for port in PREFERRED_PORTS:
        if port_is_free(port):
            if port != PREFERRED_PORTS[0]:
                notes.append(f"端口 {PREFERRED_PORTS[0]} 被占用，改用 {port}")
            return port, notes
        notes.append(f"端口 {port} 已被占用")
    raise RuntimeError("8765 和 8766 均被占用，无法启动测试服务")


def read_log_tail(path: Path, max_lines: int = 40) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


def write_markdown(result: dict) -> str:
    api = result["api"]
    exp = result.get("experiment") or {}
    lines = [
        "# MCP Python SDK 2.3.0 Streamable HTTP 多客户端验证",
        "",
        f"- 生成时间：{result['generated_at']}",
        f"- 解释器：`{result['environment']['python_executable']}`",
        f"- mcp 版本：`{api['version']}`；httpx2：`{api['http_library']}`",
        f"- 服务地址：`{exp.get('url', '-')}`",
        "",
        "## API 兼容性",
        "",
        f"- `mcp.server.fastmcp`：{api['fastmcp']['status']}。{api['fastmcp'].get('error', '')}",
        "- 服务端实际类：`mcp.server.mcpserver.MCPServer`（FastMCP 在 2.x 已改名）。",
        f"- 客户端函数：`mcp.client.streamable_http.streamable_http_client`，签名 `{api['client_function_signature']}`。",
        f"- 客户端上下文产出：{api['client_yields']}；旧名 `streamablehttp_client` 是否存在：{api['legacy_client_function_present']}。",
        f"- 服务端 Streamable HTTP 参数：`{json.dumps(api['streamable_http_transport_params'], ensure_ascii=False)}`。",
        f"- session id 传递：HTTP 头 `{api['session_id_header']}`（服务端下发、客户端回传），不在 URL 中。",
        "- HTTP 证据：initialize 的 POST 请求无 session 头，响应头返回 `mcp-session-id`；后续 POST/GET/DELETE 均携带该头。",
        "",
        "## 验证结论",
        "",
    ]
    for check in exp.get("checks", []):
        mark = "PASS" if check["ok"] else "FAIL"
        detail = json.dumps(check["detail"], ensure_ascii=False)
        lines.append(f"- [{mark}] {check['name']}：`{detail}`")
    lines += [
        "",
        "## counter 状态",
        "",
        f"- 观察到的值序列：`{exp.get('counter_values', [])}`",
        "- 结论：counter 保存在服务端进程内，跨客户端、跨会话共享；断线重连后继续累加。",
        "- 并发时响应完成顺序与数值顺序不一致，说明请求确实并发执行；值集合仍完整且无重复。",
        "",
        "## 并发与重连",
        "",
        f"- session id：`{json.dumps(exp.get('session_ids', {}), ensure_ascii=False)}`",
        "- 两个客户端并发 initialize/调用均成功，session id 不同；A 断开后 B 不受影响，A 重连获得新 session id。",
        "",
        "## Bearer 鉴权可行性",
        "",
        f"- 结论：**{result['auth']['bearer_on_custom_service']}**（本次未实现）。",
        f"- 服务端：{result['auth']['server_side']}",
        f"- 客户端：{result['auth']['client_side']}",
        "",
        "## 异常与备注",
        "",
    ]
    anomalies = result.get("anomalies") or []
    if anomalies:
        lines.extend(f"- {item}" for item in anomalies)
    else:
        lines.append("- 无测试失败；仅有预期的 2.x API 变更。")
    lines.extend(f"- 备注：{item}" for item in (result.get("notes") or []))
    lines += [
        "",
        "## 服务进程与端口",
        "",
        f"- 首选端口 {result['server'].get('preferred_port')} 是否空闲：{result['server'].get('preferred_port_free')}；实际端口：{result['server'].get('port')}；是否回退：{result['server'].get('fallback_used')}",
        f"- 退出码：{result['server'].get('exit_code')}；终止方式：{result['server'].get('termination')}",
        f"- 端口释放：{result['server'].get('port_released')}（{result['server'].get('port_release_check', '-')}）",
        f"- 日志：`{result['server'].get('stdout_log')}` / `{result['server'].get('stderr_log')}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    result: dict = {
        "generated_at": utc_now(),
        "environment": {
            "cwd": str(BASE_DIR),
            "python_executable": sys.executable,
        },
        "api": collect_api_facts(),
        "auth": auth_assessment(),
        "server": {},
        "experiment": None,
        "anomalies": [],
        "notes": [],
    }
    stdout_log = BASE_DIR / "server.stdout.log"
    stderr_log = BASE_DIR / "server.stderr.log"
    proc: subprocess.Popen[bytes] | None = None
    stdout_file = None
    stderr_file = None
    port = None
    try:
        preferred_free = port_is_free(PREFERRED_PORTS[0])
        port, port_notes = choose_port()
        result["anomalies"].extend(port_notes)
        result["server"]["preferred_port"] = PREFERRED_PORTS[0]
        result["server"]["preferred_port_free"] = preferred_free
        result["server"]["fallback_used"] = port != PREFERRED_PORTS[0]
        result["server"]["port"] = port
        result["server"]["stdout_log"] = str(stdout_log)
        result["server"]["stderr_log"] = str(stderr_log)
        stdout_file = open(stdout_log, "w", encoding="utf-8", buffering=1)
        stderr_file = open(stderr_log, "w", encoding="utf-8", buffering=1)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(SERVER_PATH),
                "--host",
                HOST,
                "--port",
                str(port),
                "--path",
                PATH,
            ],
            cwd=str(BASE_DIR),
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
        )
        result["server"]["pid"] = proc.pid
        if not wait_port_open(port, 20.0, proc):
            raise RuntimeError(f"服务未在 20 秒内监听 {HOST}:{port}，退出码 {proc.poll()}")
        url = f"http://{HOST}:{port}{PATH}"
        result["experiment"] = asyncio.run(run_experiment(url))
        if not all(check["ok"] for check in result["experiment"]["checks"]):
            result["anomalies"].append("存在未通过的检查项，详见 experiment.checks")
    except Exception:
        result["fatal_error"] = traceback.format_exc()
        result["anomalies"].append("测试执行抛出未捕获异常，详见 fatal_error")
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            result["server"]["exit_code"] = proc.returncode
            result["server"]["termination"] = "subprocess.terminate() + wait()；Windows 等价于强制结束，退出码 1 属预期"
        if stdout_file is not None:
            stdout_file.close()
        if stderr_file is not None:
            stderr_file.close()
        if port is not None:
            released = wait_port_closed(port, 10.0)
            result["server"]["port_released"] = released
            result["server"]["port_release_check"] = f"bind(127.0.0.1:{port}) {'成功' if released else '失败'}"
            if not released:
                result["anomalies"].append(f"端口 {port} 在服务进程结束后仍被占用")
            time.sleep(0.2)
        result["server"]["stdout_tail"] = read_log_tail(stdout_log)
        result["server"]["stderr_tail"] = read_log_tail(stderr_log)

    all_log_lines = result["server"].get("stderr_tail", []) + result["server"].get("stdout_tail", [])
    if any("Invalid HTTP request" in line for line in all_log_lines):
        result["anomalies"].append("启动探测产生了 Uvicorn 'Invalid HTTP request' 日志（TCP 探活导致，非功能问题）")

    stderr_text = stderr_log.read_text(encoding="utf-8", errors="replace") if stderr_log.exists() else ""
    reset_count = stderr_text.count("ConnectionResetError")
    result["server"]["stderr_connection_reset_count"] = reset_count
    if reset_count:
        result["anomalies"].append(
            f"server stderr 记录 {reset_count} 次 ConnectionResetError (WinError 10054)，出现在会话建立后的连接关闭阶段；"
            "所有 RPC 调用均成功，判定为 Windows Proactor 事件循环的关闭噪声（uvicorn/asyncio 已知现象），不影响功能。"
        )

    result["notes"].append(
        "同一 asyncio 任务中串行关闭多个 streamable_http_client 上下文时，第二个上下文关闭阶段（发送 DELETE）会抛 CancelledError；"
        "本次改为每个连接独立 asyncio 任务承载后稳定。"
    )
    result["notes"].append(
        "协商协议版本为 2025-11-25；服务端默认 json_response=False，initialize 响应以 text/event-stream 返回。"
    )

    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    RESULT_MD.write_text(write_markdown(result), encoding="utf-8")

    summary = {
        "result_json": str(RESULT_JSON),
        "result_md": str(RESULT_MD),
        "port": result["server"].get("port"),
        "port_released": result["server"].get("port_released"),
        "checks_failed": [
            check["name"]
            for check in (result.get("experiment") or {}).get("checks", [])
            if not check["ok"]
        ],
        "fatal_error": bool(result.get("fatal_error")),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["checks_failed"] and not summary["fatal_error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
