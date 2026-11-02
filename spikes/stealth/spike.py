# -*- coding: utf-8 -*-
"""SeleniumBase stealth spike: standard / uc / cdp 三模式对比。"""
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE_DIR, "result.json")
MD_PATH = os.path.join(BASE_DIR, "result.md")

DRIVER_DIR = r"E:\selenium-mcp\.venv\Lib\site-packages\seleniumbase\drivers"
CHROMEDRIVER_EXE = os.path.join(DRIVER_DIR, "chromedriver.exe")
UC_DRIVER_EXE = os.path.join(DRIVER_DIR, "uc_driver.exe")
CHROME_CANDIDATES = [
    r"C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe",
    r"C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe",
]

SANNY_URL = "https://bot.sannysoft.com/"
BSCAN_URL = "https://browserscan.net/bot-detection"
DEMO_URL = "https://seleniumbase.io/demo_page"
TURNSTILE_URL = "https://seleniumbase.io/apps/turnstile"

CHALLENGE_PATTERNS = [
    "Just a moment",
    "challenge-platform",
    "cf-chl",
    "Attention Required",
    "Verify you are human",
]

PAGE_TIMEOUT = 30
SCRIPT_TIMEOUT = 15

SNY_JS = r"""
(() => {
  const n = navigator;
  return {
    webdriver: n.webdriver,
    userAgent: n.userAgent,
    plugins: (n.plugins && n.plugins.length !== undefined) ? n.plugins.length : null,
    window_chrome: (typeof window.chrome !== 'undefined'),
    passed: document.querySelectorAll('.passed').length,
    failed: document.querySelectorAll('.failed').length,
    body_len: (document.body ? document.body.innerText.length : 0),
    body_excerpt: (document.body ? document.body.innerText.slice(0, 300) : ''),
    title: document.title
  };
})()
"""

BSCAN_JS = r"""
(() => {
  const title = document.title || '';
  const text = document.body ? document.body.innerText : '';
  let summary = '';
  const idx = text.indexOf('Test Results:');
  if (idx >= 0) {
    summary = text.slice(idx, idx + 240).split('\n')
      .map(s => s.trim()).filter(s => s).slice(0, 10).join(' | ');
  }
  const kws = ['Normal', 'Bot', 'WebDriver', 'Headless', 'Robot', 'Human'];
  const flags = {};
  for (const k of kws) {
    flags[k] = (title + '\n' + text).toLowerCase().includes(k.toLowerCase());
  }
  const detail = {};
  for (const k of ['WebDriver', 'Headless Chrome', 'CDP', 'Navigator']) {
    const i = text.indexOf(k);
    detail[k] = i >= 0 ? text.slice(i, i + 70).replace(/\s+/g, ' ') : null;
  }
  return {
    title: title,
    url: location.href,
    summary: summary,
    body_excerpt: text.slice(0, 2000),
    keyword_flags: flags,
    detail_snippets: detail
  };
})()
"""

CHALLENGE_JS = r"""
(() => {
  const pats = %s;
  const title = document.title || '';
  const text = document.body ? document.body.innerText : '';
  const html = document.documentElement ? document.documentElement.outerHTML : '';
  const matches = {};
  let any = false;
  for (const p of pats) {
    const lp = p.toLowerCase();
    const m = {
      title: title.toLowerCase().includes(lp),
      text: text.toLowerCase().includes(lp),
      html: html.toLowerCase().includes(lp)
    };
    m.any = m.title || m.text || m.html;
    matches[p] = m;
    if (m.any) any = true;
  }
  return {
    title: title,
    url: location.href,
    false_positive: any,
    matches: matches,
    text_excerpt: text.slice(0, 500)
  };
})()
""" % json.dumps(CHALLENGE_PATTERNS)

TURNSTILE_CHECK_JS = r"""
(() => {
  const okEl = document.querySelector('#captcha-success');
  const failEl = document.querySelector('#captcha-failure');
  const ok = !!(okEl && getComputedStyle(okEl).display !== 'none');
  const fail = !!(failEl && getComputedStyle(failEl).display !== 'none');
  const text = document.body ? document.body.innerText : '';
  return {
    success_visible: ok,
    failure_visible: fail,
    title: document.title,
    url: location.href,
    body_excerpt: text.slice(0, 800)
  };
})()
"""


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_cmd(args, timeout=20):
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return (p.stdout or "") + (p.stderr or "")
    except Exception:
        return ""


def driver_exe_version(path):
    if not os.path.isfile(path):
        return None
    out = run_cmd([path, "--version"])
    m = re.search(r"ChromeDriver\s+([\d.]+)", out)
    return m.group(1) if m else None


def chrome_file_version(path):
    ps = "(Get-Item -LiteralPath '%s').VersionInfo.ProductVersion" % path.replace("'", "''")
    out = run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout=25)
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    if not lines:
        return None
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)", lines[-1])
    return m.group(1) if m else None


def resolve_chrome():
    drv_ver = driver_exe_version(CHROMEDRIVER_EXE)
    drv_major = drv_ver.split(".")[0] if drv_ver else None
    found = []
    for p in CHROME_CANDIDATES:
        if os.path.isfile(p):
            found.append({"path": p, "version": chrome_file_version(p)})
    chosen = None
    for c in found:
        if drv_major and c["version"] and c["version"].split(".")[0] == drv_major:
            chosen = c
            break
    if chosen is None and found:
        chosen = found[0]
    return {
        "chosen": chosen,
        "candidates": found,
        "chromedriver_version": drv_ver,
        "uc_driver_version": driver_exe_version(UC_DRIVER_EXE),
        "driver_major": drv_major,
    }


def safe_get(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def safe_err(fn):
    try:
        return fn(), None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, str(e)[:400])


def call_in_thread(fn, timeout):
    box = {
        "ok": False, "value": None, "error": None,
        "timeout": False, "elapsed_s": None,
    }

    def _target():
        try:
            box["value"] = fn()
            box["ok"] = True
        except BaseException as e:
            box["error"] = "%s: %s" % (type(e).__name__, str(e)[:500])

    t = threading.Thread(target=_target, daemon=True)
    t0 = time.time()
    t.start()
    t.join(timeout)
    box["elapsed_s"] = round(time.time() - t0, 2)
    if t.is_alive():
        box["ok"] = False
        box["timeout"] = True
        box["error"] = "hard timeout after %ss" % timeout
    return box


def kill_tree(pid):
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=20,
        )
        return True
    except Exception:
        return False


def selenium_pids(driver):
    pids = []
    svc = getattr(driver, "service", None)
    proc = getattr(svc, "process", None)
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int):
        pids.append(pid)
    bp = getattr(driver, "browser_pid", None)
    if isinstance(bp, int):
        pids.append(bp)
    return list(dict.fromkeys(pids))


def cdp_pids(cdp):
    pids = []
    d = getattr(cdp, "driver", None)
    v = getattr(d, "_process_pid", None)
    if isinstance(v, int):
        pids.append(v)
    proc = getattr(d, "_process", None)
    v = getattr(proc, "pid", None)
    if isinstance(v, int):
        pids.append(v)
    return list(dict.fromkeys(pids))


def close_selenium(driver):
    info = {"quit_ok": False, "killed_pids": [], "error": None}
    if driver is None:
        return info
    pids = selenium_pids(driver)
    r = call_in_thread(driver.quit, 20)
    info["quit_ok"] = bool(r["ok"])
    if r["ok"]:
        return info
    info["error"] = r["error"]
    for pid in pids:
        if kill_tree(pid):
            info["killed_pids"].append(pid)
    return info


def close_cdp(cdp, force_kill=False):
    info = {"quit_ok": False, "killed_pids": [], "error": None}
    if cdp is None:
        return info
    pids = cdp_pids(cdp)
    if not force_kill:
        r = call_in_thread(cdp.quit, 20)
        info["quit_ok"] = bool(r["ok"])
        if r["ok"]:
            return info
        info["error"] = r["error"]
    for pid in pids:
        if kill_tree(pid):
            info["killed_pids"].append(pid)
    return info


def _selenium_visit(driver, url, wait_s, collect_js, collect_timeout=SCRIPT_TIMEOUT):
    out = {
        "url": url, "loaded": False, "load_error": None,
        "load_elapsed_s": None, "wait_s": wait_s,
        "final_url": None, "title": None, "elapsed_s": None,
        "collect_error": None,
    }
    t0 = time.time()
    try:
        driver.get(url)
        out["loaded"] = True
    except Exception as e:
        out["load_error"] = "%s: %s" % (type(e).__name__, str(e)[:400])
    out["load_elapsed_s"] = round(time.time() - t0, 2)
    time.sleep(wait_s)
    out["elapsed_s"] = round(time.time() - t0, 2)
    out["final_url"], out["final_url_error"] = safe_err(lambda: driver.current_url)
    out["title"], out["title_error"] = safe_err(lambda: driver.title)
    if collect_js:
        r = call_in_thread(
            lambda: driver.execute_script("return (" + collect_js + ")"),
            collect_timeout,
        )
        if r["ok"] and isinstance(r["value"], dict):
            out.update(r["value"])
        else:
            out["collect_error"] = r["error"] or "execute_script returned None"
    return out


def _cdp_eval(cdp, expr, timeout=SCRIPT_TIMEOUT):
    try:
        value = cdp.loop.run_until_complete(
            asyncio.wait_for(cdp.page.evaluate(expr), timeout)
        )
        return {"ok": True, "value": value, "error": None, "timeout": False}
    except asyncio.TimeoutError:
        return {
            "ok": False, "value": None,
            "error": "evaluate hard timeout after %ss" % timeout,
            "timeout": True,
        }
    except Exception as e:
        return {
            "ok": False, "value": None,
            "error": "%s: %s" % (type(e).__name__, str(e)[:400]),
            "timeout": False,
        }


def _cdp_get(cdp, url, timeout=PAGE_TIMEOUT):
    try:
        cdp.loop.run_until_complete(
            asyncio.wait_for(cdp.page.get(url), timeout)
        )
        return {"ok": True, "error": None, "elapsed_s": None, "timeout": False}
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "error": "page get hard timeout after %ss" % timeout,
            "elapsed_s": None, "timeout": True,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": "%s: %s" % (type(e).__name__, str(e)[:400]),
            "elapsed_s": None, "timeout": False,
        }


def _cdp_visit(cdp, url, wait_s, collect_js, collect_timeout=SCRIPT_TIMEOUT):
    out = {
        "url": url, "loaded": False, "load_error": None,
        "load_elapsed_s": None, "wait_s": wait_s,
        "final_url": None, "title": None, "elapsed_s": None,
        "collect_error": None,
    }
    t0 = time.time()
    r = _cdp_get(cdp, url, PAGE_TIMEOUT)
    out["loaded"] = r["ok"]
    out["load_error"] = r["error"]
    out["load_elapsed_s"] = round(time.time() - t0, 2)
    if r["timeout"]:
        out["hard_timeout"] = True
        out["elapsed_s"] = round(time.time() - t0, 2)
        out["collect_error"] = "页面加载硬超时，跳过采集并回收浏览器"
        return out
    time.sleep(wait_s)
    out["elapsed_s"] = round(time.time() - t0, 2)
    ev = _cdp_eval(cdp, "location.href", 10)
    out["final_url"] = ev["value"] if ev["ok"] else None
    ev = _cdp_eval(cdp, "document.title", 10)
    out["title"] = ev["value"] if ev["ok"] else None
    if collect_js:
        cr = _cdp_eval(cdp, collect_js, collect_timeout)
        if cr["ok"] and isinstance(cr["value"], dict):
            out.update(cr["value"])
        else:
            out["collect_error"] = cr["error"]
    return out


def launch_standard(chrome):
    from seleniumbase import Driver
    driver = Driver(headless=True, binary_location=chrome)
    driver.set_page_load_timeout(PAGE_TIMEOUT)
    driver.set_script_timeout(SCRIPT_TIMEOUT)
    return driver


def launch_uc(chrome):
    from seleniumbase import Driver
    first_error = None
    driver = None
    try:
        driver = Driver(headless=True, uc=True, binary_location=chrome)
        driver.set_page_load_timeout(PAGE_TIMEOUT)
        driver.set_script_timeout(SCRIPT_TIMEOUT)
        r = call_in_thread(
            lambda: (driver.get("about:blank"), driver.execute_script("return 1+1")),
            25,
        )
        if not r["ok"]:
            raise RuntimeError(r["error"])
        return driver, {"headless": True, "fallback_headed": False, "first_error": None}
    except Exception as e:
        first_error = "%s: %s" % (type(e).__name__, str(e)[:400])
        if driver is not None:
            close_selenium(driver)
        driver = Driver(headless=False, uc=True, binary_location=chrome)
        driver.set_page_load_timeout(PAGE_TIMEOUT)
        driver.set_script_timeout(SCRIPT_TIMEOUT)
        return driver, {
            "headless": False,
            "fallback_headed": True,
            "first_error": first_error,
        }


def run_selenium_mode(mode, chrome):
    rec = {
        "mode": mode, "status": "ok", "browser": {}, "launch_error": None,
        "sannysoft": None, "browserscan": None, "challenge": None,
        "turnstile": None, "close": None,
    }
    driver = None
    try:
        if mode == "standard":
            driver = launch_standard(chrome)
            rec["browser"] = {
                "kind": "selenium", "driver": "chromedriver",
                "headless": True, "fallback_headed": False,
            }
        else:
            driver, meta = launch_uc(chrome)
            rec["browser"] = {
                "kind": "selenium", "driver": "uc_driver",
                "headless": meta["headless"],
                "fallback_headed": meta["fallback_headed"],
                "first_headless_error": meta["first_error"],
            }
        rec["browser"]["browser_version"], _ = safe_err(
            lambda: driver.capabilities.get("browserVersion")
        )
        rec["browser"]["chromedriver_version"], _ = safe_err(
            lambda: driver.capabilities.get("chrome", {}).get("chromedriverVersion")
        )
    except Exception as e:
        rec["status"] = "error"
        rec["launch_error"] = "%s: %s" % (type(e).__name__, str(e)[:600])
        rec["close"] = close_selenium(driver)
        return rec

    try:
        rec["sannysoft"] = _selenium_visit(driver, SANNY_URL, 3, SNY_JS)
    except Exception:
        rec["sannysoft"] = {"url": SANNY_URL, "error": traceback.format_exc()}
    try:
        rec["browserscan"] = _selenium_visit(driver, BSCAN_URL, 7, BSCAN_JS)
    except Exception:
        rec["browserscan"] = {"url": BSCAN_URL, "error": traceback.format_exc()}
    try:
        rec["challenge"] = _selenium_visit(driver, DEMO_URL, 2, CHALLENGE_JS)
    except Exception:
        rec["challenge"] = {"url": DEMO_URL, "error": traceback.format_exc()}

    rec["turnstile"] = {
        "attempted": False,
        "url": TURNSTILE_URL,
        "reason": "%s 模式原生 Driver 未暴露 solve_captcha()（UC 需先切换 CDP 模式）；按只试一次约束不在本模式尝试" % mode,
    }
    rec["close"] = close_selenium(driver)
    return rec


def _run_turnstile_cdp(cdp):
    out = {
        "attempted": False, "url": TURNSTILE_URL, "available": None,
        "loaded": False, "load_error": None, "title_before": None,
        "has_solve_captcha": hasattr(cdp, "solve_captcha"),
        "solve_result": None, "solve_error": None, "solve_timeout": False,
        "solve_elapsed_s": None, "post": None, "reason": None,
    }
    r = _cdp_get(cdp, TURNSTILE_URL, PAGE_TIMEOUT)
    out["loaded"] = r["ok"]
    out["load_error"] = r["error"]
    if not r["ok"]:
        out["reason"] = "Turnstile 页面加载失败，放弃"
        return out
    time.sleep(3)
    ev = _cdp_eval(cdp, "document.title", 10)
    out["title_before"] = ev["value"] if ev["ok"] else None
    ev = _cdp_eval(cdp, "location.href", 10)
    out["url_after_redirect"] = ev["value"] if ev["ok"] else None
    title_l = (out["title_before"] or "").lower()
    out["available"] = ("turnstile" in title_l) or ("challenge" in title_l)
    if not out["available"]:
        out["reason"] = "目标不是 Cloudflare Turnstile 测试页（title=%r）" % out["title_before"]
        return out
    if not out["has_solve_captcha"]:
        out["reason"] = "CDP 对象无 solve_captcha()"
        return out

    out["attempted"] = True
    r = call_in_thread(cdp.solve_captcha, 60)
    out["solve_result"] = r["value"]
    out["solve_error"] = r["error"]
    out["solve_timeout"] = r["timeout"]
    out["solve_elapsed_s"] = r["elapsed_s"]

    if r["timeout"]:
        out["reason"] = "solve_captcha 超过 60s 硬上限，浏览器已终止"
        out["_browser_dead"] = True
        for pid in cdp_pids(cdp):
            kill_tree(pid)
        return out

    time.sleep(3)
    post = _cdp_eval(cdp, TURNSTILE_CHECK_JS, 20)
    if post["ok"] and isinstance(post["value"], dict):
        out["post"] = post["value"]
    else:
        out["post_error"] = post["error"]
    return out


def _recycle_cdp(cdp, chrome):
    from seleniumbase import sb_cdp
    for pid in cdp_pids(cdp):
        kill_tree(pid)
    time.sleep(1)
    return sb_cdp.Chrome(
        url="about:blank",
        headless=True,
        browser_executable_path=chrome,
    )


def run_cdp_mode(chrome, do_turnstile=True):
    from seleniumbase import sb_cdp
    rec = {
        "mode": "cdp", "status": "ok", "browser": {}, "launch_error": None,
        "sannysoft": None, "browserscan": None, "challenge": None,
        "turnstile": None, "close": None, "relaunches": 0, "errors": [],
    }
    cdp = None
    force_kill = False
    try:
        cdp = sb_cdp.Chrome(
            url="about:blank",
            headless=True,
            browser_executable_path=chrome,
        )
        rec["browser"] = {"kind": "cdp", "driver": "sb_cdp", "headless": True}
        ua = _cdp_eval(cdp, "navigator.userAgent", 10)
        rec["browser"]["user_agent"] = ua["value"]
        if not ua["ok"]:
            rec["browser"]["user_agent_error"] = ua["error"]
    except Exception as e:
        rec["status"] = "error"
        rec["launch_error"] = "%s: %s" % (type(e).__name__, str(e)[:600])
        rec["close"] = close_cdp(cdp)
        return rec

    steps = [
        ("sannysoft", SANNY_URL, 3, SNY_JS),
        ("browserscan", BSCAN_URL, 7, BSCAN_JS),
        ("challenge", DEMO_URL, 2, CHALLENGE_JS),
    ]
    for name, url, wait_s, js in steps:
        if cdp is None:
            rec[name] = {"url": url, "loaded": False, "error": "浏览器已回收且重建失败"}
            continue
        try:
            rec[name] = _cdp_visit(cdp, url, wait_s, js)
        except Exception:
            rec[name] = {"url": url, "error": traceback.format_exc()}
        if (rec[name] or {}).get("hard_timeout"):
            try:
                cdp = _recycle_cdp(cdp, chrome)
                rec["relaunches"] += 1
            except Exception:
                rec["errors"].append(
                    "CDP 浏览器回收失败: " + traceback.format_exc()[-800:])
                cdp = None

    if do_turnstile and cdp is not None:
        try:
            rec["turnstile"] = _run_turnstile_cdp(cdp)
            if rec["turnstile"].get("_browser_dead"):
                force_kill = True
                rec["turnstile"].pop("_browser_dead", None)
        except Exception:
            rec["turnstile"] = {
                "attempted": False,
                "url": TURNSTILE_URL,
                "reason": "异常: " + traceback.format_exc()[-800:],
            }
    elif do_turnstile:
        rec["turnstile"] = {
            "attempted": False, "url": TURNSTILE_URL,
            "reason": "CDP 浏览器不可用（回收失败），跳过",
        }
    else:
        rec["turnstile"] = {
            "attempted": False, "url": TURNSTILE_URL,
            "reason": "本次运行禁用该可选项",
        }

    rec["close"] = close_cdp(cdp, force_kill=force_kill)
    return rec


def summarize_challenge(ch):
    if not ch:
        return None
    pats = {}
    for p in CHALLENGE_PATTERNS:
        m = (ch.get("matches") or {}).get(p) or {}
        pats[p] = bool(m.get("any"))
    return {
        "false_positive": bool(ch.get("false_positive")),
        "patterns": pats,
        "title": ch.get("title"),
    }


def build_md(result):
    modes = result["modes"]
    env = result["env"]

    def get(mode, path, default=None):
        cur = modes.get(mode) or {}
        for key in path.split("."):
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key)
            if cur is None:
                return default
        return cur

    def cell(v):
        if v is None:
            return "—"
        if isinstance(v, bool):
            return "是" if v else "否"
        return str(v).replace("|", "\|").replace("\n", " ")

    def fp_text(mode):
        ch = get(mode, "challenge")
        if not ch:
            return "无数据"
        if ch.get("error"):
            return "异常"
        s = summarize_challenge(ch)
        if not s:
            return "无数据"
        if not s["false_positive"]:
            return "未误报"
        hit = [k for k, v in s["patterns"].items() if v]
        return "误报: " + ", ".join(hit)

    def bs_overall(mode):
        b = get(mode, "browserscan") or {}
        summ = b.get("summary") or ""
        if b.get("collect_error") and not summ:
            return "采集失败"
        if not b:
            return "—"
        return summ[:110] if summ else "—"

    def sanny_counts(mode):
        s = get(mode, "sannysoft") or {}
        if not s:
            return "—"
        return "%s / %s" % (cell(s.get("passed")), cell(s.get("failed")))

    def turnstile_text(mode):
        t = get(mode, "turnstile") or {}
        if not t:
            return "—"
        if not t.get("attempted"):
            return "跳过（%s）" % (t.get("reason") or "未尝试")
        if t.get("solve_timeout"):
            return "超时（60s）"
        post = t.get("post") or {}
        if post.get("success_visible"):
            return "成功（成功标记可见）"
        if post.get("failure_visible"):
            return "失败（失败标记可见）"
        err = t.get("solve_error")
        return "已调用，未见成功标记" + ("（%s）" % err[:80] if err else "")

    ms = ("standard", "uc", "cdp")
    lines = []
    lines.append("# SeleniumBase Stealth Spike 结果")
    lines.append("")
    lines.append("- 生成时间：%s" % result["generated_at"])
    lines.append("- Python：%s" % env.get("python"))
    lines.append("- SeleniumBase：%s" % env.get("seleniumbase"))
    lines.append("- Chrome：%s（%s）" % (env.get("chrome_version"), env.get("chrome_path")))
    lines.append("- chromedriver：%s；uc_driver：%s" % (
        env.get("chromedriver_version"), env.get("uc_driver_version")))
    lines.append("- 说明：外部站点加载硬上限 30s；sannysoft 等待 3s，browserscan 等待 7s；每模式独立浏览器。")
    lines.append("")
    lines.append("## 三模式检测项对比")
    lines.append("")
    lines.append("| 检测项 | standard | uc | cdp |")
    lines.append("|---|---|---|---|")
    lines.append("| navigator.webdriver | %s | %s | %s |" % tuple(
        cell(get(m, "sannysoft.webdriver")) for m in ms))
    lines.append("| plugins 数量 | %s | %s | %s |" % tuple(
        cell(get(m, "sannysoft.plugins")) for m in ms))
    lines.append("| window.chrome | %s | %s | %s |" % tuple(
        cell(get(m, "sannysoft.window_chrome")) for m in ms))
    lines.append("| sannysoft 加载 | %s | %s | %s |" % tuple(
        ("成功" if get(m, "sannysoft.loaded") else "超时/失败") for m in ms))
    lines.append("| sannysoft passed / failed | %s | %s | %s |" % tuple(
        sanny_counts(m) for m in ms))
    lines.append("| sannysoft 正文长度 | %s | %s | %s |" % tuple(
        cell(get(m, "sannysoft.body_len")) for m in ms))
    lines.append("| sannysoft 标题 | %s | %s | %s |" % tuple(
        cell(get(m, "sannysoft.title")) for m in ms))
    lines.append("| browserscan 总体 | %s | %s | %s |" % tuple(
        cell(bs_overall(m)) for m in ms))
    lines.append("| 挑战规则误报 | %s | %s | %s |" % tuple(
        cell(fp_text(m)) for m in ms))
    lines.append("| solve_captcha | %s | %s | %s |" % tuple(
        cell(turnstile_text(m)) for m in ms))
    lines.append("")
    lines.append("## 挑战检测规则逐项结果（demo_page 误报验证）")
    lines.append("")
    lines.append("| 规则 | standard | uc | cdp |")
    lines.append("|---|---|---|---|")
    for p in CHALLENGE_PATTERNS:
        row = []
        for m in ms:
            ch = get(m, "challenge") or {}
            match = (ch.get("matches") or {}).get(p) or {}
            row.append("命中" if match.get("any") else "未命中")
        lines.append("| %s | %s | %s | %s |" % (p, row[0], row[1], row[2]))
    lines.append("")
    lines.append("## 各模式详情")
    lines.append("")
    for m in ms:
        rec = modes.get(m) or {}
        lines.append("### %s" % m)
        lines.append("")
        lines.append("- 状态：%s" % rec.get("status"))
        b = rec.get("browser") or {}
        lines.append("- 浏览器：%s，版本 %s，headless=%s，回退 headed=%s" % (
            b.get("driver"), cell(b.get("browser_version") or b.get("user_agent")),
            cell(b.get("headless")), cell(b.get("fallback_headed"))))
        if b.get("first_headless_error"):
            lines.append("- UC headless 首次失败：%s" % b["first_headless_error"])
        if rec.get("launch_error"):
            lines.append("- 启动异常：%s" % rec["launch_error"])
        s = rec.get("sannysoft") or {}
        lines.append("- sannysoft：loaded=%s，最终 URL=%s，UA=%s" % (
            cell(s.get("loaded")), cell(s.get("final_url")), cell(s.get("userAgent"))))
        if s.get("load_error"):
            lines.append("  - 加载异常：%s" % s["load_error"])
        if s.get("collect_error"):
            lines.append("  - 采集异常：%s" % s["collect_error"])
        lines.append("  - passed=%s，failed=%s，title=%s，body_len=%s" % (
            cell(s.get("passed")), cell(s.get("failed")),
            cell(s.get("title")), cell(s.get("body_len"))))
        if s.get("body_len") == 0:
            lines.append("  - 注意：正文为空（站点被拦截/未渲染），passed/failed=0 不代表通过全部检测。")
        bs = rec.get("browserscan") or {}
        lines.append("- browserscan：title=%s，summary=%s" % (
            cell(bs.get("title")), cell((bs.get("summary") or "")[:300])))
        if bs.get("keyword_flags"):
            lines.append("  - 关键词：%s" % json.dumps(bs["keyword_flags"], ensure_ascii=False))
        if bs.get("detail_snippets"):
            lines.append("  - 结果片段：%s" % json.dumps(bs["detail_snippets"], ensure_ascii=False))
        if bs.get("load_error"):
            lines.append("  - 加载异常：%s" % bs["load_error"])
        if bs.get("collect_error"):
            lines.append("  - 采集异常：%s" % bs["collect_error"])
        ch = rec.get("challenge") or {}
        lines.append("- demo_page：title=%s，误报=%s" % (
            cell(ch.get("title")), cell(ch.get("false_positive"))))
        if ch.get("load_error"):
            lines.append("  - 加载异常：%s" % ch["load_error"])
        if ch.get("collect_error"):
            lines.append("  - 采集异常：%s" % ch["collect_error"])
        t = rec.get("turnstile") or {}
        lines.append("- turnstile：attempted=%s，%s" % (
            cell(t.get("attempted")), t.get("reason") or ""))
        if t.get("attempted"):
            lines.append("  - 页面 title=%s，最终 URL=%s" % (
                cell(t.get("title_before")), cell(t.get("url_after_redirect"))))
            lines.append("  - solve_captcha：返回=%s，耗时=%ss，超时=%s，错误=%s" % (
                cell(t.get("solve_result")), cell(t.get("solve_elapsed_s")),
                cell(t.get("solve_timeout")), cell(t.get("solve_error"))))
            post = t.get("post") or {}
            lines.append("  - 成功标记可见=%s，失败标记可见=%s" % (
                cell(post.get("success_visible")), cell(post.get("failure_visible"))))
        cl = rec.get("close") or {}
        lines.append("- 关闭：quit_ok=%s，killed=%s" % (
            cell(cl.get("quit_ok")), cell(cl.get("killed_pids"))))
        lines.append("")
    lines.append("## 异常与环境说明")
    lines.append("")
    notes = result.get("notes") or []
    for n in notes:
        lines.append("- %s" % n)
    if not notes:
        lines.append("- 无")
    lines.append("")
    return "\n".join(lines)


def main():
    import seleniumbase
    env = {
        "python": sys.version.split()[0],
        "seleniumbase": seleniumbase.__version__,
        "generated_by": "spike.py",
    }
    chrome_info = resolve_chrome()
    chosen = chrome_info.get("chosen")
    if chosen is None:
        raise RuntimeError("未找到可用的 Chrome 可执行文件")
    notes = []
    chrome_path = chosen["path"]
    env["chrome_path"] = chrome_path
    env["chrome_version"] = chosen.get("version")
    env["chromedriver_version"] = chrome_info.get("chromedriver_version")
    env["uc_driver_version"] = chrome_info.get("uc_driver_version")
    env["chrome_candidates"] = chrome_info.get("candidates")
    if not os.path.isfile(CHROME_CANDIDATES[0]):
        notes.append(
            "任务给定的 Chrome 路径不存在（%s），已回退到可用路径 %s（版本 %s）。"
            % (CHROME_CANDIDATES[0], chrome_path, chosen.get("version"))
        )
    if (chrome_info.get("uc_driver_version") or "").split(".")[0] != (chosen.get("version") or "").split(".")[0]:
        notes.append(
            "uc_driver 主版本(%s) 与 Chrome 主版本(%s) 不一致，UC 模式可能失败。"
            % (chrome_info.get("uc_driver_version"), chosen.get("version"))
        )

    print("[spike] chrome:", chrome_path, chosen.get("version"))
    print("[spike] chromedriver:", chrome_info.get("chromedriver_version"),
          "uc_driver:", chrome_info.get("uc_driver_version"))

    result = {
        "generated_at": now_str(),
        "env": env,
        "modes": {},
        "notes": notes,
    }

    for mode in ("standard", "uc", "cdp"):
        print("[spike] running mode:", mode)
        try:
            if mode == "cdp":
                rec = run_cdp_mode(chrome_path, do_turnstile=True)
            else:
                rec = run_selenium_mode(mode, chrome_path)
        except Exception:
            rec = {
                "mode": mode, "status": "error",
                "launch_error": traceback.format_exc()[-1500:],
                "sannysoft": None, "browserscan": None,
                "challenge": None, "turnstile": None,
            }
        result["modes"][mode] = rec
        print("[spike] mode done:", mode, "status=", rec.get("status"))

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(build_md(result))
    print("[spike] wrote:", JSON_PATH)
    print("[spike] wrote:", MD_PATH)


if __name__ == "__main__":
    main()
