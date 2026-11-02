# MCP Python SDK 2.3.0 Streamable HTTP 多客户端验证

- 生成时间：2026-10-30T08:04:45.269573+00:00
- 解释器：`E:\selenium-mcp\.venv\Scripts\python.exe`
- mcp 版本：`2.3.0`；httpx2：`httpx2 2.16.0`
- 服务地址：`http://127.0.0.1:8765/mcp`

## API 兼容性

- `mcp.server.fastmcp`：unavailable。ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and other APIs changed; see the migration guide at https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver or pin 'mcp<2' to keep running v1 code.
- 服务端实际类：`mcp.server.mcpserver.MCPServer`（FastMCP 在 2.x 已改名）。
- 客户端函数：`mcp.client.streamable_http.streamable_http_client`，签名 `(url: 'str', *, http_client: 'httpx2.AsyncClient | None' = None, terminate_on_close: 'bool' = True, max_sse_event_size: 'int | None' = 1048576) -> 'AsyncGenerator[TransportStreams, None]'`。
- 客户端上下文产出：2-tuple (read_stream, write_stream)，不再返回 get_session_id；旧名 `streamablehttp_client` 是否存在：False。
- 服务端 Streamable HTTP 参数：`{"host": "127.0.0.1", "port": 8000, "streamable_http_path": "/mcp", "json_response": false, "stateless_http": false, "event_store": null, "retry_interval": null, "max_request_body_size": 4194304, "session_idle_timeout": 1800, "max_sessions": 10000, "transport_security": null}`。
- session id 传递：HTTP 头 `mcp-session-id`（服务端下发、客户端回传），不在 URL 中。
- HTTP 证据：initialize 的 POST 请求无 session 头，响应头返回 `mcp-session-id`；后续 POST/GET/DELETE 均携带该头。

## 验证结论

- [PASS] 两个客户端均 initialize 成功：`"2025-11-25"`
- [PASS] 两个客户端 session id 不同：`{"A": "a85bbe35efa640548fbbe98dde65f470", "B": "72e414cd6c594f9db5cb44548f637229"}`
- [PASS] 并发 echo 结果正确：`[{"label": "A", "expected": "hello-A", "result": {"is_error": false, "text": "hello-A", "structured_content": {"result": "hello-A"}}}, {"label": "B", "expected": "hello-B", "result": {"is_error": false, "text": "hello-B", "structured_content": {"result": "hello-B"}}}, {"label": "A-reconnect", "expected": "reconnect-A", "result": {"is_error": false, "text": "reconnect-A", "structured_content": {"result": "reconnect-A"}}}]`
- [PASS] 两个客户端并发各调用 counter 两次均成功：`[1, 2, 3, 4]`
- [PASS] 并发爆发 10 次 counter 无异常：`[5, 7, 9, 11, 14, 6, 8, 10, 12, 13]`
- [PASS] 并发爆发 10 次 counter 返回值互不重复：`[5, 6, 7, 8, 9, 10, 11, 12, 13, 14]`
- [PASS] 客户端 A 已断开（发送 DELETE 终止会话）：`{"A_session": "a85bbe35efa640548fbbe98dde65f470"}`
- [PASS] A 断开后 B 仍可继续调用：`{"label": "B-after-A-close", "value": 15, "is_error": false, "structured_content": {"result": 15}}`
- [PASS] A 断开后重连成功且获得新 session id：`{"old_A": "a85bbe35efa640548fbbe98dde65f470", "B": "72e414cd6c594f9db5cb44548f637229", "new_A": "77394b1fc96c406a99e6bb0140ef84d0"}`
- [PASS] 重连后可继续调用 echo/counter：`{"echo": {"is_error": false, "text": "reconnect-A", "structured_content": {"result": "reconnect-A"}}, "counter": {"label": "A-reconnect", "value": 16, "is_error": false, "structured_content": {"result": 16}}}`
- [PASS] counter 跨客户端/跨会话共享且连续递增：`{"values": [1, 2, 3, 4, 5, 7, 9, 11, 14, 6, 8, 10, 12, 13, 15, 16], "expected": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]}`
- [PASS] 客户端上下文退出时发送 DELETE 终止会话：`{"requests": [{"phase": "request", "client": "A", "at": "2026-10-30T08:04:48.347860+00:00", "method": "DELETE", "url": "http://127.0.0.1:8765/mcp", "mcp_session_id": "a85bbe35efa640548fbbe98dde65f470", "mcp_protocol_version": "2025-11-25"}, {"phase": "request", "client": "B", "at": "2026-10-30T08:04:48.396842+00:00", "method": "DELETE", "url": "http://127.0.0.1:8765/mcp", "mcp_session_id": "72e414cd6c594f9db5cb44548f637229", "mcp_protocol_version": "2025-11-25"}, {"phase": "request", "client": "A-reconnect", "at": "2026-10-30T08:04:48.401841+00:00", "method": "DELETE", "url": "http://127.0.0.1:8765/mcp", "mcp_session_id": "77394b1fc96c406a99e6bb0140ef84d0", "mcp_protocol_version": "2025-11-25"}], "responses": [{"phase": "response", "client": "A", "at": "2026-10-30T08:04:48.352860+00:00", "method": "DELETE", "url": "http://127.0.0.1:8765/mcp", "status": 200, "mcp_session_id": "a85bbe35efa640548fbbe98dde65f470", "content_type": "application/json"}, {"phase": "response", "client": "B", "at": "2026-10-30T08:04:48.400841+00:00", "method": "DELETE", "url": "http://127.0.0.1:8765/mcp", "status": 200, "mcp_session_id": "72e414cd6c594f9db5cb44548f637229", "content_type": "application/json"}, {"phase": "response", "client": "A-reconnect", "at": "2026-10-30T08:04:48.406840+00:00", "method": "DELETE", "url": "http://127.0.0.1:8765/mcp", "status": 200, "mcp_session_id": "77394b1fc96c406a99e6bb0140ef84d0", "content_type": "application/json"}]}`
- [PASS] session id 通过 mcp-session-id 请求/响应头传递，未出现在 URL：`{"observed_session_ids": ["72e414cd6c594f9db5cb44548f637229", "77394b1fc96c406a99e6bb0140ef84d0", "a85bbe35efa640548fbbe98dde65f470"], "url_contains_session": false}`

## counter 状态

- 观察到的值序列：`[1, 2, 3, 4, 5, 7, 9, 11, 14, 6, 8, 10, 12, 13, 15, 16]`
- 结论：counter 保存在服务端进程内，跨客户端、跨会话共享；断线重连后继续累加。
- 并发时响应完成顺序与数值顺序不一致，说明请求确实并发执行；值集合仍完整且无重复。

## 并发与重连

- session id：`{"A": "a85bbe35efa640548fbbe98dde65f470", "B": "72e414cd6c594f9db5cb44548f637229", "A-reconnect": "77394b1fc96c406a99e6bb0140ef84d0"}`
- 两个客户端并发 initialize/调用均成功，session id 不同；A 断开后 B 不受影响，A 重连获得新 session id。

## Bearer 鉴权可行性

- 结论：**可行**（本次未实现）。
- 服务端：MCPServer 自带 auth/token_verifier 参数面向 OAuth 资源服务器；自研服务更简单的方式是在 ASGI/Starlette 层加中间件或反向代理校验 Authorization: Bearer <token>，未通过返回 401。
- 客户端：streamable_http_client 接受自定义 httpx2.AsyncClient，可在其 headers/auth 中统一注入 Bearer；也可用 create_mcp_http_client(headers=...)。SDK 会跟随同源重定向，不会把请求带到其他源。

## 异常与备注

- server stderr 记录 1 次 ConnectionResetError (WinError 10054)，出现在会话建立后的连接关闭阶段；所有 RPC 调用均成功，判定为 Windows Proactor 事件循环的关闭噪声（uvicorn/asyncio 已知现象），不影响功能。
- 备注：同一 asyncio 任务中串行关闭多个 streamable_http_client 上下文时，第二个上下文关闭阶段（发送 DELETE）会抛 CancelledError；本次改为每个连接独立 asyncio 任务承载后稳定。
- 备注：协商协议版本为 2025-11-25；服务端默认 json_response=False，initialize 响应以 text/event-stream 返回。

## 服务进程与端口

- 首选端口 8765 是否空闲：True；实际端口：8765；是否回退：False
- 退出码：1；终止方式：subprocess.terminate() + wait()；Windows 等价于强制结束，退出码 1 属预期
- 端口释放：True（bind(127.0.0.1:8765) 成功）
- 日志：`E:\selenium-mcp\spikes\mcp_http\server.stdout.log` / `E:\selenium-mcp\spikes\mcp_http\server.stderr.log`
