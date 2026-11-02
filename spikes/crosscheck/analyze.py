import json
import os

BASE = r"E:\selenium-mcp\spikes\crosscheck"

for name in ("crosscheck.json", "crosscheck2.json"):
    path = os.path.join(BASE, name)
    print("####", name)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for run in data["runs"]:
        print("==", run["label"])
        for site, entry in run["sites"].items():
            if "raw" in entry:
                print("  RAW", site, repr(entry["raw"])[:300])
        entry = run["sites"].get("https://browserscan.net/bot-detection", {})
        body = entry.get("body") or ""
        counts = {w: body.count(w) for w in ["Normal", "Robot", "WebDriver", "Headless", "CDP"]}
        print("  browserscan counts:", counts)
        lines = [
            line.strip()
            for line in body.splitlines()
            if any(word in line for word in ["Normal", "Robot", "WebDriver", "Headless"])
        ]
        for line in lines[:12]:
            print("   |", line[:160])
