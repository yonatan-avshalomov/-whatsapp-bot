import sys
import csv
import os
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright


def read_credentials():
    """Read credentials from credentials.env file OR environment variables."""
    creds = {}

    # First try environment variables (GitHub Actions / CI)
    for key in ["SENZEY_USERNAME", "SENZEY_PASSWORD"]:
        val = os.environ.get(key)
        if val:
            creds[key] = val

    if creds.get("SENZEY_USERNAME") and creds.get("SENZEY_PASSWORD"):
        return creds

    # Fallback: read from credentials.env file (local machine)
    for encoding in ["utf-8-sig", "utf-16", "utf-8"]:
        try:
            with open("credentials.env", encoding=encoding) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, val = line.split("=", 1)
                        key = key.replace(" ", "").replace("\x00", "")
                        val = val.replace(" ", "").replace("\x00", "")
                        creds[key] = val
            if creds.get("SENZEY_USERNAME"):
                break
        except Exception:
            continue
    return creds


def get_last_known_id(filename="senzey_data.csv"):
    """Returns the highest delivery ID already saved in the CSV."""
    try:
        with open(filename, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            ids = [int(row["id"]) for row in reader if row.get("id", "").isdigit()]
            return max(ids) if ids else 0
    except Exception:
        return 0


def scrape_new_deliveries(last_known_id=0):
    """Scrapes only deliveries with ID > last_known_id."""
    creds = read_credentials()
    new_records = []

    print(f"ID אחרון ידוע: {last_known_id}", flush=True)

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

        # Set 100 records per page
        page.goto("https://o8.senzey.com/shipmentslist.php")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        try:
            page.select_option("select[name=recperpage]", "100")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
        except Exception:
            pass

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
                clean = [
                    t for t in texts
                    if t and len(t) > 1 and "var " not in t and "opts" not in t
                ]

                if len(clean) >= 5 and clean[0] == "HE":
                    delivery_id = int(clean[1]) if clean[1].isdigit() else 0
                    date_str    = clean[2]
                    customer    = clean[3]
                    raw_branch  = clean[4]

                    # Stop — we've reached records we already have
                    if delivery_id <= last_known_id:
                        print(f"הגענו ל-ID {delivery_id} — עצירה", flush=True)
                        done = True
                        break

                    # Clean branch name: "94 שילב נתיבות - שילב נתיבות" → "שילב נתיבות"
                    if " - " in raw_branch:
                        branch = raw_branch.split(" - ", 1)[-1].strip()
                    else:
                        parts = raw_branch.split(" ", 1)
                        branch = parts[1].strip() if len(parts) > 1 and parts[0].isdigit() else raw_branch.strip()

                    new_records.append({
                        "id":       delivery_id,
                        "date":     date_str,
                        "customer": customer,
                        "branch":   branch
                    })
                    page_count += 1

            print(f"start={start}: {page_count} חדשות (סה\"כ חדשות: {len(new_records)})", flush=True)

            if page_count == 0:
                break

            start += 100

        browser.close()

    return new_records


def update_csv(new_records, filename="senzey_data.csv"):
    """Prepends new records to the existing CSV."""
    # Read existing records
    existing = []
    try:
        with open(filename, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            existing = list(reader)
    except Exception:
        pass

    # Write: new records first, then existing
    with open(filename, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "date", "customer", "branch"])
        writer.writeheader()
        for r in new_records:
            writer.writerow(r)
        for r in existing:
            # Keep existing rows (add id=0 if missing for old format)
            writer.writerow({
                "id":       r.get("id", "0"),
                "date":     r.get("date", ""),
                "customer": r.get("customer", ""),
                "branch":   r.get("branch", r.get("store", ""))
            })

    print(f"✅ נוספו {len(new_records)} תעודות חדשות. סה\"כ בקובץ: {len(existing) + len(new_records)}", flush=True)


def full_scrape(months_back=2, filename="senzey_data.csv"):
    """First-time full scrape (runs once to build the CSV from scratch)."""
    from datetime import datetime, timedelta

    creds = read_credentials()
    results = []
    cutoff = datetime.now() - timedelta(days=months_back * 30)

    print(f"סריקה ראשונית מלאה מ-{cutoff.strftime('%d/%m/%Y')}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("https://o8.senzey.com/login.php")
        page.fill("input[name='username']", creds["SENZEY_USERNAME"])
        page.fill("input[name='password']", creds["SENZEY_PASSWORD"])
        page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        page.goto("https://o8.senzey.com/shipmentslist.php")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        try:
            page.select_option("select[name=recperpage]", "100")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
        except Exception:
            pass

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
                clean = [
                    t for t in texts
                    if t and len(t) > 1 and "var " not in t and "opts" not in t
                ]

                if len(clean) >= 5 and clean[0] == "HE":
                    delivery_id = int(clean[1]) if clean[1].isdigit() else 0
                    date_str    = clean[2]
                    customer    = clean[3]
                    raw_branch  = clean[4]

                    try:
                        record_dt = datetime.strptime(date_str.strip(), "%d/%m/%y %H:%M")
                        if record_dt < cutoff:
                            done = True
                            break
                    except Exception:
                        pass

                    if " - " in raw_branch:
                        branch = raw_branch.split(" - ", 1)[-1].strip()
                    else:
                        parts = raw_branch.split(" ", 1)
                        branch = parts[1].strip() if len(parts) > 1 and parts[0].isdigit() else raw_branch.strip()

                    results.append({"id": delivery_id, "date": date_str, "customer": customer, "branch": branch})
                    page_count += 1

            print(f"start={start}: {page_count} תעודות (סה\"כ: {len(results)})", flush=True)
            if page_count == 0:
                break
            start += 100

        browser.close()

    with open(filename, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "date", "customer", "branch"])
        writer.writeheader()
        writer.writerows(results)

    print(f"✅ סריקה ראשונית הושלמה: {len(results)} תעודות", flush=True)


def push_to_supabase(records: list[dict]) -> None:
    """דוחף רשומות חדשות ל-Supabase senzey_deliveries (best-effort)."""
    if not records:
        return
    try:
        import os
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_ANON_KEY", "")
        if not url or not key:
            print("⚠️ SUPABASE_URL/SUPABASE_ANON_KEY לא מוגדרים — דילוג על Supabase push", flush=True)
            return
        client = create_client(url, key)
        batch_size = 100
        ok = 0
        for i in range(0, len(records), batch_size):
            batch = []
            for r in records[i:i+batch_size]:
                rid = r.get("id")
                try:
                    rid = int(rid)
                except (ValueError, TypeError):
                    continue
                batch.append({
                    "id":       rid,
                    "date":     r.get("date", ""),
                    "customer": r.get("customer", ""),
                    "branch":   r.get("branch", ""),
                })
            if batch:
                try:
                    client.table("senzey_deliveries").upsert(
                        batch, on_conflict="id"
                    ).execute()
                    ok += len(batch)
                except Exception as e:
                    print(f"⚠️ Supabase batch error: {e}", flush=True)
        print(f"✅ Supabase: {ok}/{len(records)} תעודות עודכנו", flush=True)
    except Exception as e:
        print(f"⚠️ Supabase push failed: {e}", flush=True)


if __name__ == "__main__":
    import sys
    filename = "senzey_data.csv"

    if "--full" in sys.argv:
        # First time: scrape everything
        full_scrape(months_back=2, filename=filename)
        # Push all records to Supabase
        with open(filename, encoding="utf-8-sig") as f:
            all_records = list(csv.DictReader(f))
        push_to_supabase(all_records)
    else:
        # Daily: only new records
        last_id = get_last_known_id(filename)
        if last_id == 0:
            print("אין CSV קיים — מריץ סריקה ראשונית...", flush=True)
            full_scrape(months_back=2, filename=filename)
            with open(filename, encoding="utf-8-sig") as f:
                all_records = list(csv.DictReader(f))
            push_to_supabase(all_records)
        else:
            new_records = scrape_new_deliveries(last_known_id=last_id)
            if new_records:
                update_csv(new_records, filename)
                push_to_supabase(new_records)
            else:
                print("✅ אין תעודות חדשות מאז הסריקה האחרונה.", flush=True)
