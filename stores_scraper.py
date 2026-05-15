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

NIZAT_REGIONS = [
    "תל אביב והמרכז", "השרון", "ירושלים והסביבה", "חיפה והכרמל",
    "הגליל התחתון", "הגליל העליון והגולן", "מישור החוף הצפוני",
    "מישור החוף הדרומי", "הנגב ואילת", "השפלה", "השומרון",
]


def normalize(name: str) -> str:
    fixes = {
        "ניצתץ":       "ניצת",
        "ניצתהדובדבן": "ניצת הדובדבן",
        "הדבדובן":     "הדובדבן",
        "הדובדבהן":    "הדובדבן",
        "הדודבן":      "הדובדבן",
        "הדודבדבן":    "הדובדבן",
    }
    for wrong, right in fixes.items():
        name = name.replace(wrong, right)
    return re.sub(r"\s{2,}", " ", name).strip()


def strip_region(text: str) -> str:
    """מסיר שם אזור שנדבק לשם הסניף."""
    for region in NIZAT_REGIONS:
        text = text.replace(region, "").strip()
    return text.strip()


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

                # הסר אזור שנדבק לשם הסניף (למשל "עפולהחיפה והכרמל" → "עפולה")
                branch_name = strip_region(branch_name)
                region      = strip_region(region)

                city = extract_city_from_address(address) or branch_name.split(" - ")[0]
                city = strip_region(city)

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
# פורמט: (עיר, כתובת, שם_ייחודי)  ← שם_ייחודי משמש כ"שילב {שם_ייחודי}"
#          אם שם_ייחודי ריק → "שילב {עיר}"  (לסניפים בודדים בעיר)
SHILAV_KNOWN = [
    # ──────────────── עיר יחידה (שם_ייחודי ריק) ────────────────
    ("בית שאן",        "צים אורבן, העמל 100",              ""),
    ("ראש העין",       "מרכז שפיר, יגאל אלון 22",         ""),
    ("רהט",            "מתחם סבן",                         ""),
    ("עפולה",          "מתחם רכבת צפון, יצחק רבין 53",    ""),
    ("לוד",            "אירפורט סיטי, כינרת 1",            ""),
    ("אילת",           "ביג אילת, הסטת 20",                ""),
    ("גן שמואל",       "מרכז מסחרי",                       ""),
    ("גדרה",           "ביג גדרה",                         ""),
    ("גבעתיים",        "קניון גבעתיים, רבין 53",           ""),
    ("רמת השרון",      "ביג גלילות",                       ""),
    ("הרצליה",         "קניון סבן סטארס, סבן סטארס 8",    ""),
    ("חולון",          "קניון חולון, גולדה מאיר 7",        ""),
    ("ראשון לציון",    "קניון הזהב, דוד סחרוב 21",        ""),
    ("קרית גת",        "ביג כרמי גת, לכיש 153",            ""),
    ("כרמיאל",         "MY Center, מעלה כמון 9",           ""),
    ("נס ציונה",       "קניותר, האירוסים 53",              ""),
    ("קרית אתא",       "שער הצפון (IKEA)",                 ""),
    ("קרית ביאליק",    "קריון, דרך עכו-חיפה 192",         ""),
    ("קרית שמונה",     "ביג קרית שמונה",                   ""),
    ("קרית אונו",      "קניון קרית אונו, שלמה המלך 37",   ""),
    ("מעלות",          "מרכז צים, שלמה שרירא 3",           ""),
    ("מבשרת ציון",     "קניון מבשרת, החצובים 10",         ""),
    ("מודיעין",        "עזריאלי מודיעין, ערער 17",         ""),
    ("נצרת",           "מרכז דודג'",                       ""),
    ("נתיבות",         "המלאכה 203",                       ""),
    ("אור עקיבא",      "ביג אור עקיבא, הנשיא ויצמן",      ""),
    ("רמת ישי",        "האקליפטוס 3",                      ""),
    ("רמלה",           "עזריאלי רמלה, דוד רזיאל 1",       ""),
    ("רחובות",         "קניון רחובות",                     ""),
    ("מגדל העמק",      "קניון מגדל העמק",                  ""),
    ("בני ברק",        "בית שילב, הירקון 4",               ""),
    ("דיר אל אסד",     "מתחם דבאח",                        ""),
    ("יהוד",           "ביג יהוד, אלטלף 4",                ""),
    ("בת ים",          "קניון בת ים, יוסף טל 92",          ""),
    ("בית שמש",        "ביג פאשן, יגאל אלון 3",            ""),
    ("חדרה",           "בי\"ח הלל יפה, שלום 10",           ""),
    # ──────────────── ריבוי סניפים — שם_ייחודי מפורש ────────────────
    # באר יעקב
    ("באר יעקב",       "קניון באר יעקב, שנס 17",          "באר יעקב קניון"),
    ("באר יעקב",       "בי\"ח אסף הרופא",                  "באר יעקב אסף הרופא"),
    # אשדוד
    ("אשדוד",          "בי\"ח אסותא, הרפואה 7",            "אשדוד אסותא"),
    ("אשדוד",          "ביג פאשן, דרך הרכבת 1",            "אשדוד ביג"),
    # פתח תקווה
    ("פתח תקווה",      "קניון אבנת, ז'בוטינסקי 72",        "פתח תקווה אבנת"),
    ("פתח תקווה",      "בי\"ח בילינסון, ז'בוטינסקי 39",    "פתח תקווה בילינסון"),
    ("פתח תקווה",      "גלובל פתח תקווה",                  "פתח תקווה גלובל"),
    # כפר סבא
    ("כפר סבא",        "קניון ערים, ויצמן 83",             "כפר סבא קניון ערים"),
    ("כפר סבא",        "קניון G, ויצמן 207",               "כפר סבא קניון G"),
    ("כפר סבא",        "בי\"ח מאיר, טשרניחובסקי 59",       "כפר סבא מאיר"),
    # חיפה
    ("חיפה",           "עזריאלי, משה פלימן 4",             "חיפה עזריאלי"),
    ("חיפה",           "גרנד קניון, שמחה גולן 54",         "חיפה גרנד קניון"),
    ("חיפה",           "בי\"ח רמב\"ם, העלייה 8",            "חיפה רמב\"ם"),
    ("חיפה",           "חוצות המפרץ, החרושת 9000",         "חיפה חוצות המפרץ"),
    # אשקלון
    ("אשקלון",         "בי\"ח ברזילי, ההסתדרות 2",         "אשקלון ברזילי"),
    ("אשקלון",         "גלובוס סנטר",                      "אשקלון גלובוס"),
    # באר שבע
    ("באר שבע",        "ביג באר שבע, דרך חברון 21",        "באר שבע ביג"),
    ("באר שבע",        "גרנד קניון, טוביהו דוד 125",       "באר שבע גרנד קניון"),
    ("באר שבע",        "קרית הממשלה, תקווה 4",             "באר שבע קרית הממשלה"),
    # ירושלים
    ("ירושלים",        "בי\"ח הדסה עין כרם",               "ירושלים הדסה"),
    ("ירושלים",        "קניון מלחה",                       "ירושלים מלחה"),
    ("ירושלים",        "קניון גבעת שאול",                  "ירושלים גבעת שאול"),
    # נהריה
    ("נהריה",          "ביג רגבה",                         "נהריה ביג"),
    ("נהריה",          "בי\"ח ממשלתי",                     "נהריה בי\"ח"),
    # נתניה — 3 סניפים
    ("נתניה",          "קניון עיר ימים, בני ברמן 2",       "נתניה עיר ימים"),
    ("נתניה",          "פולג, גיבור ישראל 5",              "נתניה פולג"),
    # תל אביב
    ("תל אביב",        "עזריאלי, דרך בגין 132",            "תל אביב עזריאלי"),
    ("תל אביב",        "דיזנגוף סנטר, דיזנגוף 50",         "תל אביב דיזנגוף"),
    ("תל אביב",        "גן העיר, בן גוריון 71",            "תל אביב גן העיר"),
    ("תל אביב",        "קניון רמת אביב, אינשטיין 40",      "תל אביב רמת אביב"),
    ("תל אביב",        "בי\"ח איכילוב, ויצמן 14",          "תל אביב איכילוב"),
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
        for tup in SHILAV_KNOWN:
            city, address = tup[0], tup[1]
            branch_label  = tup[2] if len(tup) > 2 else ""
            display_name  = f"שילב {branch_label}" if branch_label else f"שילב {city}"
            key = (city, address)
            if key not in seen:
                seen.add(key)
                stores.append({
                    "chain": "שילב", "name": display_name,
                    "city":  city, "address": address, "phone": "",
                })

    print(f"  ✅ {len(stores)} סניפים", flush=True)
    return stores


# ── מכבי פארם — רשימה ידועה מהאינטרנט (גיבוי) ──────────────────────────────
MACCABI_KNOWN = [
    # תל אביב
    ("מכבי פארם תל אביב בלפור",       "תל אביב"),
    ("מכבי פארם תל אביב השלום",        "תל אביב"),
    ("מכבי פארם תל אביב השלה",         "תל אביב"),
    ("מכבי פארם תל אביב יגאל אלון",    "תל אביב"),
    ("מכבי פארם תל אביב רמת אביב",     "תל אביב"),
    # גוש דן
    ("מכבי פארם בת ים",                "בת ים"),
    ("מכבי פארם בת ים קצנלסון",        "בת ים"),
    ("מכבי פארם חולון",                "חולון"),
    ("מכבי פארם גבעתיים",              "גבעתיים"),
    ("מכבי פארם רמת גן",               "רמת גן"),
    ("מכבי פארם בני ברק עקיבא",        "בני ברק"),
    ("מכבי פארם בני ברק קהנמן",        "בני ברק"),
    ("מכבי פארם קרית אונו",            "קרית אונו"),
    ("מכבי פארם פסגת אונו",            "קרית אונו"),
    ("מכבי פארם אור יהודה",            "אור יהודה"),
    ("מכבי פארם אלעד",                 "אלעד"),
    ("מכבי פארם גני תקווה",            "גני תקווה"),
    # פתח תקווה
    ("מכבי פארם פתח תקווה שפיגל",      "פתח תקווה"),
    ("מכבי פארם פתח תקווה דרך בגין",   "פתח תקווה"),
    # שרון
    ("מכבי פארם הרצליה",               "הרצליה"),
    ("מכבי פארם רמת השרון",            "רמת השרון"),
    ("מכבי פארם הוד השרון הבנים",      "הוד השרון"),
    ("מכבי פארם הוד השרון סוקולוב",    "הוד השרון"),
    ("מכבי פארם רעננה אחוזה",          "רעננה"),
    ("מכבי פארם כפר סבא הירוקה",       "כפר סבא"),
    ("מכבי פארם כפר סבא רוטשילד",      "כפר סבא"),
    ("מכבי פארם ראש העין הציונות",     "ראש העין"),
    ("מכבי פארם ראש העין פסגות אפק",   "ראש העין"),
    # נתניה
    ("מכבי פארם נתניה מרכז",           "נתניה"),
    ("מכבי פארם נתניה דרום",           "נתניה"),
    ("מכבי פארם נתניה לניאדו",         "נתניה"),
    # צפון
    ("מכבי פארם חיפה חורב",            "חיפה"),
    ("מכבי פארם חיפה שלום עליכם",      "חיפה"),
    ("מכבי פארם חיפה ילגה",            "חיפה"),
    ("מכבי פארם קריית מוצקין גושן",    "קרית מוצקין"),
    ("מכבי פארם קריית מוצקין יונתן",   "קרית מוצקין"),
    ("מכבי פארם חדרה",                 "חדרה"),
    ("מכבי פארם זכרון יעקב",           "זכרון יעקב"),
    ("מכבי פארם נהריה",                "נהריה"),
    ("מכבי פארם כרמיאל",               "כרמיאל"),
    ("מכבי פארם עכו",                  "עכו"),
    ("מכבי פארם נצרת נוף הגליל",       "נוף הגליל"),
    ("מכבי פארם אום אל פחם",           "אום אל פחם"),
    ("מכבי פארם עפולה",                 "עפולה"),
    ("מכבי פארם יקנעם",                "יקנעם"),
    ("מכבי קריית טבעון",               "קרית טבעון"),
    ("מכבי פארם טבריה",                "טבריה"),
    ("מכבי פארם בית שאן",              "בית שאן"),
    ("מכבי פארם מגדל העמק",            "מגדל העמק"),
    ("מכבי פארם קרית שמונה",           "קרית שמונה"),
    ("מכבי פארם צפת",                  "צפת"),
    ("מכבי פארם נשר",                  "נשר"),
    # מרכז
    ("מכבי פארם ראשון לציון מזרח",     "ראשון לציון"),
    ("מכבי פארם ראשון לציון מערב",     "ראשון לציון"),
    ("מכבי פארם ראשון לציון נחלת",     "ראשון לציון"),
    ("מכבי פארם רחובות",               "רחובות"),
    ("מכבי פארם נס ציונה",             "נס ציונה"),
    ("מכבי פארם לוד",                  "לוד"),
    ("מכבי פארם רמלה",                 "רמלה"),
    ("מכבי פארם יבנה גיבורי החיל",     "יבנה"),
    ("מכבי פארם קדימה",                "קדימה"),
    # ירושלים
    ("מכבי פארם ירושלים אגריפס",       "ירושלים"),
    ("מכבי פארם ירושלים רמות",         "ירושלים"),
    ("מכבי פארם ירושלים ארנונה",       "ירושלים"),
    ("מכבי פארם ירושלים גבעת מרדכי",   "ירושלים"),
    ("מכבי פארם ירושלים ק.יובל",       "ירושלים"),
    ("מכבי פארם בית שמש",              "בית שמש"),
    ("מכבי פארם מודיעין",              "מודיעין"),
    ("מכבי פארם מודיעין עילית",        "מודיעין עילית"),
    ("מכבי פארם מבשרת ציון",           "מבשרת ציון"),
    ("מכבי פארם אריאל",                "אריאל"),
    # דרום
    ("מכבי פארם אשדוד רובע ד",            "אשדוד"),
    ("מכבי פארם אשדוד סי מול",            "אשדוד"),
    ("מכבי פארם אשקלון ברנע",             "אשקלון"),
    ("מכבי פארם אשקלון עזריאלי",          "אשקלון"),
    ("מכבי פארם קרית גת",                 "קרית גת"),
    ("מכבי פארם נתיבות",                  "נתיבות"),
    ("מכבי פארם אופקים",                  "אופקים"),
    # באר שבע — 2 סניפים
    ("מכבי פארם באר שבע מרכז",            "באר שבע"),
    ("מכבי פארם באר שבע קרית הממשלה",    "באר שבע"),
    # נגב
    ("מכבי פארם ערד",                     "ערד"),
    ("מכבי פארם דימונה",                  "דימונה"),
    ("מכבי פארם אילת",                    "אילת"),
]

# ── מכבי פארם — מתוך קובץ הסנזי ────────────────────────────────────────────

def extract_maccabi_from_senzey(filename="senzey_data.csv") -> list[dict]:
    """שולף סניפי מכבי ייחודיים מתוך תעודות המשלוח — אלה הלקוחות האמיתיים."""
    print("💊 שולף סניפי מכבי פארם מסנזי ...", flush=True)

    def clean(branch: str) -> str:
        import re
        branch = re.sub(r'הזמנה[\s\-:]*[\d]+', '', branch)
        branch = re.sub(r'מספר הזמנה[\s:]*[\d]+', '', branch)
        branch = re.sub(r'[\d]{5,}', '', branch)
        branch = re.sub(r'[\s\-:]+$', '', branch).strip()   # נקה קצוות לפני התבניות
        branch = re.sub(r'מכבי שירותי בריאות', 'מכבי פארם', branch)
        # "עיר - מכבי פארם - עיר" → "מכבי פארם עיר"
        branch = re.sub(r'^.+?\s*-\s*(מכבי)', r'\1', branch)
        branch = re.sub(r'(מכבי פארם)\s*-\s*', r'\1 ', branch)
        # "ראש העין הציונות מכבי פארם" → "מכבי פארם ראש העין הציונות"
        branch = re.sub(r'^(.+?)\s+(מכבי פארם)$', r'\2 \1', branch)
        branch = re.sub(r'^(.+?)\s+(מכבי\b)(?!\s*פארם)', r'מכבי פארם \1', branch)
        branch = re.sub(r'\s{2,}', ' ', branch).strip()
        return branch

    try:
        with open(filename, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        print("  ⚠️  לא נמצא senzey_data.csv", flush=True)
        return []

    seen, stores = set(), []
    for r in rows:
        b = r.get("branch", "")
        if "מכבי" not in b:
            continue
        clean_name = clean(b)
        if not clean_name or clean_name in seen:
            continue
        seen.add(clean_name)
        city = extract_city_from_address(clean_name)
        stores.append({
            "chain":   "מכבי פארם",
            "name":    clean_name,
            "city":    city,
            "address": "",
            "phone":   "",
        })

    def maccabi_key(name: str) -> str:
        """מפתח נירמול: מסיר 'מכבי', 'פארם' ומשווה רק את שם המקום."""
        import re
        k = re.sub(r'מכבי|פארם', '', name)
        k = re.sub(r'\s+', ' ', k).strip()
        return k

    # הוסף סניפים ידועים שלא מופיעים בסנזי (ללא כפילויות)
    seen_keys = {maccabi_key(s) for s in seen}
    for name, city in MACCABI_KNOWN:
        key = maccabi_key(name)
        if key not in seen_keys:
            seen_keys.add(key)
            seen.add(name)
            stores.append({
                "chain":   "מכבי פארם",
                "name":    name,
                "city":    city,
                "address": "",
                "phone":   "",
            })

    print(f"  ✅ {len(stores)} סניפים", flush=True)
    return stores


# ── Google Sheets (חנויות פרטיות בלבד) ──────────────────────────────────────

CHAIN_PREFIXES = ("ניצת הדובדבן", "שילב", "מכבי")   # these come from other sources

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
    nizat    = scrape_nizat()
    shilav   = scrape_shilav()
    maccabi  = extract_maccabi_from_senzey()
    sheets   = scrape_google_sheets()

    all_stores = nizat + shilav + maccabi + sheets

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
