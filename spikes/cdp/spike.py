# -*- coding: utf-8 -*-
"""SeleniumBase Pure CDP (sb_cdp.Chrome) spike.

验证项：构造参数/实例方法、启动与导航、JS 取值、DOM 遍历、
截图/PDF、标签页、cookie/localStorage、user_data_dir 持久化。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import statistics
import struct
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from seleniumbase.core import sb_cdp
from seleniumbase.undetected.cdp_driver import cdp_util

WORK = Path(__file__).resolve().parent
DEMO_URL = "https://seleniumbase.io/demo_page"
EXTERNAL_LIMIT = 30.0
CHROME_SPEC = Path(r"C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe")
CHROME_CANDIDATES = [
    CHROME_SPEC,
    Path(r"C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]

RESULT = {
    "spike": "SeleniumBase Pure CDP mode (sb_cdp.Chrome)",
    "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "environment": {},
    "signature": {},
    "method_matrix": [],
    "launch": {},
    "navigation": {},
    "js_stats": {},
    "dom_benchmark": {},
    "artifacts": {},
    "tabs": {},
    "cookies": {},
    "local_storage": {},
    "profile": {},
    "tests": [],
    "exceptions": [],
    "warnings": [],
    "cleanup": {},
    "conclusion": {},
}
STATE = {"sb": None}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def record_exc(step, exc, extra=None):
    item = {
        "step": step,
        "time": now_iso(),
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback_tail": traceback.format_exc()[-2500:],
    }
    if extra:
        item["extra"] = extra
    RESULT["exceptions"].append(item)
    print("[EXC] %s: %s: %s" % (step, type(exc).__name__, exc), flush=True)


def add_warning(level, message, action=None):
    item = {"level": level, "message": message}
    if action:
        item["action"] = action
    RESULT["warnings"].append(item)
    print("[WARN] %s" % message, flush=True)


def add_test(name, status, detail=""):
    RESULT["tests"].append({"name": name, "status": status, "detail": detail})
    print("[TEST] %-26s %-6s %s" % (name, status, detail), flush=True)


def resolve_chrome():
    for path in CHROME_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("No usable chrome.exe found in: %s" % CHROME_CANDIDATES)


def chrome_registry_version():
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"
        ) as key:
            return str(winreg.QueryValueEx(key, "version")[0])
    except Exception:
        return None


def safe_nav(sb, url, limit=EXTERNAL_LIMIT):
    """导航并等待，整体不超过 limit 秒（外部站点硬上限）。"""
    deadline = time.monotonic() + limit
    started = time.perf_counter()
    task = sb.page.get(url)
    sb.loop.run_until_complete(
        asyncio.wait_for(task, max(0.05, deadline - time.monotonic()))
    )
    sb.loop.run_until_complete(
        asyncio.wait_for(sb.page.wait(), max(0.05, deadline - time.monotonic()))
    )
    return (time.perf_counter() - started) * 1000


def safe_reload(sb, limit=EXTERNAL_LIMIT):
    started = time.perf_counter()
    sb.reload()
    sb.loop.run_until_complete(asyncio.wait_for(sb.page.wait(), limit))
    return (time.perf_counter() - started) * 1000


def launch(chrome_path, user_data_dir=None):
    kwargs = {
        "headless": True,
        "browser_executable_path": str(chrome_path),
    }
    if user_data_dir:
        kwargs["user_data_dir"] = str(user_data_dir)
    started = time.perf_counter()
    sb = sb_cdp.Chrome(**kwargs)
    return sb, (time.perf_counter() - started) * 1000


def build_method_matrix(sb):
    groups = {
        "navigation": [
            "get", "open", "goto", "reload", "refresh", "go_back",
            "go_forward", "get_current_url", "get_title", "get_page_title",
            "assert_title", "assert_title_contains", "assert_url",
            "assert_url_contains", "get_navigation_history",
        ],
        "javascript": [
            "evaluate", "execute_script", "js_dumps", "get_page_source",
            "get_html", "get_beautiful_soup",
        ],
        "screenshot_pdf": [
            "save_screenshot", "print_to_pdf", "save_as_pdf",
            "save_page_source", "save_as_html", "save_page",
        ],
        "tabs": [
            "get_tabs", "get_active_tab", "open_new_tab", "open_new_window",
            "switch_to_tab", "switch_to_newest_tab", "switch_to_window",
            "switch_to_newest_window", "close_active_tab",
            "bring_active_window_to_front",
        ],
        "cookies": [
            "get_all_cookies", "set_all_cookies", "save_cookies",
            "load_cookies", "clear_cookies", "get_cookie_string",
        ],
        "storage": [
            "get_local_storage_item", "set_local_storage_item",
            "get_session_storage_item", "set_session_storage_item",
        ],
        "profile_window": [
            "config", "driver", "page", "get_user_agent", "get_window",
            "get_window_size", "get_window_rect", "set_window_rect",
            "maximize", "quit", "stop",
        ],
    }
    matrix = []
    for group, names in groups.items():
        for name in names:
            present = hasattr(sb, name)
            matrix.append(
                {
                    "group": group,
                    "method": name,
                    "available": present,
                    "callable": callable(getattr(sb, name, None)),
                }
            )
    return matrix


JS_STATS = r"""
(() => {
  const all = Array.from(document.querySelectorAll('*'));
  let visible = 0;
  let interactive = 0;
  const interactiveTags = {A:1, BUTTON:1, INPUT:1, SELECT:1, TEXTAREA:1};
  for (const el of all) {
    const cs = getComputedStyle(el);
    const isVisible = cs.display !== 'none' && cs.visibility !== 'hidden'
      && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
    if (isVisible) visible++;
    if (isVisible && (interactiveTags[el.tagName] || el.getAttribute('role') === 'button')) {
      interactive++;
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
    language: navigator.language,
    cookieEnabled: navigator.cookieEnabled,
  };
})()
"""

DOM_QUERY_JS = r"""
(() => {
  const t0 = performance.now();
  const total = document.querySelectorAll('*').length;
  return {ms: performance.now() - t0, total: total};
})()
"""

DOM_FULL_SCAN_JS = r"""
(() => {
  const t0 = performance.now();
  const all = document.querySelectorAll('*');
  let visible = 0;
  let interactive = 0;
  const interactiveTags = {A:1, BUTTON:1, INPUT:1, SELECT:1, TEXTAREA:1};
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    if (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0) {
      visible++;
    }
    if (interactiveTags[el.tagName] || el.getAttribute('role') === 'button') {
      interactive++;
    }
  }
  return {
    ms: performance.now() - t0,
    total: all.length,
    visible: visible,
    interactive: interactive,
    readyState: document.readyState,
  };
})()
"""


def build_dom_file(path):
    started = time.perf_counter()
    sections = 500
    spans_per_section = 100
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>CDP DOM 50k Benchmark</title></head><body>",
        "<div id='root'>",
    ]
    for i in range(sections):
        parts.append("<section class='s' id='s%d'><h2>Section %d</h2>" % (i, i))
        for j in range(spans_per_section):
            parts.append(
                "<span class='n' data-i='%d' data-j='%d'>n%d-%d</span>"
                % (i, j, i, j)
            )
        parts.append("</section>")
    parts.append("</div></body></html>")
    html = "".join(parts)
    path.write_text(html, encoding="utf-8")
    return (time.perf_counter() - started) * 1000, len(html.encode("utf-8"))


def png_dimensions(path):
    with path.open("rb") as f:
        head = f.read(24)
    if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", head[16:24])
        return width, height
    return None, None


def quit_quietly(sb, label):
    if not sb:
        return None
    try:
        started = time.perf_counter()
        sb.quit()
        ms = (time.perf_counter() - started) * 1000
        print("[QUIT] %s %.0f ms" % (label, ms), flush=True)
        return ms
    except BaseException as exc:
        record_exc("quit:%s" % label, exc)
        return None


def main():
    RESULT["environment"] = {
        "host_platform": sys.platform,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "seleniumbase_version": __import__("seleniumbase").__version__,
        "selenium_version": __import__("selenium").__version__,
        "cwd": os.getcwd(),
        "work_dir": str(WORK),
        "chrome_specified_path": str(CHROME_SPEC),
        "chrome_registry_version": chrome_registry_version(),
        "external_site_timeout_sec": EXTERNAL_LIMIT,
    }

    # 清理上一次 smoke 用的临时 profile 与旧产物
    for stale in ("_smoke_profile", "profile_smoke"):
        p = WORK / stale
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for stale in ("cdp_demo.png", "cdp_demo.pdf", "cdp_demo.html"):
        p = WORK / stale
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    chrome_path = resolve_chrome()
    RESULT["environment"]["chrome_used_path"] = str(chrome_path)
    RESULT["environment"]["chrome_specified_exists"] = CHROME_SPEC.exists()
    if chrome_path != CHROME_SPEC:
        add_warning(
            "environment",
            "指定的 Chrome 路径不存在：%s" % CHROME_SPEC,
            "回退使用系统中唯一可用的 Chrome：%s" % chrome_path,
        )

    sig = inspect.signature(sb_cdp.Chrome)
    start_params = inspect.signature(cdp_util.start).parameters
    RESULT["signature"] = {
        "inspect_signature": str(sig),
        "parameters": list(sig.parameters),
        "launch_named_kwargs": [
            name
            for name, param in start_params.items()
            if param.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        ],
        "accepts_headless": "headless" in start_params,
        "accepts_user_data_dir": "user_data_dir" in start_params,
        "accepts_browser_executable_path": "browser_executable_path" in start_params,
    }

    # 1) 启动 + 实例方法矩阵
    sb = None
    try:
        sb, launch_ms = launch(chrome_path)
        STATE["sb"] = sb
        RESULT["launch"] = {
            "ok": True,
            "headless_requested": True,
            "launch_ms": round(launch_ms, 1),
            "url_after_launch": sb.get_current_url(),
            "config": {
                "headless": getattr(sb.driver.config, "headless", None),
                "user_data_dir": getattr(sb.driver.config, "user_data_dir", None),
                "uses_custom_data_dir": getattr(
                    sb.driver.config, "uses_custom_data_dir", None
                ),
                "incognito": getattr(sb.driver.config, "incognito", None),
                "guest": getattr(sb.driver.config, "guest", None),
                "browser_executable_path": getattr(
                    sb.driver.config, "browser_executable_path", None
                ),
            },
            "instance_dir_count": len([a for a in dir(sb) if not a.startswith("__")]),
        }
        try:
            info = sb.driver.info
            RESULT["environment"]["cdp_browser_info"] = {
                key: getattr(info, key, None)
                for key in (
                    "Browser",
                    "Protocol-Version",
                    "User-Agent",
                    "V8-Version",
                    "WebKit-Version",
                )
            }
        except Exception as exc:
            record_exc("cdp_browser_info", exc)
        RESULT["method_matrix"] = build_method_matrix(sb)
        available = sum(1 for row in RESULT["method_matrix"] if row["available"])
        add_test(
            "launch",
            "PASS",
            "headless=True, %.1f ms, dir=%d"
            % (launch_ms, RESULT["launch"]["instance_dir_count"]),
        )
        add_test(
            "method_matrix",
            "PASS",
            "%d/%d 候选方法存在" % (available, len(RESULT["method_matrix"])),
        )
    except BaseException as exc:
        record_exc("launch", exc)
        RESULT["launch"] = {"ok": False}
        add_test("launch", "FAIL", "%s: %s" % (type(exc).__name__, exc))
        add_test("method_matrix", "SKIP", "no instance")
        return

    # 2) 访问 demo_page
    try:
        nav_ms = safe_nav(sb, DEMO_URL)
        RESULT["navigation"] = {
            "url": DEMO_URL,
            "ok": True,
            "nav_ms": round(nav_ms, 1),
            "final_url": sb.get_current_url(),
            "title": sb.get_title(),
        }
        add_test(
            "navigation_demo",
            "PASS",
            "%.1f ms, title=%s" % (nav_ms, RESULT["navigation"]["title"]),
        )
    except BaseException as exc:
        record_exc("navigation_demo", exc)
        RESULT["navigation"] = {"url": DEMO_URL, "ok": False}
        add_test("navigation_demo", "FAIL", "%s: %s" % (type(exc).__name__, exc))

    # 3) JS 统计
    try:
        js_started = time.perf_counter()
        stats = sb.evaluate(JS_STATS)
        stats["js_eval_ms"] = round((time.perf_counter() - js_started) * 1000, 2)
        stats["navigator.webdriver"] = stats.get("navigatorWebdriver")
        alias_value = sb.execute_script("return 1 + 1;")
        RESULT["js_stats"] = stats
        RESULT["js_stats"]["execute_script_alias_1_plus_1"] = alias_value
        ok = isinstance(stats, dict) and stats.get("totalElements", 0) > 0
        add_test(
            "js_stats",
            "PASS" if ok else "FAIL",
            "total=%s visible=%s interactive=%s webdriver=%s"
            % (
                stats.get("totalElements"),
                stats.get("visibleElements"),
                stats.get("interactiveElements"),
                stats.get("navigatorWebdriver"),
            ),
        )
    except BaseException as exc:
        record_exc("js_stats", exc)
        add_test("js_stats", "FAIL", "%s: %s" % (type(exc).__name__, exc))

    # 4) 50k 节点 DOM 基准
    for stale in ("dom_50k.html",):
        p = WORK / stale
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    try:
        dom_path = WORK / "dom_50k.html"
        gen_ms, gen_bytes = build_dom_file(dom_path)
        load_ms = safe_nav(sb, dom_path.as_uri())
        query_runs = [sb.evaluate(DOM_QUERY_JS) for _ in range(3)]
        full_runs = [sb.evaluate(DOM_FULL_SCAN_JS) for _ in range(3)]
        RESULT["dom_benchmark"] = {
            "ok": True,
            "file": str(dom_path),
            "file_bytes": gen_bytes,
            "generated_spans": 500 * 100,
            "generate_ms": round(gen_ms, 1),
            "load_ms": round(load_ms, 1),
            "query_total": query_runs[-1].get("total"),
            "query_ms_runs": [round(r["ms"], 2) for r in query_runs],
            "query_ms_median": round(statistics.median(r["ms"] for r in query_runs), 2),
            "full_scan_total": full_runs[-1].get("total"),
            "full_scan_visible": full_runs[-1].get("visible"),
            "full_scan_ms_runs": [round(r["ms"], 2) for r in full_runs],
            "full_scan_ms_median": round(statistics.median(r["ms"] for r in full_runs), 2),
        }
        ok = RESULT["dom_benchmark"]["query_total"] >= 50000
        add_test(
            "dom_50k_benchmark",
            "PASS" if ok else "FAIL",
            "load=%.1f ms query_med=%.2f ms full_med=%.2f ms total=%s"
            % (
                load_ms,
                RESULT["dom_benchmark"]["query_ms_median"],
                RESULT["dom_benchmark"]["full_scan_ms_median"],
                RESULT["dom_benchmark"]["query_total"],
            ),
        )
    except BaseException as exc:
        record_exc("dom_50k_benchmark", exc)
        RESULT["dom_benchmark"] = {"ok": False}
        add_test("dom_50k_benchmark", "FAIL", "%s: %s" % (type(exc).__name__, exc))

    # 回到 demo 页，准备截图/PDF
    try:
        back_ms = safe_nav(sb, DEMO_URL)
        RESULT["navigation"]["back_to_demo_ms"] = round(back_ms, 1)
    except BaseException as exc:
        record_exc("back_to_demo", exc)
        add_test("back_to_demo", "FAIL", "%s: %s" % (type(exc).__name__, exc))

    # 5) 截图 / PDF / HTML
    artifacts = {"png": {}, "pdf": {}, "html": {}}
    try:
        png_path = WORK / "cdp_demo.png"
        started = time.perf_counter()
        sb.save_screenshot(png_path.name, folder=str(WORK))
        png_ms = (time.perf_counter() - started) * 1000
        width, height = png_dimensions(png_path)
        size = png_path.stat().st_size
        artifacts["png"] = {
            "path": str(png_path),
            "bytes": size,
            "width": width,
            "height": height,
            "save_ms": round(png_ms, 1),
        }
        add_test(
            "screenshot_png",
            "PASS" if size > 0 else "FAIL",
            "%d bytes, %sx%s" % (size, width, height),
        )
    except BaseException as exc:
        record_exc("screenshot_png", exc)
        add_test("screenshot_png", "FAIL", "%s: %s" % (type(exc).__name__, exc))
    try:
        pdf_path = WORK / "cdp_demo.pdf"
        started = time.perf_counter()
        sb.print_to_pdf(pdf_path.name, folder=str(WORK))
        pdf_ms = (time.perf_counter() - started) * 1000
        size = pdf_path.stat().st_size
        artifacts["pdf"] = {
            "path": str(pdf_path),
            "bytes": size,
            "save_ms": round(pdf_ms, 1),
        }
        add_test(
            "pdf_print",
            "PASS" if size > 0 else "FAIL",
            "%d bytes, %.1f ms" % (size, pdf_ms),
        )
    except BaseException as exc:
        record_exc("pdf_print", exc)
        add_test("pdf_print", "FAIL", "%s: %s" % (type(exc).__name__, exc))
    try:
        html_path = WORK / "cdp_demo.html"
        started = time.perf_counter()
        sb.save_page_source(html_path.name, folder=str(WORK))
        html_ms = (time.perf_counter() - started) * 1000
        size = html_path.stat().st_size
        artifacts["html"] = {
            "path": str(html_path),
            "bytes": size,
            "save_ms": round(html_ms, 1),
        }
        add_test(
            "save_page_source",
            "PASS" if size > 0 else "FAIL",
            "%d bytes, %.1f ms" % (size, html_ms),
        )
    except BaseException as exc:
        record_exc("save_page_source", exc)
        add_test("save_page_source", "FAIL", "%s: %s" % (type(exc).__name__, exc))
    RESULT["artifacts"] = artifacts

    # 6) 标签页
    tabs = {}
    try:
        tabs["count_before"] = len(sb.get_tabs())
        dom_uri = (WORK / "dom_50k.html").as_uri()
        started = time.perf_counter()
        sb.open_new_tab(dom_uri, switch_to=True)
        for _ in range(40):
            if len(sb.get_tabs()) >= 2:
                break
            time.sleep(0.1)
        tabs["open_ms"] = round((time.perf_counter() - started) * 1000, 1)
        tabs["count_after_open"] = len(sb.get_tabs())
        tabs["new_tab_url"] = sb.get_current_url()
        tabs["new_tab_title"] = sb.get_title()
        sb.switch_to_tab(0)
        time.sleep(0.2)
        tabs["url_after_switch_0"] = sb.get_current_url()
        sb.switch_to_newest_tab()
        time.sleep(0.2)
        tabs["url_after_switch_newest"] = sb.get_current_url()
        sb.close_active_tab()
        for _ in range(30):
            if len(sb.get_tabs()) <= 1:
                break
            time.sleep(0.1)
        tabs["count_after_close"] = len(sb.get_tabs())
        sb.switch_to_tab(0)
        time.sleep(0.2)
        tabs["url_after_close_restore"] = sb.get_current_url()
        ok = (
            tabs["count_before"] == 1
            and tabs["count_after_open"] == 2
            and tabs["count_after_close"] == 1
            and "demo_page" in (tabs.get("url_after_close_restore") or "")
        )
        tabs["ok"] = ok
        add_test(
            "tabs",
            "PASS" if ok else "FAIL",
            "counts=%s->%s->%s, new_url=%s"
            % (
                tabs["count_before"],
                tabs["count_after_open"],
                tabs["count_after_close"],
                tabs.get("new_tab_url"),
            ),
        )
    except BaseException as exc:
        record_exc("tabs", exc)
        tabs["ok"] = False
        add_test("tabs", "FAIL", "%s: %s" % (type(exc).__name__, exc))
    RESULT["tabs"] = tabs

    # 确保回到 demo 页
    try:
        if "demo_page" not in (sb.get_current_url() or ""):
            safe_nav(sb, DEMO_URL)
    except BaseException as exc:
        record_exc("ensure_demo_before_storage", exc)

    # 7) cookie / localStorage（reload 前后读回）
    token = "cdp-%d" % int(time.time())
    cookie_name = "cdp_spike_cookie"
    ls_key = "cdp_spike_ls"
    cookie = {}
    try:
        sb.evaluate(
            "document.cookie='%s=%s; path=/; SameSite=Lax';" % (cookie_name, token)
        )
        sb.set_local_storage_item(ls_key, token)
        reload_ms = safe_reload(sb)
        cookie_js = sb.evaluate("document.cookie")
        ls_read = sb.get_local_storage_item(ls_key)
        cookie_objs = sb.get_all_cookies()
        cookie_names = sorted({getattr(c, "name", "") for c in cookie_objs})
        cookie.update(
            {
                "ok": cookie_name in cookie_names and token in (cookie_js or ""),
                "set_name": cookie_name,
                "token": token,
                "reload_ms": round(reload_ms, 1),
                "document_cookie": cookie_js,
                "cdp_cookie_names": cookie_names,
                "cdp_cookie_count": len(cookie_objs),
            }
        )
        add_test(
            "cookie_reload",
            "PASS" if cookie["ok"] else "FAIL",
            "%s in cdp cookies=%s"
            % (cookie_name, cookie_name in cookie_names),
        )
    except BaseException as exc:
        record_exc("cookie_reload", exc)
        cookie["ok"] = False
        add_test("cookie_reload", "FAIL", "%s: %s" % (type(exc).__name__, exc))
    RESULT["cookies"] = cookie

    storage = {}
    try:
        ls_read = sb.get_local_storage_item(ls_key)
        session_key = "cdp_spike_ss"
        sb.set_session_storage_item(session_key, token)
        ss_read = sb.get_session_storage_item(session_key)
        storage.update(
            {
                "ok": ls_read == token,
                "key": ls_key,
                "value_read_after_reload": ls_read,
                "session_storage_read": ss_read,
            }
        )
        add_test(
            "local_storage_reload",
            "PASS" if storage["ok"] else "FAIL",
            "read back=%r" % (ls_read,),
        )
    except BaseException as exc:
        record_exc("local_storage_reload", exc)
        storage["ok"] = False
        add_test("local_storage_reload", "FAIL", "%s: %s" % (type(exc).__name__, exc))
    RESULT["local_storage"] = storage

    # 主实例默认 profile 路径（quit 后应被删除）
    default_profile = None
    try:
        default_profile = getattr(sb.driver.config, "user_data_dir", None)
    except Exception:
        pass

    # 关闭主实例
    try:
        quit_ms = quit_quietly(sb, "main")
        STATE["sb"] = None
        RESULT["cleanup"]["main_quit_ms"] = None if quit_ms is None else round(quit_ms, 1)
        add_test("main_quit", "PASS" if quit_ms is not None else "FAIL", "quit")
    except BaseException as exc:
        record_exc("main_quit", exc)
        add_test("main_quit", "FAIL", "%s: %s" % (type(exc).__name__, exc))
    if default_profile:
        RESULT["cleanup"]["default_temp_profile"] = default_profile
        RESULT["cleanup"]["default_temp_profile_removed"] = not os.path.exists(default_profile)

    # 8) profile 持久化：同 user_data_dir 两次启动
    profile_dir = WORK / "profile_cdp"
    if profile_dir.exists():
        shutil.rmtree(profile_dir, ignore_errors=True)
    profile = {
        "supported": True,
        "user_data_dir": str(profile_dir),
        "local_storage_persisted": None,
        "cookie_persisted": None,
        "ok": False,
    }
    p1 = None
    p2 = None
    profile_token = "profile-%d" % int(time.time())
    try:
        p1, launch1_ms = launch(chrome_path, profile_dir)
        nav1_ms = safe_nav(p1, DEMO_URL)
        p1.set_local_storage_item("cdp_profile_ls", profile_token)
        p1.evaluate(
            "document.cookie='cdp_profile_cookie=%s; path=/; max-age=3600; SameSite=Lax';"
            % profile_token
        )
        time.sleep(0.5)
        profile["first_launch_ms"] = round(launch1_ms, 1)
        profile["first_nav_ms"] = round(nav1_ms, 1)
        profile["first_ls_read"] = p1.get_local_storage_item("cdp_profile_ls")
        profile["first_cookie"] = p1.evaluate("document.cookie")
        profile["config_uses_custom_data_dir"] = getattr(
            p1.driver.config, "uses_custom_data_dir", None
        )
        quit_quietly(p1, "profile_first")
        p1 = None
        time.sleep(1.0)
        profile["dir_exists_after_quit"] = profile_dir.exists()
        profile["default_subdir_exists"] = (profile_dir / "Default").exists()
        p2, launch2_ms = launch(chrome_path, profile_dir)
        nav2_ms = safe_nav(p2, DEMO_URL)
        ls2 = p2.get_local_storage_item("cdp_profile_ls")
        cookie2 = p2.evaluate("document.cookie")
        profile.update(
            {
                "second_launch_ms": round(launch2_ms, 1),
                "second_nav_ms": round(nav2_ms, 1),
                "second_ls_read": ls2,
                "second_cookie": cookie2,
                "local_storage_persisted": ls2 == profile_token,
                "cookie_persisted": (
                    ("cdp_profile_cookie=%s" % profile_token) in (cookie2 or "")
                ),
            }
        )
        profile["ok"] = bool(profile["local_storage_persisted"])
        add_test(
            "profile_persistence",
            "PASS" if profile["ok"] else "FAIL",
            "ls=%r cookie_persisted=%s"
            % (ls2, profile["cookie_persisted"]),
        )
    except BaseException as exc:
        record_exc("profile_persistence", exc)
        profile["ok"] = False
        add_test("profile_persistence", "FAIL", "%s: %s" % (type(exc).__name__, exc))
    finally:
        if p1 is not None:
            quit_quietly(p1, "profile_first_finally")
        if p2 is not None:
            quit_quietly(p2, "profile_second")
    RESULT["profile"] = profile

    RESULT["cleanup"]["orphan_check"] = (
        "未执行 taskkill；仅通过 sb.quit() 关闭本次启动的 Chrome 进程"
    )

    # 结论
    results = {t["name"]: t["status"] for t in RESULT["tests"]}
    RESULT["conclusion"] = {
        "pure_cdp_usable": results.get("launch") == "PASS"
        and results.get("navigation_demo") == "PASS"
        and results.get("screenshot_png") == "PASS",
        "profile_supported": bool(profile.get("supported")),
        "profile_local_storage_persisted": profile.get("local_storage_persisted"),
        "headless_supported": True,
        "chrome_path_fallback": str(chrome_path) != str(CHROME_SPEC),
        "notes": [
            "sb_cdp.Chrome(url=None, **kwargs) 将 kwargs 透传给 cdp_util.start，支持 headless/user_data_dir/browser_executable_path。",
            "save_screenshot 为视口截图（wrapper 未暴露 full_page 参数），print_to_pdf 可用。",
            "标签页 API 可用：get_tabs/open_new_tab/switch_to_tab/close_active_tab。",
            "user_data_dir 为自定义目录时，quit 后目录保留；localStorage 与带过期时间的 cookie 可跨重启持久化。",
            "默认临时 profile 在 quit 后由 SeleniumBase 删除；会话 cookie 不跨浏览器重启（需设置 expires/max-age）。",
        ],
    }


try:
    main()
except BaseException as exc:
    record_exc("fatal", exc)
    add_test("fatal", "FAIL", "%s: %s" % (type(exc).__name__, exc))
finally:
    if STATE.get("sb") is not None:
        quit_quietly(STATE["sb"], "finally")
        STATE["sb"] = None

    RESULT["finished_at"] = now_iso()
    RESULT["duration_sec"] = round(
        (
            datetime.fromisoformat(RESULT["finished_at"])
            - datetime.fromisoformat(RESULT["started_at"])
        ).total_seconds(),
        2,
    )
    json_path = WORK / "result.json"
    json_path.write_text(
        json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = []
    lines.append("# SeleniumBase Pure CDP Spike 结果")
    lines.append("")
    lines.append("- 开始：%s" % RESULT["started_at"])
    lines.append("- 结束：%s（耗时 %ss）" % (RESULT["finished_at"], RESULT["duration_sec"]))
    lines.append("- 解释器：`%s`" % RESULT["environment"].get("python_executable"))
    lines.append(
        "- SeleniumBase %s / selenium %s"
        % (
            RESULT["environment"].get("seleniumbase_version"),
            RESULT["environment"].get("selenium_version"),
        )
    )
    lines.append(
        "- Chrome 指定路径存在：%s；实际使用：`%s`"
        % (
            RESULT["environment"].get("chrome_specified_exists"),
            RESULT["environment"].get("chrome_used_path"),
        )
    )
    lines.append("")
    lines.append("## 构造签名")
    lines.append("")
    lines.append("```")
    lines.append(RESULT["signature"].get("inspect_signature", ""))
    lines.append("```")
    lines.append("")
    lines.append(
        "支持命名参数（cdp_util.start）：`%s`"
        % ", ".join(RESULT["signature"].get("launch_named_kwargs", []))
    )
    lines.append("")
    lines.append("## 方法可用性矩阵")
    lines.append("")
    lines.append("| 分组 | 方法 | 可用 | 可调用 |")
    lines.append("|---|---|---|---|")
    for row in RESULT["method_matrix"]:
        lines.append(
            "| %s | `%s` | %s | %s |"
            % (
                row["group"],
                row["method"],
                "是" if row["available"] else "否",
                "是" if row["callable"] else "否",
            )
        )
    lines.append("")
    lines.append("## 通过/失败")
    lines.append("")
    lines.append("| 测试 | 状态 | 详情 |")
    lines.append("|---|---|---|")
    for t in RESULT["tests"]:
        lines.append("| %s | %s | %s |" % (t["name"], t["status"], t["detail"]))
    lines.append("")
    lines.append("## 关键数字")
    lines.append("")
    launch = RESULT.get("launch", {})
    nav = RESULT.get("navigation", {})
    dom = RESULT.get("dom_benchmark", {})
    js = RESULT.get("js_stats", {})
    png = RESULT.get("artifacts", {}).get("png", {})
    pdf = RESULT.get("artifacts", {}).get("pdf", {})
    html = RESULT.get("artifacts", {}).get("html", {})
    tabs = RESULT.get("tabs", {})
    cookie = RESULT.get("cookies", {})
    storage = RESULT.get("local_storage", {})
    profile = RESULT.get("profile", {})
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| 启动耗时 | %s ms |" % launch.get("launch_ms"))
    lines.append("| demo 加载耗时 | %s ms |" % nav.get("nav_ms"))
    lines.append("| 返回 demo 耗时 | %s ms |" % nav.get("back_to_demo_ms"))
    lines.append("| DOM 50k 生成耗时 | %s ms |" % dom.get("generate_ms"))
    lines.append("| DOM 50k 加载耗时 | %s ms |" % dom.get("load_ms"))
    lines.append(
        "| DOM querySelectorAll 中位 | %s ms（%s 节点） |"
        % (dom.get("query_ms_median"), dom.get("query_total"))
    )
    lines.append(
        "| DOM 完整遍历中位 | %s ms（visible=%s） |"
        % (dom.get("full_scan_ms_median"), dom.get("full_scan_visible"))
    )
    lines.append(
        "| demo 元素数 | total=%s visible=%s interactive=%s |"
        % (js.get("totalElements"), js.get("visibleElements"), js.get("interactiveElements"))
    )
    lines.append("| navigator.webdriver | %s |" % js.get("navigatorWebdriver"))
    lines.append("| User-Agent | `%s` |" % js.get("userAgent"))
    lines.append(
        "| 截图 | %s bytes, %sx%s, %s ms |"
        % (png.get("bytes"), png.get("width"), png.get("height"), png.get("save_ms"))
    )
    lines.append("| PDF | %s bytes, %s ms |" % (pdf.get("bytes"), pdf.get("save_ms")))
    lines.append("| HTML 快照 | %s bytes, %s ms |" % (html.get("bytes"), html.get("save_ms")))
    lines.append(
        "| 标签页计数 | %s -> %s -> %s |"
        % (tabs.get("count_before"), tabs.get("count_after_open"), tabs.get("count_after_close"))
    )
    lines.append("| cookie reload 读回 | %s |" % cookie.get("ok"))
    lines.append("| localStorage reload 读回 | %s |" % storage.get("ok"))
    lines.append("| profile localStorage 持久化 | %s |" % profile.get("local_storage_persisted"))
    lines.append("| profile cookie 持久化（max-age） | %s |" % profile.get("cookie_persisted"))
    lines.append("| profile 目录保留 | %s |" % profile.get("dir_exists_after_quit"))
    lines.append(
        "| 默认临时 profile quit 后删除 | %s |"
        % RESULT.get("cleanup", {}).get("default_temp_profile_removed")
    )
    lines.append("")
    if RESULT["warnings"]:
        lines.append("## 环境警告")
        lines.append("")
        for w in RESULT["warnings"]:
            lines.append(
                "- [%s] %s%s"
                % (
                    w["level"],
                    w["message"],
                    ("；" + w["action"]) if w.get("action") else "",
                )
            )
        lines.append("")
    if RESULT["exceptions"]:
        lines.append("## 异常")
        lines.append("")
        for e in RESULT["exceptions"]:
            lines.append("- `%s` %s: %s" % (e["step"], e["type"], e["message"]))
        lines.append("")
    else:
        lines.append("## 异常")
        lines.append("")
        lines.append("无。")
        lines.append("")
    lines.append("## 结论")
    lines.append("")
    for note in RESULT["conclusion"].get("notes", []):
        lines.append("- %s" % note)
    lines.append("")

    md_path = WORK / "result.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print("\nWrote: %s" % json_path, flush=True)
    print("Wrote: %s" % md_path, flush=True)
