"""
fix_stores_data.py
==================
תיקון stores.csv:
1. שמות כפולים — מוסיף עיר לשם כשאותו שם מופיע בערים שונות
2. GPS שגוי — 11 חנויות מכבי קיבלו GPS של הוד השרון (32.15,34.893), מתקן לפי שם/עיר
3. שמות מסנזי לא נוקו — מסיר "מספר הזמנה" משמות חנויות
"""
import csv, re, sys, math
sys.stdout.reconfigure(encoding="utf-8")

CITY_COORDS = {
    "הוד השרון":      (32.150, 34.893),
    "רעננה":          (32.184, 34.871),
    "כפר סבא":        (32.175, 34.906),
    "ראש העין":       (32.096, 34.958),
    "פתח תקווה":      (32.084, 34.887),
    "תל אביב":        (32.087, 34.780),
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
    "חיפה":           (32.794, 34.989),
    "קרית אתא":       (32.813, 35.107),
    "קרית ביאליק":    (32.831, 35.079),
    "קרית מוצקין":    (32.836, 35.074),
    "קרית טבעון":     (32.723, 35.132),
    "קריית טבעון":    (32.723, 35.132),
    "עפולה":          (32.607, 35.289),
    "נצרת":           (32.701, 35.303),
    "נוף הגליל":      (32.701, 35.303),
    "יוקנעם":         (32.660, 35.100),
    "יקנעם":          (32.660, 35.100),
    "מגדל העמק":      (32.676, 35.239),
    "בית שאן":        (32.498, 35.499),
    "טבריה":          (32.795, 35.531),
    "נהריה":          (33.007, 35.098),
    "כרמיאל":         (32.916, 35.298),
    "עכו":            (32.926, 35.082),
    "חדרה":           (32.434, 34.918),
    "זכרון יעקב":     (32.573, 34.952),
    "זכרון":          (32.573, 34.952),
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
    "נשר":            (32.773, 35.042),
    "שוהם":           (31.990, 34.943),
    "מודיעין עילית":  (31.930, 35.043),
    "ביתר עילית":     (31.697, 35.119),
    "אפרת":           (31.658, 35.166),
    "קרית ים":        (32.854, 35.073),
    "קרית שמונה":     (33.207, 35.571),
    "צפת":            (32.963, 35.496),
    "רמת ישי":        (32.708, 35.168),
    "באר יעקב":       (31.943, 34.839),
    "גדרה":           (31.812, 34.779),
    "יהוד":           (32.030, 34.888),
    "בית שאן":        (32.498, 35.499),
    "מעלות":          (33.015, 35.271),
}

HOME = (32.150, 34.893)

def get_city_from_name(name):
    """שולף עיר משם חנות — לדוגמה 'מכבי פארם יקנעם' → 'יקנעם'"""
    for city in sorted(CITY_COORDS.keys(), key=len, reverse=True):
        if city in name:
            return city
    return ""

def get_city_coords(city):
    for key, coords in CITY_COORDS.items():
        if key in city or city in key:
            return coords
    return None

with open("stores.csv", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

print(f"נטענו {len(rows)} חנויות")
fixed_gps = 0
fixed_names = 0
fixed_senzey = 0
removed = 0

# ─── תיקון 1: ניקוי שמות שנכנסו מסנזי לא נוקו ─────────────────────────────
for r in rows:
    original = r["name"]
    cleaned = re.sub(r'מספר הזמנה[\s:]*[\d]+', '', original)
    cleaned = re.sub(r'הזמנה[\s\-]*[\-\s]*\d+', '', cleaned)
    cleaned = re.sub(r'\s*:\s*$', '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    if cleaned != original:
        print(f"  🔧 שם: '{original}' → '{cleaned}'")
        r["name"] = cleaned
        fixed_senzey += 1

# ─── תיקון 2: GPS שגוי — חנויות שקיבלו GPS של הוד השרון בטעות ────────────
HOME_THRESHOLD = 0.002   # כ-200 מטר — כל מה שקרוב מזה הוא חשוד (אלא אם בהוד השרון)
wrong_gps = []
for r in rows:
    try:
        lat = float(r.get("lat", "") or "nan")
        lon = float(r.get("lon", "") or "nan")
        if abs(lat - HOME[0]) < HOME_THRESHOLD and abs(lon - HOME[1]) < HOME_THRESHOLD:
            city = r.get("city", "")
            if city not in ("הוד השרון", "הוד", ""):
                wrong_gps.append(r)
            elif not city:
                # אם גם העיר ריקה — חשוד
                wrong_gps.append(r)
    except ValueError:
        pass

print(f"\nנמצאו {len(wrong_gps)} חנויות עם GPS שגוי (קיבלו קואורדינטות הוד השרון):")
for r in wrong_gps:
    # נסה לחלץ עיר מהשם
    name = r["name"]
    city = r.get("city", "") or get_city_from_name(name)

    # אם מצאנו עיר — עדכן GPS
    coords = get_city_coords(city) if city else None
    if coords:
        print(f"  ✅ '{name}' → עיר: {city} | GPS: {coords[0]},{coords[1]}")
        r["lat"] = str(coords[0])
        r["lon"] = str(coords[1])
        if not r.get("city"):
            r["city"] = city
        fixed_gps += 1
    else:
        print(f"  ⚠️  '{name}' — לא נמצאה עיר, מסיר GPS שגוי")
        r["lat"] = ""
        r["lon"] = ""
        fixed_gps += 1

# ─── תיקון 3: שמות כפולים — מוסיף עיר לשם ──────────────────────────────────
from collections import Counter
name_counts = Counter(r["name"] for r in rows)
dup_names = {n for n, c in name_counts.items() if c > 1}

print(f"\nכפולים ({len(dup_names)}):")
seen_name_city = set()
to_remove = []

for i, r in enumerate(rows):
    name = r["name"]
    city = r.get("city", "")
    addr = r.get("address", "")

    if name not in dup_names:
        continue

    # אדונית התבלינים — אותה כתובת, עיר שונה → מחק את זה בלי עיר
    if name == "אדונית התבלינים" and not city and addr:
        # בדוק אם יש גרסה עם עיר ואותה כתובת
        twin = next((r2 for r2 in rows if r2["name"] == name and r2["city"] and r2["address"] == addr), None)
        if twin:
            print(f"  🗑️  מסיר כפיל: '{name}' (ריק עיר, כתובת זהה ל{twin['city']})")
            to_remove.append(i)
            removed += 1
            continue

    # אחרים — הוסף עיר לשם
    if city:
        new_name = f"{name} {city}"
        print(f"  🔧 '{name}' → '{new_name}'")
        r["name"] = new_name
        fixed_names += 1

# מחק כפולים שיש להסיר
rows = [r for i, r in enumerate(rows) if i not in to_remove]

# ─── שמירה ─────────────────────────────────────────────────────────────────
with open("stores.csv", "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"""
✅ סיכום תיקונים:
   GPS תוקן: {fixed_gps}
   שמות נוקו מסנזי: {fixed_senzey}
   כפולים תוקנו: {fixed_names}
   כפולים הוסרו: {removed}
   סה"כ חנויות: {len(rows)}
""")
