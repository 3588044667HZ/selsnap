# SeleniumBase Pure CDP Spike 结果

- 开始：2026-10-30T16:09:58+08:00
- 结束：2026-10-30T16:10:12+08:00（耗时 14.0s）
- 解释器：`E:\selenium-mcp\.venv\Scripts\python.exe`
- SeleniumBase 4.56.5 / selenium 4.51.0
- Chrome 指定路径存在：False；实际使用：`C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe`

## 构造签名

```
(url=None, **kwargs)
```

支持命名参数（cdp_util.start）：`config, user_data_dir, headless, incognito, guest, browser_executable_path, browser_args, xvfb_metrics, ad_block, sandbox, lang, host, port, xvfb, headed, expert, agent, proxy, tzone, geoloc, mobile, disable_csp, extension_dir, use_chromium, cft`

## 方法可用性矩阵

| 分组 | 方法 | 可用 | 可调用 |
|---|---|---|---|
| navigation | `get` | 是 | 是 |
| navigation | `open` | 是 | 是 |
| navigation | `goto` | 是 | 是 |
| navigation | `reload` | 是 | 是 |
| navigation | `refresh` | 是 | 是 |
| navigation | `go_back` | 是 | 是 |
| navigation | `go_forward` | 是 | 是 |
| navigation | `get_current_url` | 是 | 是 |
| navigation | `get_title` | 是 | 是 |
| navigation | `get_page_title` | 是 | 是 |
| navigation | `assert_title` | 是 | 是 |
| navigation | `assert_title_contains` | 是 | 是 |
| navigation | `assert_url` | 是 | 是 |
| navigation | `assert_url_contains` | 是 | 是 |
| navigation | `get_navigation_history` | 是 | 是 |
| javascript | `evaluate` | 是 | 是 |
| javascript | `execute_script` | 是 | 是 |
| javascript | `js_dumps` | 是 | 是 |
| javascript | `get_page_source` | 是 | 是 |
| javascript | `get_html` | 是 | 是 |
| javascript | `get_beautiful_soup` | 是 | 是 |
| screenshot_pdf | `save_screenshot` | 是 | 是 |
| screenshot_pdf | `print_to_pdf` | 是 | 是 |
| screenshot_pdf | `save_as_pdf` | 是 | 是 |
| screenshot_pdf | `save_page_source` | 是 | 是 |
| screenshot_pdf | `save_as_html` | 是 | 是 |
| screenshot_pdf | `save_page` | 否 | 否 |
| tabs | `get_tabs` | 是 | 是 |
| tabs | `get_active_tab` | 是 | 是 |
| tabs | `open_new_tab` | 是 | 是 |
| tabs | `open_new_window` | 是 | 是 |
| tabs | `switch_to_tab` | 是 | 是 |
| tabs | `switch_to_newest_tab` | 是 | 是 |
| tabs | `switch_to_window` | 是 | 是 |
| tabs | `switch_to_newest_window` | 是 | 是 |
| tabs | `close_active_tab` | 是 | 是 |
| tabs | `bring_active_window_to_front` | 是 | 是 |
| cookies | `get_all_cookies` | 是 | 是 |
| cookies | `set_all_cookies` | 是 | 是 |
| cookies | `save_cookies` | 是 | 是 |
| cookies | `load_cookies` | 是 | 是 |
| cookies | `clear_cookies` | 是 | 是 |
| cookies | `get_cookie_string` | 是 | 是 |
| storage | `get_local_storage_item` | 是 | 是 |
| storage | `set_local_storage_item` | 是 | 是 |
| storage | `get_session_storage_item` | 是 | 是 |
| storage | `set_session_storage_item` | 是 | 是 |
| profile_window | `config` | 否 | 否 |
| profile_window | `driver` | 是 | 否 |
| profile_window | `page` | 是 | 是 |
| profile_window | `get_user_agent` | 是 | 是 |
| profile_window | `get_window` | 是 | 是 |
| profile_window | `get_window_size` | 是 | 是 |
| profile_window | `get_window_rect` | 是 | 是 |
| profile_window | `set_window_rect` | 是 | 是 |
| profile_window | `maximize` | 是 | 是 |
| profile_window | `quit` | 是 | 是 |
| profile_window | `stop` | 是 | 是 |

## 通过/失败

| 测试 | 状态 | 详情 |
|---|---|---|
| launch | PASS | headless=True, 1223.7 ms, dir=286 |
| method_matrix | PASS | 56/58 候选方法存在 |
| navigation_demo | PASS | 1295.1 ms, title=Web Testing Page |
| js_stats | PASS | total=141 visible=96 interactive=19 webdriver=False |
| dom_50k_benchmark | PASS | load=317.1 ms query_med=1.00 ms full_med=88.10 ms total=51006 |
| screenshot_png | PASS | 64010 bytes, 1264x752 |
| pdf_print | PASS | 210352 bytes, 1289.7 ms |
| save_page_source | PASS | 26598 bytes, 21.7 ms |
| tabs | PASS | counts=1->2->1, new_url=file:///E:/selenium-mcp/spikes/cdp/dom_50k.html |
| cookie_reload | PASS | cdp_spike_cookie in cdp cookies=True |
| local_storage_reload | PASS | read back='cdp-1793347805' |
| main_quit | PASS | quit |
| profile_persistence | PASS | ls='profile-1793347806' cookie_persisted=True |

## 关键数字

| 指标 | 值 |
|---|---|
| 启动耗时 | 1223.7 ms |
| demo 加载耗时 | 1295.1 ms |
| 返回 demo 耗时 | 447.8 ms |
| DOM 50k 生成耗时 | 46.6 ms |
| DOM 50k 加载耗时 | 317.1 ms |
| DOM querySelectorAll 中位 | 1 ms（51006 节点） |
| DOM 完整遍历中位 | 88.1 ms（visible=51003） |
| demo 元素数 | total=141 visible=96 interactive=19 |
| navigator.webdriver | False |
| User-Agent | `Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36` |
| 截图 | 64010 bytes, 1264x752, 451.7 ms |
| PDF | 210352 bytes, 1289.7 ms |
| HTML 快照 | 26598 bytes, 21.7 ms |
| 标签页计数 | 1 -> 2 -> 1 |
| cookie reload 读回 | True |
| localStorage reload 读回 | True |
| profile localStorage 持久化 | True |
| profile cookie 持久化（max-age） | True |
| profile 目录保留 | True |
| 默认临时 profile quit 后删除 | True |

## 环境警告

- [environment] 指定的 Chrome 路径不存在：C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe；回退使用系统中唯一可用的 Chrome：C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe

## 异常

无。

## 结论

- sb_cdp.Chrome(url=None, **kwargs) 将 kwargs 透传给 cdp_util.start，支持 headless/user_data_dir/browser_executable_path。
- save_screenshot 为视口截图（wrapper 未暴露 full_page 参数），print_to_pdf 可用。
- 标签页 API 可用：get_tabs/open_new_tab/switch_to_tab/close_active_tab。
- user_data_dir 为自定义目录时，quit 后目录保留；localStorage 与带过期时间的 cookie 可跨重启持久化。
- 默认临时 profile 在 quit 后由 SeleniumBase 删除；会话 cookie 不跨浏览器重启（需设置 expires/max-age）。
