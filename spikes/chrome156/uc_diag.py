from seleniumbase import Driver, SB

CHROME = r"E:\selenium-mcp\browsers\chrome-win64\chrome.exe"


def show_caps(driver):
    caps = driver.capabilities
    print("  browserVersion:", caps.get("browserVersion"))
    chrome = caps.get("chrome") or {}
    print("  chromedriver:", chrome.get("chromedriverVersion"))


def try_sb(label, **kwargs):
    print("==", label)
    try:
        with SB(**kwargs) as sb:
            show_caps(sb.driver)
            sb.open("https://seleniumbase.io/demo_page")
            print("  url:", sb.get_current_url())
            print("  title:", sb.get_title())
            print("  webdriver:", sb.driver.execute_script("return navigator.webdriver"))
    except Exception as exc:
        print("  ERR:", type(exc).__name__, str(exc)[:300])


def try_driver(label, **kwargs):
    print("==", label)
    driver = None
    try:
        driver = Driver(**kwargs)
        show_caps(driver)
        driver.get("https://seleniumbase.io/demo_page")
        print("  url:", driver.current_url)
        print("  webdriver:", driver.execute_script("return navigator.webdriver"))
    except Exception as exc:
        print("  ERR:", type(exc).__name__, str(exc)[:300])
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


try_sb("SB uc headless", uc=True, headless=True, binary_location=CHROME)
try_driver("Driver uc headless", uc=True, headless=True, binary_location=CHROME)
try_sb("SB uc headed", uc=True, headless=False, binary_location=CHROME)
