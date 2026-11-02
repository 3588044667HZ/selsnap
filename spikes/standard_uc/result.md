# SeleniumBase standard / UC Spike 结果

- 开始时间: 2026-10-30T16:04:10
- Python: 3.11.9
- seleniumbase: 4.56.5
- selenium: 4.51.0
- 任务给定 Chrome 路径存在: 否
- 环境备注: 准备阶段观察：预下载 chromedriver/uc_driver 为 156.0.8078.80，实际 Chrome 为 109.0.5414.120，版本不匹配；SeleniumBase 首次启动时自动下载并替换为 109.0.5414.74（未执行 pip install/upgrade）。
- 环境备注: 任务给定的 Chrome 路径不存在: C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe
- 环境备注: 实际存在的 Chrome 位于: C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe（Chrome 109 系列）
- 驱动 chromedriver: ChromeDriver 109.0.5414.74 (e7c5703604daa9cc128ccf5a5d3e993513758913-refs/branch-heads/5414@{#1172})
- 驱动 uc_driver: ChromeDriver 109.0.5414.74 (e7c5703604daa9cc128ccf5a5d3e993513758913-refs/branch-heads/5414@{#1172})

## Driver 签名检查

| 参数 | 是否存在 |
|---|---|
| headless | 是 |
| uc | 是 |
| user_data_dir | 是 |
| binary_location | 是 |

```text
(browser=None, headless=None, headless1=None, headless2=None, headed=None, locale_code=None, protocol=None, servername=None, port=None, proxy=None, proxy_bypass_list=None, proxy_pac_url=None, multi_proxy=None, agent=None, cap_file=None, cap_string=None, recorder_ext=None, disable_cookies=None, disable_js=None, disable_csp=None, enable_ws=None, disable_ws=None, enable_sync=None, use_auto_ext=None, undetectable=None, uc_cdp_events=None, uc_subprocess=None, log_cdp_events=None, no_sandbox=None, disable_gpu=None, incognito=None, guest_mode=None, dark_mode=None, devtools=None, remote_debug=None, enable_3d_apis=None, swiftshader=None, ad_block_on=None, host_resolver_rules=None, block_images=None, do_not_track=None, chromium_arg=None, firefox_arg=None, firefox_pref=None, user_data_dir=None, extension_zip=None, extension_dir=None, disable_features=None, binary_location=None, driver_version=None, page_load_strategy=None, external_pdf=None, window_position=None, window_size=None, is_mobile=None, mobile=None, d_width=None, d_height=None, d_p_r=None, position=None, size=None, uc=None, undetected=None, uc_cdp=None, uc_sub=None, locale=None, log_cdp=None, ad_block=None, server=None, guest=None, pls=None, cft=None, chs=None, use_chromium=None) -> seleniumbase.core.sb_driver.DriverMethods
```

## standard 模式（headless=True）

| 项目 | 结果 |
|---|---|
| 启动 | 是（1.752s） |
| 浏览器版本 | 109.0.5414.120 |
| demo_page 加载 | 是（1.054s） |
| JS 注入 | 是（0.009s） |
| 元素总数 / 可见 / 可交互 | 141 / 98 / 23 |
| navigator.webdriver | 是 |
| UA | Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/109.0.5414.120 Safari/537.36 |
| 截图 | 是（71.9 KB，0.311s） |
| 标签页 | 是（handle 1 -> 2，切回 是，0.645s） |
| Cookie / localStorage | 是 / 是 |
| 本地 5 万节点 HTML | 节点 50000，文件 1797017 字节，生成 0.039s |
| 本地页面加载 | 是（1.690s） |
| 本地 DOM 遍历 | 是（0.118s，总数 50006） |
| 结论 | 通过 |

## profile 持久化（standard）

| 项目 | 结果 |
|---|---|
| user_data_dir 参数支持 | 是 |
| profile 目录 | E:\selenium-mcp\spikes\standard_uc\profile_std |
| 首次启动 | 109.0.5414.120（1.538s） |
| 首次写入 | {'cookie': '_ga=GA1.1.1196941888.1793347461; _ga_P5KFWRNLRN=GS2.1.s1793347461$o1$g0$t1793347461$j60$l0$h0; profile_cookie=profile_value', 'marker': 'spike-profile-1793347458'} |
| 第二次启动 | 1.545s |
| 重启后读取 | {'cookie': '_ga=GA1.1.1196941888.1793347461; profile_cookie=profile_value; _ga_P5KFWRNLRN=GS2.1.s1793347461$o1$g1$t1793347469$j52$l0$h0', 'marker': 'spike-profile-1793347458', 'url': 'https://seleniumbase.io/demo_page'} |
| localStorage 保留 | 是 |
| Cookie 保留 | 是 |
| 结论 | localStorage 已保留；Cookie 已保留 |

## UC 模式

| headless | 启动 | 启动耗时 | 导航 | 加载耗时 | JS | webdriver | 截图 | Cookie/Storage | 结果 |
|---|---|---|---|---|---|---|---|---|---|
| 是 | 是 | 3.260s | 是 | 1.613s | 是 | 否 | 是 | 是 / 是 | 通过 |

- 实际 headless: 是
- 使用 headed 兜底: 否
- 结论: 通过

## 异常

无
