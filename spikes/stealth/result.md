# SeleniumBase Stealth Spike 结果

- 生成时间：2026-10-30 16:22:10
- Python：3.11.9
- SeleniumBase：4.56.5
- Chrome：109.0.5414.120（C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe）
- chromedriver：109.0.5414.74；uc_driver：109.0.5414.74
- 说明：外部站点加载硬上限 30s；sannysoft 等待 3s，browserscan 等待 7s；每模式独立浏览器。

## 三模式检测项对比

| 检测项 | standard | uc | cdp |
|---|---|---|---|
| navigator.webdriver | 是 | 否 | 否 |
| plugins 数量 | 0 | 5 | 5 |
| window.chrome | 否 | 是 | 是 |
| sannysoft 加载 | 成功 | 成功 | 成功 |
| sannysoft passed / failed | 3 / 8 | 31 / 0 | 0 / 0 |
| sannysoft 正文长度 | 1452 | 14271 | 0 |
| sannysoft 标题 | Antibot | Antibot |  |
| browserscan 总体 | Test Results: \| Robot \| Webdriver \| User-Agent \| CDP \| Navigator \| Browser bot detection guide \| BrowserScan d | Test Results: \| Robot \| Webdriver \| User-Agent \| CDP \| Navigator \| Browser bot detection guide \| BrowserScan d | Test Results: \| Normal \| Webdriver \| User-Agent \| CDP \| Navigator \| Browser bot detection guide \| BrowserScan  |
| 挑战规则误报 | 未误报 | 未误报 | 未误报 |
| solve_captcha | 跳过（standard 模式原生 Driver 未暴露 solve_captcha()（UC 需先切换 CDP 模式）；按只试一次约束不在本模式尝试） | 跳过（uc 模式原生 Driver 未暴露 solve_captcha()（UC 需先切换 CDP 模式）；按只试一次约束不在本模式尝试） | 成功（成功标记可见） |

## 挑战检测规则逐项结果（demo_page 误报验证）

| 规则 | standard | uc | cdp |
|---|---|---|---|
| Just a moment | 未命中 | 未命中 | 未命中 |
| challenge-platform | 未命中 | 未命中 | 未命中 |
| cf-chl | 未命中 | 未命中 | 未命中 |
| Attention Required | 未命中 | 未命中 | 未命中 |
| Verify you are human | 未命中 | 未命中 | 未命中 |

## 各模式详情

### standard

- 状态：ok
- 浏览器：chromedriver，版本 109.0.5414.120，headless=是，回退 headed=否
- sannysoft：loaded=是，最终 URL=https://bot.sannysoft.com/，UA=Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/109.0.5414.120 Safari/537.36
  - passed=3，failed=8，title=Antibot，body_len=1452
- browserscan：title=BrowserScan - Robot Detection/WebDriver \| BrowserScan，summary=Test Results: \| Robot \| Webdriver \| User-Agent \| CDP \| Navigator \| Browser bot detection guide \| BrowserScan detects automated activities on scripts or browsers. It analyzes various browser properties to determine whether the browser environment is cont
  - 关键词：{"Bot": true, "Headless": true, "Human": true, "Normal": true, "Robot": true, "WebDriver": true}
  - 结果片段：{"CDP": "CDP Navigator Browser bot detection guide BrowserScan detects automat", "Headless Chrome": "Headless Chrome Robot Discover more Automated Browser Testing Source R", "Navigator": "Navigator Browser bot detection guide BrowserScan detects automated a", "WebDriver": "WebDriver Robot WebDriver Advance Normal Selenium Robot NightmareJS No"}
- demo_page：title=Web Testing Page，误报=否
- turnstile：attempted=否，standard 模式原生 Driver 未暴露 solve_captcha()（UC 需先切换 CDP 模式）；按只试一次约束不在本模式尝试
- 关闭：quit_ok=是，killed=[]

### uc

- 状态：ok
- 浏览器：uc_driver，版本 109.0.5414.120，headless=是，回退 headed=否
- sannysoft：loaded=是，最终 URL=https://bot.sannysoft.com/，UA=Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36
  - passed=31，failed=0，title=Antibot，body_len=14271
- browserscan：title=BrowserScan - Robot Detection/WebDriver \| BrowserScan，summary=Test Results: \| Robot \| Webdriver \| User-Agent \| CDP \| Navigator \| Browser bot detection guide \| BrowserScan detects automated activities on scripts or browsers. It analyzes various browser properties to determine whether the browser environment is cont
  - 关键词：{"Bot": true, "Headless": true, "Human": true, "Normal": true, "Robot": true, "WebDriver": true}
  - 结果片段：{"CDP": "CDP Navigator Browser bot detection guide BrowserScan detects automat", "Headless Chrome": "Headless Chrome Normal Discover more Bot Detection Service Plugin Dete", "Navigator": "Navigator Browser bot detection guide BrowserScan detects automated a", "WebDriver": "WebDriver Normal WebDriver Advance Normal Selenium Normal NightmareJS "}
- demo_page：title=Web Testing Page，误报=否
- turnstile：attempted=否，uc 模式原生 Driver 未暴露 solve_captcha()（UC 需先切换 CDP 模式）；按只试一次约束不在本模式尝试
- 关闭：quit_ok=是，killed=[]

### cdp

- 状态：ok
- 浏览器：sb_cdp，版本 Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36，headless=是，回退 headed=—
- sannysoft：loaded=是，最终 URL=https://bot.sannysoft.com/，UA=Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36
  - passed=0，failed=0，title=，body_len=0
  - 注意：正文为空（站点被拦截/未渲染），passed/failed=0 不代表通过全部检测。
- browserscan：title=BrowserScan - Robot Detection/WebDriver \| BrowserScan，summary=Test Results: \| Normal \| Webdriver \| User-Agent \| CDP \| Navigator \| Browser bot detection guide \| BrowserScan detects automated activities on scripts or browsers. It analyzes various browser properties to determine whether the browser environment is con
  - 关键词：{"Normal": true, "Bot": true, "WebDriver": true, "Headless": true, "Robot": true, "Human": true}
  - 结果片段：{"WebDriver": "WebDriver Normal WebDriver Advance Normal Selenium Normal NightmareJS ", "Headless Chrome": "Headless Chrome Normal Discover more Plugin Detection Tool WebdriverIO", "CDP": "CDP Navigator Browser bot detection guide BrowserScan detects automat", "Navigator": "Navigator Browser bot detection guide BrowserScan detects automated a"}
- demo_page：title=Web Testing Page，误报=否
- turnstile：attempted=是，
  - 页面 title=Cloudflare Turnstile Test，最终 URL=https://seleniumbase.io/apps/turnstile
  - solve_captcha：返回=—，耗时=2.06s，超时=否，错误=—
  - 成功标记可见=是，失败标记可见=否
- 关闭：quit_ok=是，killed=[]

## 异常与环境说明

- 任务给定的 Chrome 路径不存在（C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe），已回退到可用路径 C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe（版本 109.0.5414.120）。
