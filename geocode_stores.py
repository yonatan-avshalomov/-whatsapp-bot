"""
geocode_stores.py
=================
מוסיף קואורדינטות GPS (lat, lon) לכל חנות ב-stores.csv
משתמש ב-Nominatim (OpenStreetMap) — בחינם, ללא API Key

הרצה: python geocode_stores.py
"""

import csv
import sys
import time
import requests

sys.stdout.reconfigure(encoding="utf-8")

INPUT_FILE  = "stores.csv"
OUTPUT_FILE = "stores.csv"

HEADERS = {
    "User-Agent": "store-manager-il/1.0 (yonatan@avshalomov.com)",
    "Accept-Language": "he,en"
}

# קואורדינטות ברירת מחדל לפי עיר (כשאין כתובת מדויקת)
CITY_COORDS = {
    "הוד השרון":   (32.150, 34.893),
    "רעננה":        (32.184, 34.871),
    "כפר סבא":     (32.175, 34.906),
    "ראש העין":    (32.096, 34.958),
    "פתח תקווה":   (32.084, 34.887),
    "תל אביב":     (32.087, 34.780),
    "ת\"א":        (32.087, 34.780),
    "רמת גן":      (32.082, 34.814),
    "גבעתיים":     (32.071, 34.812),
    "בני ברק":     (32.084, 34.834),
    "חולון":        (32.011, 34.779),
    "בת ים":        (32.019, 34.751),
    "ראשון לציון": (31.964, 34.806),
    "נס ציונה":    (31.929, 34.795),
    "רחובות":       (31.896, 34.811),
    "יבנה":         (31.877, 34.744),
    "רמלה":         (31.929, 34.872),
    "לוד":          (31.952, 34.898),
    "נתניה":        (32.329, 34.857),
    "הרצליה":       (32.165, 34.843),
    "רמת השרון":   (32.146, 34.840),
    "אור יהודה":   (32.028, 34.856),
    "יהוד":         (32.030, 34.888),
    "קרית אונו":   (32.059, 34.861),
    "גני תקווה":   (32.057, 34.877),
    "אלעד":         (32.053, 34.951),
    "מודיעין":      (31.893, 35.010),
    "מבשרת ציון":  (31.805, 35.152),
    "ירושלים":      (31.768, 35.214),
    "בית שמש":     (31.745, 34.988),
    "אשדוד":        (31.804, 34.649),
    "אשקלון":       (31.668, 34.572),
    "חיפה":         (32.794, 34.989),
    "קרית אתא":    (32.813, 35.107),
    "קרית ביאליק": (32.831, 35.079),
    "קרית מוצקין": (32.836, 35.074),
    "קרית טבעון":  (32.723, 35.132),
    "עפולה":        (32.607, 35.289),
    "נצרת":         (32.701, 35.303),
    "נוף הגליל":   (32.701, 35.303),
    "יוקנעם":       (32.660, 35.100),
    "מגדל העמק":   (32.676, 35.239),
    "בית שאן":     (32.498, 35.499),
    "טבריה":        (32.795, 35.531),
    "נהריה":        (33.007, 35.098),
    "כרמיאל":       (32.916, 35.298),
    "עכו":          (32.926, 35.082),
    "חדרה":         (32.434, 34.918),
    "זכרון יעקב":  (32.573, 34.952),
    "בנימינה":      (32.524, 34.948),
    "פרדס חנה":    (32.474, 34.969),
    "קדימה":        (32.271, 34.914),
    "אור עקיבא":   (32.508, 34.920),
    "באר שבע":     (31.244, 34.791),
    "נתיבות":       (31.424, 34.591),
    "אופקים":       (31.314, 34.622),
    "קרית גת":     (31.606, 34.770),
    "ערד":          (31.258, 35.215),
    "דימונה":       (31.066, 35.033),
    "אילת":         (29.558, 34.952),
    "אריאל":        (32.103, 35.171),
    "אום אל פחם":  (32.524, 35.152),
    "נשר":          (32.773, 35.042),
    "גדרה":         (31.812, 34.779),
    "שוהם":         (31.990, 34.943),
    "מעלות":        (33.015, 35.271),
    "קרית שמונה":  (33.207, 35.571),
    "צפת":          (32.963, 35.496),
    "רמת ישי":     (32.708, 35.168),
    "כרכור":        (32.484, 34.978),
    "אבן יהודה":   (32.261, 34.891),
    "טל מונד":     (32.262, 34.921),
    "כפר ויתקין":  (32.375, 34.905),
    "בית שמש":     (31.745, 34.988),
    "מודיעין עילית": (31.930, 35.043),
    "ביתר עילית":  (31.697, 35.119),
    "אפרת":         (31.658, 35.166),
    "חריש":         (32.459, 35.031),
    "קרית ים":     (32.854, 35.073),
}


def get_city_coords(city: str):
    for key, coords in CITY_COORDS.items():
        if key in city or city in key:
            return coords
    return None


def geocode_address(address: str, city: str):
    """מנסה לגאוקד כתובת מדויקת, נופל על מרכז העיר."""
    if address and len(address) > 3:
        try:
            query = f"{address}, {city}, Israel"
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "il"},
                headers=HEADERS,
                timeout=8
            )
            data = r.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"]), "address"
        except Exception:
            pass
        time.sleep(1.1)   # Nominatim rate limit: 1 req/sec

    # fallback: מרכז עיר
    coords = get_city_coords(city)
    if coords:
        return coords[0], coords[1], "city"
    return None, None, "unknown"


def main():
    # קרא קובץ קיים
    with open(INPUT_FILE, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    fieldnames = ["chain", "name", "city", "address", "phone", "lat", "lon"]

    # בדוק כמה כבר יש קואורדינטות
    already_done = sum(1 for r in rows if r.get("lat") and r.get("lat") != "")
    todo = [r for r in rows if not r.get("lat") or r.get("lat") == ""]

    print(f"סה\"כ: {len(rows)} חנויות | כבר יש קואורדינטות: {already_done} | נשאר: {len(todo)}")

    done = 0
    for i, row in enumerate(rows):
        if row.get("lat") and row.get("lat") != "":
            continue   # כבר יש

        city    = row.get("city", "")
        address = row.get("address", "")

        lat, lon, source = geocode_address(address, city)

        row["lat"] = str(lat) if lat else ""
        row["lon"] = str(lon) if lon else ""
        done += 1

        print(f"[{done}/{len(todo)}] {row['name'][:35]:<35} → {lat:.4f},{lon:.4f} ({source})" if lat else
              f"[{done}/{len(todo)}] {row['name'][:35]:<35} → לא נמצא")

        # שמור כל 20 חנויות (גיבוי)
        if done % 20 == 0:
            with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            print(f"  💾 נשמר ({done} חנויות חדשות)")

    # שמירה סופית
    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    success = sum(1 for r in rows if r.get("lat"))
    print(f"\n✅ הושלם! {success}/{len(rows)} חנויות עם קואורדינטות GPS")


if __name__ == "__main__":
    main()
