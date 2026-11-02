#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SeleniumBase standard / UC 模式 spike 验证（仅验证，不做项目实现）。"""

import inspect
import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import selenium
import seleniumbase
from seleniumbase import Driver

BASE = Path(__file__).resolve().parent
STATED_CHROME = Path(r"C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe")
FALLBACK_CHROME = Path(r"C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe")
DEMO_URL = "https://seleniumbase.io/demo_page"
SITE_LIMIT = 30
PROFILE_DIR = BASE / "profile_std"
SHOT_STD = BASE / "demo_page.png"
SHOT_UC = BASE / "demo_page_uc.png"
SHOT_UC_HEADED = BASE / "demo_page_uc_headed.png"
LOCAL_HTML = BASE / "local_50k.html"
RESULT_JSON = BASE / "result.json"
RESULT_MD = BASE / "result.md"
DRIVER_DIR = Path(seleniumbase.__file__).parent / "drivers"

result = {
    "meta": {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "seleniumbase": seleniumbase.__version__,
        "selenium": selenium.__version__,
        "stated_chrome_path": str(STATED_CHROME),
        "stated_chrome_exists": STATED_CHROME.exists(),
        "site_limit_s": SITE_LIMIT,
        "environment_notes": [],
    },
    "signature": {},
    "standard": {},
    "profile_persistence": {},
    "uc": {},
    "exceptions": [],
}

JS_INFO = r"""
const all = document.querySelectorAll('*');
let visible = 0;
let interactive = 0;
const interactiveSelector = 'a,button,input,select,textarea,[onclick],[role="button"]';
for (let i = 0; i < all.length; i++) {
    const el = all[i];
    if (el === document.body || el === document.documentElement || el.offsetParent !== null) {
        visible += 1;
    }
    if (el.matches && el.matches(interactiveSelector)) {
        interactive += 1;
    }
}
return {
    title: document.title,
    url: location.href,
    readyState: document.readyState,
    totalElements: all.length,
    visibleElements: visible,
    interactiveElements: interactive,
    navigatorWebdriver: navigator.webdriver,
    userAgent: navigator.userAgent,
};
"""

SET_STORAGE_JS = r"""
document.cookie = "spike_cookie=spike_value; path=/";
localStorage.setItem("spike_ls", "spike_ls_value");
return {cookie: document.cookie, localStorage: localStorage.getItem("spike_ls")};
"""

READ_STORAGE_JS = r"""
return {
    cookie: document.cookie,
    localStorage: localStorage.getItem("spike_ls"),
    url: location.href,
};
"""

READ_PROFILE_JS = r"""
return {
    cookie: document.cookie,
    marker: localStorage.getItem("profile_marker"),
    url: location.href,
};
"""


def record_exception(section, step, exc, extra=None):
    item = {
        "section": section,
        "step": step,
        "type": type(exc).__name__,
        "message": str(exc)[:1200],
    }
    if extra:
        item.update(extra)
    result["exceptions"].append(item)
    print("[EXC] %s / %s: %s: %s" % (section, step, type(exc).__name__, str(exc)[:300]), flush=True)


def new_driver(**kwargs):
    t0 = time.perf_counter()
    drv = Driver(**kwargs)
    return drv, round(time.perf_counter() - t0, 3)


def safe_quit(drv, section):
    if drv is None:
        return
    try:
        drv.quit()
    except Exception as exc:
        record_exception(section, "quit", exc)


def navigate(drv, url, section, step, timeout=SITE_LIMIT, retries=1):
    attempts = []
    for i in range(retries + 1):
        t0 = time.perf_counter()
        try:
            drv.set_page_load_timeout(timeout)
            drv.get(url)
            elapsed = round(time.perf_counter() - t0, 3)
            attempts.append({"attempt": i + 1, "ok": True, "elapsed_s": elapsed})
            return {"ok": True, "elapsed_s": elapsed, "attempts": attempts}
        except Exception as exc:
            elapsed = round(time.perf_counter() - t0, 3)
            attempts.append({
                "attempt": i + 1,
                "ok": False,
                "elapsed_s": elapsed,
                "error_type": type(exc).__name__,
                "error": str(exc)[:800],
            })
            record_exception(section, "%s (attempt %d)" % (step, i + 1), exc)
            if i < retries:
                time.sleep(1)
    return {"ok": False, "elapsed_s": attempts[-1]["elapsed_s"], "attempts": attempts}


def refresh_page(drv, section, step, timeout=SITE_LIMIT, retries=1):
    attempts = []
    for i in range(retries + 1):
        t0 = time.perf_counter()
        try:
            drv.set_page_load_timeout(timeout)
            drv.refresh()
            elapsed = round(time.perf_counter() - t0, 3)
            attempts.append({"attempt": i + 1, "ok": True, "elapsed_s": elapsed})
            return {"ok": True, "elapsed_s": elapsed, "attempts": attempts}
        except Exception as exc:
            elapsed = round(time.perf_counter() - t0, 3)
            attempts.append({
                "attempt": i + 1,
                "ok": False,
                "elapsed_s": elapsed,
                "error_type": type(exc).__name__,
                "error": str(exc)[:800],
            })
            record_exception(section, "%s (attempt %d)" % (step, i + 1), exc)
            if i < retries:
                time.sleep(1)
    return {"ok": False, "elapsed_s": attempts[-1]["elapsed_s"], "attempts": attempts}


def inject_js(drv, section):
    out = {}
    try:
        t0 = time.perf_counter()
        data = drv.execute_script(JS_INFO) or {}
        out.update(data)
        out["elapsed_s"] = round(time.perf_counter() - t0, 3)
        out["ok"] = True
    except Exception as exc:
        record_exception(section, "js injection", exc)
        out["ok"] = False
        out["error"] = {"type": type(exc).__name__, "message": str(exc)[:800]}
    return out


def take_screenshot(drv, path, section):
    t0 = time.perf_counter()
    try:
        png = drv.get_screenshot_as_png()
        path.write_bytes(png)
        return {
            "ok": True,
            "path": str(path),
            "size_bytes": len(png),
            "size_kb": round(len(png) / 1024.0, 1),
            "elapsed_s": round(time.perf_counter() - t0, 3),
        }
    except Exception as exc:
        record_exception(section, "screenshot", exc)
        return {
            "ok": False,
            "path": str(path),
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "error": {"type": type(exc).__name__, "message": str(exc)[:800]},
        }


def test_tabs(drv, section):
    out = {}
    try:
        before = len(drv.window_handles)
        original = drv.current_window_handle
        t0 = time.perf_counter()
        drv.switch_to.new_window("tab")
        time.sleep(0.5)
        out["handles_before"] = before
        out["handles_after"] = len(drv.window_handles)
        out["new_handle_created"] = out["handles_after"] == before + 1
        out["new_handle_differs"] = drv.current_window_handle != original
        drv.switch_to.window(original)
        out["switched_back"] = drv.current_window_handle == original
        out["elapsed_s"] = round(time.perf_counter() - t0, 3)
        out["ok"] = out["new_handle_created"] and out["switched_back"]
    except Exception as exc:
        record_exception(section, "tabs", exc)
        out["ok"] = False
        out["error"] = {"type": type(exc).__name__, "message": str(exc)[:800]}
    return out


def test_cookie_storage(drv, section, label):
    out = {}
    try:
        t0 = time.perf_counter()
        out["set"] = drv.execute_script(SET_STORAGE_JS)
        out["set_elapsed_s"] = round(time.perf_counter() - t0, 4)
        out["reload"] = refresh_page(drv, section, label + " reload")
        out["read_after_reload"] = drv.execute_script(READ_STORAGE_JS)
        cookie = out["read_after_reload"].get("cookie") or ""
        ls_val = out["read_after_reload"].get("localStorage")
        out["cookie_ok"] = "spike_cookie=spike_value" in cookie
        out["localstorage_ok"] = ls_val == "spike_ls_value"
        out["ok"] = bool(out["cookie_ok"] and out["localstorage_ok"] and out["reload"]["ok"])
    except Exception as exc:
        record_exception(section, label, exc)
        out["ok"] = False
        out["error"] = {"type": type(exc).__name__, "message": str(exc)[:800]}
    return out


def build_local_html(target=50000):
    t0 = time.perf_counter()
    parts = [
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
        "<title>spike-50k</title></head><body><div id=\"root\">\n"
    ]
    for i in range(target):
        if i % 25 == 0:
            parts.append('<button class="btn">btn %d</button>\n' % i)
        else:
            parts.append('<div class="item">node %d</div>\n' % i)
    parts.append("</div></body></html>\n")
    LOCAL_HTML.write_text("".join(parts), encoding="utf-8")
    return {
        "path": str(LOCAL_HTML),
        "uri": LOCAL_HTML.as_uri(),
        "body_nodes": target,
        "file_size_bytes": LOCAL_HTML.stat().st_size,
        "generation_s": round(time.perf_counter() - t0, 3),
    }


def run_local_dom(drv, section, local_html):
    out = {"html": local_html}
    out["navigation"] = navigate(drv, local_html["uri"], section, "local_50k", timeout=SITE_LIMIT, retries=1)
    if not out["navigation"]["ok"]:
        return out
    try:
        drv.set_script_timeout(180)
        t0 = time.perf_counter()
        data = drv.execute_script(JS_INFO) or {}
        out["traversal"] = {"elapsed_s": round(time.perf_counter() - t0, 3), "ok": True}
        out["traversal"].update(data)
    except Exception as exc:
        record_exception(section, "local DOM traversal", exc)
        out["traversal"] = {
            "ok": False,
            "error": {"type": type(exc).__name__, "message": str(exc)[:800]},
        }
    return out


def collect_signature():
    sig = inspect.signature(Driver)
    params = list(sig.parameters)
    result["signature"] = {
        "signature": str(sig),
        "parameter_count": len(params),
        "has_headless": "headless" in params,
        "has_uc": "uc" in params,
        "has_user_data_dir": "user_data_dir" in params,
        "has_binary_location": "binary_location" in params,
    }


def exe_version(path):
    try:
        proc = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )
        text = (proc.stdout or proc.stderr or "").strip().splitlines()
        return text[0] if text else "unknown"
    except Exception as exc:
        return "error: %s: %s" % (type(exc).__name__, str(exc)[:200])


def pick_chrome():
    notes = result["meta"]["environment_notes"]
    if STATED_CHROME.exists():
        notes.append("使用任务给定的 Chrome 路径: %s" % STATED_CHROME)
        return str(STATED_CHROME)
    notes.append("任务给定的 Chrome 路径不存在: %s" % STATED_CHROME)
    if FALLBACK_CHROME.exists():
        notes.append("实际存在的 Chrome 位于: %s（Chrome 109 系列）" % FALLBACK_CHROME)
        return str(FALLBACK_CHROME)
    raise FileNotFoundError("未找到可用 Chrome: %s / %s" % (STATED_CHROME, FALLBACK_CHROME))


def run_standard(chrome):
    section = "standard"
    s = result["standard"]
    s["requested"] = {"headless": True, "binary_location": chrome}
    drv = None
    try:
        drv, startup = new_driver(headless=True, binary_location=chrome)
        s["startup_s"] = startup
        s["browser_version"] = drv.capabilities.get("browserVersion")
        s["startup_ok"] = True
        print("[standard] started in %ss, browser=%s" % (startup, s["browser_version"]), flush=True)

        s["navigation"] = navigate(drv, DEMO_URL, section, "demo_page")
        s["js"] = inject_js(drv, section)
        s["screenshot"] = take_screenshot(drv, SHOT_STD, section)
        s["tabs"] = test_tabs(drv, section)
        s["cookie_storage"] = test_cookie_storage(drv, section, "cookie/localStorage")
        s["local_dom"] = run_local_dom(drv, section, s["local_html"])

        s["passed"] = bool(
            s["navigation"]["ok"]
            and s["js"].get("ok")
            and s["screenshot"].get("ok")
            and s["tabs"].get("ok")
            and s["cookie_storage"].get("ok")
            and s["local_dom"].get("traversal", {}).get("ok")
        )
    except Exception as exc:
        record_exception(section, "unexpected", exc)
        s["startup_ok"] = s.get("startup_ok", False)
        s["passed"] = False
        s["unexpected_error"] = {"type": type(exc).__name__, "message": str(exc)[:1200]}
    finally:
        safe_quit(drv, section)


def run_profile(chrome):
    section = "profile"
    s = result["profile_persistence"]
    s["user_data_dir"] = str(PROFILE_DIR)
    s["param_supported"] = result["signature"]["has_user_data_dir"]
    if not s["param_supported"]:
        s["conclusion"] = "Driver 签名无 user_data_dir 参数，未测试"
        return

    try:
        if PROFILE_DIR.exists():
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        record_exception(section, "prepare profile dir", exc)
        s["conclusion"] = "profile 目录准备失败"
        return

    marker = "spike-profile-%d" % int(time.time())
    s["marker"] = marker
    drv = None
    try:
        drv, startup = new_driver(
            headless=True,
            binary_location=chrome,
            user_data_dir=str(PROFILE_DIR),
        )
        s["first_session_startup_s"] = startup
        s["first_session_browser_version"] = drv.capabilities.get("browserVersion")
        s["first_navigation"] = navigate(drv, DEMO_URL, section, "first demo_page")
        if s["first_navigation"]["ok"]:
            set_js = r"""
document.cookie = "profile_cookie=profile_value; path=/; max-age=86400";
localStorage.setItem("profile_marker", %s);
return {cookie: document.cookie, marker: localStorage.getItem("profile_marker")};
""" % json.dumps(marker)
            s["written"] = drv.execute_script(set_js)
            time.sleep(2)
    except Exception as exc:
        record_exception(section, "first session", exc)
        s["first_session_error"] = {"type": type(exc).__name__, "message": str(exc)[:800]}
    finally:
        safe_quit(drv, section)

    time.sleep(2)
    try:
        s["profile_dir_exists"] = PROFILE_DIR.exists()
        s["profile_file_count"] = sum(1 for _ in PROFILE_DIR.rglob("*")) if PROFILE_DIR.exists() else 0
    except Exception as exc:
        record_exception(section, "inspect profile dir", exc)

    drv2 = None
    try:
        drv2, startup2 = new_driver(
            headless=True,
            binary_location=chrome,
            user_data_dir=str(PROFILE_DIR),
        )
        s["second_session_startup_s"] = startup2
        s["second_navigation"] = navigate(drv2, DEMO_URL, section, "second demo_page")
        if s["second_navigation"]["ok"]:
            read = drv2.execute_script(READ_PROFILE_JS)
            s["read_after_restart"] = read
            s["localstorage_persisted"] = read.get("marker") == marker
            s["cookie_persisted"] = "profile_cookie=profile_value" in (read.get("cookie") or "")
            s["conclusion"] = (
                "localStorage 已保留" if s["localstorage_persisted"] else "localStorage 未保留"
            ) + ("；Cookie 已保留" if s["cookie_persisted"] else "；Cookie 未保留")
        else:
            s["conclusion"] = "重启后页面导航失败，无法读取"
    except Exception as exc:
        record_exception(section, "second session", exc)
        s["second_session_error"] = {"type": type(exc).__name__, "message": str(exc)[:800]}
        s["conclusion"] = "重启会话失败"
    finally:
        safe_quit(drv2, section)


def attempt_uc(chrome, headless):
    section = "uc"
    info = {
        "headless": headless,
        "startup_ok": False,
        "usable": False,
        "ok": False,
    }
    drv = None
    try:
        drv, startup = new_driver(headless=headless, uc=True, binary_location=chrome)
        info["startup_s"] = startup
        info["startup_ok"] = True
        info["browser_version"] = drv.capabilities.get("browserVersion")
        print("[uc] started in %ss (headless=%s)" % (startup, headless), flush=True)
        info["navigation"] = navigate(drv, DEMO_URL, section, "demo_page (headless=%s)" % headless)
        if not info["navigation"]["ok"]:
            info["error"] = "navigation failed"
            return info
        info["usable"] = True
        info["js"] = inject_js(drv, section)
        shot = SHOT_UC if headless else SHOT_UC_HEADED
        info["screenshot"] = take_screenshot(drv, shot, section)
        info["cookie_storage"] = test_cookie_storage(
            drv, section, "cookie/localStorage (headless=%s)" % headless
        )
        info["ok"] = bool(
            info["js"].get("ok")
            and info["screenshot"].get("ok")
            and info["cookie_storage"].get("ok")
        )
        return info
    except Exception as exc:
        record_exception(section, "unexpected (headless=%s)" % headless, exc)
        info["error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        return info
    finally:
        safe_quit(drv, section)


def run_uc(chrome):
    s = result["uc"]
    s["requested"] = {"headless": True, "uc": True, "binary_location": chrome}
    s["attempts"] = []
    selected = None
    for headless in (True, False):
        info = attempt_uc(chrome, headless)
        s["attempts"].append(info)
        if info.get("usable"):
            selected = info
            break
        if headless is False:
            break
    s["selected_headless"] = selected.get("headless") if selected else None
    s["headed_fallback_used"] = bool(
        s["attempts"]
        and s["attempts"][0].get("headless") is True
        and not s["attempts"][0].get("usable")
        and len(s["attempts"]) > 1
    )
    s["passed"] = bool(selected and selected.get("ok"))


def md_escape(value):
    return str(value).replace("|", "\|").replace("\n", " ")


def fmt(value):
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return "%.3f" % value
    return str(value)


def render_markdown():
    lines = []
    lines.append("# SeleniumBase standard / UC Spike 结果")
    lines.append("")
    meta = result["meta"]
    lines.append("- 开始时间: %s" % meta["started_at"])
    lines.append("- Python: %s" % meta["python"])
    lines.append("- seleniumbase: %s" % meta["seleniumbase"])
    lines.append("- selenium: %s" % meta["selenium"])
    lines.append("- 任务给定 Chrome 路径存在: %s" % fmt(meta["stated_chrome_exists"]))
    for note in meta.get("environment_notes", []):
        lines.append("- 环境备注: %s" % note)
    for key, val in meta.get("driver_versions", {}).items():
        lines.append("- 驱动 %s: %s" % (key, val))
    lines.append("")

    sig = result["signature"]
    lines.append("## Driver 签名检查")
    lines.append("")
    lines.append("| 参数 | 是否存在 |")
    lines.append("|---|---|")
    lines.append("| headless | %s |" % fmt(sig.get("has_headless")))
    lines.append("| uc | %s |" % fmt(sig.get("has_uc")))
    lines.append("| user_data_dir | %s |" % fmt(sig.get("has_user_data_dir")))
    lines.append("| binary_location | %s |" % fmt(sig.get("has_binary_location")))
    lines.append("")
    lines.append("```text")
    lines.append(sig.get("signature", ""))
    lines.append("```")
    lines.append("")

    s = result["standard"]
    lines.append("## standard 模式（headless=True）")
    lines.append("")
    lines.append("| 项目 | 结果 |")
    lines.append("|---|---|")
    lines.append("| 启动 | %s（%.3fs） |" % (fmt(s.get("startup_ok")), s.get("startup_s", 0)))
    lines.append("| 浏览器版本 | %s |" % fmt(s.get("browser_version")))
    nav = s.get("navigation", {})
    lines.append("| demo_page 加载 | %s（%.3fs） |" % (fmt(nav.get("ok")), nav.get("elapsed_s", 0)))
    js = s.get("js", {})
    lines.append("| JS 注入 | %s（%.3fs） |" % (fmt(js.get("ok")), js.get("elapsed_s", 0)))
    lines.append("| 元素总数 / 可见 / 可交互 | %s / %s / %s |" % (
        fmt(js.get("totalElements")), fmt(js.get("visibleElements")), fmt(js.get("interactiveElements"))))
    lines.append("| navigator.webdriver | %s |" % fmt(js.get("navigatorWebdriver")))
    lines.append("| UA | %s |" % fmt(js.get("userAgent")))
    shot = s.get("screenshot", {})
    lines.append("| 截图 | %s（%.1f KB，%.3fs） |" % (
        fmt(shot.get("ok")), shot.get("size_kb", 0), shot.get("elapsed_s", 0)))
    tabs = s.get("tabs", {})
    lines.append("| 标签页 | %s（handle %s -> %s，切回 %s，%.3fs） |" % (
        fmt(tabs.get("ok")), fmt(tabs.get("handles_before")), fmt(tabs.get("handles_after")),
        fmt(tabs.get("switched_back")), tabs.get("elapsed_s", 0)))
    cs = s.get("cookie_storage", {})
    lines.append("| Cookie / localStorage | %s / %s |" % (
        fmt(cs.get("cookie_ok")), fmt(cs.get("localstorage_ok"))))
    lh = s.get("local_html", {})
    ld = s.get("local_dom", {})
    lnav = ld.get("navigation", {})
    trav = ld.get("traversal", {})
    lines.append("| 本地 5 万节点 HTML | 节点 %s，文件 %s 字节，生成 %.3fs |" % (
        fmt(lh.get("body_nodes")), fmt(lh.get("file_size_bytes")), lh.get("generation_s", 0)))
    lines.append("| 本地页面加载 | %s（%.3fs） |" % (fmt(lnav.get("ok")), lnav.get("elapsed_s", 0)))
    lines.append("| 本地 DOM 遍历 | %s（%.3fs，总数 %s） |" % (
        fmt(trav.get("ok")), trav.get("elapsed_s", 0), fmt(trav.get("totalElements"))))
    lines.append("| 结论 | %s |" % ("通过" if s.get("passed") else "失败"))
    lines.append("")

    p = result["profile_persistence"]
    lines.append("## profile 持久化（standard）")
    lines.append("")
    lines.append("| 项目 | 结果 |")
    lines.append("|---|---|")
    lines.append("| user_data_dir 参数支持 | %s |" % fmt(p.get("param_supported")))
    lines.append("| profile 目录 | %s |" % fmt(p.get("user_data_dir")))
    lines.append("| 首次启动 | %s（%.3fs） |" % (
        fmt(p.get("first_session_browser_version")), p.get("first_session_startup_s", 0)))
    lines.append("| 首次写入 | %s |" % fmt(p.get("written")))
    lines.append("| 第二次启动 | %.3fs |" % p.get("second_session_startup_s", 0))
    lines.append("| 重启后读取 | %s |" % fmt(p.get("read_after_restart")))
    lines.append("| localStorage 保留 | %s |" % fmt(p.get("localstorage_persisted")))
    lines.append("| Cookie 保留 | %s |" % fmt(p.get("cookie_persisted")))
    lines.append("| 结论 | %s |" % fmt(p.get("conclusion")))
    lines.append("")

    u = result["uc"]
    lines.append("## UC 模式")
    lines.append("")
    lines.append("| headless | 启动 | 启动耗时 | 导航 | 加载耗时 | JS | webdriver | 截图 | Cookie/Storage | 结果 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for att in u.get("attempts", []):
        ujs = att.get("js", {})
        ushot = att.get("screenshot", {})
        ucs = att.get("cookie_storage", {})
        unav = att.get("navigation", {})
        lines.append("| %s | %s | %ss | %s | %ss | %s | %s | %s | %s / %s | %s |" % (
            fmt(att.get("headless")),
            fmt(att.get("startup_ok")),
            fmt(att.get("startup_s")),
            fmt(unav.get("ok")),
            fmt(unav.get("elapsed_s")),
            fmt(ujs.get("ok")),
            fmt(ujs.get("navigatorWebdriver")),
            fmt(ushot.get("ok")),
            fmt(ucs.get("cookie_ok")),
            fmt(ucs.get("localstorage_ok")),
            "通过" if att.get("ok") else "失败",
        ))
    lines.append("")
    lines.append("- 实际 headless: %s" % fmt(u.get("selected_headless")))
    lines.append("- 使用 headed 兜底: %s" % fmt(u.get("headed_fallback_used")))
    lines.append("- 结论: %s" % ("通过" if u.get("passed") else "失败"))
    lines.append("")

    lines.append("## 异常")
    lines.append("")
    if result["exceptions"]:
        lines.append("| # | 区域 | 步骤 | 类型 | 消息 |")
        lines.append("|---|---|---|---|---|")
        for i, exc in enumerate(result["exceptions"], 1):
            lines.append("| %d | %s | %s | %s | %s |" % (
                i, md_escape(exc.get("section")), md_escape(exc.get("step")),
                md_escape(exc.get("type")), md_escape(exc.get("message"))))
    else:
        lines.append("无")
    lines.append("")
    return "\n".join(lines)
    return "\n".join(lines)


def write_outputs():
    RESULT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    RESULT_MD.write_text(render_markdown(), encoding="utf-8")
    print("[done] wrote %s and %s" % (RESULT_JSON, RESULT_MD), flush=True)


def main():
    collect_signature()
    print("[sig] headless=%s uc=%s user_data_dir=%s" % (
        result["signature"]["has_headless"],
        result["signature"]["has_uc"],
        result["signature"]["has_user_data_dir"],
    ), flush=True)
    result["meta"]["driver_versions"] = {
        "chromedriver": exe_version(DRIVER_DIR / "chromedriver.exe"),
        "uc_driver": exe_version(DRIVER_DIR / "uc_driver.exe"),
    }
    result["meta"]["environment_notes"].append(
        "准备阶段观察：预下载 chromedriver/uc_driver 为 156.0.8078.80，"
        "实际 Chrome 为 109.0.5414.120，版本不匹配；SeleniumBase 首次启动时"
        "自动下载并替换为 109.0.5414.74（未执行 pip install/upgrade）。"
    )
    chrome = pick_chrome()
    result["meta"]["chrome_used"] = chrome
    print("[env] chrome=%s" % chrome, flush=True)

    result["standard"]["local_html"] = build_local_html()
    run_standard(chrome)
    run_profile(chrome)
    run_uc(chrome)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        record_exception("main", "fatal", exc)
        result["fatal_error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:1500],
            "traceback": traceback.format_exc()[-4000:],
        }
    finally:
        try:
            write_outputs()
        except Exception as exc:
            print("[fatal] failed to write outputs: %s" % exc, flush=True)
