# selsnap 项目交接文档

- 日期：2026-11-08
- 仓库：`E:\selsnap`（remote：https://github.com/3588044667HZ/selsnap.git）
- 分支：`main`；已推送提交：`743a471`（M0），M1/M2 见 `git log -1`
- 当前状态：**M2 完成**（导航 + 快照 + 动作 + 团队共享/审计/鉴权 + 截图 + 模式升级），下一步 M3
- 本地未跟踪：`opencode.json`、`.opencode/`、`.idea/`

## 0. 新会话快速恢复

新会话先按顺序读：

1. `README.md`（项目定位与用法）
2. `docs/handover.md`（本文，环境与坑）
3. `docs/architecture.md`（架构决策）
4. `docs/spike-report-2026-10-30.md`（验证结论）

然后执行基线验证：

```powershell
cd E:\selsnap
E:\selsnap\.venv\Scripts\python.exe -m pytest -q
E:\selsnap\.venv\Scripts\python.exe scripts\smoke_m0.py
E:\selsnap\.venv\Scripts\python.exe scripts\smoke_m1.py
E:\selsnap\.venv\Scripts\python.exe scripts\smoke_m2.py
```

预期：`76 passed`；smoke_m0 `{"checks": 8, "failed": [], ...}`；smoke_m1 `{"checks": 16, "failed": [], ...}`；smoke_m2 `{"checks": 20, "failed": [], ...}`。

可直接复制给新会话的提示词：

> 继续开发 E:\selsnap（selsnap 项目）。先读 docs/handover.md、docs/architecture.md 和 README.md。当前 M0/M1/M2 已完成（M0 已推送，M1/M2 本地未提交）。先跑 pytest、scripts/smoke_m0.py、smoke_m1.py、smoke_m2.py 确认基线，然后按 handover 的 M3 计划实现 iframe/shadow 完善、上传下载、secret 注入、CAPTCHA 实测与超时重启。

## 1. 项目是什么

selsnap = Selenium + semantic snapshot。把 SeleniumBase 浏览器包装成 MCP 服务，让 agent 用**语义文本快照**而不是 HTML/截图理解页面：

- 每个可交互元素带稳定 `ref`（如 `[e12]`）
- 页面文档带 `doc_id`，导航后变化
- 文本预算默认 800 节点 / 16000 字符
- 单进程 Streamable HTTP，多客户端；命名会话；浏览器池上限 4
- 三种后端：`standard` / `uc` / `cdp`（后两者用于反检测场景）

目标场景：单机、Windows、agent team（≤ 4 个 agent）。

## 2. 代码地图

```
E:\selsnap\
├─ pyproject.toml             # 包名 selsnap；入口 selsnap = selsnap.server:main
├─ opencode.json              # opencode 的 remote MCP 配置（未提交）
├─ README.md                  # 对外文档（M1 状态、用法、路线图）
├─ LICENSE                    # MIT
├─ docs\
│  ├─ architecture.md         # ADR：9 条决策、工具面、错误协议、里程碑
│  ├─ spike-report-2026-10-30.md  # Chrome 156 三模式验证结果
│  └─ handover.md             # 本文
├─ src\selsnap\
│  ├─ config.py               # CLI/env 配置（前缀 SELSNAP_）、默认浏览器路径
│  ├─ errors.py               # ToolError + 结构化错误 payload
│  ├─ identity.py             # token→agent 映射、ContextVar、Bearer ASGI 中间件
│  ├─ audit.py                # JSONL 审计、参数脱敏
│  ├─ backend.py              # BrowserBackend：standard/uc/cdp，导航/JS/快照/截图/对话框/challenge
│  ├─ sessions.py             # SessionActor（线程+队列+ACL+挂起）、SessionRegistry（池/空闲清扫）
│  ├─ snapshot.py             # 注入 JS（语义遍历）+ Python 文本渲染/预算/diff
│  ├─ actions.py              # 动作管线：ref 探测、可操作性、重试、settle、观察与 diff
│  ├─ screenshots.py          # 视口/整页/元素截图、Pillow ref 标注、产物落盘
│  ├─ maintenance.py          # 启动时清理孤儿 Chrome/chromedriver
│  └─ server.py               # MCPServer、18 个工具、URL 策略、uvicorn+鉴权、main()
├─ tests\
│  ├─ test_snapshot.py        # 渲染、嵌套、转义、截断、空树
│  ├─ test_actions.py         # diff、ref/按键/选项校验、可操作性
│  ├─ test_acl.py             # owner/share/TTL/forbidden
│  ├─ test_audit.py           # 审计写入与脱敏
│  ├─ test_identity.py        # token map 解析与校验
│  ├─ test_sessions_lifecycle.py # 挂起/恢复/自动恢复 hook
│  ├─ test_challenge.py       # challenge 规则
│  ├─ test_screenshot_annotate.py # 标注绘制/缩放/越界
│  └─ test_url_policy.py      # scheme/凭据/无 scheme/端口
├─ scripts\smoke_m0.py        # 端到端 M0：起服务 → MCP 客户端 → standard+cdp
├─ scripts\smoke_m1.py        # 端到端 M1：动作、diff、stale_ref、standard/uc/cdp
├─ scripts\smoke_m2.py        # 端到端 M2：双 agent ACL/TTL、401、审计、截图、dialog、escalate、idle
├─ spikes\                    # 历史验证脚本与结果（含旧路径，见 §12）
├─ browsers\                  # 项目内 CFT Chrome（被 git 忽略）
└─ .venv\                     # Python 虚拟环境（被 git 忽略）
```

## 3. 环境与依赖（本机实测）

| 项 | 值 |
|---|---|
| OS | Windows（Git Bash 可用） |
| Python | 3.11.9（基础解释器 `D:\python311`） |
| venv | `E:\selsnap\.venv`（项目改名后仍可用；editable 已重装） |
| seleniumbase | 4.56.5 |
| selenium | 4.51.0 |
| mcp | 2.3.0（v2 API，见 §6.1） |
| pillow | 13.0.0 |
| Chrome（主） | CFT **156.0.8078.80**：`E:\selsnap\browsers\chrome-win64\chrome.exe` |
| chromedriver / uc_driver | 156.0.8078.80，位于 venv 的 `seleniumbase\drivers\` |
| 旧 Chrome | 109.0.5414.120：`%LOCALAPPDATA%\Google\Chrome\Bin\chrome.exe`（保留，不再作为测试目标） |
| Edge | 156.0.4314.50（备选；CDP+Edge 在 sannysoft 会卡 loading） |
| 代理 | `127.0.0.1:10808`（HTTP/SOCKS 都可用） |
| 磁盘 | E: 约 6.8GB 可用（`browsers\*.zip` 约 210MB，可删） |

安装/修复：

```powershell
E:\selsnap\.venv\Scripts\python.exe -m pip install -e E:\selsnap --no-deps
```

> 若项目目录再次移动，必须重跑上面的 editable 安装；Windows venv 本身可随目录移动，但 `.pth` 指向旧 `src` 路径。

下载 Chrome 的注意点：

- Google Storage 经当前代理返回 **403**（地区限制）
- 可用镜像：`https://cdn.npmmirror.com/binaries/chrome-for-testing/156.0.8078.80/win64/chrome-win64.zip`
- SeleniumBase 会自动下载匹配 driver；显式传浏览器路径可避免它误选系统旧 Chrome 109

## 4. 运行方式

```powershell
# 启动服务（先确保 8765 端口空闲）
E:\selsnap\.venv\Scripts\selsnap.exe --port 8765

# 或
E:\selsnap\.venv\Scripts\python.exe -m selsnap.server --port 8765
```

- MCP 端点：`http://127.0.0.1:8765/mcp`（Streamable HTTP）
- 默认绑定 `127.0.0.1`，池 4，headless
- 环境变量前缀：`SELSNAP_`（`SELSNAP_BROWSER`、`SELSNAP_PORT`、`SELSNAP_POOL_SIZE` 等）

opencode 配置（`E:\selsnap\opencode.json`，未提交）：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "selsnap": {
      "type": "remote",
      "url": "http://127.0.0.1:8765/mcp",
      "enabled": true
    }
  },
  "experimental": { "mcp_timeout": 120000 }
}
```

使用前提：

1. 先启动 selsnap 服务
2. 从 `E:\selsnap` 启动 opencode 才会加载该配置
3. 改配置后必须重启 opencode
4. 当前默认工作区（`...\Default Project`）有自己的 `opencode.json`（含 ppt/word MCP），不会自动加载这份；要用需把同一段复制过去

## 5. 已实现能力（M2）

| 工具 | 行为 |
|---|---|
| `session_open(name, mode, headless, auto_escalate)` | 打开/复用会话；mode = standard/uc/cdp |
| `session_attach(name)` | 返回已有会话信息（挂起会自动恢复） |
| `session_list()` | 列出当前 agent 可见会话 |
| `session_close(name)` | 关闭并释放浏览器（仅 owner） |
| `session_share(name, agent, mode, ttl)` | read/write/revoke 共享，可选 TTL |
| `session_escalate(session, mode)` | standard → uc → cdp，同 profile 重启并恢复 URL |
| `navigate(session, url)` | 导航；自动返回快照与 challenge 检测 |
| `snapshot(session)` | 返回当前页面语义快照 |
| `page_info(session)` | URL、标题、`doc_id`、`readyState`、challenge |
| `screenshot(session, ref, full_page, annotate)` | PNG image content + 元数据 |
| `click(session, ref, button, count, full)` | 左键/右键单击、左键双击 |
| `click_at(session, x, y, button, count, full)` | 按视口坐标点击 |
| `type(session, ref, text, clear, submit, full)` | 清空后输入，可选 Enter 提交 |
| `select(session, ref, option, full)` | 原生 select，按 value 或可见文本匹配 |
| `press(session, keys, ref, full)` | Enter/Tab/Escape/方向键/F1-F12/单字符/组合键 |
| `hover(session, ref, full)` | 鼠标悬停 |
| `scroll(session, ref, dy, full)` | 页面滚动或滚动元素到视口中央 |
| `dialog(session, action, text, full)` | 处理原生 alert/confirm/prompt |

- URL 策略：仅 http/https；拒绝 URL 内凭据；无 scheme 自动补 `https://`
- 浏览器池：`threading.BoundedSemaphore(4)`；第 5 个请求最多等 30s，然后 `resource_busy`
- 会话级 actor 线程：命令串行，避免 WebDriver 竞态
- 动作默认只返回 diff；`full=true` 强制完整快照
- `stale_ref` 错误自动附最新快照、`doc_id`、`url`

### 5.1 动作管线（M1）

每次动作按以下顺序执行：

1. `_assert_doc`：当前 `data-mcp-doc` 必须等于会话最近快照的 `doc_id`
2. 原生对话框检测（standard/uc/CDP）：存在则 `dialog_open`
3. `scrollIntoView({block:"center"})`，轮询探测直到 bounding rect 跨两帧稳定
4. 可操作性检查：found / disabled / visible / in_viewport / covered（`elementFromPoint`）/ editable / select
5. 执行动作；Stale 或 not_actionable 重试 2 次（共 3 次尝试）
6. 动作后再次检测原生对话框
7. settle：MutationObserver 静默 300ms + `readyState` + 最近 500ms 无新资源，封顶 `settle_timeout`（默认 5s）
8. 重新采集快照并按 ref 对比，返回 diff

动作响应示例：

```json
{
  "ok": true,
  "action": "type",
  "ref": "e14",
  "doc_id": "d...",
  "settle": {"settled": true, "reason": "quiet", "elapsed_ms": 537},
  "changed": true,
  "diff": {
    "added": [], "removed": [],
    "updated": ["- textbox [e14] value=\"hello\" type=\"text\""],
    "new_refs": [], "removed_refs": [], "updated_refs": ["e14"],
    "change_ratio": 0.012
  }
}
```

全量快照返回条件：导航（`doc_id` 变化）、没有历史快照、`change_ratio > 0.5`、显式 `full=true`；此时响应含 `snapshot` 与 `full_snapshot_reason`。

### 5.2 身份 / ACL / 审计（M2）

- **身份**：`SELSNAP_TOKENS='{"token":"agent"}'` 支持多 token；`SELSNAP_TOKEN` 单 token 映射到 `SELSNAP_AGENT_NAME`（默认 `local`）。未配置 token 时鉴权关闭，所有请求按默认 agent 处理。
- **鉴权**：纯 ASGI middleware 校验每个 HTTP 请求的 `Authorization: Bearer ...`（POST/GET SSE/DELETE）；失败返回 401 JSON。token 只存在于配置与请求头，不写日志/审计。
- **ACL**：会话默认私有；owner 拥有 read/write/close/share；`session_share` 支持 `read` / `write` / `revoke`，`ttl` 秒（上限 30 天），授权按 agent 记录并在访问时惰性过期。写权限不做服务端强锁。
- **审计**：默认写 `var/audit-YYYY-MM-DD.jsonl`，字段：`ts/agent/owner/tool/session/args/ok/error_code/duration_ms/url/doc_id`。`type` 的文本只记录长度与 SHA256 前缀；token/password/secret 等参数键替换为 `***`。写失败只告警，不影响工具。
- **截图**：`screenshot` 返回 MCP image content（PNG）+ JSON 元数据；支持视口/整页/元素，`annotate=true` 用 Pillow 叠加 ref 标签。产物保存在 `var/artifacts/<session>/`（可配 `--artifact-dir`），单图上限 4000 万像素。
- **对话框**：standard/uc 走 Selenium alert API；CDP 注册 `Page.javascriptDialogOpening/Closed` 事件并通过 `Page.handleJavaScriptDialog` 处理。
- **模式升级**：`session_escalate` 关闭当前 driver，以同一 profile 重启到目标模式并恢复 URL；`session_open(auto_escalate=true)` 在导航检测到挑战页时自动升级。每会话 profile 位于 `var/profiles/<name>`，持久 cookie 可跨重启保留。
- **空闲生命周期**：默认 2h 未使用后挂起（关闭浏览器、保留 profile、释放池许可）；再次访问 `get`/`call` 自动恢复并重新采集快照。启动时按 profile 根目录清理孤儿 Chrome，并清理 venv 下父进程已消失的 chromedriver。

## 6. 关键实现细节与坑（务必读）

### 6.1 mcp 2.3.0 是 v2 API，不要按旧文档写

- 服务端：`from mcp.server.mcpserver import MCPServer`
- M2 起用 `app = mcp.streamable_http_app(...)` + `uvicorn.run(app)`，以便挂 Bearer 中间件；不要再调 `mcp.run()`（它内部同样走 `streamable_http_app`）
- 客户端（测试用）：`from mcp.client.streamable_http import streamable_http_client`，返回 `(read, write)` 两元组
- session id 走 HTTP 头 `mcp-session-id`，不在 URL
- 协议版本实测 2025-11-25
- 工具函数是**同步**的，SDK 会放到工作线程执行；我们的会话 actor 再串行化每个浏览器
- dict 返回值会进 `structured_content`（可能包一层 `result`）；smoke 的 `payload()` 兼容两种

### 6.2 WebDriver 与 CDP 的 execute_script 语义不同

- CDP（`sb_cdp`）：按**表达式**求值，不能写 `return {...}`
- WebDriver：需要 `return`，且必须写成 `"return (" + expr + ")"`
- **坑**：`"return\n(expr)"` 会触发 JS 自动分号插入，结果是 `undefined` → Python 收到 `None`（M0 已修）

### 6.3 UC 模式用 `Driver(uc=True)`，不要用 `SB(uc=True)`

- 本机实测：`SB(uc=True)` 能启动/导航，但 `sb.driver.execute_script` 会断连（WinError 10061）
- `Driver(uc=True, binary_location=CFT)` 稳定：Chrome 156 下 sannysoft 31/0，webdriver=false
- `Driver` 不暴露 `solve_captcha`；CAPTCHA 通过升级到 CDP 会话处理（M2）

### 6.4 快照 ref 生命周期

- JS 在 `<html>` 上维护：
  - `data-mcp-doc`：文档 id（导航后重建）
  - `data-mcp-ref-counter`：ref 计数器
- 元素首次出现时写 `data-mcp-ref="eN"`；后续快照复用
- ref 按文档顺序预分配（父节点先于子节点）
- ref 编号按会话跨文档单调递增：新文档从上一文档最大 ref 继续（`SessionActor.next_ref_base`），因此导航后旧 ref 不会误命中新元素
- 导航后 `doc_id` 变化 → 旧 ref 失效；M1 动作工具已强制校验（`stale_ref`）
- 隐藏节点、`aria-hidden="true"`、脚本/样式/SVG 被剔除
- 开放 Shadow DOM 会遍历；跨源 iframe 只保留占位；closed shadow root 不可见
- 结构型 role（document/navigation/list/listitem/table/row/cell 等）不把 innerText 当 name，避免重复

### 6.5 会话与池

- `SessionRegistry.open`：先拿池许可，再查重名；已存在则复用并释放许可
- `SessionActor`：每会话一个线程 + `queue.Queue` + `concurrent.futures.Future`
- 工具调用超时后，命令**仍可能**在 actor 中继续执行，后续命令排队；M2 可考虑超时重启会话
- 没有空闲回收（ADR 计划 2h，未实现）；退出进程才会清理
- `session_close` 会 quit 浏览器并释放池许可

### 6.6 M1 动作实现细节

- **状态**：`SessionActor.last_doc_id / last_tree / last_snapshot_text / last_url`，只在 actor 线程内读写；每次 `navigate`、`snapshot`、动作后的采集都会 `record_snapshot`
- **ref 定位**：统一用 CSS `[data-mcp-ref="eN"]`，三种后端一致；不跨调用传元素句柄
- **动作实现分支**：
  - standard/uc：WebDriver 原生 `element.click()` / `ActionChains.double_click` / `context_click` / `send_keys`；异常按类名与消息翻译成 `stale_ref` / `not_actionable` / `dialog_open`
  - cdp：左键单击用 `sb_cdp.click()`；右键/双击用 `mycdp.input_.dispatch_mouse_event`（`click_count` 1 再 2 触发 dblclick）；输入用 `element.send_keys`；按键用 `dispatch_key_event` + modifiers 位掩码
- **settle 是异步脚本**：`backend.execute_async_script` 对 WebDriver 用 `execute_async_script` 包装 Promise，对 CDP 用 `page.evaluate(await_promise=True)`；动作触发导航时脚本上下文会被销毁，返回 `reason="context_destroyed"`，随后 `wait_document_ready` 等待 `readyState=complete`
- **diff 协议**：结构化 patch + 渲染后的文本行（`added` / `removed` / `updated` 各为行数组，另附 `*_refs`）；按 ref 对比，跨文档导航不计算 diff，直接返回完整快照
- **重试边界**：只重试 `stale_ref`（且不是 doc 不匹配）与 `not_actionable`；每次重试重新滚动、探测、检查。动作执行后若已发生部分输入再重试，可能出现重复输入（已知风险）
- **原生对话框**：standard/uc 用 `switch_to.alert` 检测；CDP 通过 `Page.javascriptDialogOpening/Closed` handler 维护状态。动作打开对话框会返回 `dialog_open` 且不再采集快照
- **性能实测**（demo 页，standard）：click ~0.82s、type ~0.78s、select ~0.78s（smoke_m1 计时，含 settle ~0.5s 与快照）

### 6.7 M2 实现细节与坑

- **鉴权上下文**：`identity.py` 用 ContextVar 保存当前 agent；ASGI 中间件在每个请求开始时 set、结束时 reset。MCP 同步工具由 anyio 线程池执行，会复制 context，所以工具里 `current_agent()` 能看到请求身份。多 token 用 `SELSNAP_TOKENS` JSON，单 token 仍兼容 `SELSNAP_TOKEN`。
- **会话 ACL**：owner/share/TTL 状态在 `SessionActor`；`SessionRegistry.get(session, agent, access)` 是唯一入口，读工具用 `read`、动作/导航/升级用 `write`、close/share 仅 owner。`session_share` 在 server 层再检查 owner。
- **审计包装**：`server._tool` 装饰器包住所有工具（保留 `__signature__`），根据返回 dict/CallToolResult 提取 `ok/error_code/url/doc_id`；`type` 文本只存长度 + SHA256 前 16 位。审计写失败不会影响工具调用。
- **截图返回类型坑**：`from __future__ import annotations` 会让 `-> CallToolResult` 变成字符串注解，MCPServer 无法识别 CallToolResult 特例，会生成 `{"result": ...}` 输出模型导致 `ValidationError`。因此 screenshot 注册时必须 `@_tool(structured_output=False)`，返回 `CallToolResult(content=[ImageContent, TextContent], structured_content=meta)`。
- **截图坐标**：整页截图尺寸等于 `documentElement.scrollWidth/scrollHeight * DPR`，而 `innerWidth` 可能含滚动条；标注/裁剪用 `scrollWidth` 计算 scale，并加 `scrollX/scrollY` 偏移。元素截图先 `scrollIntoView`，再整页截图裁剪。
- **CDP 对话框**：在 open 时注册 `Page.javascriptDialogOpening/JavascriptDialogClosed` handler；打开的对话框会让 Page 命令阻塞，检测到标志后不要再执行普通 JS，直接 `Page.handleJavaScriptDialog`。
- **模式升级 / profile**：`SessionActor.escalate_locked` 只允许在 actor 线程内调用；关闭旧 backend、用同一 `var/profiles/<name>` 新建 backend、恢复 URL。持久 cookie 会保留，但 session cookie（无 expiry）不会。
- **空闲挂起**：`SessionActor.suspend()` 关闭浏览器并保留 profile；registry 释放池许可；`call()` 在检测到挂起时调用 `_resume_hook`（`_ensure_active`）重新申请许可并恢复。suspend 内还有一次 idle 复核，避免浏览器启动期间被误挂起。
- **孤儿清理**：`maintenance.cleanup_orphans` 用 psutil 按 profile 根目录匹配 chrome 命令行；对 venv 下 seleniumbase chromedriver，仅当父进程已消失时清理，避免误杀另一个运行中的 selsnap。

## 7. 已知限制

- 共享写权限不做服务端强锁；多个 agent 同时写同一会话需自行协调
- 审计写本地 JSONL，不做集中日志、签名或防篡改
- 截图上限 4000 万像素；超长页面直接返回 `screenshot_failed`
- 元素截图基于当前整页渲染，不展开 iframe / closed shadow root
- 模式升级只保留持久 cookie；无 expiry 的 session cookie 会丢失
- 命令超时后不会自动重启会话（M3）
- 动作后 diff 只按 ref 对比；跨文档导航直接返回完整快照，不做行级 diff
- 自定义下拉（非原生 select）需用 click 序列操作
- `press` 在动作重试时可能重复发送部分按键（已知风险）
- 仅 HTTP 传输，没有 stdio；opencode 用 remote 配置
- 空闲 2h 挂起，但不会删除 profile；profile 会持续占用磁盘
- 跨源 iframe 不展开；closed shadow root 不可见
- Windows 优先验证（代码本身未绑定平台，但默认浏览器路径按项目目录）
- 状态：**M2，不适合生产**

## 8. 下一步：M3（建议实施顺序）

1. **iframe / Shadow DOM 完善**
   - 同源 iframe 内联快照与动作（ref 空间不冲突）
   - 跨源 iframe 通过 `snapshot scope=<ref>` 单帧快照；动作在 frame 内定位
   - open shadow root 已支持；closed root 继续标注为不可见
2. **上传 / 下载**
   - `upload(session, ref, paths)`：路径白名单、会话沙箱
   - `download` 事件监听、文件大小上限、产物落盘与审计
3. **secret 注入**
   - `${secret:NAME}` 服务端替换（type 的文本不进入模型上下文）
   - secret 只存在服务端配置/环境，不写审计/日志
4. **CAPTCHA best-effort**
   - `captcha_solve(session)`；失败返回截图 + `captcha_present`
   - 区分 Turnstile/reCAPTCHA/hCaptcha 的实测覆盖率
5. **超时重启**
   - 命令超时后安全回收 actor，重建 backend（保留 profile），标记会话可恢复
   - 避免超时命令仍在 actor 中继续执行造成竞态
6. **性能与稳定性**
   - 大 DOM / SPA 快照预算调优；snapshot p50 目标
   - 截图 p95、动作 p95 纳入 smoke 输出
   - 空闲挂起/恢复的并发测试（池满时恢复返回 `resource_busy`）

验收建议：

- pytest 增加 iframe/upload/secret/timeout 单测
- smoke_m3 覆盖同源 iframe、上传下载、secret 替换、CAPTCHA 演示页、超时重启
- 审计确认 secret 与上传路径不泄露

## 9. M2 验收记录

- 单测 76 个：`pytest -q`
- smoke_m0 8 项、smoke_m1 16 项、smoke_m2 20 项全部通过
- smoke_m2 覆盖：双 agent share/read/write/TTL/revoke、401、审计脱敏、视口/整页/元素截图、`click_at`、`dialog accept`、`session_escalate`、`auto_escalate`、空闲挂起/自动恢复
- 截图实测：viewport 1424x1785、full page 1409x4000、element 220x60；整页标注正常
- 动作实测（demo 页，standard）：click ~0.82s、type ~0.78s、select ~0.78s（含 settle 与快照），满足 p50 < 1.2s
- Chrome 156 stealth 结论（spike，非 SLA）：
  - standard：sannysoft 6/5，browserScan Robot
  - uc：sannysoft **31/0**，BrowserScan Normal
  - cdp：sannysoft **30/0**，BrowserScan Normal
  - CDP Turnstile demo：solve 成功 1.98s（`#captcha-success` 可见）

## 10. Git / 发布状态

- remote：`origin https://github.com/3588044667HZ/selsnap.git`
- 已推送：`743a471`（M0）；M1/M2 提交见 `git log -1`
- 本地未跟踪：`opencode.json`、`.opencode/`、`.idea/`
- License：MIT
- PyPI 包名 `selsnap` 目前可用（`selenium-mcp` 已被同名项目占用，勿使用）
- 没有 `.gitattributes`；Windows 提交会有 LF→CRLF 警告，属正常

## 12. 历史产物与旧路径

`spikes\` 已提交，包含验证脚本、结果 JSON/MD。注意：

- 这些脚本里仍写着旧路径 `E:\selenium-mcp\...`（项目后来改名为 `E:\selsnap`）
- 归档脚本**不可直接重跑**；结论看 `docs/spike-report-2026-10-30.md`
- profile、下载文件、HTML、PNG/PDF、日志已被 `.gitignore` 排除

## 13. 协作约定（沿用）

- 中文交流；代码注释用中文，只在逻辑不显然时添加
- 不写多余注释与防御性冗余；但 API/外部输入边界要做校验
- 任务清单只用于超过 5 步或跨 3 个文件的任务
- 不主动 commit / push；需要时用户会明确说
- 验证优先于口头结论：改完代码跑 `pytest` 和 smoke

## 14. 待决策问题

1. ~~鉴权身份模型~~：已定 token → agent 映射（`SELSNAP_TOKENS`），单 token 兼容
2. ~~动作后 diff 的协议~~：已定为结构化 patch + 渲染文本行（`added/removed/updated/change_ratio`）
3. ~~全页截图~~：已定 `Page.captureScreenshot(captureBeyondViewport=True)`，元素截图用整页裁剪
4. 是否增加 stdio 传输（如果 opencode 需要 local 模式）
5. 超时重启策略：何时判定 actor 已卡死、是否保留 profile、是否自动恢复
6. 是否发布 PyPI（`selsnap`，当前 0.2.0）、是否需要 GitHub Actions CI
7. 审计是否增加集中式日志/签名，或仅保留本地 JSONL

## 15. 关键参考

- `docs/architecture.md`：9 条决策、工具面、错误协议
- `docs/spike-report-2026-10-30.md`：环境、三模式、MCP SDK、风险
- Playwright MCP（快照 + ref 先例）、SeleniumBase MCP（SeleniumBase 官方）、browser-use（DOM 索引算法）
