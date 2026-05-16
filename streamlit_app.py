import streamlit as st
import requests
import csv
import io
import os
import json
import re
import math
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from visit_tracker import get_all_visit_stats, urgency_label, urgency_color_hex, get_overdue_stores, get_never_visited
from route_planner import optimize_route, build_gmaps_url, build_waze_url, build_qr_code, total_distance, filter_stores
from database import db as supabase_db
from kml_exporter import build_kml, build_kml_filename

# שעון ישראל — Render רץ על UTC
ISRAEL_TZ = timezone(timedelta(hours=3))

def now_il():
    """datetime נוכחי בשעון ישראל."""
    return datetime.now(ISRAEL_TZ)

def today_il():
    """תאריך היום בפורמט DD/MM/YY לפי שעון ישראל."""
    return now_il().strftime("%d/%m/%y")

load_dotenv()

# ── מפתחות ───────────────────────────────────────────────
try:
    ANTHROPIC_API_KEY    = st.secrets["ANTHROPIC_API_KEY"]
    GOOGLE_SHEET_ID      = st.secrets["GOOGLE_SHEET_ID"]
    GITHUB_TOKEN         = st.secrets.get("GITHUB_TOKEN", "")
    GOOGLE_MAPS_API_KEY  = st.secrets.get("GOOGLE_MAPS_API_KEY", "")
    SUPABASE_URL         = st.secrets.get("SUPABASE_URL", "")
    SUPABASE_ANON_KEY    = st.secrets.get("SUPABASE_ANON_KEY", "")
except Exception:
    ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
    GOOGLE_SHEET_ID      = os.getenv("GOOGLE_SHEET_ID", "")
    GITHUB_TOKEN         = os.getenv("GITHUB_TOKEN", "")
    GOOGLE_MAPS_API_KEY  = os.getenv("GOOGLE_MAPS_API_KEY", "")
    SUPABASE_URL         = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY", "")

# העבר credentials ל-Supabase client
if SUPABASE_URL:
    os.environ["SUPABASE_URL"]      = SUPABASE_URL
    os.environ["SUPABASE_ANON_KEY"] = SUPABASE_ANON_KEY

GITHUB_REPO  = "yonatan-avshalomov/-whatsapp-bot"
NOTES_FILE   = "store_notes.csv"
VISITS_FILE  = "manual_visits.csv"

# ── הגדרות עמוד ──────────────────────────────────────────
st.set_page_config(
    page_title="ניהול חנויות",
    page_icon="🏪",
    layout="centered"
)

st.markdown("""
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="ניהול חנויות">
    <meta name="theme-color" content="#1f77b4">
    <style>
        body, .stApp { direction: rtl; }
        .stChatMessage { direction: rtl; text-align: right; }
        h1, h2, h3 { text-align: center; }
        .stTextInput input, .stTextArea textarea, .stSelectbox select {
            direction: rtl; text-align: right;
        }
        .stButton button { width: 100%; }
        .note-card {
            background: #f0f2f6; border-radius: 10px;
            padding: 10px; margin: 5px 0; direction: rtl;
        }
    </style>
""", unsafe_allow_html=True)

# ── בסיס בית: הוד השרון ──────────────────────────────────
HOME_CITY = "הוד השרון"
HOME_COORDS = (32.150, 34.893)   # lat, lon

# קואורדינטות ערים בישראל
CITY_COORDS = {
    "הוד השרון":      (32.150, 34.893),
    "רעננה":          (32.184, 34.871),
    "כפר סבא":        (32.175, 34.906),
    "ראש העין":       (32.096, 34.958),
    "פתח תקווה":      (32.084, 34.887),
    "תל אביב":        (32.087, 34.780),
    "ת\"א":           (32.087, 34.780),
    "רמת גן":         (32.082, 34.814),
    "גבעתיים":        (32.071, 34.812),
    "בני ברק":        (32.084, 34.834),
    "חולון":          (32.011, 34.779),
    "בת ים":          (32.019, 34.751),
    "ראשון לציון":    (31.964, 34.806),
    "נס ציונה":       (31.929, 34.795),
    "רחובות":         (31.896, 34.811),
    "יבנה":           (31.877, 34.744),
    "רמלה":           (31.929, 34.872),
    "לוד":            (31.952, 34.898),
    "נתניה":          (32.329, 34.857),
    "הרצליה":         (32.165, 34.843),
    "רמת השרון":      (32.146, 34.840),
    "אור יהודה":      (32.028, 34.856),
    "יהוד":           (32.030, 34.888),
    "קרית אונו":      (32.059, 34.861),
    "גני תקווה":      (32.057, 34.877),
    "אלעד":           (32.053, 34.951),
    "מודיעין":        (31.893, 35.010),
    "מבשרת ציון":     (31.805, 35.152),
    "ירושלים":        (31.768, 35.214),
    "בית שמש":        (31.745, 34.988),
    "אשדוד":          (31.804, 34.649),
    "אשקלון":         (31.668, 34.572),
    "גדרה":           (31.812, 34.779),
    "קסטינה":         (31.757, 34.726),
    "ריינה":          (32.726, 35.295),
    "חיפה":           (32.794, 34.989),
    "קרית אתא":       (32.813, 35.107),
    "קרית ביאליק":    (32.831, 35.079),
    "קרית מוצקין":    (32.836, 35.074),
    "קרית טבעון":     (32.723, 35.132),
    "עפולה":          (32.607, 35.289),
    "נצרת":           (32.701, 35.303),
    "נוף הגליל":      (32.701, 35.303),
    "יוקנעם":         (32.660, 35.100),
    "מגדל העמק":      (32.676, 35.239),
    "בית שאן":        (32.498, 35.499),
    "טבריה":          (32.795, 35.531),
    "נהריה":          (33.007, 35.098),
    "כרמיאל":         (32.916, 35.298),
    "עכו":            (32.926, 35.082),
    "נצרת עילית":     (32.701, 35.303),
    "מעלות":          (33.015, 35.271),
    "קרית שמונה":     (33.207, 35.571),
    "צפת":            (32.963, 35.496),
    "חדרה":           (32.434, 34.918),
    "זכרון יעקב":     (32.573, 34.952),
    "בנימינה":        (32.524, 34.948),
    "פרדס חנה":       (32.474, 34.969),
    "קדימה":          (32.271, 34.914),
    "אור עקיבא":      (32.508, 34.920),
    "כרכור":          (32.484, 34.978),
    "באר שבע":        (31.244, 34.791),
    "נתיבות":         (31.424, 34.591),
    "אופקים":         (31.314, 34.622),
    "קרית גת":        (31.606, 34.770),
    "ערד":            (31.258, 35.215),
    "דימונה":         (31.066, 35.033),
    "אילת":           (29.558, 34.952),
    "אריאל":          (32.103, 35.171),
    "אום אל פחם":     (32.524, 35.152),
    "שפרעם":          (32.806, 35.171),
    "רהט":            (31.392, 34.754),
    "אבן יהודה":      (32.261, 34.891),
    "טל מונד":        (32.262, 34.921),
    "תל מונד":        (32.262, 34.921),
    "נשר":            (32.773, 35.042),
    "גבעת שמואל":     (32.079, 34.846),
    "שוהם":           (31.990, 34.943),
    "מודיעין עילית":  (31.930, 35.043),
    "ביתר עילית":     (31.697, 35.119),
    "אפרת":           (31.658, 35.166),
    "גוש עציון":      (31.630, 35.115),
    "מעלה אדומים":    (31.777, 35.302),
    "כפר ויתקין":     (32.375, 34.905),
    "גן שמואל":       (32.465, 34.959),
    "נתיבות":         (31.424, 34.591),
    "רמת ישי":        (32.708, 35.168),
    "קרית ים":        (32.854, 35.073),
}


def haversine(lat1, lon1, lat2, lon2) -> float:
    """מרחק בק\"מ בין שתי נקודות GPS."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def city_distance_from_home(city: str) -> float:
    """מרחק בק\"מ מהוד השרון לעיר נתונה. 999 אם לא ידוע."""
    for key, coords in CITY_COORDS.items():
        if key in city or city in key:
            return haversine(HOME_COORDS[0], HOME_COORDS[1], coords[0], coords[1])
    return 999.0


def store_distance_from_home(store: dict) -> float:
    """מרחק מדויק לפי GPS של החנות, או לפי עיר אם אין."""
    try:
        lat = float(store.get("lat", "") or "")
        lon = float(store.get("lon", "") or "")
        return haversine(HOME_COORDS[0], HOME_COORDS[1], lat, lon)
    except (ValueError, TypeError):
        return city_distance_from_home(store.get("city", ""))


def sort_stores_by_distance(stores: list) -> list:
    """ממיין חנויות מהקרובה לרחוקה מהוד השרון לפי GPS מדויק."""
    return sorted(stores, key=lambda s: store_distance_from_home(s))


def is_route_question(msg: str) -> bool:
    """זיהוי שאלות על מסלול / סדר ביקורים."""
    keywords = ["מסלול", "סדר", "מה לבקר", "איפה לנסוע", "לאן לנסוע",
                "לאן כדאי", "תכנן", "יציאה", "נסיעה", "מה קרוב",
                "מה יש ב", "חנויות ב", "כמה יש ב"]
    return any(k in msg for k in keywords)


# ── נרמול שמות ───────────────────────────────────────────
def normalize_store_name(name):
    fixes = {
        "ניצתץ":       "ניצת",
        "ניצתהדובדבן": "ניצת הדובדבן",
        "הדבדובן":     "הדובדבן",
        "הדובדבהן":    "הדובדבן",
        "הדודבן":      "הדובדבן",
        "הדודבדבן":    "הדובדבן",
    }
    for wrong, correct in fixes.items():
        name = name.replace(wrong, correct)
    # הסר אזורים שנדבקו לשם
    for region in ["תל אביב והמרכז","השרון","ירושלים והסביבה","חיפה והכרמל",
                   "הגליל התחתון","הגליל העליון והגולן","מישור החוף הצפוני",
                   "מישור החוף הדרומי","הנגב ואילת","השפלה","השומרון"]:
        name = name.replace(region, "").strip()
    return re.sub(r"\s{2,}", " ", name).strip()

# ── טעינת נתונים ─────────────────────────────────────────
@st.cache_data(ttl=60)
def get_stores():
    """
    קורא חנויות מ-stores.csv (מסקריפר האתרים) — מקיף יותר.
    אם לא זמין, נופל חזרה ל-Google Sheets.
    """
    stores, seen = [], set()

    # ── ראשון: stores.csv מהרפו (ניצת + שילב + מכבי + פרטי) ──────────────
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/stores.csv"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            text = r.content.decode("utf-8-sig")
            for row in csv.DictReader(io.StringIO(text)):
                name = normalize_store_name(row.get("name", "").strip())
                city = row.get("city", "").strip()
                if not name:
                    continue
                key = (name, city)
                if key not in seen:
                    seen.add(key)
                    stores.append({
                        "name":    name,
                        "city":    city,
                        "address": row.get("address", "").strip(),
                        "chain":   row.get("chain", "").strip(),
                        "phone":   row.get("phone", "").strip(),
                        "lat":     row.get("lat", "").strip(),
                        "lon":     row.get("lon", "").strip(),
                    })
            if stores:
                return stores
    except Exception:
        pass

    # ── גיבוי: Google Sheets ────────────────────────────────────────────────
    try:
        url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQFvzEaqPb8mnyMwNo40WRFkBMYAnsnGWsnkLmfRZaW0saA92t3moVb9heglVartTfX0MQKOEXHRBF2/pub?output=csv"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "utf-8"
        for row in csv.reader(io.StringIO(r.text)):
            if len(row) >= 5 and row[4].strip():
                name = normalize_store_name(row[4].strip())
                city = row[6].strip() if len(row) > 6 else ""
                key  = (name, city)
                if key not in seen:
                    seen.add(key)
                    stores.append({"name": name, "city": city,
                                   "address": row[5].strip() if len(row) > 5 else "",
                                   "chain": "", "phone": ""})
    except Exception:
        pass

    return stores


@st.cache_data(ttl=120)
def get_deliveries():
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/senzey_data.csv"
        r = requests.get(url, timeout=10)
        text = r.content.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        return rows
    except:
        return []


@st.cache_data(ttl=30)
def get_notes():
    """קורא הערות מ-Supabase (מהיר) עם fallback ל-GitHub."""
    try:
        rows = supabase_db.get_notes(limit=300)
        if rows:
            return rows
    except Exception:
        pass
    # GitHub fallback
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/store_notes.csv"
        r = requests.get(url, timeout=10)
        return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    except Exception:
        return []


@st.cache_data(ttl=30)
def get_manual_visits():
    """קורא ביקורים מ-Supabase (מהיר) עם fallback ל-GitHub."""
    try:
        rows = supabase_db.get_visits(limit=500)
        if rows:
            return rows
    except Exception:
        pass
    # GitHub fallback
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/manual_visits.csv"
        r = requests.get(url, timeout=10)
        return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    except Exception:
        return []


def save_note_to_github(date, store, city, note):
    """שומר הערה — Supabase ראשון, GitHub כגיבוי."""
    # ── Supabase (מהיר) ──
    ok = supabase_db.add_note(date, store, city, note)
    if ok:
        return True
    # ── GitHub fallback ──
    if not GITHUB_TOKEN:
        return False
    try:
        import base64
        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{NOTES_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(api, headers=headers)
        data = r.json()
        current = base64.b64decode(data["content"]).decode("utf-8-sig") if "content" in data else ""
        sha = data.get("sha", "")
        new_line = f'\n{date},{store},{city},"{note}"'
        updated = current.rstrip() + new_line + "\n"
        payload = {"message": f"הערה: {store}",
                   "content": base64.b64encode(updated.encode("utf-8")).decode(), "sha": sha}
        r = requests.put(api, headers=headers, json=payload)
        return r.status_code in [200, 201]
    except Exception:
        return False


def save_visit_to_github(date, store, city, status, notes=""):
    """שומר ביקור — Supabase ראשון, GitHub כגיבוי."""
    # ── Supabase (מהיר) ──
    ok = supabase_db.add_visit(date, store, city, status, notes)
    if ok:
        return True
    # ── GitHub fallback ──
    if not GITHUB_TOKEN:
        return False
    try:
        import base64
        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{VISITS_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(api, headers=headers)
        data = r.json()
        current = base64.b64decode(data["content"]).decode("utf-8-sig") if "content" in data else ""
        sha = data.get("sha", "")
        new_line = f'\n{date},{store},{city},{status},{notes}'
        updated = current.rstrip() + new_line + "\n"
        payload = {"message": f"ביקור: {store}",
                   "content": base64.b64encode(updated.encode("utf-8")).decode(), "sha": sha}
        r = requests.put(api, headers=headers, json=payload)
        return r.status_code in [200, 201]
    except Exception:
        return False


# ── Rule A: בדיקת כפילויות (fuzzy matching) ──────────────
def find_duplicate_stores(name: str, city: str, address: str,
                           existing: list[dict],
                           name_thresh: int = 85,
                           addr_thresh: int = 80) -> list[dict]:
    """
    מחזיר רשימת חנויות קיימות שעלולות להיות כפילות של החנות החדשה.
    משתמש ב-difflib לדמיון שמות וכתובות.

    Parameters
    ----------
    name_thresh : int  סף דמיון שמות (0-100), ברירת מחדל 85
    addr_thresh : int  סף דמיון כתובות (0-100), ברירת מחדל 80
    """
    from difflib import SequenceMatcher

    def sim(a: str, b: str) -> int:
        """אחוז דמיון בין שתי מחרוזות."""
        if not a or not b:
            return 0
        return int(SequenceMatcher(None, a.strip(), b.strip()).ratio() * 100)

    suspects = []
    name_norm    = name.strip()
    city_norm    = city.strip()
    address_norm = address.strip()

    for s in existing:
        s_name = s.get("name", "").strip()
        s_city = s.get("city", "").strip()
        s_addr = s.get("address", "").strip()

        name_score = sim(name_norm, s_name)
        addr_score = sim(address_norm, s_addr)

        # כפילות חזקה: שם דומה + אותה עיר
        if name_score >= name_thresh and s_city == city_norm:
            suspects.append({**s, "_match_reason": f"שם דומה {name_score}%", "_score": name_score})
            continue

        # כפילות חזקה: כתובת זהה + אותה עיר
        if addr_score >= addr_thresh and s_city == city_norm and address_norm:
            suspects.append({**s, "_match_reason": f"כתובת דומה {addr_score}%", "_score": addr_score})

    return suspects


# ── Rule B: שמירת חנות חדשה ל-GitHub עם Auto-Geocode ─────
def save_store_to_github(name: str, city: str, address: str,
                          chain: str, phone: str) -> tuple[bool, dict | None]:
    """
    שומר חנות חדשה ל-stores.csv ב-GitHub.
    מגאוקד אוטומטית לפי Google Maps לפני השמירה.

    Returns
    -------
    (success: bool, geocode_result: dict | None)
    """
    import base64
    from geocoder import geocode as geo_geocode

    if not GITHUB_TOKEN:
        return False, None

    # ── Rule B: Geocode אוטומטי ──
    geo = None
    if address:
        # הגדר GOOGLE_MAPS_API_KEY כ-env var כדי שהמודול יראה אותו
        os.environ["GOOGLE_MAPS_API_KEY"] = GOOGLE_MAPS_API_KEY
        geo = geo_geocode(address, city)

    lat = str(geo["lat"])   if geo else ""
    lon = str(geo["lon"])   if geo else ""

    # ── קרא CSV קיים מ-GitHub ──
    api     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/stores.csv"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}

    try:
        r    = requests.get(api, headers=headers)
        data = r.json()
        sha  = data.get("sha", "")
        current_csv = base64.b64decode(data["content"]).decode("utf-8-sig") if "content" in data else ""
    except Exception:
        return False, None

    # ── הוסף שורה חדשה ──
    new_row = f'{name},{city},{address},{chain},{phone},{lat},{lon}\n'
    updated = current_csv.rstrip() + "\n" + new_row

    payload = {
        "message": f"הוספת חנות: {name}",
        "content": base64.b64encode(updated.encode("utf-8")).decode(),
        "sha": sha,
    }

    try:
        r = requests.put(api, headers=headers, json=payload)
        success = r.status_code in [200, 201]
        return success, geo
    except Exception:
        return False, None


# ── ניקוי שמות סניפים מסנזי ──────────────────────────────
def clean_senzey_branch(branch: str) -> str:
    """ניקוי שם סניף סנזי לצורך התאמה לשמות חנויות.
    מסיר מספרי הזמנה, מנרמל קיצורים ואיותים."""
    # נרמול גרשיים עבריים (U+05F4/U+05F3) → תווים רגילים
    branch = branch.replace('״', '"').replace('׳', "'")
    # הסרת קידומת ל' לפני שם רשת (כגון "לשילב עפולה")
    branch = re.sub(r'^ל(?=שילב|מכבי|ניצת)', '', branch)
    # הסרת מספרי הזמנה — סגנונות שונים
    branch = re.sub(r'הזמנה[\s\-:]*\d+', '', branch)
    branch = re.sub(r'מספר הזמנה\s*:?\s*\d+', '', branch)
    branch = re.sub(r':מספר הזמנה\s*\d*', '', branch)          # :מספר הזמנה בסוף (עם/בלי מספר)
    branch = re.sub(r'\s+\d{6,}\s*:?\s*מספר.*$', '', branch)   # NUMBER :מספר... בסוף
    branch = re.sub(r'\bהזמנת רכש[\s\-]*[\d]+', '', branch)
    branch = re.sub(r'\btעודת משלוח רכש.*$', '', branch)
    # הסרת "הזמנה-שם חנות (מספר)" — שם חנות כפול אחרי הזמנה
    branch = re.sub(r'\s+הזמנה\b.*$', '', branch)
    # נרמול מקף בין אותיות עבריות (כגון "בית שמש-ישעיהו") → רווח
    branch = re.sub(r'(?<=[א-ת])-(?=[א-ת])', ' ', branch)
    # הסרת מספרים בודדים בתחילת/סוף השם
    branch = re.sub(r'^\d{7,}\s*', '', branch)
    branch = re.sub(r'\s+\d{7,}$', '', branch)
    branch = re.sub(r'\s+10[0-9]{7,}', '', branch)
    # הסרת "מספר" שנשאר בסוף
    branch = re.sub(r'\s*מספר\s*:?\s*$', '', branch)
    # נרמול קיצורים נפוצים
    branch = branch.replace('ת"א', 'תל אביב').replace('ת.א.', 'תל אביב')
    branch = re.sub(r'(?<!\S)תא(?!\S)', 'תל אביב', branch)     # "תא" לבד (ללא גרש)
    branch = branch.replace('ראשל"צ', 'ראשון לציון')
    branch = re.sub(r'ק\.\s*יובל', 'קרית יובל', branch)
    # נרמול איות
    branch = branch.replace('קריית', 'קרית')
    branch = branch.replace('מודיעים', 'מודיעין')
    # הסרת " - הזמנה" ללא מספר בסוף
    branch = re.sub(r'\s*[-–]\s*הזמנה\s*$', '', branch)
    # נרמול מכבי
    branch = branch.replace('מכבי שירותי בריאות', 'מכבי פארם')
    branch = re.sub(r'(מכבי פארם)\s*-\s*', r'\1 ', branch)
    # ניקוי שורשים
    branch = re.sub(r'\s*-\s*$', '', branch)
    branch = re.sub(r'\s{2,}', ' ', branch).strip()
    # פילטר GARBAGE — ספקים/מוצרים/אתר שאינם חנויות
    GARBAGE_KEYWORDS = [
        'בל בוקס', 'מור סילבר', 'ביו גאיה', 'סופרסאפ', 'ווולט',
        'תעודת משלוח רכש', 'הזמנת רכש', 'פרסום ושיווק', 'פרסום ומכירות',
        'שמן אמבט', 'שמן עיסוי', 'קרם החתלה', 'קרטון משלוחים',
        'אתר סחר', 'אתר חודש', 'מבצע חודש', 'מבצע באתר',
        'תחליב גוף', 'שמפו', 'החתלה/', '/קרם',
        'מחסן ', 'מוס /', 'סבון החתלה', 'מכירות ווולט',
    ]
    if any(g in branch for g in GARBAGE_KEYWORDS):
        return ""
    # סינון שמות שהם רק תאריכים (כגון "31/03/2026")
    if re.match(r'^\d{2}/\d{2}(/\d{2,4})?', branch):
        return ""
    return branch.strip()


def format_date(raw: str) -> str:
    """'14/05/26 13:31' → '14/05 13:31' להצגה קצרה."""
    try:
        parts = raw.split()
        date_parts = parts[0].split("/")   # DD/MM/YY
        time_part  = parts[1] if len(parts) > 1 else ""
        return f"{date_parts[0]}/{date_parts[1]} {time_part}".strip()
    except Exception:
        return raw


def visit_status(raw_date: str) -> str:
    """'14/05/26 13:31' → '✅ אתמול' / '⚠️ 3 שבועות' / '🔴 45 ימים'"""
    try:
        dt = datetime.strptime(raw_date[:14], "%d/%m/%y %H:%M")
        diff = (now_il().replace(tzinfo=None) - dt).days
        if diff == 0:
            return "✅ היום!"
        if diff == 1:
            return "✅ אתמול!"
        if diff <= 7:
            return f"✅ לפני {diff} ימים"
        if diff <= 21:
            return f"⚠️ לפני {diff} ימים"
        if diff <= 60:
            return f"⚠️ לפני {diff//7} שבועות"
        return f"🔴 לפני {diff} ימים"
    except Exception:
        return "❓ לא ידוע"


def route_by_city(stores_list: list) -> list:
    """מקבץ חנויות לפי עיר, ממיין ערים מהרחוקה לקרובה, ובתוך כל עיר מהרחוק לקרוב.
    תוצאה: מסלול יעיל — יוצאים לנקודה הרחוקה, עוברים עיר-עיר ומסיימים קרוב לבית."""
    by_city: dict = {}
    for s in stores_list:
        city = s.get("city") or "אחר"
        by_city.setdefault(city, []).append(s)

    def city_avg_dist(city):
        dists = [store_distance_from_home(s) for s in by_city[city]]
        return sum(dists) / len(dists) if dists else 0

    cities_sorted = sorted(by_city.keys(), key=city_avg_dist, reverse=True)

    result = []
    for city in cities_sorted:
        city_stores = sorted(by_city[city],
                             key=lambda s: store_distance_from_home(s),
                             reverse=True)
        result.extend(city_stores)
    return result


# ── בניית הקשר לשיחה ─────────────────────────────────────
def build_context(user_msg, stores, deliveries, notes, visits):
    today = today_il()
    lines = []

    # חפש עיר בהודעה
    mentioned_city = next((s["city"] for s in stores if s["city"] and s["city"] in user_msg), None)

    # מיפוי מהיר: שם סניף נוקה → תאריך אחרון (מחושב פעם אחת לכל ה-context)
    branch_last_date: dict[str, str] = {}
    for d in deliveries:
        cleaned = clean_senzey_branch(d.get("branch", ""))
        date    = d.get("date", "")
        if cleaned and (cleaned not in branch_last_date or date > branch_last_date[cleaned]):
            branch_last_date[cleaned] = date

    # ── כינויים: שם מסנזי → שם ברשימה ─────────────────────────
    SENZEY_ALIASES = {
        # שילב — שמות קיצור / מיקום שונה
        "שילב גלילות":                   "שילב רמת השרון",
        "שילב קריון":                    "שילב קרית ביאליק",
        "שילב רגבה":                     "שילב נהריה ביג",
        "שילב שבעת הכוכבים הרצליה":     "שילב הרצליה",
        "שילב דיזינגוף סנטר":           "שילב תל אביב דיזנגוף",
        "שילב דיזינגוף":                "שילב תל אביב דיזנגוף",
        "שילב בית חולים בלינסון":       "שילב פתח תקווה בילינסון",
        "שילב בית חולים ברזילי":        "שילב אשקלון ברזילי",
        "שילב נמל תא":                  "שילב נמל תל אביב",
        "שילב נמל ת״א":                 "שילב נמל תל אביב",
        "שילב פולג":                     "שילב נתניה פולג",
        "שילב קניון הזהב":              "שילב ראשון לציון",
        "שילב קניון הזהב ראשון-לציון":  "שילב ראשון לציון",
        "שילב קניון הזהב ראשון לציון":  "שילב ראשון לציון",
        "שילב ביג יהוד":                "שילב יהוד",
        "שילב ביג אשדוד":               "שילב אשדוד ביג",
        "שילב ביג באר שבע":             "שילב באר שבע ביג",
        "ביג באר שבע שילב":             "שילב באר שבע ביג",
        "שילב גרנד באר שבע":            "שילב באר שבע גרנד קניון",
        "שילב גרנד ברר שבע":            "שילב באר שבע גרנד קניון",
        "שילב גרנד חיפה":               "שילב חיפה גרנד קניון",
        "שילב עזריאלי חיפה":            "שילב חיפה עזריאלי",
        "שילב חוצות חיפה":              "שילב חיפה חוצות המפרץ",
        "שילב שער הצפון קרית אתא":      "שילב קרית אתא",
        "שילב תלפיות":                  "שילב ירושלים תלפיות",
        "שילב ויצמן":                   "שילב כפר סבא קניון ערים",
        "שילב כפר סבא g":               "שילב כפר סבא קניון G",
        "שילב אבנת פתח תקווה":          "שילב פתח תקווה אבנת",
        "שילב גלובל פתח תקווה":         "שילב פתח תקווה גלובל",
        "שילב שרונים":                  "שילב שרונים הוד השרון",
        "שילב ראשונים":                 "שילב ראשונים ראשון לציון",
        "שילב רמת אביב":                "שילב תל אביב רמת אביב",
        "שילב גן העיר":                 "שילב תל אביב גן העיר",
        "שילב אסותא אשדוד":             "שילב אשדוד אסותא",
        "שילב אסף הרופא":               "שילב באר יעקב אסף הרופא",
        "שילב עיר ימים":                "שילב נתניה עיר ימים",
        "שילב פולג נתניה":              "שילב נתניה פולג",
        "שילב מבשרת":                   "שילב מבשרת ציון",
        # מיקומים נוספים שזוהו בתעודות
        "שילב אשדוד סטאר":             "שילב אשדוד סטאר סנטר",
        "שילב אשקלון סילבר":           "שילב אשקלון סילבר",
        'שילב ג׳י כפס':               "שילב כפר סבא קניון G",   # G = ג׳י בכפר סבא
        "שילב ג'י כפס":               "שילב כפר סבא קניון G",
        "שילב רננים":                  "שילב רעננה קניון רננים", # רננים = רעננה
        "שילב שער ראשון":              "שילב שער ראשון",
        "בית שילב":                    "שילב בני ברק אילון",
        "בית שילב אילון":              "שילב בני ברק אילון",
        # מכבי — סדר הפוך
        "ראש העין הציונות מכבי פארם":   "מכבי פארם ראש העין הציונות",
        "ראשון לציון מזרח - מכבי פארם ראשון לציון מזרח": "מכבי פארם ראשון לציון מזרח",
        "כפר סבא הירוקה - מכבי פארם - כפר סבא הירוקה": "מכבי פארם כפר סבא הירוקה",
        "עקיבא - מכבי פארם בני ברק - עקיבא": "מכבי פארם בני ברק עקיבא",
        "נוף הגליל - מכבי פארם נצרת נוף הגליל": "מכבי פארם נצרת נוף הגליל",
        # מכבי — קיצורים ואיות שונה
        "מכבי הרצליה":                   "מכבי פארם הרצליה",
        "מכבי פארם חיפה-הדר":            "מכבי פארם חיפה הדר",
        "מכבי פארם יד אליהו":            "מכבי פארם תל אביב יד אליהו",
        "מכבי פארם תל אביב- התקומה":    "מכבי פארם תל אביב התקומה",
        "מכבי פארם מודיעים עלית":        "מכבי פארם מודיעין עילית",
        "מכבי פארם ק. יובל ירושלים":    "מכבי פארם קרית יובל ירושלים",
        "מכבי פארם ק. יובל":             "מכבי פארם קרית יובל ירושלים",
        "מכבי פארם מ.פ. ק.יובל ירושלים": "מכבי פארם קרית יובל ירושלים",
        "מכבי פארם גני ראשון ראשון לציון": "מכבי פארם גני ראשון ראשון לציון",
        "מכבי פארם קרית מוצקין":           "מכבי פארם קריית מוצקין- גושן",
        "מכבי קרית טבעון":                 "מכבי פארם קרית טבעון",
        "מכבי פארם גבעתיים":               "מכבי גבעתיים",
        "מכבי פארם מבשרת":                 "מכבי פארם מבשרת ציון",
        # השלום / השלה — שני סניפים נפרדים בתל אביב
        "מכבי פארם השלום תל אביב":         "מכבי פארם תל אביב השלום",
        "מכבי תל אביב השלום":              "מכבי פארם תל אביב השלום",
        "מכבי פארם השלה תל אביב":          "מכבי פארם תל אביב השלה",
        "מכבי תל אביב השלה":               "מכבי פארם תל אביב השלה",
        # שילב — שגיאות כתיב
        "שילב גן העיק":                  "שילב תל אביב גן העיר",
        # שקדיה — איות שונה
        "שקדייה גבעתיים":               "שקדיה גבעתיים",
        "שקדייה הוד השרון":             "שקדיה הוד השרון",
        "שקדייה רמת גן":                "שקדיה רמת גן",
    }

    # ── זיהוי רשת מהשם ────────────────────────────────────────
    def get_chain(text: str) -> str:
        if "שילב" in text:
            return "שילב"
        if "מכבי" in text:
            return "מכבי"
        if "ניצת" in text or "הדובדבן" in text:
            return "ניצת"
        return ""

    # מילות עצירה — לא מספיקות לזיהוי ייחודי
    STOP_WORDS = {"שילב", "מכבי", "פארם", "ניצת", "הדובדבן", "בית", "חולים",
                  "קניון", "מרכז", "ביג", "פארק", "סניף", "סנטר", "שירותי", "בריאות"}

    def norm_word(w: str) -> str:
        """נרמול מילה לצורך השוואה — קריית↔קרית ועוד."""
        return w.replace('קריית', 'קרית').replace('מודיעים', 'מודיעין')

    def words_overlap(a: str, b: str) -> int:
        wa = {norm_word(w) for w in a.split() if len(w) > 1 and w not in STOP_WORDS}
        wb = {norm_word(w) for w in b.split() if len(w) > 1 and w not in STOP_WORDS}
        return len(wa & wb)

    def names_match(store_name: str, branch: str) -> bool:
        """האם שם חנות מתאים לשם סניף מסנזי — גמיש, מודע-רשת."""
        # 1. כינוי מפורש
        aliased = SENZEY_ALIASES.get(branch, branch)
        if aliased == store_name:
            return True
        # 2. אל תתאים בין רשתות שונות
        sc, bc = get_chain(store_name), get_chain(branch)
        if sc and bc and sc != bc:
            return False
        # 3. התאמה ישירה
        if store_name in branch or branch in store_name:
            return True
        # 4. מילות תוכן משותפות — מינימום 2
        if words_overlap(store_name, branch) >= 2:
            return True
        return False

    # מיפוי ביקורים ידניים: שם חנות → תאריך אחרון
    manual_last: dict[str, str] = {}
    for v in visits:
        store_v = v.get("store", "").strip()
        date_v  = v.get("date", "")
        if store_v and date_v:
            # המר DD/MM/YY → YYYY-MM-DD לצורך השוואה
            try:
                parts = date_v.split("/")
                if len(parts) == 3:
                    normalized = f"20{parts[2]}-{parts[1]}-{parts[0]}"
                else:
                    normalized = date_v
            except Exception:
                normalized = date_v
            if store_v not in manual_last or normalized > manual_last[store_v]:
                manual_last[store_v] = date_v  # שמור כפי שהוא לתצוגה

    def last_visit_raw(store) -> str | None:
        """מחזיר תאריך גולמי של הביקור/משלוח האחרון — משני מקורות."""
        store_name = store["name"].strip()

        # ── מקור 1: תעודות סנזי ─────────────────────────────
        senzey_best = None
        for cleaned, date in branch_last_date.items():
            if names_match(store_name, cleaned):
                if senzey_best is None or date > senzey_best:
                    senzey_best = date

        # המר תאריך סנזי "DD/MM/YY HH:MM" → "YYYY-MM-DD HH:MM" להשוואה תקינה
        if senzey_best:
            try:
                sp = senzey_best.split()
                dp = sp[0].split("/")
                tp = sp[1] if len(sp) > 1 else "00:00"
                senzey_comparable = f"20{dp[2]}-{dp[1]}-{dp[0]} {tp}"
            except Exception:
                senzey_comparable = senzey_best
        else:
            senzey_comparable = None

        # ── מקור 2: ביקורים ידניים ──────────────────────────
        manual_best = manual_last.get(store_name)
        if manual_best:
            # המר לפורמט YYYY-MM-DD 00:00 להשוואה
            try:
                parts = manual_best.split("/")
                manual_comparable = f"20{parts[2]}-{parts[1]}-{parts[0]} 00:00"
            except Exception:
                manual_comparable = None
        else:
            manual_comparable = None

        # בחר את המאוחר — השוואה ב-ISO (YYYY-MM-DD) כדי למנוע באג מחרוזת
        candidates = [(senzey_comparable, senzey_best), (manual_comparable, manual_best)]
        candidates = [(cmp, raw) for cmp, raw in candidates if cmp]
        if not candidates:
            return None
        _, best_raw = max(candidates, key=lambda x: x[0])
        return best_raw

    if mentioned_city:
        # כל החנויות בעיר + ערים קרובות (רדיוס 40 ק"מ) — מינימום 10 חנויות
        city_dist = city_distance_from_home(mentioned_city)

        # חנויות בעיר עצמה
        in_city = [s for s in stores if s.get("city","") == mentioned_city or mentioned_city in s.get("city","")]

        # אם פחות מ-10 — הוסף ערים קרובות עד רדיוס 40 ק"מ
        nearby = []
        center = CITY_COORDS.get(mentioned_city)
        if len(in_city) < 10 and center:
            for s in stores:
                if s in in_city:
                    continue
                try:
                    sd = haversine(center[0], center[1],
                                   float(s.get("lat") or 0),
                                   float(s.get("lon") or 0))
                    if sd <= 40:
                        nearby.append(s)
                except Exception:
                    pass

        # מסלול מקובץ לפי עיר: רחוק → קרוב, בתוך כל עיר רחוק → קרוב
        relevant = route_by_city(in_city + nearby)

        # ודא לפחות 10
        if len(relevant) < 10 and center:
            already = {id(s) for s in in_city + nearby}
            extra = sorted(
                [s for s in stores if id(s) not in already],
                key=lambda s: haversine(center[0], center[1],
                                        float(s.get("lat") or center[0]),
                                        float(s.get("lon") or center[1]))
            )[:10]
            relevant = route_by_city(in_city + nearby + extra)

        lines.append(f"📍 מסלול באזור {mentioned_city} ({len(relevant)} חנויות) — {city_dist:.0f} ק\"מ מהוד השרון:")
        lines.append(f"⬇️ סדר: מקובץ לפי עיר, בכל עיר מהרחוק לקרוב — יוצאים רחוק ומתקרבים הביתה")
        lines.append(f"⚠️ הנחיה: הצג את הסטטוס (✅/⚠️/🔴) שמופיע לפני כל חנות בדיוק כפי שהוא — אל תשנה!")
        prev_city_r = None
        for i, s in enumerate(relevant, 1):
            raw = last_visit_raw(s)
            status = visit_status(raw) if raw else "🔴 אין מידע"
            d = store_distance_from_home(s)
            city_label = s.get("city", "")
            if city_label != prev_city_r:
                lines.append(f"\n🏙️ {city_label} (~{d:.0f} ק\"מ):")
                prev_city_r = city_label
            addr = s.get("address","")
            # סטטוס קודם לשם — כך Claude לא יכול לפספס אותו
            lines.append(f"  {i}. [{status}] {s['name']}{' | '+addr if addr else ''}")

    elif is_route_question(user_msg):
        # מסלול יומי כללי — מינימום 10 חנויות, מקובץ לפי עיר
        area_stores = stores
        for s in stores:
            if s.get("city") and s["city"] in user_msg:
                area_stores = [x for x in stores if s["city"] in x.get("city","")]
                break

        if len(area_stores) < 10:
            area_stores = stores

        # מסלול מקובץ לפי עיר
        area_stores = route_by_city(area_stores)

        lines.append(f"מסלול יומי — מקובץ לפי עיר, מהרחוקה לקרובה:")
        lines.append(f"⬇️ סדר: יוצאים לעיר הרחוקה ביותר, גומרים את כל חנויותיה, ממשיכים לעיר הבאה")
        prev_city = None
        for s in area_stores[:80]:
            city = s.get("city", "")
            dist = store_distance_from_home(s)
            raw = last_visit_raw(s)
            status = visit_status(raw) if raw else "🔴 אין מידע"
            if city != prev_city:
                lines.append(f"\n📍 {city} (~{dist:.0f} ק\"מ):")
                prev_city = city
            lines.append(f"  • [{status}] {s['name']}")
    else:
        by_city = {}
        for s in stores:
            by_city.setdefault(s.get("city") or "אחר", []).append(s)
        # מיין ערים לפי מרחק
        cities_sorted = sorted(by_city.keys(), key=lambda c: city_distance_from_home(c))
        lines.append(f"סה\"כ {len(stores)} חנויות (מקרוב לרחוק מהוד השרון):")
        for city in cities_sorted[:20]:
            dist = city_distance_from_home(city)
            lines.append(f"\n📍 {city} (~{dist:.0f} ק\"מ):")
            for s in by_city[city][:4]:
                raw = last_visit_raw(s)
                status = visit_status(raw) if raw else "🔴 אין מידע"
                lines.append(f"  • {s['name']} — {status}")

    # תעודות משלוח היום
    today_deliveries = [d for d in deliveries if d.get("date","").startswith(today)]
    if today_deliveries:
        lines.append(f"\n🚚 תעודות משלוח היום — ירידת סחורה מהמחסן (לא ביקור אישי!) ({len(today_deliveries)}):")
        for d in today_deliveries:
            lines.append(f"• {d['date']} — {d.get('branch','')[:40]}")
    else:
        lines.append(f"\n🚚 תעודות משלוח היום: אין עדיין")

    # תעודות אחרונות (כל הזמן)
    if deliveries:
        lines.append(f"\n📦 תעודות משלוח אחרונות (ירידת סחורה מהמחסן, לא ביקורים אישיים):")
        for d in deliveries[:8]:
            lines.append(f"• {d['date']} — {d.get('branch','')[:40]}")

    # ביקורים ידניים היום
    today_visits = [v for v in visits if v.get("date","").startswith(today)]
    if today_visits:
        lines.append(f"\n👣 ביקורים ידניים היום ({len(today_visits)}):")
        for v in today_visits:
            lines.append(f"• {v.get('store','')} — {v.get('status','')}")
    else:
        lines.append(f"\n👣 ביקורים ידניים היום: אין — המשתמש לא הזין ביקורים להיום")

    # הערות — אם המשתמש שאל על חנות ספציפית, הצג רק שלה
    if notes:
        # בדוק אם נשאלה חנות ספציפית
        specific_store_notes = []
        for s in stores:
            if s["name"] in user_msg or (s["city"] and s["city"] in user_msg and s["name"] in user_msg):
                specific_store_notes = [n for n in notes if n.get("store","") == s["name"]]
                if specific_store_notes:
                    lines.append(f"\n📝 הערות על {s['name']} ({len(specific_store_notes)} הערות):")
                    for n in sorted(specific_store_notes, key=lambda x: x.get("date",""), reverse=True)[:8]:
                        lines.append(f"• {n.get('date','')} — {n.get('note','')}")
                    break

        # אם לא נשאלה חנות ספציפית — הצג אחרונות
        if not specific_store_notes:
            lines.append(f"\nהערות שטח אחרונות ({len(notes)} סה\"כ):")
            for n in sorted(notes, key=lambda x: x.get("date",""), reverse=True)[:10]:
                lines.append(f"• {n.get('date','')} | {n.get('store','')} — {n.get('note','')}")

    return "\n".join(lines)[:12000]


# ── שאל את Claude ─────────────────────────────────────────
def is_history_question(msg):
    """זיהוי שאלות על היסטוריה/ביקורים שכבר היו — אסור לענות עליהן מהדמיון."""
    keywords = ["איפה היית", "איפה הייתי", "איפה הלכת", "ביקרת היום",
                "מה עשית", "היום הייתי", "היום ביקרתי", "סיכום היום",
                "כמה ביקרת", "אצל מי היית"]
    return any(k in msg for k in keywords)


def detect_visit_in_msg(msg: str, stores_list: list) -> list:
    """
    אם המשתמש כותב 'ביקרתי ב...' / 'הייתי ב...' / 'הגעתי ל...' —
    מחזיר רשימת חנויות שזוהו בהודעה.
    """
    VISIT_TRIGGERS = ["ביקרתי", "הייתי ב", "הגעתי ל", "ביקור ב", "סיימתי ב"]
    if not any(kw in msg for kw in VISIT_TRIGGERS):
        return []

    found = []
    # חיפוש שם מדויק
    for s in stores_list:
        if s["name"] in msg:
            found.append(s)

    # אם לא נמצא שם מדויק — חפש רשת + עיר
    if not found:
        for s in stores_list:
            city  = s.get("city", "")
            chain = s.get("chain", "")
            if city and chain and len(city) > 2 and city in msg:
                chain_word = chain.split()[0] if chain else ""
                if chain_word and chain_word in msg:
                    found.append(s)
    return found


def ask_claude(user_msg, context_text, chat_history):
    try:
        today = now_il().strftime("%d/%m/%Y")
        system_prompt = f"""אתה עוזר אישי חכם לניהול רשת חנויות בישראל.
ענה תמיד בעברית, קצר וברור. השתמש בבוליטים כשיש רשימות.
תאריך היום: {today}
בית המשתמש: הוד השרון.
כלל מסלול יומי: מינימום 10 חנויות ביום — מסדר מהרחוק לקרוב! כלומר: מתחיל בנקודה הכי רחוקה מהוד השרון וחוזר הביתה. כך יוצאים לקצה הרחוק ומסיימים קרוב לבית.

⛔ חוקים שאסור לעבור עליהם:
1. השתמש אך ורק במידע שמופיע בין "--- נתונים ---" ו"--- סוף נתונים ---" למטה
2. אסור בהחלט להשתמש בידע כללי על חנויות בישראל — שכח כל מה שאתה יודע על "טוב לי טבע", "טבע וארץ", "גוד פארם" וכו'
3. כשמישהו שואל "איפה היית היום" — הסתכל רק על סעיף "ביקורים ידניים היום". אם כתוב "אין" — אמור "לא הוזנו ביקורים להיום" ותו לא
4. אסור לתת המלצות על ביקורים אלא אם המשתמש מבקש במפורש "מה לבקר מחר" או "מה דחוף"
5. תעודת משלוח = סחורה שנשלחה מהמחסן — לא ביקור של המשתמש!
6. ⛔ אסור בהחלט לומר "אין לי נתונים על ערים אחרות" או "שלח לי רשימת חנויות" — יש לך נתונים על 350+ חנויות בכל הארץ! אם לא מופיעות חנויות בנתונים — זה כי אין לנו חנויות שם, לא כי חסר מידע
7. ⛔ חשוב מאוד: כשמוצג סטטוס [✅ ...] או [⚠️ ...] או [🔴 ...] לפני שם חנות — חובה להציג את הסמל הזה בדיוק! אסור להשמיט או לשנות סטטוסים!
8. אם שאלו על אזור ויש מעט חנויות — הצג מה שיש וציין שזה מה שיש באזור זה

כללים נוספים:
- ⚠️ = לא בוקר יותר מחודש
- ✅ = בוקר בשבועיים האחרונים
- כשמישהו שואל "מה דחוף" — הצג רק חנויות מהרשימה שבנתונים
- כל ניצת הדובדבן = לקוחות סופר סאפ (הפצה דרכם, אבל כדאי לבקר)

--- נתונים אמיתיים בלבד ---
{context_text}
--- סוף נתונים ---"""

        messages = []
        for msg in chat_history[-8:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_msg})

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": messages
            },
            timeout=30
        )
        data = r.json()
        if "content" in data:
            return data["content"][0]["text"]
        return f"שגיאה: {str(data)[:200]}"
    except Exception as e:
        return f"שגיאה: {str(e)}"


# ══════════════════════════════════════════════════════════
# ── ממשק ראשי ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════

st.title("🏪 ניהול חנויות")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["💬 שיחה", "📝 הוסף הערה", "📊 סיכום יום", "🗺️ מפה", "➕ חנות חדשה", "📅 מעקב ביקורים", "🧭 מסלול יומי"])


# ════════════════════════════
# לשונית 1 — שיחה
# ════════════════════════════
with tab1:
    if "messages" not in st.session_state:
        st.session_state.messages = [{
            "role": "assistant",
            "content": "שלום! אני העוזר לניהול החנויות שלך 🏪\n\n• **מה יש לי ב[עיר]** — רשימת חנויות + סטטוס\n• **מה דחוף** — מה לא בוקר הרבה זמן\n• **סיכום היום / איפה הייתי** — ביקורים של היום\n• **ביקרתי בשילב הרצליה** — רישום ביקור ישיר מהשיחה ✅\n• **כתובת [חנות]** — כתובת מדויקת של החנות\n\nמה תרצה לדעת?"
        }]

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("שאל על החנויות שלך..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("מחפש..."):
                stores     = get_stores()
                deliveries = get_deliveries()
                notes      = get_notes()
                visits     = get_manual_visits()

                # ── זיהוי ביקור מהשיחה: "ביקרתי ב...", "הייתי ב..." ──
                visited_stores = detect_visit_in_msg(prompt, stores)
                if visited_stores:
                    today_str = today_il()
                    saved, failed = [], []
                    for vs in visited_stores:
                        ok = save_visit_to_github(today_str, vs["name"], vs.get("city",""), "ביקור", "")
                        if ok:
                            saved.append(vs["name"])
                        else:
                            failed.append(vs["name"])
                    if saved:
                        get_manual_visits.clear()
                    lines = [f"✅ **נרשמו ביקורים להיום ({today_str}):**"]
                    for n in saved:
                        lines.append(f"• {n}")
                    if failed:
                        lines.append(f"\n⚠️ לא הצלחתי לשמור (בעיית חיבור): {', '.join(failed)}")
                        lines.append("נסה לרשום שוב דרך לשונית 📝")
                    if not saved and not failed:
                        lines = ["לא זיהיתי שם חנות ספציפי בהודעה. אפשר לכתוב את השם המלא? לדוגמה: 'ביקרתי בשילב הרצליה'"]
                    reply = "\n".join(lines)

                # שאלות היסטוריה — תשובה ישירה מהנתונים, ללא Claude
                elif is_history_question(prompt):
                    today_str = today_il()
                    today_vis = [v for v in visits if v.get("date","").startswith(today_str)]
                    today_del = [d for d in deliveries if d.get("date","").startswith(today_str)]

                    lines = [f"📅 **סיכום היום ({today_str}):**\n"]
                    if today_vis:
                        lines.append("👣 **ביקורים שהוזנו:**")
                        for v in today_vis:
                            icon = "✅" if v.get("status") == "ביקור" else "⚠️"
                            lines.append(f"{icon} {v.get('store','')} — {v.get('status','')}")
                    else:
                        lines.append("👣 לא הוזנו ביקורים להיום")

                    if today_del:
                        lines.append(f"\n🚚 **תעודות משלוח שירדו היום ({len(today_del)}):**")
                        for d in today_del:
                            lines.append(f"• {d.get('branch','')} ({d.get('date','')[6:11]})")
                    else:
                        lines.append("\n🚚 לא ירדו תעודות משלוח היום")

                    reply = "\n".join(lines)
                else:
                    context = build_context(prompt, stores, deliveries, notes, visits)
                    reply   = ask_claude(prompt, context, st.session_state.messages[:-1])

            st.markdown(reply)

        st.session_state.messages.append({"role": "assistant", "content": reply})


# ════════════════════════════
# לשונית 2 — הוסף הערה
# ════════════════════════════
with tab2:
    st.subheader("📝 הוסף הערה על חנות")

    stores = get_stores()
    store_names = sorted(set(s["name"] for s in stores))
    cities      = sorted(set(s["city"] for s in stores if s["city"]))

    col1, col2 = st.columns(2)
    with col1:
        selected_store = st.selectbox("חנות", [""] + store_names, key="note_store")
    with col2:
        selected_city = st.selectbox("עיר", [""] + cities, key="note_city")

    if selected_store:
        store_info = next((s for s in stores if s["name"] == selected_store), None)
        if store_info and store_info.get("address"):
            st.caption(f"📍 {store_info['address']}, {store_info.get('city','')}")

    note_text = st.text_area("הערה", placeholder="לדוגמה: המנהל ביקש עוד מוס, המדף דליל...", key="note_text")

    note_type = st.radio("סוג", ["הערה כללית", "ביקרתי היום", "לא הגעתי", "צריך הזמנה"], horizontal=True)

    if st.button("💾 שמור הערה", type="primary"):
        if selected_store and note_text:
            today_str = today_il()
            city_val  = selected_city or next((s["city"] for s in stores if s["name"] == selected_store), "")
            full_note = f"[{note_type}] {note_text}"

            ok = save_note_to_github(today_str, selected_store, city_val, full_note)
            if ok:
                st.success(f"✅ נשמר! הערה על {selected_store}")
                get_notes.clear()
            else:
                st.warning("⚠️ לא ניתן לשמור לענן כרגע — ההערה נשמרה בסשן")
                if "local_notes" not in st.session_state:
                    st.session_state.local_notes = []
                st.session_state.local_notes.append({
                    "date": today_str, "store": selected_store,
                    "city": city_val, "note": full_note
                })
        else:
            st.error("נא לבחור חנות ולכתוב הערה")

    st.divider()
    all_notes = get_notes()
    local     = st.session_state.get("local_notes", [])
    all_combined = all_notes + local

    # ── הערות לחנות שנבחרה ──────────────────────────────
    if selected_store:
        store_notes = [n for n in all_combined
                       if n.get("store","").strip() == selected_store.strip()]
        store_notes = sorted(store_notes, key=lambda n: n.get("date",""), reverse=True)

        st.subheader(f"📋 הערות על: {selected_store}")
        if store_notes:
            for n in store_notes:
                note_txt = n.get("note","")
                # צבע לפי סוג הערה
                if "ביקרתי" in note_txt or "ביקור" in note_txt:
                    border_color = "#2E7D32"
                elif "לא הגעתי" in note_txt:
                    border_color = "#C62828"
                elif "הזמנה" in note_txt or "דליל" in note_txt:
                    border_color = "#E65100"
                else:
                    border_color = "#1565C0"

                st.markdown(f"""<div class='note-card' style='border-right: 4px solid {border_color};'>
                    <small style='color:#888'>{n.get('date','')}</small><br>
                    {note_txt}
                </div>""", unsafe_allow_html=True)
        else:
            st.info("אין הערות עדיין לחנות זו")

    # ── כל ההערות האחרונות ──────────────────────────────
    st.divider()
    st.subheader("🕐 הערות אחרונות (כל החנויות)")

    search_note = st.text_input("🔍 חפש בהערות", placeholder="שם חנות / מילה מהערה...", key="note_search")

    combined = sorted(all_combined, key=lambda n: n.get("date",""), reverse=True)
    if search_note:
        combined = [n for n in combined
                    if search_note in n.get("store","") or search_note in n.get("note","")]

    combined = combined[:20]

    if combined:
        for n in combined:
            note_txt = n.get("note","")
            if "ביקרתי" in note_txt or "ביקור" in note_txt:
                border_color = "#2E7D32"
            elif "לא הגעתי" in note_txt:
                border_color = "#C62828"
            elif "הזמנה" in note_txt or "דליל" in note_txt:
                border_color = "#E65100"
            else:
                border_color = "#1565C0"
            st.markdown(f"""<div class='note-card' style='border-right: 4px solid {border_color};'>
                <b>{n.get('store','')}</b> — <small>{n.get('city','')}</small>
                &nbsp;&nbsp;<small style='color:#888'>{n.get('date','')}</small><br>
                {note_txt}
            </div>""", unsafe_allow_html=True)
    else:
        st.info("אין הערות")


# ════════════════════════════
# לשונית 3 — סיכום יום
# ════════════════════════════
with tab3:
    st.subheader("📊 סיכום היום")

    today_str  = today_il()
    deliveries = get_deliveries()
    visits     = get_manual_visits()
    notes      = get_notes()

    today_del = [d for d in deliveries if d.get("date","").startswith(today_str)]
    today_vis = [v for v in visits    if v.get("date","") == today_str or v.get("date","").startswith(today_str)]
    today_not = [n for n in notes     if n.get("date","") == today_str or n.get("date","").startswith(today_str)]

    col1, col2, col3 = st.columns(3)
    col1.metric("תעודות משלוח", len(today_del))
    col2.metric("ביקורים ידניים", len(today_vis))
    col3.metric("הערות", len(today_not))

    if today_del:
        st.subheader("🚚 תעודות משלוח")
        for d in today_del:
            raw   = d.get('branch', '')
            clean = clean_senzey_branch(raw)
            time  = d.get('date','')[9:14]   # HH:MM
            st.markdown(f"• **{time}** — {clean}")

    if today_vis:
        st.subheader("👣 ביקורים")
        stores_tab3 = get_stores()
        stores_map  = {s["name"]: s for s in stores_tab3}
        for v in today_vis:
            icon       = "✅" if v.get("status") == "ביקור" else "⚠️"
            v_store    = v.get('store', '')
            s_info     = stores_map.get(v_store, {})
            addr_part  = f" | 📍 {s_info['address']}" if s_info.get("address") else ""
            st.markdown(f"{icon} {v_store} — {v.get('status','')}{addr_part}")

    if today_not:
        st.subheader("📝 הערות")
        for n in today_not:
            st.markdown(f"• **{n.get('store','')}** — {n.get('note','')}")

    if not today_del and not today_vis and not today_not:
        st.info("אין נתונים להיום עדיין")

    st.divider()
    if st.button("🔄 רענן נתונים"):
        get_deliveries.clear()
        get_notes.clear()
        get_manual_visits.clear()
        st.rerun()


# ════════════════════════════
# לשונית 4 — מפה
# ════════════════════════════
def build_store_map_html(stores_list, deliveries_list, visits_list) -> str:
    """מייצר HTML של מפת Leaflet עם כל החנויות + סטטוס ביקור."""

    # ── חשב תאריך אחרון לכל סניף מסנזי ──────────────────────
    branch_last: dict = {}
    for d in deliveries_list:
        cl = clean_senzey_branch(d.get("branch", ""))
        dt = d.get("date", "")
        if cl and (cl not in branch_last or dt > branch_last[cl]):
            branch_last[cl] = dt

    # ── ביקורים ידניים ────────────────────────────────────────
    manual_last: dict = {}
    for v in visits_list:
        sv = v.get("store", "").strip()
        dv = v.get("date", "")
        if sv and dv:
            try:
                p = dv.split("/")
                cmp = f"20{p[2]}-{p[1]}-{p[0]} 00:00"
            except Exception:
                cmp = dv
            if sv not in manual_last or cmp > manual_last[sv][1]:
                manual_last[sv] = (dv, cmp)

    def last_raw(store_name: str):
        # סנזי — התאמה פשוטה
        chain = ""
        if "שילב"  in store_name: chain = "שילב"
        elif "מכבי" in store_name: chain = "מכבי"
        elif "ניצת" in store_name or "הדובדבן" in store_name: chain = "ניצת"

        senz_best = None
        senz_cmp  = None
        for br, dt in branch_last.items():
            bc = ""
            if "שילב"  in br: bc = "שילב"
            elif "מכבי" in br: bc = "מכבי"
            elif "ניצת" in br or "הדובדבן" in br: bc = "ניצת"
            if chain and bc and chain != bc:
                continue
            if store_name in br or br in store_name:
                try:
                    sp = dt.split(); dp = sp[0].split("/"); tp = sp[1] if len(sp)>1 else "00:00"
                    cmp = f"20{dp[2]}-{dp[1]}-{dp[0]} {tp}"
                except Exception:
                    cmp = dt
                if senz_cmp is None or cmp > senz_cmp:
                    senz_best, senz_cmp = dt, cmp

        man = manual_last.get(store_name)
        if man and senz_cmp:
            return man[0] if man[1] > senz_cmp else senz_best
        if man:
            return man[0]
        return senz_best

    def status_color(raw):
        """green / orange / red based on days since last visit."""
        if not raw:
            return "#CC2200"
        try:
            fmt = "%d/%m/%y %H:%M" if "/" in raw and len(raw) >= 14 else "%Y-%m-%d"
            src = raw[:14] if "/" in raw else raw[:10]
            dt  = datetime.strptime(src, fmt if "/" in raw else "%Y-%m-%d")
            diff = (now_il().replace(tzinfo=None) - dt).days
        except Exception:
            return "#CC2200"
        if diff <= 7:  return "#22AA22"
        if diff <= 21: return "#FF8800"
        if diff <= 60: return "#FF8800"
        return "#CC2200"

    CHAIN_FILL = {"שילב": "#1F4E79", "מכבי": "#2E7D32", "ניצת": "#C55A11"}

    def chain_fill(chain):
        for k, v in CHAIN_FILL.items():
            if k in (chain or ""):
                return v
        return "#555555"

    markers = []
    for s in stores_list:
        try:
            lat = float(s.get("lat") or 0)
            lon = float(s.get("lon") or 0)
        except Exception:
            continue
        if abs(lat) < 0.001 or abs(lon) < 0.001:
            continue
        name   = s.get("name", "")
        raw    = last_raw(name)
        s_txt  = visit_status(raw) if raw else "🔴 לא בוקר"
        ring   = status_color(raw)
        fill   = chain_fill(s.get("chain", ""))
        addr   = s.get("address", "")
        markers.append({
            "lat": round(lat, 5), "lon": round(lon, 5),
            "name": name, "city": s.get("city",""),
            "addr": addr, "chain": s.get("chain","") or "פרטי",
            "fill": fill, "ring": ring, "status": s_txt,
        })

    mj = json.dumps(markers, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html dir="rtl">
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body,html{{margin:0;padding:0;font-family:Arial,sans-serif}}
    #map{{width:100%;height:560px}}
    .legend{{background:white;padding:10px 12px;border-radius:6px;
             font-size:12px;line-height:22px;direction:rtl;
             box-shadow:0 2px 6px rgba(0,0,0,.25)}}
    .dot{{display:inline-block;width:11px;height:11px;
          border-radius:50%;margin-left:5px;vertical-align:middle}}
  </style>
</head>
<body>
<div id="map"></div>
<script>
const DATA = {mj};
const map = L.map('map').setView([32.0,34.9],8);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{attribution:'© OpenStreetMap',maxZoom:18}}).addTo(map);

let allMarkers=[], curFilter='all';

function buildIcon(fill,ring){{
  return L.divIcon({{
    className:'',
    html:`<div style="background:${{fill}};width:12px;height:12px;border-radius:50%;
          border:3px solid ${{ring}};box-shadow:0 0 4px rgba(0,0,0,.45)"></div>`,
    iconSize:[18,18],iconAnchor:[9,9],popupAnchor:[0,-9]
  }});
}}

DATA.forEach(m=>{{
  const mk = L.marker([m.lat,m.lon],{{icon:buildIcon(m.fill,m.ring)}});
  const popup = `<div dir="rtl" style="min-width:180px">
    <b style="font-size:14px">${{m.name}}</b><br>
    📍 ${{m.city}}${{m.addr?' — '+m.addr:''}}<br>
    <span style="font-size:13px">${{m.status}}</span>
  </div>`;
  mk.bindPopup(popup);
  mk._chain = m.chain;
  allMarkers.push(mk);
  mk.addTo(map);
}});

function filterChain(chain){{
  curFilter = chain;
  allMarkers.forEach(mk=>{{
    const show = (chain==='all') || mk._chain.includes(chain);
    if(show) mk.addTo(map); else map.removeLayer(mk);
  }});
  document.querySelectorAll('.filter-btn').forEach(b=>
    b.style.fontWeight = b.dataset.chain===chain?'bold':'normal');
}}

// Filter bar
const ctrl = L.control({{position:'topleft'}});
ctrl.onAdd=()=>{{
  const d=L.DomUtil.create('div');
  d.innerHTML=`<div style="background:white;padding:6px 10px;border-radius:6px;
    box-shadow:0 2px 6px rgba(0,0,0,.2);display:flex;gap:8px;direction:rtl">
    <button class="filter-btn" data-chain="all"    onclick="filterChain('all')"    style="font-weight:bold;cursor:pointer;border:1px solid #ccc;border-radius:4px;padding:3px 8px;background:#1F4E79;color:white">הכל</button>
    <button class="filter-btn" data-chain="שילב"  onclick="filterChain('שילב')"   style="cursor:pointer;border:1px solid #ccc;border-radius:4px;padding:3px 8px;background:#3579b0;color:white">שילב</button>
    <button class="filter-btn" data-chain="מכבי"  onclick="filterChain('מכבי')"   style="cursor:pointer;border:1px solid #ccc;border-radius:4px;padding:3px 8px;background:#2E7D32;color:white">מכבי</button>
    <button class="filter-btn" data-chain="ניצת"  onclick="filterChain('ניצת')"   style="cursor:pointer;border:1px solid #ccc;border-radius:4px;padding:3px 8px;background:#C55A11;color:white">ניצת</button>
  </div>`;
  L.DomEvent.disableClickPropagation(d);
  return d;
}};
ctrl.addTo(map);

// Legend
const leg=L.control({{position:'bottomright'}});
leg.onAdd=()=>{{
  const d=L.DomUtil.create('div','legend');
  d.innerHTML=`<b>מקרא</b><br>
    <span class='dot' style='background:#1F4E79'></span> שילב<br>
    <span class='dot' style='background:#2E7D32'></span> מכבי פארם<br>
    <span class='dot' style='background:#C55A11'></span> ניצת הדובדבן<br>
    <span class='dot' style='background:#555'></span> פרטי<br>
    <hr style='margin:5px 0;border-color:#ddd'>
    <span class='dot' style='border:2px solid #22AA22;background:transparent'></span> ✅ פחות משבוע<br>
    <span class='dot' style='border:2px solid #FF8800;background:transparent'></span> ⚠️ שבוע–חודש<br>
    <span class='dot' style='border:2px solid #CC2200;background:transparent'></span> 🔴 לא בוקר<br>
    <hr style='margin:5px 0;border-color:#ddd'>
    <small style='color:#666'>{len(markers)} חנויות</small>`;
  return d;
}};
leg.addTo(map);
</script>
</body>
</html>"""


with tab4:
    st.subheader("🗺️ מפת חנויות")

    col_a, col_b = st.columns([3, 1])
    with col_b:
        if st.button("🔄 רענן מפה"):
            get_stores.clear()
            get_deliveries.clear()
            get_manual_visits.clear()
            st.rerun()

    with st.spinner("טוען מפה..."):
        map_stores     = get_stores()
        map_deliveries = get_deliveries()
        map_visits     = get_manual_visits()
        map_html = build_store_map_html(map_stores, map_deliveries, map_visits)

    st.components.v1.html(map_html, height=580, scrolling=False)

    # סיכום מהיר מתחת למפה
    st.caption(
        f"🔵 שילב: {sum(1 for s in map_stores if 'שילב' in s.get('chain',''))} | "
        f"🟢 מכבי: {sum(1 for s in map_stores if 'מכבי' in s.get('chain',''))} | "
        f"🟠 ניצת: {sum(1 for s in map_stores if 'ניצת' in s.get('chain','') or 'הדובדבן' in s.get('chain',''))} | "
        f"⚫ פרטי: {sum(1 for s in map_stores if not s.get('chain',''))} | "
        f"סה\"כ {len(map_stores)} חנויות"
    )

    # ── ייצוא KML ל-Google My Maps ───────────────────────────
    st.divider()
    st.markdown("#### 📥 ייצוא ל-Google My Maps")
    col_kml1, col_kml2 = st.columns([2, 3])
    with col_kml1:
        with st.spinner("בונה קובץ KML..."):
            try:
                _kml_vstats = get_all_visit_stats(map_stores, map_deliveries, map_visits)
                _kml_bytes  = build_kml(map_stores, _kml_vstats)
                _kml_name   = build_kml_filename()
                st.download_button(
                    label="📥 הורד KML (Google My Maps)",
                    data=_kml_bytes,
                    file_name=_kml_name,
                    mime="application/vnd.google-earth.kml+xml",
                    use_container_width=True,
                )
            except Exception as _kml_err:
                st.error(f"שגיאה בבניית KML: {_kml_err}")
    with col_kml2:
        st.info(
            "**איך לייבא ב-Google My Maps:**\n"
            "1. פתח [maps.google.com/maps/d](https://www.google.com/maps/d/) ← צור מפה חדשה\n"
            "2. לחץ **ייבא** ← העלה את קובץ ה-KML\n"
            "3. בחר את עמודת **השם** ← כל הסניפים מופיעים עם צבעים לפי רשת"
        )


# ════════════════════════════════════════════
# לשונית 5 — הוספת חנות חדשה (Rule A + Rule B)
# ════════════════════════════════════════════
with tab5:
    st.subheader("➕ הוסף חנות חדשה")

    if not GITHUB_TOKEN:
        st.error("❌ GITHUB_TOKEN לא מוגדר — לא ניתן לשמור.")
        st.stop()

    if not GOOGLE_MAPS_API_KEY:
        st.warning("⚠️ GOOGLE_MAPS_API_KEY לא מוגדר — הגיאוקודינג יתבצע דרך OpenStreetMap (פחות מדויק).")

    # ── טופס ──────────────────────────────────────────────
    with st.form("add_store_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            new_name  = st.text_input("שם החנות *", placeholder="שילב פתח תקווה קניון")
            new_city  = st.text_input("עיר *", placeholder="פתח תקווה")
            new_chain = st.selectbox("רשת", ["שילב", "מכבי פארם", "ניצת הדובדבן", "פרטי", ""])
        with col2:
            new_addr  = st.text_input("כתובת", placeholder="שד' הנשיא 30")
            new_phone = st.text_input("טלפון", placeholder="03-1234567")

        st.caption("🗺️ הגיאוקודינג מתבצע אוטומטית לפי הכתובת והעיר שהזנת.")
        submitted = st.form_submit_button("🔍 בדוק ושמור", use_container_width=True)

    # ── לוגיקה אחרי הגשה ──────────────────────────────────
    if submitted:
        # ── וולידציה בסיסית ──
        if not new_name.strip() or not new_city.strip():
            st.error("⚠️ שם חנות ועיר הם שדות חובה.")
        else:
            existing_stores = get_stores()

            # ── Rule A: בדיקת כפילויות ──────────────────────
            duplicates = find_duplicate_stores(
                new_name, new_city, new_addr, existing_stores
            )

            if duplicates:
                st.warning(f"⚠️ נמצאו {len(duplicates)} חנות/ות דומות — בדוק לפני שמירה!")
                for dup in duplicates[:5]:
                    st.markdown(
                        f"🔁 **{dup['name']}** | {dup.get('city','')} | "
                        f"{dup.get('address','')}  \n"
                        f"_סיבה: {dup.get('_match_reason','')} _",
                        unsafe_allow_html=False
                    )

                # ── אפשר המשך גם כשיש כפילות חשודה ──
                st.divider()
                if st.button("💾 שמור בכל זאת (אני בטוח שזו חנות חדשה)",
                             key="force_save"):
                    with st.spinner("מגאוקד ושומר..."):
                        ok, geo = save_store_to_github(
                            new_name, new_city, new_addr, new_chain, new_phone
                        )
                    if ok:
                        get_stores.clear()
                        _show_save_success(new_name, new_city, geo)
                    else:
                        st.error("❌ שמירה נכשלה — בדוק GITHUB_TOKEN.")

            else:
                # ── אין כפילות — שמור ישירות ──
                with st.spinner("מגאוקד ושומר..."):
                    ok, geo = save_store_to_github(
                        new_name, new_city, new_addr, new_chain, new_phone
                    )
                if ok:
                    get_stores.clear()
                    _show_save_success(new_name, new_city, geo)
                else:
                    st.error("❌ שמירה נכשלה — בדוק GITHUB_TOKEN.")


def _show_save_success(name: str, city: str, geo: dict | None):
    """מציג הודעת הצלחה עם פרטי גיאוקודינג."""
    st.success(f"✅ חנות **{name}** נשמרה בהצלחה!")
    if geo:
        src_icon = "🗺️ Google Maps" if geo.get("source") == "google" else "🌍 OpenStreetMap"
        st.info(
            f"{src_icon}  \n"
            f"📍 {geo.get('formatted_address', '')}  \n"
            f"🎯 `{geo['lat']}, {geo['lon']}`"
        )
    else:
        st.warning("⚠️ לא הצלחנו לגאוקד — הכתובת נשמרה ללא GPS. תוכל לעדכן אחר כך.")


# ════════════════════════════════════════════════════
# לשונית 6 — מעקב ביקורים (Rule D)
# ════════════════════════════════════════════════════
with tab6:
    st.subheader("📅 מעקב ביקורים — 3 חודשים אחרונים")

    with st.spinner("מחשב היסטוריית ביקורים..."):
        v_stores    = get_stores()
        v_deliveries = get_deliveries()
        v_manual    = get_manual_visits()
        visit_stats = get_all_visit_stats(v_stores, v_deliveries, v_manual)

    # ── נתונים כלליים ──────────────────────────────
    total       = len(v_stores)
    visited_cnt = sum(1 for d in visit_stats.values() if d["days_since"] is not None)
    never_cnt   = total - visited_cnt
    overdue     = get_overdue_stores(visit_stats, v_stores, threshold_days=45)
    warning     = get_overdue_stores(visit_stats, v_stores, threshold_days=21)
    warning     = [s for s in warning if s["days_since"] < 45]

    # ── כרטיסי סיכום ────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("סה\"כ חנויות", total)
    col2.metric("✅ בוקרו", visited_cnt)
    col3.metric("🔴 דחוף (45+ יום)", len(overdue))
    col4.metric("⚫ לא בוקרו מעולם", never_cnt)

    st.divider()

    # ── פילטר תצוגה ─────────────────────────────────
    view = st.radio(
        "הצג:",
        ["🔴 דחוף (45+ ימים)", "🟡 שים לב (21-44 ימים)", "⚫ לא בוקרו כלל", "✅ כל הביקורים"],
        horizontal=True
    )

    # ── בנה טבלה לפי פילטר ──────────────────────────
    if view == "🔴 דחוף (45+ ימים)":
        display_stores = overdue
        empty_msg = "אין חנויות דחופות 🎉"
    elif view == "🟡 שים לב (21-44 ימים)":
        display_stores = warning
        empty_msg = "אין חנויות בהמתנה 👍"
    elif view == "⚫ לא בוקרו כלל":
        display_stores = get_never_visited(visit_stats, v_stores)
        empty_msg = "כל החנויות בוקרו! 🎉"
    else:  # כל הביקורים
        display_stores = sorted(
            [s for s in v_stores if visit_stats.get(s["name"], {}).get("days_since") is not None],
            key=lambda s: visit_stats[s["name"]]["days_since"]
        )
        empty_msg = "אין ביקורים רשומים"

    if not display_stores:
        st.success(empty_msg)
    else:
        st.caption(f"מציג {len(display_stores)} חנויות")

        # ── טבלה ────────────────────────────────────
        tab6_notes = get_notes() + st.session_state.get("local_notes", [])

        for s in display_stores:
            name  = s["name"]
            city  = s.get("city", "")
            chain = s.get("chain", "")
            stats = visit_stats.get(name, {})
            days  = stats.get("days_since") or s.get("days_since")
            last  = stats.get("last_date_str", "—")
            count = stats.get("visit_count", 0)
            label = urgency_label(days)

            # הערות לחנות זו
            store_notes = sorted(
                [n for n in tab6_notes if n.get("store","").strip() == name.strip()],
                key=lambda n: n.get("date",""), reverse=True
            )
            notes_badge = f" 📝{len(store_notes)}" if store_notes else ""

            with st.expander(f"{label}  |  **{name}**  ({city}){notes_badge}", expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.metric("ביקור אחרון", last)
                c2.metric("ימים מאז", days if days is not None else "—")
                c3.metric("ביקורים ב-3 חודשים", count)

                # ── היסטוריית ביקורים ──
                visits_list = stats.get("visits", [])
                if visits_list:
                    st.caption("**📦 היסטוריית ביקורים:**")
                    for v in visits_list[:8]:
                        src_icon = "📦" if v["source"] == "delivery" else "✋"
                        note_str = f" | תעודה #{v['note_id']}" if v.get("note_id") else ""
                        st.text(f"  {src_icon} {v['date'].strftime('%d/%m/%y')}{note_str}")

                # ── הערות CRM ──
                if store_notes:
                    st.caption("**📝 הערות שטח:**")
                    for n in store_notes[:5]:
                        note_txt = n.get("note","")
                        if "ביקרתי" in note_txt:
                            icon = "✅"
                        elif "לא הגעתי" in note_txt:
                            icon = "❌"
                        elif "הזמנה" in note_txt or "דליל" in note_txt:
                            icon = "📋"
                        else:
                            icon = "💬"
                        st.markdown(
                            f"&nbsp;&nbsp;{icon} **{n.get('date','')}** — {note_txt}",
                            unsafe_allow_html=True
                        )

                st.divider()
                col_a, col_b = st.columns([2, 1])
                with col_b:
                    # כפתור רישום ביקור מהיר
                    if st.button("✅ ביקרתי עכשיו", key=f"visit_{name}"):
                        today_str = today_il()
                        ok = save_visit_to_github(today_str, name, city, "ביקור", "")
                        if ok:
                            get_manual_visits.clear()
                            st.success("✅ נרשם!")
                            st.rerun()
                with col_a:
                    # הוספת הערה מהירה ישירות מהטאב
                    quick_note = st.text_input("הערה מהירה", key=f"qnote_{name}",
                                               placeholder="הוסף הערה...")
                    if st.button("💾 שמור הערה", key=f"qsave_{name}") and quick_note:
                        ok = save_note_to_github(today_il(), name, city,
                                                  f"[הערה כללית] {quick_note}")
                        if ok:
                            get_notes.clear()
                            st.success("✅ הערה נשמרה!")
                            st.rerun()

    st.divider()

    # ── העלאת תעודות משלוח ──────────────────────────
    st.subheader("📤 העלאת תעודות משלוח")
    st.caption("העלה קובץ CSV עם עמודות: id, date, branch (כמו senzey_data.csv)")

    uploaded = st.file_uploader("בחר קובץ CSV", type=["csv"], key="upload_deliveries")
    if uploaded:
        try:
            content   = uploaded.read().decode("utf-8-sig")
            new_rows  = list(csv.DictReader(io.StringIO(content)))
            st.success(f"✅ נטענו {len(new_rows)} תעודות. מאמת...")

            # בדוק עמודות
            required = {"id", "date", "branch"}
            cols = set(new_rows[0].keys()) if new_rows else set()
            if not required.issubset(cols):
                st.error(f"❌ חסרות עמודות: {required - cols}")
            else:
                # הצג תצוגה מקדימה
                st.dataframe(
                    [{"תאריך": r["date"], "סניף": r["branch"], "מזהה": r["id"]}
                     for r in new_rows[:10]],
                    use_container_width=True
                )
                if st.button("💾 הוסף לתעודות הקיימות ב-GitHub", key="save_deliveries"):
                    import base64
                    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/senzey_data.csv"
                    gh_headers = {"Authorization": f"token {GITHUB_TOKEN}",
                                  "Accept": "application/vnd.github.v3+json"}
                    r = requests.get(api, headers=gh_headers)
                    data = r.json()
                    sha  = data.get("sha", "")
                    existing_csv = base64.b64decode(data["content"]).decode("utf-8-sig") if "content" in data else ""

                    # הוסף שורות חדשות
                    new_lines = "\n".join(
                        f"{row.get('id','')},{row.get('date','')},{row.get('customer','')},{row.get('branch','')}"
                        for row in new_rows
                    )
                    updated = existing_csv.rstrip() + "\n" + new_lines + "\n"
                    payload = {
                        "message": f"הוספת {len(new_rows)} תעודות משלוח",
                        "content": base64.b64encode(updated.encode("utf-8")).decode(),
                        "sha": sha
                    }
                    resp = requests.put(api, headers=gh_headers, json=payload)
                    if resp.status_code in [200, 201]:
                        get_deliveries.clear()
                        st.success(f"✅ {len(new_rows)} תעודות נוספו!")
                        st.rerun()
                    else:
                        st.error("❌ שגיאה בשמירה לגיטהאב.")
        except Exception as e:
            st.error(f"❌ שגיאה בקריאת הקובץ: {e}")


# ════════════════════════════════════════════════════
# לשונית 7 — מסלול יומי (Rule B Action 2)
# ════════════════════════════════════════════════════
with tab7:
    st.subheader("🧭 תכנון מסלול יומי")

    route_stores = get_stores()

    # ── סינון ראשוני ───────────────────────────────
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        all_chains = sorted(set(s.get("chain","") or "פרטי" for s in route_stores))
        sel_chains = st.multiselect("סנן לפי רשת", all_chains,
                                     default=[], key="route_chains")
    with col_f2:
        all_cities = sorted(set(s.get("city","") for s in route_stores if s.get("city")))
        sel_cities = st.multiselect("סנן לפי עיר", all_cities,
                                     default=[], key="route_cities")

    # החל סינון
    filtered = filter_stores(
        route_stores,
        cities=sel_cities  if sel_cities  else None,
        chains=sel_chains  if sel_chains  else None
    )

    # ── בחירת חנויות ────────────────────────────────
    st.caption(f"{len(filtered)} חנויות זמינות לאחר סינון")
    store_options = [f"{s['name']} ({s.get('city','')})" for s in filtered]
    store_map     = {f"{s['name']} ({s.get('city','')})": s for s in filtered}

    selected_labels = st.multiselect(
        "בחר חנויות למסלול",
        options=store_options,
        default=[],
        key="route_selection",
        help="בחר 2-23 חנויות (מגבלת Google Maps)"
    )
    selected_stops = [store_map[lbl] for lbl in selected_labels if lbl in store_map]

    # ── נקודת התחלה ─────────────────────────────────
    st.divider()
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        start_name = st.text_input("נקודת התחלה", value="הוד השרון", key="route_start")
    with col_s2:
        start_lat  = st.number_input("Lat", value=32.150, format="%.4f", key="route_lat")
    with col_s3:
        start_lon  = st.number_input("Lon", value=34.893, format="%.4f", key="route_lon")

    travel_mode = st.radio("אמצעי תחבורה", ["🚗 נהיגה", "🚶 הליכה"], horizontal=True)
    mode_str = "driving" if "נהיגה" in travel_mode else "walking"

    # ── חשב מסלול ───────────────────────────────────
    if len(selected_stops) < 2:
        st.info("בחר לפחות 2 חנויות כדי לחשב מסלול.")
    else:
        if len(selected_stops) > 23:
            st.warning("⚠️ Google Maps תומך במקסימום 23 ציונים. נבחרו 23 הראשונות.")
            selected_stops = selected_stops[:23]

        with st.spinner("מחשב מסלול אופטימלי..."):
            route = optimize_route(selected_stops, start_lat, start_lon)
            total_km = total_distance(route)
            gmaps_url = build_gmaps_url(route, start_lat, start_lon, mode_str)
            waze_url  = build_waze_url(route)

        # ── סיכום מסלול ─────────────────────────────
        st.success(f"✅ מסלול מיטבי — {len(route)} עצירות | סה\"כ ~{total_km:.0f} ק\"מ")

        # טבלת עצירות
        st.subheader("📋 סדר הביקורים")
        for i, s in enumerate(route, 1):
            chain = s.get("chain","")
            chain_icon = "🔵" if "שילב" in chain else "🟢" if "מכבי" in chain else "🟠" if "ניצת" in chain else "⚫"
            col_a, col_b, col_c = st.columns([1, 5, 2])
            col_a.markdown(f"**{i}**")
            col_b.markdown(f"{chain_icon} **{s['name']}** — {s.get('city','')}")
            col_c.markdown(f"📏 {s.get('leg_km',0)} ק\"מ")

        st.divider()

        # ── כפתורי ניווט ────────────────────────────
        st.subheader("📱 פתח לניווט")
        col_g, col_w = st.columns(2)
        with col_g:
            st.link_button("🗺️ פתח ב-Google Maps",
                            gmaps_url,
                            use_container_width=True,
                            type="primary")
        with col_w:
            if waze_url:
                st.link_button("🔵 נווט ב-Waze (עצירה ראשונה)",
                                waze_url,
                                use_container_width=True)

        # ── QR Code לסריקה מהנייד ───────────────────
        st.divider()
        st.subheader("📲 סרוק מהטלפון")
        st.caption("סרוק את ה-QR Code כדי לפתוח את המסלול ישירות בנייד שלך")

        qr_buf = build_qr_code(gmaps_url)
        if qr_buf:
            col_qr, col_url = st.columns([1, 2])
            with col_qr:
                st.image(qr_buf, width=200)
            with col_url:
                st.text_area("קישור Google Maps", gmaps_url, height=120, key="route_url_display")
                if st.button("📋 העתק קישור", key="copy_url"):
                    st.toast("✅ הקישור מוכן — העתק מהתיבה למעלה")
        else:
            st.text_area("קישור Google Maps", gmaps_url, height=100, key="route_url_display2")
