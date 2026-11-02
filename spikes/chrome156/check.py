import json
import os
import time
import traceback

from seleniumbase import Driver, SB, sb_cdp

CHROME = r"E:\selenium-mcp\browsers\chrome-win64\chrome.exe"
OUT_DIR = r"E:\selenium-mcp\spikes\chrome156"
OUT_JSON = os.path.join(OUT_DIR, "result.json")

JS_BODY = """
return (() => {
  return {
    title: document.title,
    url: location.href,
    ua: navigator.userAgent,
    webdriver: navigator.webdriver,
    plugins: navigator.plugins.length,
    chrome_obj: !!window.chrome,
    ready: document.readyState,
    body_len: document.body ? document.body.innerText.length : -1,
    passed: document.querySelectorAll('.passed').length,
    failed: document.querySelectorAll('.failed').length,
    body: document.body ? document.body.innerText.slice(0, 4000) : ''
  };
})()
"""

JS_EXPR = JS_BODY.replace("return (() =>", "(() =>", 1).rstrip()


def browserscan_verdict(body):
    idx = body.find("Test Results")
    if idx < 0:
        return None
    return body[idx:idx + 80].replace("\n", " | ")


def wait_cdp_ready(sb, seconds=25):
    last = None
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            last = sb.execute_script(JS_EXPR)
        except Exception:
            time.sleep(1.5)
            continue
        if isinstance(last, dict) and (last.get("body_len") or 0) > 500:
            if last.get("ready") in ("interactive", "complete"):
                return last
        time.sleep(1.5)
    return last


def probe_standard():
    run = {"mode": "standard", "sites": {}, "errors": []}
    driver = None
    try:
        t0 = time.time()
        driver = Driver(binary_location=CHROME, headless=True)
        run["launch_s"] = round(time.time() - t0, 2)
        run["browser_version"] = driver.capabilities.get("browserVersion")
        for url, wait in [
            ("https://bot.sannysoft.com/", 6),
            ("https://browserscan.net/bot-detection", 8),
            ("https://seleniumbase.io/demo_page", 1),
        ]:
            entry = {}
            try:
                t1 = time.time()
                driver.get(url)
                time.sleep(wait)
                entry["load_s"] = round(time.time() - t1 - wait, 2)
                entry.update(driver.execute_script(JS_BODY))
                entry["ok"] = True
            except Exception as exc:
                entry["ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
                run["errors"].append(entry["error"])
            run["sites"][url] = entry
    except Exception as exc:
        run["errors"].append(f"launch: {type(exc).__name__}: {exc}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:
                run["errors"].append(f"quit: {type(exc).__name__}: {exc}")
    return run


def probe_uc():
    run = {"mode": "uc", "sites": {}, "errors": []}
    try:
        t0 = time.time()
        with SB(uc=True, headless=True, binary_location=CHROME) as sb:
            run["launch_s"] = round(time.time() - t0, 2)
            for url, wait in [
                ("https://bot.sannysoft.com/", 6),
                ("https://browserscan.net/bot-detection", 8),
                ("https://seleniumbase.io/demo_page", 1),
            ]:
                entry = {}
                try:
                    t1 = time.time()
                    sb.open(url)
                    time.sleep(wait)
                    entry["load_s"] = round(time.time() - t1 - wait, 2)
                    entry.update(sb.driver.execute_script(JS_BODY))
                    entry["ok"] = True
                except Exception as exc:
                    entry["ok"] = False
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    run["errors"].append(entry["error"])
                run["sites"][url] = entry
            try:
                run["browser_version"] = sb.driver.capabilities.get("browserVersion")
            except Exception:
                pass
    except Exception as exc:
        run["errors"].append(f"launch: {type(exc).__name__}: {exc}")
    return run


def probe_cdp():
    run = {"mode": "cdp", "sites": {}, "errors": []}
    browser = None
    try:
        t0 = time.time()
        browser = sb_cdp.Chrome(headless=True, browser_executable_path=CHROME)
        run["launch_s"] = round(time.time() - t0, 2)
        for url, wait in [
            ("https://bot.sannysoft.com/", 6),
            ("https://browserscan.net/bot-detection", 8),
            ("https://seleniumbase.io/demo_page", 1),
        ]:
            entry = {}
            try:
                t1 = time.time()
                browser.goto(url)
                time.sleep(wait)
                data = wait_cdp_ready(browser)
                entry["load_s"] = round(time.time() - t1 - wait, 2)
                if isinstance(data, dict):
                    entry.update(data)
                else:
                    entry["raw"] = str(data)[:300]
                entry["ok"] = True
            except Exception as exc:
                entry["ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
                run["errors"].append(entry["error"])
            run["sites"][url] = entry
        try:
            run["ua"] = browser.execute_script(JS_EXPR).get("ua")
        except Exception:
            pass
        turnstile = {}
        try:
            browser.goto("https://seleniumbase.io/apps/turnstile")
            time.sleep(3)
            info = wait_cdp_ready(browser, 10) or {}
            turnstile["title"] = info.get("title")
            turnstile["attempted"] = False
            if hasattr(browser, "solve_captcha"):
                t2 = time.time()
                turnstile["attempted"] = True
                browser.solve_captcha()
                turnstile["solve_s"] = round(time.time() - t2, 2)
                time.sleep(2)
                after = browser.execute_script(JS_EXPR) or {}
                body = after.get("body") or ""
                turnstile["success_marker"] = any(
                    key in body for key in ("Success", "success", "verified", "Verification")
                )
                turnstile["body_snippet"] = body[:600]
            else:
                turnstile["skipped"] = "no solve_captcha"
        except Exception as exc:
            turnstile["error"] = f"{type(exc).__name__}: {exc}"
            run["errors"].append(turnstile["error"])
        run["turnstile"] = turnstile
    except Exception as exc:
        run["errors"].append(f"launch: {type(exc).__name__}: {exc}")
    finally:
        if browser is not None:
            try:
                browser.quit()
            except Exception as exc:
                run["errors"].append(f"quit: {type(exc).__name__}: {exc}")
            except BaseException:
                pass
    return run


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    data = {"chrome": CHROME, "runs": []}
    for fn in (probe_standard, probe_uc, probe_cdp):
        try:
            data["runs"].append(fn())
        except Exception:
            data["runs"].append({"mode": fn.__name__, "errors": [traceback.format_exc()]})
    with open(OUT_JSON, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    for run in data["runs"]:
        print("==", run.get("mode"), "launch", run.get("launch_s"), "errors", len(run.get("errors", [])))
        for url, entry in run.get("sites", {}).items():
            verdict = browserscan_verdict(entry.get("body") or "")
            print(
                " ",
                url,
                {
                    "ok": entry.get("ok"),
                    "title": entry.get("title"),
                    "wd": entry.get("webdriver"),
                    "plugins": entry.get("plugins"),
                    "ready": entry.get("ready"),
                    "body_len": entry.get("body_len"),
                    "passed": entry.get("passed"),
                    "failed": entry.get("failed"),
                    "verdict": verdict,
                },
            )
        if "turnstile" in run:
            print("  turnstile", run["turnstile"])
        for err in run.get("errors", []):
            print("  ERR", err.splitlines()[0] if err else err)


if __name__ == "__main__":
    main()
