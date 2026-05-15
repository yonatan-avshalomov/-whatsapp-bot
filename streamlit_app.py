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
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
    GOOGLE_SHEET_ID   = st.secrets["GOOGLE_SHEET_ID"]
    GITHUB_TOKEN      = st.secrets.get("GITHUB_TOKEN", "")
except Exception:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    GOOGLE_SHEET_ID   = os.getenv("GOOGLE_SHEET_ID", "")
    GITHUB_TOKEN      = os.getenv("GITHUB_TOKEN", "")

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
@st.cache_data(ttl=300)
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


@st.cache_data(ttl=60)
def get_notes():
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/store_notes.csv"
        r = requests.get(url, timeout=10)
        text = r.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    except:
        return []


@st.cache_data(ttl=60)
def get_manual_visits():
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/manual_visits.csv"
        r = requests.get(url, timeout=10)
        text = r.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    except:
        return []


def save_note_to_github(date, store, city, note):
    """שומר הערה חדשה לקובץ store_notes.csv בגיטהאב."""
    if not GITHUB_TOKEN:
        return False
    try:
        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{NOTES_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

        # קבל תוכן נוכחי
        r = requests.get(api, headers=headers)
        data = r.json()
        current = ""
        sha = ""
        if "content" in data:
            import base64
            current = base64.b64decode(data["content"]).decode("utf-8-sig")
            sha = data["sha"]

        # הוסף שורה
        new_line = f'\n{date},{store},{city},"{note}"'
        updated = current.rstrip() + new_line + "\n"

        import base64
        payload = {
            "message": f"הערה חדשה: {store}",
            "content": base64.b64encode(updated.encode("utf-8")).decode(),
            "sha": sha
        }
        r = requests.put(api, headers=headers, json=payload)
        return r.status_code in [200, 201]
    except:
        return False


def save_visit_to_github(date, store, city, status, notes=""):
    """שומר ביקור ידני לקובץ manual_visits.csv בגיטהאב."""
    if not GITHUB_TOKEN:
        return False
    try:
        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{VISITS_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

        r = requests.get(api, headers=headers)
        data = r.json()
        current, sha = "", ""
        if "content" in data:
            import base64
            current = base64.b64decode(data["content"]).decode("utf-8-sig")
            sha = data["sha"]

        new_line = f'\n{date},{store},{city},{status},{notes}'
        updated = current.rstrip() + new_line + "\n"

        import base64
        payload = {
            "message": f"ביקור: {store}",
            "content": base64.b64encode(updated.encode("utf-8")).decode(),
            "sha": sha
        }
        r = requests.put(api, headers=headers, json=payload)
        return r.status_code in [200, 201]
    except:
        return False


# ── ניקוי שמות סניפים מסנזי ──────────────────────────────
def clean_senzey_branch(branch: str) -> str:
    """ניקוי שם סניף סנזי לצורך התאמה לשמות חנויות.
    מסיר מספרי הזמנה, מנרמל קיצורים ואיותים."""
    # נרמול גרשיים עבריים (U+05F4/U+05F3) → תווים רגילים
    branch = branch.replace('״', '"').replace('׳', "'")
    # הסרת מספרי הזמנה בסגנונות שונים
    branch = re.sub(r'הזמנה[\s\-:]*\d+', '', branch)
    branch = re.sub(r'מספר הזמנה\s*:?\s*\d+', '', branch)
    branch = re.sub(r':מספר הזמנה\s*\d+', '', branch)
    branch = re.sub(r'\bהזמנת רכש[\s\-]*[\d]+', '', branch)
    # הסרת מספרים בודדים בתחילת/סוף השם
    branch = re.sub(r'^\d{7,}\s*', '', branch)   # 7+ ספרות בהתחלה
    branch = re.sub(r'\s+\d{7,}$', '', branch)   # 7+ ספרות בסוף
    branch = re.sub(r'\s+10[0-9]{7,}', '', branch)  # ID שמתחיל ב-10...
    # נרמול קיצורים נפוצים (replace פשוט — ללא regex בגלל תווים מיוחדים)
    branch = branch.replace('ת"א', 'תל אביב').replace('ת.א.', 'תל אביב')
    branch = branch.replace('ראשל"צ', 'ראשון לציון')
    branch = re.sub(r'ק\.\s*יובל', 'קרית יובל', branch)
    # נרמול איות קריית→קרית + שגיאות כתיב
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
    # פילטר GARBAGE — ספקים / חברות שאינן חנויות רלוונטיות
    GARBAGE = {
        'בל בוקס בע"מ', "בל בוקס", 'מור סילבר', "מור סילבר בע"מ",
        "לוגיסטיקה", "מחסן", "ספק",
    }
    if any(g in branch for g in GARBAGE):
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
        if diff <= 14:
            return f"⚠️ לפני {diff} ימים"
        if diff <= 30:
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

        # ── מקור 2: ביקורים ידניים ──────────────────────────
        manual_best = manual_last.get(store_name)
        if manual_best:
            # המר לפורמט DD/MM/YY 00:00 לצורך השוואה
            try:
                parts = manual_best.split("/")
                manual_comparable = f"20{parts[2]}-{parts[1]}-{parts[0]} 00:00"
            except Exception:
                manual_comparable = None
        else:
            manual_comparable = None

        # בחר את המאוחר
        candidates = [(senzey_best, senzey_best), (manual_comparable, manual_best)]
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
            extra = sorted(
                [s for s in stores if s not in set(in_city + nearby)],
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

    # הערות
    if notes:
        lines.append(f"\nהערות שטח אחרונות:")
        for n in notes[-10:]:
            lines.append(f"• {n.get('date','')} | {n.get('store','')} — {n.get('note','')}")

    return "\n".join(lines)[:12000]


# ── שאל את Claude ─────────────────────────────────────────
def is_history_question(msg):
    """זיהוי שאלות על היסטוריה/ביקורים שכבר היו — אסור לענות עליהן מהדמיון."""
    keywords = ["איפה היית", "איפה הייתי", "איפה הלכת", "ביקרת היום",
                "מה עשית", "היום הייתי", "היום ביקרתי", "סיכום היום",
                "כמה ביקרת", "אצל מי היית"]
    return any(k in msg for k in keywords)


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

tab1, tab2, tab3 = st.tabs(["💬 שיחה", "📝 הוסף הערה", "📊 סיכום יום"])


# ════════════════════════════
# לשונית 1 — שיחה
# ════════════════════════════
with tab1:
    if "messages" not in st.session_state:
        st.session_state.messages = [{
            "role": "assistant",
            "content": "שלום! אני העוזר לניהול החנויות שלך 🏪\n\n• **מה יש לי ב[עיר]** — רשימת חנויות\n• **מה דחוף** — מה לא בוקר הרבה זמן\n• **סיכום היום** — מה יצא היום\n\nמה תרצה לדעת?"
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

                # שאלות היסטוריה — תשובה ישירה מהנתונים, ללא Claude
                if is_history_question(prompt):
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

    # הצג הערות אחרונות
    st.divider()
    st.subheader("הערות אחרונות")
    all_notes = get_notes()
    local     = st.session_state.get("local_notes", [])
    combined  = (all_notes + local)[-15:][::-1]

    if combined:
        for n in combined:
            st.markdown(f"""<div class='note-card'>
                <b>{n.get('store','')}</b> — {n.get('city','')}<br>
                <small>{n.get('date','')}</small><br>
                {n.get('note','')}
            </div>""", unsafe_allow_html=True)
    else:
        st.info("אין הערות עדיין")


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
        for v in today_vis:
            icon = "✅" if v.get("status") == "ביקור" else "⚠️"
            st.markdown(f"{icon} {v.get('store','')} — {v.get('status','')}")

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
