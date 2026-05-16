"""
route_planner.py
================
מנוע תכנון מסלול יומי — Rule B Action 2.

פונקציות:
  optimize_route(stores, start_lat, start_lon)  → רשימה מסודרת (Nearest-Neighbor)
  build_gmaps_url(stops)                         → URL ניווט Google Maps
  build_qr_code(url)                             → BytesIO של תמונת QR

פורמט URL של Google Maps עם ציונים:
  https://www.google.com/maps/dir/LAT1,LON1/LAT2,LON2/.../LATn,LONn
"""

import math
import io
from urllib.parse import quote


# ── חישוב מרחק ────────────────────────────────────────────
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """מרחק בק\"מ בין שתי נקודות GPS."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v) if v and str(v).strip() not in ("", "0", "0.0", "None") else default
    except (ValueError, TypeError):
        return default


# ── אלגוריתם Nearest-Neighbor ──────────────────────────────
def optimize_route(stores: list[dict],
                   start_lat: float = 32.150,
                   start_lon: float = 34.893) -> list[dict]:
    """
    מסדר חנויות לפי מסלול Nearest-Neighbor — מנקודת ההתחלה.

    Parameters
    ----------
    stores    : list[dict]  חנויות עם שדות lat, lon, name, city
    start_lat : float       נקודת התחלה (ברירת מחדל: הוד השרון)
    start_lon : float

    Returns
    -------
    list[dict]  — החנויות בסדר המסלול האופטימלי + שדה "leg_km" לכל עצירה
    """
    if not stores:
        return []
    if len(stores) == 1:
        store = stores[0].copy()
        store["leg_km"] = round(haversine(
            start_lat, start_lon,
            _safe_float(store.get("lat"), start_lat),
            _safe_float(store.get("lon"), start_lon)
        ), 1)
        return [store]

    remaining = [s.copy() for s in stores]
    route     = []
    cur_lat, cur_lon = start_lat, start_lon

    while remaining:
        # מצא את הקרובה ביותר
        nearest = min(
            remaining,
            key=lambda s: haversine(cur_lat, cur_lon,
                                     _safe_float(s.get("lat"), cur_lat),
                                     _safe_float(s.get("lon"), cur_lon))
        )
        dist = haversine(cur_lat, cur_lon,
                          _safe_float(nearest.get("lat"), cur_lat),
                          _safe_float(nearest.get("lon"), cur_lon))
        nearest["leg_km"] = round(dist, 1)
        route.append(nearest)
        remaining.remove(nearest)
        cur_lat = _safe_float(nearest.get("lat"), cur_lat)
        cur_lon = _safe_float(nearest.get("lon"), cur_lon)

    return route


def total_distance(route: list[dict],
                   start_lat: float = 32.150,
                   start_lon: float = 34.893) -> float:
    """סה\"כ ק\"מ של המסלול."""
    return sum(s.get("leg_km", 0) for s in route)


# ── בניית URL Google Maps ──────────────────────────────────
def build_gmaps_url(route: list[dict],
                    start_lat: float = 32.150,
                    start_lon: float = 34.893,
                    travelmode: str = "driving") -> str:
    """
    בונה URL ניווט Google Maps עם כל הציונים.

    Google Maps Directions URL format:
    https://www.google.com/maps/dir/ORIGIN/STOP1/STOP2/.../DEST?travelmode=driving

    Parameters
    ----------
    route      : list[dict]  חנויות בסדר המסלול (עם lat, lon)
    start_lat  : float       נקודת ההתחלה
    start_lon  : float
    travelmode : str         "driving" | "walking" | "bicycling"

    Returns
    -------
    str  — URL מוכן לפתיחה בנייד
    """
    if not route:
        return ""

    # נקודת ההתחלה
    stops = [f"{start_lat},{start_lon}"]

    for s in route:
        lat = _safe_float(s.get("lat"))
        lon = _safe_float(s.get("lon"))
        if lat and lon:
            stops.append(f"{lat},{lon}")
        else:
            # fallback — כתובת טקסט אם אין GPS
            addr = f"{s.get('address','')}, {s.get('city','')}, Israel"
            stops.append(quote(addr))

    path = "/".join(stops)
    return f"https://www.google.com/maps/dir/{path}?travelmode={travelmode}"


def build_waze_url(route: list[dict]) -> str:
    """
    URL Waze לנווט לחנות הראשונה במסלול.
    (Waze לא תומך ב-waypoints מרובים דרך URL)
    """
    if not route:
        return ""
    first = route[0]
    lat = _safe_float(first.get("lat"))
    lon = _safe_float(first.get("lon"))
    if lat and lon:
        return f"https://waze.com/ul?ll={lat},{lon}&navigate=yes"
    return ""


# ── QR Code ────────────────────────────────────────────────
def build_qr_code(url: str) -> io.BytesIO | None:
    """
    מייצר תמונת QR Code מ-URL.
    מחזיר BytesIO (PNG) לשימוש ב-st.image().
    """
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except ImportError:
        return None


# ── פונקציית עזר: רשימת חנויות לפי עיר/שרשרת ────────────
def filter_stores(stores: list[dict],
                  cities:  list[str] | None = None,
                  chains:  list[str] | None = None) -> list[dict]:
    """מסנן חנויות לפי ערים ו/או רשתות."""
    result = stores
    if cities:
        result = [s for s in result if s.get("city","") in cities]
    if chains:
        result = [s for s in result
                  if any(c in s.get("chain","") for c in chains)]
    return result


# ── הרצה ישירה (בדיקה) ────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    # בדיקת מסלול דוגמה
    sample = [
        {"name": "שילב הרצליה",    "city": "הרצליה",    "lat": "32.166", "lon": "34.844"},
        {"name": "שילב רעננה",      "city": "רעננה",      "lat": "32.184", "lon": "34.871"},
        {"name": "שילב כפר סבא",    "city": "כפר סבא",    "lat": "32.175", "lon": "34.906"},
        {"name": "שילב נתניה",      "city": "נתניה",      "lat": "32.329", "lon": "34.857"},
        {"name": "שילב פתח תקווה",  "city": "פתח תקווה",  "lat": "32.084", "lon": "34.887"},
    ]

    START_LAT, START_LON = 32.150, 34.893  # הוד השרון

    route = optimize_route(sample, START_LAT, START_LON)
    total = total_distance(route)

    print("📍 מסלול מיטבי מהוד השרון:\n")
    for i, s in enumerate(route, 1):
        print(f"  {i}. {s['name']:30s} | {s['leg_km']} ק\"מ")
    print(f"\n  סה\"כ: {total:.1f} ק\"מ")

    url = build_gmaps_url(route, START_LAT, START_LON)
    print(f"\n🗺️  Google Maps URL:\n  {url[:80]}...")
