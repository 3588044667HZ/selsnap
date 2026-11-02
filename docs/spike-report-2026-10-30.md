# Spike 报告：SeleniumBase 三模式验证（含 Chrome 156 复测）

- 日期：2026-10-30（Chrome 156 复测完成）
- 环境：Windows、Python 3.11.9、SeleniumBase 4.56.5、selenium 4.51.0、mcp 2.3.0
- 结论：三模式均可运行；Chrome 156 上 UC / CDP 达到预期 stealth；standard 被检测站识别。浏览器已固定在项目内，后续不依赖自动发现。

## 1. 环境

| 项 | 值 |
|---|---|
| 项目内 CFT Chrome | **156.0.8078.80**，`E:\selsnap\browsers\chrome-win64\chrome.exe`（通过 npmmirror 镜像安装） |
| chromedriver | 156.0.8078.80，已放入 SeleniumBase drivers 目录 |
| 系统旧 Chrome | 109.0.5414.120，`%LOCALAPPDATA%\Google\Chrome\Bin\chrome.exe`（保留，不再作为测试目标） |
| Edge | 156.0.4314.50（现代浏览器对照与 CDP 备选） |
| 下载备注 | Google Storage 经代理返回 403（地区限制）；CFT 改从 `cdn.npmmirror.com` 下载（Chrome zip 199MB + driver 11MB） |

## 2. 能力与性能（Chrome 109 基线）

| 测试 | standard `Driver()` | uc `Driver(uc=True)` | cdp `sb_cdp.Chrome()` |
|---|---|---|---|
| 启动 | PASS 1.75s | PASS 3.26s | PASS 1.22s |
| demo_page 加载 | PASS 1.05s | PASS 1.61s | PASS 1.30s |
| JS 注入（普通页） | PASS 9ms | PASS 9ms | PASS |
| 元素 total/visible/interactive | 141/98/23 | 141/98/23 | 141/96/19 |
| 截图 | PASS 71.9KB | PASS 64.5KB | PASS 64.0KB（仅视口） |
| 标签页 开/列/切/关 | PASS | 未测 | PASS |
| cookie / localStorage | PASS | PASS | PASS |
| profile 持久化 | PASS | - | PASS |
| PDF 导出 | 未测 | - | PASS 210KB |
| 50k 节点 DOM 遍历 | 118ms | - | 88ms |
| 截图耗时 | 0.31s | 0.27s | 0.45s |
| navigator.webdriver | true | false | false |
| plugins 数量 | 0 | 5 | 5 |
| window.chrome | false | true | true |

补充：CDP 方法面共 286 个非 dunder 方法，导航/JS/标签页/cookie/storage/profile 全可用；`save_page` 不存在；截图无 full-page 参数。

## 3. Stealth 对比

### sannysoft（passed / failed，越大越好）

| 模式 | Chrome 109 | Chrome 156（项目内） | Edge 156 |
|---|---|---|---|
| standard | 3 / 8 | 6 / 5 | 7 / 4 |
| uc | **31 / 0** | **31 / 0** | 不支持（UC 为 Chrome 系） |
| cdp | **31 / 0** | **30 / 0** | 页面 25s 仍 loading、body 为空（未出结果） |

### browserscan 判定（Test Results 第一项）

| 模式 | Chrome 109 | Chrome 156（项目内） | Edge 156 |
|---|---|---|---|
| standard | **Robot** | **Robot** | **Robot** |
| uc | **Normal** | **Normal** | - |
| cdp | **Normal** | **Normal** | **Normal** |

### CAPTCHA（Chrome 156 / CDP）

- 页面：`https://seleniumbase.io/apps/turnstile`
- `solve_captcha()`：成功，**1.98s**；`#captcha-success` 可见，`#captcha-failure` 不可见。
- demo 站点结果，不代表通用绕过；生产仍需人工兜底路径。

### 结论

- 「只隐藏 webdriver」不够：standard 在 Chrome 156 上 webdriver 为 true、Edge 156 上为 false，但 browserscan 都判 Robot。
- UC / CDP 在现代 Chrome 上稳定达标，可作为绕过主路径。

## 4. 后端入口差异（重要）

| 场景 | 结论 |
|---|---|
| UC | 用 `Driver(uc=True, binary_location=CFT)`：稳定，Chrome 156 下 sannysoft 31/0。 |
| UC + SB() | `SB(uc=True)` 能启动并导航，但 `sb.driver.execute_script` 会断连（WinError 10061），不能用于快照注入。 |
| CAPTCHA | `Driver(uc=True)` 不暴露 `solve_captcha`；通过会话升级到 `cdp`（同 profile 重启）处理，不依赖 `activate_cdp_mode`。 |
| CDP | `sb_cdp.Chrome(browser_executable_path=CFT)` 正常；`execute_script` 是表达式求值，不能写 `return` 函数体。 |

## 5. CDP API 关键差异

- `sb_cdp.Chrome(url=None, **kwargs)`，支持 `headless`、`user_data_dir`、`browser_executable_path`。
- `execute_script` 是表达式求值：写成 `(() => ({...}))()`；`Driver.execute_script` 需要 `return (...)`。快照脚本按后端分别封装。
- 截图仅视口；全页需要 `Page.captureScreenshot(captureBeyondViewport)` 或滚动拼接（待验证）。
- 提供 `get_all_cookies/set_all_cookies`、local/session storage、`get_tabs/open_new_tab/switch_to_tab`、`print_to_pdf`。

## 6. MCP SDK（mcp 2.3.0）验证

- v2 API：`mcp.server.fastmcp` 已移除；服务端类为 `mcp.server.mcpserver.MCPServer`。
- 客户端 `streamable_http_client` 返回 `(read, write)` 两元组，不再提供 `get_session_id`。
- session id 仅通过 HTTP 头 `mcp-session-id` 传递（initialize 响应下发，后续 POST/GET/DELETE 回传）；URL 不含 session。
- 两个并发客户端 session id 不同、互不影响；断开重连获得新 session，工具可继续调用。
- 服务端全局状态跨会话共享；同步工具由 SDK 放入工作线程执行，实际并行（counter 需加锁）。
- Bearer 鉴权可行：ASGI/Starlette 中间件或反向代理；GET SSE 与 DELETE 也必须携带；SDK 自带 auth 偏 OAuth，复杂度高。
- 协商协议版本：2025-11-25；关闭阶段有 Windows `ConnectionResetError` 噪声。

## 7. 问题与风险

1. **浏览器发现不稳定**：SeleniumBase 在本机会找不到或选错 Chrome（旧 Chrome 在 `Bin\`、CFT 空目录）。已固定项目内 CFT 156 并显式传路径，规避该问题。
2. **UC 与 SB 不兼容（本机实测）**：`SB(uc=True)` 下 `sb.driver.execute_script` 断连；UC 统一用 `Driver(uc=True)`。
3. **CDP + Edge 156 在 sannysoft 卡住**：25s 仍 loading、body 为空；browserscan 正常。Chrome 156 + CDP 正常，Chrome 为主路径。
4. **视觉截图的 full-page**：CDP 当前只有视口截图，需自研拼接或走 CDP 原生能力。
5. **快照性能尚未测真实角色计算**：50k 节点纯遍历 88–118ms；加入 role/name/可见性判断后预计明显增加，需在 M0 优化并设预算。
6. **绕过不是 SLA**：Turnstile demo 成功不代表真实站点通用；挑战规则需要在真实页面上统计命中率/误报。

## 8. 对架构的落地调整

- 后端实现：standard 用 `Driver()`；uc 用 `Driver(uc=True)`；cdp 用 `sb_cdp.Chrome()`。
- 浏览器固定：项目内 `browsers/chrome-win64/chrome.exe`（CFT 156.0.8078.80）+ 同版本 chromedriver，显式传 `binary_location` / `browser_executable_path`。
- 快照注入脚本按后端适配调用方式（Driver `return`，CDP 表达式）。
- CAPTCHA 走「会话升级到 CDP」路径；`activate_cdp_mode` 不作为依赖。
- 工具 `screenshot` 的 full-page 模式列为 M2/M3 任务；v1 先用视口 + 滚动截图。
- MCP 依赖锁定 `mcp == 2.3.0`（v2 API），按 `MCPServer` + `streamable_http_client` 写，不按旧的 FastMCP 文档。

## 9. 待补验证

1. CDP 全页截图方案（`captureBeyondViewport` / 拼接）。
2. 真实挑战页（Cloudflare 等）的检测规则命中率与误报。
3. 真实快照 walker（role/name/可见性）在重页面上的耗时与 token。
4. 4 个 Chrome 并发时的内存/CPU 与调度表现。
5. `mcp` 2.3.0 自研服务的 Bearer 中间件实现与鉴权联调。

## 10. 产物索引

- `spikes/standard_uc/result.md`（standard/uc 详细结果，Chrome 109）
- `spikes/cdp/result.md`（CDP 方法矩阵与全部用例，Chrome 109）
- `spikes/stealth/result.md`（三模式检测对比、Turnstile demo，Chrome 109）
- `spikes/mcp_http/result.md`（MCP SDK 并发/会话/鉴权结论）
- `spikes/crosscheck/crosscheck.json`、`crosscheck2.json`（Edge 156 对照与 CDP 复测）
- `spikes/chrome156/check.py`、`result.json`（Chrome 156 三模式检测）
- `spikes/chrome156/verify156.py`、`verify156.json`（UC 复测 + Turnstile 判定）
