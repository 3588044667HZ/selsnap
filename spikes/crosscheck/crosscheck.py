import json
import os
import time

from seleniumbase import Driver, sb_cdp

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CHROME = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Bin\chrome.exe")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crosscheck.json")

JS = """
return {
  title: document.title,
  url: location.href,
  ua: navigator.userAgent,
  webdriver: navigator.webdriver,
  plugins: navigator.plugins.length,
  chrome_obj: !!window.chrome,
  ready: document.readyState,
  body_len: document.body ? document.body.innerText.length : -1,
  html_len: document.documentElement.outerHTML.length,
  passed: document.querySelectorAll('.passed').length,
  failed: document.querySelectorAll('.failed').length,
  body: document.body ? document.body.innerText.slice(0, 1500) : ''
};
"""

WAITS = {
    "https://bot.sannysoft.com/": 6,
    "https://browserscan.net/bot-detection": 8,
    "https://seleniumbase.io/demo_page": 1,
}


def probe_std(browser, label):
    result = {"label": label, "sites": {}, "errors": []}
    driver = None
    try:
        t0 = time.time()
        driver = Driver(browser=browser, headless=True)
        result["launch_s"] = round(time.time() - t0, 2)
        for url, wait in WAITS.items():
            entry = {}
            try:
                t1 = time.time()
                driver.get(url)
                time.sleep(wait)
                entry["load_s"] = round(time.time() - t1 - wait, 2)
                data = driver.execute_script(JS)
                if isinstance(data, dict):
                    entry.update(data)
                else:
                    entry["raw"] = str(data)[:500]
                entry["ok"] = True
            except Exception as exc:
                entry["ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
                result["errors"].append(entry["error"])
            result["sites"][url] = entry
    except Exception as exc:
        result["errors"].append(f"launch: {type(exc).__name__}: {exc}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:
                result["errors"].append(f"quit: {type(exc).__name__}: {exc}")
    return result


def probe_cdp(browser_path, label):
    result = {"label": label, "sites": {}, "errors": []}
    sb = None
    try:
        t0 = time.time()
        kwargs = {"headless": True}
        if browser_path:
            kwargs["browser_executable_path"] = browser_path
        sb = sb_cdp.Chrome(**kwargs)
        result["launch_s"] = round(time.time() - t0, 2)
        for url, wait in WAITS.items():
            entry = {}
            try:
                t1 = time.time()
                sb.goto(url)
                time.sleep(wait)
                entry["load_s"] = round(time.time() - t1 - wait, 2)
                data = sb.execute_script(JS)
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        pass
                if isinstance(data, dict):
                    entry.update(data)
                else:
                    entry["raw"] = str(data)[:500]
                entry["ok"] = True
            except Exception as exc:
                entry["ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
                result["errors"].append(entry["error"])
            result["sites"][url] = entry
    except Exception as exc:
        result["errors"].append(f"launch: {type(exc).__name__}: {exc}")
    finally:
        if sb is not None:
            try:
                sb.quit()
            except Exception as exc:
                result["errors"].append(f"quit: {type(exc).__name__}: {exc}")
    return result


def main():
    out = {"chrome": CHROME, "edge": EDGE, "runs": []}
    out["runs"].append(probe_std("chrome", "standard-chrome109"))
    out["runs"].append(probe_cdp(None, "cdp-chrome109"))
    out["runs"].append(probe_std("edge", "standard-edge156"))
    out["runs"].append(probe_cdp(EDGE, "cdp-edge156"))
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)
    for run in out["runs"]:
        print("==", run["label"], "launch", run.get("launch_s"), "errors", len(run["errors"]))
        for url, entry in run["sites"].items():
            keys = ("ok", "title", "webdriver", "plugins", "chrome_obj", "ready", "body_len", "passed", "failed")
            print(" ", url, {k: entry.get(k) for k in keys})
        for err in run["errors"]:
            print("  ERR", err)


if __name__ == "__main__":
    main()
