import sys
import csv
from datetime import datetime, timedelta

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


def parse_senzey_date(date_str):
    """Parse 'dd/mm/yy HH:MM' into a datetime object for comparison."""
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%y %H:%M")
    except Exception:
        try:
            return datetime.strptime(date_str.strip()[:8], "%d/%m/%y")
        except Exception:
            return None


def scrape_all_deliveries(months_back=2):
    creds = read_credentials()
    results = []

    cutoff_date = datetime.now() - timedelta(days=months_back * 30)
    print(f"סריקה מ-{cutoff_date.strftime('%d/%m/%Y')} עד היום", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login
        page.goto("https://o8.senzey.com/login.php")
        page.fill("input[name='username']", creds["SENZEY_USERNAME"])
        page.fill("input[name='password']", creds["SENZEY_PASSWORD"])
        page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Set records per page to 100
        page.goto("https://o8.senzey.com/shipmentslist.php")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        try:
            page.select_option("select[name=recperpage]", "100")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
        except Exception:
            pass  # keep default 50 per page

        start = 0
        done = False

        while not done:
            url = f"https://o8.senzey.com/shipmentslist.php?start={start}"
            page.goto(url)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            rows = page.query_selector_all("table tr")
            page_count = 0

            for row in rows:
                cells = row.query_selector_all("td")
                texts = [c.inner_text().strip() for c in cells]
                # Filter junk (JS code, short strings)
                clean = [
                    t for t in texts
                    if t and len(t) > 1 and "var " not in t and "opts" not in t
                ]

                # Data rows: 6+ clean fields, first is "HE", third has a date
                if len(clean) >= 5 and clean[0] == "HE":
                    date_str = clean[2]
                    customer = clean[3]
                    raw_branch = clean[4]

                    # Clean branch: "94 שילב נתיבות - שילב נתיבות" → "שילב נתיבות"
                    if " - " in raw_branch:
                        branch = raw_branch.split(" - ", 1)[-1].strip()
                    else:
                        # Remove leading number: "94 שם חנות" → "שם חנות"
                        parts = raw_branch.split(" ", 1)
                        branch = parts[1].strip() if len(parts) > 1 and parts[0].isdigit() else raw_branch.strip()

                    # Check if this record is within our date range
                    record_date = parse_senzey_date(date_str)
                    if record_date and record_date < cutoff_date:
                        print(f"הגענו לתאריך {date_str} — עצירה", flush=True)
                        done = True
                        break

                    results.append({
                        "date": date_str,
                        "customer": customer,
                        "branch": branch
                    })
                    page_count += 1

            print(f"start={start}: {page_count} תעודות (סה\"כ: {len(results)})", flush=True)

            if page_count == 0:
                break  # No data on this page — finished

            start += 100  # Next page (100 records per page)

        browser.close()

    return results


def save_to_csv(results, filename="senzey_data.csv"):
    with open(filename, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "customer", "branch"])
        for r in results:
            writer.writerow([r["date"], r["customer"], r["branch"]])
    print(f"נשמר: {len(results)} תעודות → {filename}", flush=True)


if __name__ == "__main__":
    print("מתחיל סריקת תעודות משלוח...", flush=True)
    results = scrape_all_deliveries(months_back=2)
    save_to_csv(results)
    print(f"✅ סיום. {len(results)} תעודות נשמרו.", flush=True)
