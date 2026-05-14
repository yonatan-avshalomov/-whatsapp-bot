"""
stores_scraper.py
=================
מושך רשימת סניפים עדכנית מהאתרים הרשמיים:
  • ניצת הדובדבן  →  nizat.com/snifim.aspx
  • שילב           →  shilav.co.il/branches
  • מכבי פארם + חנויות פרטיות → Google Sheets (לא כל 600 סניפי מכבי, רק מה שהוזן ידנית)

מריץ: python stores_scraper.py
פלט:  stores.csv  (נשמר ב-repo, האפליקציה קוראת ממנו)
"""

import csv
import io
import re
import sys
import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_FILE = "stores.csv"

GOOGLE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQFvzEaqPb8mnyMwNo40WRFkBMYAnsnGWsnkLmfRZaW0saA92t3moVb9heglVartTfX0MQKOEXHRBF2"
    "/pub?output=csv"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; store-scraper/1.0)"}


# ── עזרים ────────────────────────────────────────────────────────────────────

def normalize(name: str) -> str:
    fixes = {
        "ניצתץ": "ניצת",
        "ניצתהדובדבן": "ניצת הדובדבן",
        "הדבדובן": "הדובדבן",
        "הדובדבהן": "הדובדבן",
        "הדודבן": "הדובדבן",
    }
    for wrong, right in fixes.items():
        name = name.replace(wrong, right)
    return re.sub(r"\s{2,}", " ", name).strip()


# ── ניצת הדובדבן ─────────────────────────────────────────────────────────────

REGION_TO_CITY = {
    "תל אביב והמרכז": "",   # keep city as branch name hint
    "השרון": "",
    "ירושלים והסביבה": "ירושלים",
    "חיפה והכרמל": "חיפה",
    "הגליל התחתון": "",
    "הגליל העליון והגולן": "",
    "מישור החוף הצפוני": "",
    "מישור החוף הדרומי": "",
    "הנגב ואילת": "",
    "השפלה": "",
    "השומרון": "",
}

def scrape_nizat() -> list[dict]:
    print("🌸 שולף סניפי ניצת הדובדבן ...", flush=True)
    try:
        r = requests.get("https://www.nizat.com/snifim.aspx", headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        stores = []
        # The page has a table with columns: branch name | region | address | phone
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                tds = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(tds) < 3:
                    continue
                branch_name = tds[0].strip()
                region      = tds[1].strip() if len(tds) > 1 else ""
                address     = tds[2].strip() if len(tds) > 2 else ""

                if not branch_name or branch_name in ("שם הסניף", "סניף"):
                    continue

                # Try to extract city from address (last token often city)
                city = extract_city_from_address(address) or branch_name.split(" - ")[0]

                stores.append({
                    "chain":   "ניצת הדובדבן",
                    "name":    f"ניצת הדובדבן {branch_name}",
                    "city":    city,
                    "address": address,
                    "phone":   tds[3].strip() if len(tds) > 3 else "",
                })

        print(f"  ✅ {len(stores)} סניפים", flush=True)
        return stores
    except Exception as e:
        print(f"  ❌ שגיאה: {e}", flush=True)
        return []


def extract_city_from_address(address: str) -> str:
    """Tries to identify the city from an address string."""
    cities = [
        "תל אביב","ירושלים","חיפה","באר שבע","ראשון לציון","פתח תקווה",
        "נתניה","אשדוד","אשקלון","בני ברק","חולון","רמת גן","גבעתיים",
        "הרצליה","כפר סבא","רעננה","הוד השרון","רמת השרון","נס ציונה",
        "רחובות","ראש העין","מודיעין","בית שמש","אילת","אופקים","דימונה",
        "קרית גת","קרית שמונה","קרית ביאליק","קרית אתא","קרית מוצקין","קרית טבעון","קרית ים",
        "חדרה","זיכרון יעקב","בנימינה","פרדס חנה","קדימה","כרכור","אור עקיבא",
        "טבריה","עפולה","נהריה","כרמיאל","נצרת","שפרעם","מעלות","ראש פינה",
        "יהוד","שוהם","גדרה","גן שמואל","קסטינה","נתיבות","ערד",
        "ביתר","אפרת","מבשרת ציון","גוש עציון","בית שאן","יוקנעם",
        "אריאל","רהט","דאלית אל כרמל","לוד","רמלה","יבנה","ת\"א",
        "בת ים","מגדל העמק","מעלה אדומים","כפר ויתקין","טל מונד","רמת ישי",
        "אבן יהודה","תל מונד","הוד השרון",
    ]
    for city in cities:
        if city in address:
            return city
    return ""


# ── שילב ─────────────────────────────────────────────────────────────────────

# רשימה מאומתת של סניפי שילב (נשלפה ידנית מהאתר — גיבוי כשה-JS לא נטען)
SHILAV_KNOWN = [
    ("בית שאן",        "צים אורבן, העמל 100"),
    ("ראש העין",       "מרכז שפיר, יגאל אלון 22"),
    ("באר יעקב",       "קניון באר יעקב, שנס 17"),
    ("רהט",            "מתחם סבן"),
    ("עפולה",          "מתחם רכבת צפון, יצחק רבין 53"),
    ("לוד",            "אירפורט סיטי, כינרת 1"),
    ("כפר סבא",        "קניון ערים, ויצמן 83"),
    ("באר יעקב",       "בי\"ח אסף הרופא"),
    ("אשדוד",          "בי\"ח אסותא, הרפואה 7"),
    ("פתח תקווה",      "קניון אבנת, ז'בוטינסקי 72"),
    ("חיפה",           "עזריאלי, משה פלימן 4"),
    ("תל אביב",        "עזריאלי, דרך בגין 132"),
    ("אשקלון",         "בי\"ח ברזילי, ההסתדרות 2"),
    ("בת ים",          "קניון בת ים, יוסף טל 92"),
    ("פתח תקווה",      "בי\"ח בילינסון, ז'בוטינסקי 39"),
    ("באר שבע",        "ביג באר שבע, דרך חברון 21"),
    ("אשדוד",          "ביג פאשן, דרך הרכבת 1"),
    ("בית שמש",        "ביג פאשן, יגאל אלון 3"),
    ("נהריה",          "ביג רגבה"),
    ("יהוד",           "ביג יהוד, אלטלף 4"),
    ("בני ברק",        "בית שילב, הירקון 4"),
    ("דיר אל אסד",     "מתחם דבאח"),
    ("תל אביב",        "דיזנגוף סנטר, דיזנגוף 50"),
    ("אילת",           "ביג אילת, הסטת 20"),
    ("תל אביב",        "גן העיר, בן גוריון 71"),
    ("גן שמואל",       "מרכז מסחרי"),
    ("גדרה",           "ביג גדרה"),
    ("גבעתיים",        "קניון גבעתיים, רבין 53"),
    ("רמת השרון",      "ביג גלילות"),
    ("פתח תקווה",      "גלובל פתח תקווה"),
    ("אשקלון",         "גלובוס סנטר"),
    ("כפר סבא",        "קניון G, ויצמן 207"),
    ("חיפה",           "גרנד קניון, שמחה גולן 54"),
    ("באר שבע",        "גרנד קניון, טוביהו דוד 125"),
    ("ירושלים",        "בי\"ח הדסה עין כרם"),
    ("הרצליה",         "קניון סבן סטארס, סבן סטארס 8"),
    ("חדרה",           "בי\"ח הלל יפה, שלום 10"),
    ("חולון",          "קניון חולון, גולדה מאיר 7"),
    ("חיפה",           "בי\"ח רמב\"ם, העלייה 8"),
    ("נתניה",          "קניון עיר ימים, בני ברמן 2"),
    ("ראשון לציון",    "קניון הזהב, דוד סחרוב 21"),
    ("קרית גת",        "ביג כרמי גת, לכיש 153"),
    ("כרמיאל",         "MY Center, מעלה כמון 9"),
    ("נס ציונה",       "קניותר, האירוסים 53"),
    ("קרית אתא",       "שער הצפון (IKEA)"),
    ("קרית ביאליק",    "קריון, דרך עכו-חיפה 192"),
    ("באר שבע",        "קרית הממשלה, תקווה 4"),
    ("קרית שמונה",     "ביג קרית שמונה"),
    ("קרית אונו",      "קניון קרית אונו, שלמה המלך 37"),
    ("מעלות",          "מרכז צים, שלמה שרירא 3"),
    ("ירושלים",        "קניון מלחה"),
    ("כפר סבא",        "בי\"ח מאיר, טשרניחובסקי 59"),
    ("מבשרת ציון",     "קניון מבשרת, החצובים 10"),
    ("מודיעין",        "עזריאלי מודיעין, ערער 17"),
    ("נהריה",          "בי\"ח ממשלתי"),
    ("נצרת",           "מרכז דודג'"),
    ("נתיבות",         "המלאכה 203"),
    ("אור עקיבא",      "ביג אור עקיבא, הנשיא ויצמן"),
    ("נתניה",          "פולג, גיבור ישראל 5"),
    ("תל אביב",        "קניון רמת אביב, אינשטיין 40"),
    ("רמת ישי",        "האקליפטוס 3"),
    ("רמלה",           "עזריאלי רמלה, דוד רזיאל 1"),
    ("רחובות",         "קניון רחובות"),
    ("ירושלים",        "קניון גבעת שאול"),
    ("נתניה",          "קניון עזריאלי נתניה"),
    ("תל אביב",        "בי\"ח איכילוב, ויצמן 14"),
    ("חיפה",           "חוצות המפרץ, החרושת 9000"),
    ("מגדל העמק",      "קניון מגדל העמק"),
]


def scrape_shilav() -> list[dict]:
    print("👶 שולף סניפי שילב ...", flush=True)
    stores = []
    seen = set()

    # ── ניסיון 1: requests + BS4 (עובד אם דף server-rendered) ─────────────
    try:
        r = requests.get("https://www.shilav.co.il/branches", headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        for item in soup.select(".branch-item, .store-item, [class*='branch'], [class*='store']"):
            city_el    = item.select_one("[class*='city'], [class*='name'], h3, h4, strong")
            address_el = item.select_one("[class*='address'], p, span")
            if not city_el:
                continue
            city    = city_el.get_text(strip=True)
            address = address_el.get_text(strip=True) if address_el else ""
            key = (city, address)
            if key in seen or not city:
                continue
            seen.add(key)
            stores.append({
                "chain": "שילב", "name": f"שילב {city}",
                "city":  extract_city_from_address(city + " " + address) or city,
                "address": address, "phone": "",
            })
    except Exception:
        pass

    # ── ניסיון 2: Playwright (JS render) ────────────────────────────────────
    if not stores:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto("https://www.shilav.co.il/branches", wait_until="networkidle")
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
            soup = BeautifulSoup(html, "html.parser")
            for item in soup.select("[class*='branch'], [class*='store'], li, .location"):
                city_el    = item.select_one("h3, h4, strong, [class*='name'], [class*='city']")
                address_el = item.select_one("p, span, [class*='address']")
                if not city_el:
                    continue
                city    = city_el.get_text(strip=True)
                address = address_el.get_text(strip=True) if address_el else ""
                key = (city, address)
                if key in seen or not city or len(city) < 2:
                    continue
                seen.add(key)
                stores.append({
                    "chain": "שילב", "name": f"שילב {city}",
                    "city":  extract_city_from_address(city + " " + address) or city,
                    "address": address, "phone": "",
                })
        except Exception:
            pass

    # ── גיבוי: רשימה קשיחה מאומתת ──────────────────────────────────────────
    if len(stores) < 20:
        print("  ⚠️  שימוש ברשימה קשיחה (האתר לא נטען כראוי)", flush=True)
        for city, address in SHILAV_KNOWN:
            key = (city, address)
            if key not in seen:
                seen.add(key)
                stores.append({
                    "chain": "שילב", "name": f"שילב {city}",
                    "city":  city, "address": address, "phone": "",
                })

    print(f"  ✅ {len(stores)} סניפים", flush=True)
    return stores


# ── Google Sheets (מכבי + חנויות פרטיות) ────────────────────────────────────

CHAIN_PREFIXES = ("ניצת הדובדבן", "שילב")   # these come from web, skip from Sheets

def scrape_google_sheets() -> list[dict]:
    print("📊 קורא מ-Google Sheets (מכבי + פרטיות) ...", flush=True)
    try:
        r = requests.get(GOOGLE_SHEET_URL, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        stores = []
        seen = set()
        for row in csv.reader(io.StringIO(r.text)):
            if len(row) < 5 or not row[4].strip():
                continue
            name = normalize(row[4].strip())
            city = row[6].strip() if len(row) > 6 else ""
            addr = row[5].strip() if len(row) > 5 else ""

            # Skip chains we already scrape from their websites
            if any(name.startswith(p) for p in CHAIN_PREFIXES):
                continue

            key = (name, city)
            if key in seen:
                continue
            seen.add(key)

            # Determine chain
            chain = "מכבי פארם" if "מכבי" in name else "פרטי"

            stores.append({
                "chain":   chain,
                "name":    name,
                "city":    city,
                "address": addr,
                "phone":   "",
            })
        print(f"  ✅ {len(stores)} חנויות (ללא ניצת/שילב)", flush=True)
        return stores
    except Exception as e:
        print(f"  ❌ שגיאה: {e}", flush=True)
        return []


# ── ראשי ─────────────────────────────────────────────────────────────────────

def main():
    nizat  = scrape_nizat()
    shilav = scrape_shilav()
    sheets = scrape_google_sheets()

    all_stores = nizat + shilav + sheets

    # Write
    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["chain", "name", "city", "address", "phone"])
        writer.writeheader()
        writer.writerows(all_stores)

    # Summary
    chains = {}
    for s in all_stores:
        chains[s["chain"]] = chains.get(s["chain"], 0) + 1

    print(f"\n✅ נשמר {OUTPUT_FILE}  —  סה\"כ {len(all_stores)} חנויות:")
    for chain, count in sorted(chains.items(), key=lambda x: -x[1]):
        print(f"   {chain}: {count}")


if __name__ == "__main__":
    main()
