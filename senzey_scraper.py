import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

def read_credentials():
    creds = {}
    for encoding in ["utf-8-sig", "utf-16", "utf-8"]:
        try:
            with open("credentials.env", encoding=encoding) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, val = line.split("=", 1)
                        creds[key.strip()] = val.strip()
            break
        except Exception:
            continue
    return creds


def get_deliveries():
    creds = read_credentials()
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # login
        page.goto("https://o8.senzey.com/login.php")
        page.fill("input[name='username']", creds["SENZEY_USERNAME"])
        page.fill("input[name='password']", creds["SENZEY_PASSWORD"])
        page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")

        # go to shipments
        page.goto("https://o8.senzey.com/shipmentslist.php")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # get all table rows
        rows = page.query_selector_all("table tr")
        current = {}

        for row in rows:
            cells = row.query_selector_all("td")
            texts = [c.inner_text().strip() for c in cells]
            texts = [t for t in texts if t and len(t) > 1 and "var " not in t and "opts" not in t]

            if len(texts) >= 3:
                # check if row has a date pattern
                has_date = any("/" in t and len(t) <= 14 for t in texts)
                if has_date:
                    date = next((t for t in texts if "/" in t and len(t) <= 14), "")
                    store = next((t for t in texts if len(t) > 10 and "/" not in t), "")
                    results.append({
                        "date": date,
                        "store": store,
                        "raw": " | ".join(texts[:6])
                    })

        browser.close()

    return results


def get_deliveries_summary():
    deliveries = get_deliveries()
    if not deliveries:
        return "לא נמצאו תעודות משלוח"

    summary = f"תעודות משלוח אחרונות ({len(deliveries)} תעודות):\n\n"
    for d in deliveries[:20]:
        summary += f"• {d['date']} — {d['store'][:40]}\n"

    return summary


if __name__ == "__main__":
    print(get_deliveries_summary())
