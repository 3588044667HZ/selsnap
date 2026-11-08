# selsnap — 架构决策记录（ADR-001）

- 状态：M2 已实现（基线 smoke_m2 20/20）；首轮 spike 见 `docs/spike-report-2026-10-30.md`
- 日期：2026-10-30（M2 更新：2026-11-08）
- 项目路径：`E:\selsnap`
- 范围：单机 Windows、agent team（≤ 4 个 agent）网页访问

## 1. 背景与目标

为 agent team 提供统一的网页访问 MCP 服务：文本为主、视觉辅助；低 token 观测；交互稳定；团队可共享会话；行为可审计。

约束与前提：

- 单机部署，Windows 原生进程，暂不引入 Docker
- 团队规模 ≤ 4，并发浏览器上限 4
- Python 技术栈
- 需要 stealth / 反检测能力（UC / CDP 模式），但不承诺万能绕过
- 当前处于设计阶段，尚未开始实现

## 2. 决策总览

| 编号 | 决策 | 理由 |
|---|---|---|
| D1 | Streamable HTTP 单服务 + Bearer；浏览器会话独立于 MCP 连接 | 团队共享、断线重连可恢复 |
| D2 | 每会话一个 Chrome 进程，池上限 4；每会话一个 actor 线程串行执行 | Selenium 同步模型简单可靠，避免竞态 |
| D3 | 自动化底座用 SeleniumBase（standard / uc / cdp 三模式），MCP 与观测层自研 | 获得 stealth 能力，同时保留团队/快照/动作设计 |
| D4 | 文本优先：语义快照 + 稳定 ref + 动作后 diff | token 经济、可操作、可跨调用引用 |
| D5 | 动作自带观测；内置 settle/遮挡检测/stale 重试 | Selenium 无自动等待，这层是可靠性核心 |
| D6 | 会话默认私有，显式 share（read/write/revoke + TTL） | 团队交接可控，防误操作 |
| D7 | 挑战页检测 + 自动/手动升级模式；CAPTCHA best-effort | 「绕过」需求落地为可配置能力 |
| D8 | secret 占位符、URL 策略、上传/下载沙箱、JSONL 审计 | agent 浏览的是不可信内容 |
| D9 | 结构化错误协议（错误码 + hint，必要时附新快照） | agent 自愈，减少往返回合 |

## 3. 拓扑

```text
Agent A ─┐
Agent B ─┼── MCP Streamable HTTP ──┐   Bearer token（映射 agent 身份）
Agent C ─┘   Mcp-Session-Id        │
                                   ▼
                     ┌──────────────────────────────┐
                     │ MCP Server（Python / asyncio）│
                     │  Tool Router                 │
                     │  Session Registry + ACL      │
                     │  Scheduler（池=4，公平队列）   │
                     │  Session Actor ×N（线程）     │
                     │   ├ BrowserBackend 适配       │
                     │   │   standard / uc / cdp    │
                     │   ├ Snapshot Engine（注入 JS）│
                     │   └ Settle / Retry 管线       │
                     │  Artifact Store + Audit      │
                     └──────────────┬───────────────┘
                                    │
                 Chrome 进程 #1 … #4（每会话独立 profile）
```

## 4. D1 部署与传输

- 单一常驻 MCP 服务，默认监听 `127.0.0.1`（端口可配），Streamable HTTP 传输。
- 鉴权：Bearer token，映射到 agent 名称，用于 ACL 与审计归属。
- 浏览器会话是服务端资源，按名字持有；MCP 连接断开或 agent 重启后，可 `session_attach(name)` 恢复。
- 备选：若 agent 框架只支持 stdio，增加一个薄 stdio shim 转发到本服务；不改变服务端设计。
- 不支持：多机、Grid、Docker/K8s（当前非目标）。

## 5. D2/D6 会话模型

- 每个会话 = 一个 Chrome 进程 + 一个独立 profile 目录 + 一个 actor 线程（命令队列串行执行）。
- 池上限 4；第 5 个请求排队，30s 超时返回 `resource_busy`；调度按 agent 轮转，避免单 agent 独占。
- 会话默认私有；`session_share(session, agent, mode=read|write|revoke, ttl=...)` 授权/撤销，TTL 上限 30 天；越权返回 `forbidden`。写权限不做服务端强锁，靠 agent 协调，审计同时记录 owner 与操作者。
- 空闲 2h 后挂起 driver（关闭浏览器、保留 profile、释放池许可）；下次访问自动恢复并重新采集快照；显式关闭或进程异常才删除会话；启动时按 profile 目录前缀清理孤儿 Chrome/chromedriver。
- 资源隔离：每会话独立 profile，cookie/storage 不串；持久 cookie 跨模式升级与挂起恢复保留，session cookie 不保留。

## 6. D3 技术栈与后端适配

| 层 | 选型 |
|---|---|
| 运行时 | Python 3.11+，asyncio |
| MCP | 官方 `mcp` Python SDK 2.3（`MCPServer` + Streamable HTTP；session id 走 `mcp-session-id` 头） |
| 自动化内核 | SeleniumBase（MIT）：`Driver()` / `SB()` / `sb_cdp.Chrome()` |
| 图像 | Pillow（截图叠加 ref 编号气泡） |
| 审计/产物 | 本地 JSONL + 文件目录，无数据库 |

后端三模式（`BrowserBackend` 接口，统一暴露 goto/click/type/find/注入 JS/screenshot/cookies/tabs/eval）：

| mode | 内核 | 用途 |
|---|---|---|
| `standard` | `Driver()`（WebDriver） | 普通站点，稳定优先（默认） |
| `uc` | `Driver(uc=True)` | 有 bot 检测的站点 |
| `cdp` | `sb_cdp.Chrome()` | 最强 stealth，纯 CDP，无需 chromedriver |

要点：

- 快照 ref 同时保存 CSS 选择器（`[data-mcp-ref="e12"]`），三种后端都按选择器定位，规避 CDP「元素不能跨调用传 handle」的问题。
- 快照引擎、动作管线不感知后端。
- 默认 headless；按会话可切 headful（部分检测对 headful 更宽松）。
- SeleniumBase 会锁定 selenium 版本，属较重的依赖；spike 需验证我们依赖的 API 面（见 §15）。
- UC 模式入口用 `Driver(uc=True)`（实测稳定）；`SB(uc=True)` 下 `sb.driver.execute_script` 会断连，不使用。CAPTCHA 通过会话升级到 `cdp` 模式处理，不依赖 `activate_cdp_mode`。CDP 的 `execute_script` 是表达式求值（不能写 `return` 函数体）；M2 已用 `Page.captureScreenshot(captureBeyondViewport=True)` 实现整页截图，CDP 对话框用 `Page.handleJavaScriptDialog`。
- 浏览器固定为项目内 CFT 156：`E:\selsnap\browsers\chrome-win64\chrome.exe`（156.0.8078.80），chromedriver 同版本置于 venv；所有后端显式传 `binary_location` / `browser_executable_path`，不依赖自动发现。系统里另有旧 Chrome 109（`Bin\`）与 Edge 156，仅作备选。

## 7. D4/D5 观测层与动作层

### 7.1 快照

注入 JS 遍历 DOM，按可见性过滤、计算 role/name，压缩为缩进文本；不是 HTML。

```text
- banner: link "首页" [e2], link "购物车(3)" [e4]
- main:
  - heading "搜索结果" level=1
  - textbox "搜索商品" value="耳机" [e9]
  - button "搜索" [e10]
  - list "结果 20 条":
    - link "无线耳机 A ¥199" [e12]
    - link "降噪耳机 B ¥399" [e13]
    - [18 条未展开，snapshot scope=e11]
```

规则：

- **稳定 ref**：首次出现给元素打 `data-mcp-ref`，后续快照复用；ref 编号按会话跨文档单调递增，每次导航生成新 `doc_id`，旧 ref 明确报 `stale_ref` 且不会误命中新文档中的同号元素。
- **动作后 diff**：动作工具默认返回变更行 + 新增 ref；全量快照仅在导航、变更 >50%、显式请求时返回。
- **预算**：默认 ≤4k tokens；优先交互元素/标题/地标，折叠长列表，长文本截断标注；隐藏节点与 `aria-hidden` 默认剔除。
- **frame**：同源 iframe 内联；跨源 iframe 占位，`snapshot scope=<ref>` 单帧快照。
- **Shadow DOM**：open root 内联遍历；closed root 不可见（Selenium 限制，文档注明）。
- **视觉辅助**：canvas/图表、节点极少、纯视觉反馈、最终验证时用截图；`screenshot(ref/full_page/annotate)` 服务端叠加 ref 编号；`click_at(x,y)` 处理 canvas。
- **不可信内容封装**：工具结果以 `<page url=...>` 包裹页面内容；密码框 value 恒为掩码。

### 7.2 动作管线

1. 解析 ref（不存在 → `stale_ref` + 自动附最新快照）
2. scrollIntoView → rect 跨两帧稳定
3. 可操作性：可见、启用、`elementFromPoint` 命中（未被遮挡）
4. 执行；Stale / ClickIntercepted 有限重试（2 次）
5. settle：MutationObserver 静默 300ms + `readyState` + 网络启发式（最近 500ms 无新资源请求），封顶超时
6. 返回 `{ok, doc_id, changed, settle}`；默认附结构化 diff（`added/removed/updated` 文本行 + `*_refs` + `change_ratio`），导航/无历史快照/变化 >50%/显式 `full` 时改附完整快照

实现状态（M2）：`click` / `type` / `select` / `press` / `hover` / `scroll` / `click_at` 已按上述管线实现；diff 采用「结构化 patch + 渲染文本行」协议；原生 dialog 在 standard/uc/CDP 均可检测并处理。

其他：上传路径白名单、下载进会话沙箱、`${secret:NAME}` 由服务端替换（明文不进模型上下文）留待 M3。

### 7.3 截图

- `screenshot` 返回 MCP image content（PNG）+ JSON 元数据，同时把产物写到 `var/artifacts/<session>/`。
- 视口截图用驱动原生截图；整页截图用 CDP `Page.captureScreenshot(captureBeyondViewport=True)`；元素截图先滚动到视口，再整页截图按 `getBoundingClientRect + scrollX/Y` 裁剪。
- `annotate=true` 时用 Pillow 在当前快照 ref 集合上绘制红框 + ref 标签；坐标按图片尺寸 / `scrollWidth`（或 `innerWidth`）缩放。
- 单图上限 4000 万像素；超限返回 `screenshot_failed`。

## 8. D7 Stealth 与绕过

- `session_open(mode, headless, profile)` 选择模式；`auto_escalate` 开启自动升级。
- 挑战检测器（可插拔规则）：标题/正文特征（`Just a moment`、`challenge-platform`、`cf-chl` 等）、403/429 + challenge 标记。
- 升级流程：同 profile 目录（cookie/localStorage 天然保留）→ 关闭 → 以更强模式重启 → 恢复 URL/标签页；顺序 `standard → uc → cdp`；冷启动约 3–8s。
- 手动：`session_escalate(session, mode)`；统一走同 profile 重启（不依赖 `activate_cdp_mode`）。
- Chrome 156 实测：UC sannysoft 31/0、CDP 30/0，browserscan 均 Normal；standard 仍判 Robot；CDP 在 Turnstile demo 上 solve 成功（1.98s，`#captcha-success` 可见）。
- CAPTCHA：`captcha_solve(session)` best-effort；失败返回截图 + `captcha_present`，交给 agent/人。
- 边界：绕过仅用于已授权目标；不承诺通用绕过，挑战站点是军备竞赛。

## 9. D8 安全与审计

- URL scheme 默认只放行 http/https；禁 `file:`/`chrome:`/`view-source:`。
- 可选私网/元数据地址黑名单（默认禁 `169.254.169.254`；loopback 可配）。
- Bearer 鉴权：纯 ASGI 中间件校验每个 HTTP 请求（POST/GET SSE/DELETE），token 映射 agent；未配置 token 时关闭鉴权并使用默认 agent。
- 会话 ACL：owner + read/write/revoke share + TTL；越权 `forbidden`。
- `js_eval` 默认关闭；上传限制在允许根目录；下载强制会话沙箱 + 大小上限（M3）。
- 会话审计 JSONL：时间、agent、owner、工具、参数（脱敏）、耗时、结果、URL、`doc_id`；`type` 文本只存长度与 SHA256 前缀；token/password/secret 参数键为 `***`。
- 提示注入：快照剔除隐藏节点 + 来源信封，降低风险；最终防线在 agent 侧策略。

## 10. 工具面（v1）

| 组 | 工具 |
|---|---|
| 会话 | `session_open` `session_attach` `session_list` `session_close` `session_share` `session_escalate` |
| 导航 | `navigate`（url/back/forward/reload） `tabs`（list/new/switch/close） |
| 观测 | `snapshot`（full/diff，可 scope） `screenshot` `extract` `console_logs` `page_info` |
| 动作 | `click` `click_at` `type` `press` `select` `hover` `scroll` `drag` `upload` `dialog` `captcha_solve` |
| 等待 | `wait_for`（visible/text/url/network_quiet/dom_stable，可组合） |
| 逃生 | `js_eval`（默认关闭） |

M2 已实现：`session_share` `session_escalate` `screenshot` `click_at` `dialog`；`tabs` `extract` `console_logs` `wait_for` `drag` `upload` `captcha_solve` 尚未实现（M3 或后续）。

## 11. D9 错误协议

`stale_ref` `not_found` `not_actionable(covered|disabled|offscreen|not_editable|not_interactable)` `option_not_found` `dialog_open` `dialog_not_open` `nav_timeout` `browser_dead` `policy_blocked` `resource_busy` `timeout` `action_failed` `screenshot_failed` `session_suspended` `forbidden` `unauthorized` `challenge_detected` `captcha_present` `stealth_unavailable`

每个错误附 `hint`；可能时附最新快照（如 `stale_ref`）或截图（如 `challenge_detected`）。

## 12. 非功能目标

- 快照 p50 < 250ms；动作 + settle p50 < 1.2s
- 默认快照 ≤ 4k tokens；diff 响应显著更小
- 单会话内存 < 500MB（Chrome 为主）；并发 4
- 崩溃自愈 < 5s（profile 保留）；空闲 2h 挂起
- 审计可回溯到 agent 与工具调用

## 13. 里程碑

| 阶段 | 内容 |
|---|---|
| Spike | Windows 上验证三模式 API 面与 stealth（见 §15） |
| M0（已完成 2026-10-30） | HTTP + 会话 actor + `navigate`/`snapshot` + ref 生命周期；pytest 16/16，smoke 8/8（standard + cdp） |
| M1（已完成 2026-11-08） | 动作管线 + settle + 动作后 diff + 结构化错误；pytest 47/47，smoke_m0 8/8，smoke_m1 16/16（standard/uc/cdp） |
| M2（已完成 2026-11-08） | share/ACL/TTL + 审计 JSONL + Bearer 鉴权 + 截图/标注/`click_at` + dialog + 模式升级 + 空闲挂起/孤儿清理；pytest 76/76，smoke_m0 8/8，smoke_m1 16/16，smoke_m2 20/20 |
| M3 | frames/shadow、上传下载、secret、预算调优、CAPTCHA 实测、超时重启 |

## 14. 风险与缓解

| 风险 | 缓解 |
|---|---|
| SeleniumBase 锁定 selenium 版本、依赖较重 | spike 验证；只依赖 Driver/SB/sb_cdp 稳定 API；必要时抽象隔离 |
| CDP 模式元素模型差异 | ref → CSS 选择器，统一按选择器操作 |
| stealth 稳定性与军备竞赛 | best-effort 策略；auto_escalate；失败可降级截图 + 人工 |
| headless 被识别 | 按会话切 headful；池仍限制 4 |
| 页面提示注入 | 剔除隐藏节点、来源信封、策略层、审计 |
| 4 个 Chrome 抢资源 | 池上限、空闲挂起、调度公平 |
| 长驻服务进程管理 | Windows 任务计划/NSSM 托管（部署阶段再定） |

## 15. Spike 验证（首轮已完成）

首轮结果见 `docs/spike-report-2026-10-30.md`：Chrome 156 上 UC / CDP 达标，standard 被识别；待补 CDP 全页截图、真实挑战页规则验证、真实快照 walker 性能。清单：

1. `Driver()`、`Driver(uc=True)`、`sb_cdp.Chrome()` 在 Windows 上 headless/headful 启动
2. 三种模式的 JS 注入（快照采集）是否等价可用
3. cookie/localStorage 在 profile 复用与模式升级后是否保留
4. tabs、截图（viewport/full/element）、PDF 导出
5. `solve_captcha` 在演示页的实际效果
6. 挑战检测启发式在 3–5 个真实站点上的命中率/误报
7. 重页面（DOM > 5 万节点）快照耗时与裁剪效果
8. 官方 MCP SDK 的 Streamable HTTP 多客户端与会话映射

## 16. 非目标 / v2

非目标：Docker/K8s、Grid、多机、视频录制、断言框架、录制回放、云端浏览器。

v2 候选：WebDriver BiDi 网络拦截/请求 mock、CDP browser context 复用（省内存）、快照 diff 协议精细化、追踪导出、PDF 文本抽取。

## 17. 参考项目（GitHub 数据，2026-10-30）

| 项目 | 许可 | 与本项目关系 |
|---|---|---|
| seleniumbase/seleniumbase-mcp | MIT | 官方 SeleniumBase MCP（stdio、单会话），工具面与 stealth 参考；README 自述多会话/并发需扩展 |
| microsoft/playwright-mcp | Apache-2.0 | 语义快照 + ref 的事实标准，观测层参照 |
| ChromeDevTools/chrome-devtools-mcp | Apache-2.0 | CDP 路线的官方实现，工具面参考 |
| angiejones/mcp-selenium | MIT | Selenium 薄封装，driver 生命周期参考 |
| browser-use/browser-use | MIT | 可交互元素索引与 DOM 裁剪算法参考 |
| hangwin/mcp-chrome | MIT | 扩展控制已登录浏览器，模型不同 |
