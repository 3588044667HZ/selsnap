import json
import os
import time

from seleniumbase import Driver, sb_cdp

CHROME = r"E:\selenium-mcp\browsers\chrome-win64\chrome.exe"
OUT_DIR = r"E:\selenium-mcp\spikes\chrome156"
OUT_JSON = os.path.join(OUT_DIR, "verify156.json")

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

TURNSTILE_JS = """
(() => {
  const vis = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  return {
    title: document.title,
    success: vis(document.querySelector('#captcha-success')),
    failure: vis(document.querySelector('#captcha-failure')),
    iframes: Array.from(document.querySelectorAll('iframe')).map((f) => f.src).slice(0, 5),
    body: document.body ? document.body.innerText.slice(0, 600) : ''
  };
})()
"""


def verdict(body):
    idx = (body or "").find("Test Results")
    if idx < 0:
        return None
    return body[idx:idx + 80].replace("\n", " | ")


def probe_uc():
    out = {"mode": "uc-driver", "sites": {}, "errors": []}
    driver = None
    try:
        t0 = time.time()
        driver = Driver(uc=True, headless=True, binary_location=CHROME)
        out["launch_s"] = round(time.time() - t0, 2)
        out["browser_version"] = driver.capabilities.get("browserVersion")
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
                out["errors"].append(entry["error"])
            out["sites"][url] = entry
    except Exception as exc:
        out["errors"].append(f"launch: {type(exc).__name__}: {exc}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
    return out


def probe_turnstile():
    out = {"mode": "cdp-turnstile", "errors": []}
    browser = None
    try:
        browser = sb_cdp.Chrome(headless=True, browser_executable_path=CHROME)
        browser.goto("https://seleniumbase.io/apps/turnstile")
        deadline = time.time() + 15
        before = None
        while time.time() < deadline:
            before = browser.execute_script(TURNSTILE_JS) or {}
            if before.get("iframes") or before.get("success") or before.get("failure"):
                break
            time.sleep(1)
        out["before"] = before
        t0 = time.time()
        browser.solve_captcha()
        out["solve_s"] = round(time.time() - t0, 2)
        deadline = time.time() + 20
        after = None
        while time.time() < deadline:
            after = browser.execute_script(TURNSTILE_JS) or {}
            if after.get("success") or after.get("failure"):
                break
            time.sleep(1)
        out["after"] = after
        out["success"] = bool((after or {}).get("success"))
        out["failure"] = bool((after or {}).get("failure"))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["errors"].append(out["error"])
    finally:
        if browser is not None:
            try:
                browser.quit()
            except Exception:
                pass
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    data = {"uc": probe_uc(), "turnstile": probe_turnstile()}
    with open(OUT_JSON, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    uc = data["uc"]
    print("== uc", "launch", uc.get("launch_s"), "errors", len(uc["errors"]))
    for url, entry in uc["sites"].items():
        print(
            " ",
            url,
            {
                "ok": entry.get("ok"),
                "title": entry.get("title"),
                "wd": entry.get("webdriver"),
                "plugins": entry.get("plugins"),
                "passed": entry.get("passed"),
                "failed": entry.get("failed"),
                "verdict": verdict(entry.get("body")),
            },
        )
    for err in uc["errors"]:
        print("  ERR", err.splitlines()[0] if err else err)
    print("== turnstile", json.dumps(data["turnstile"], ensure_ascii=False)[:800])


if __name__ == "__main__":
    main()
