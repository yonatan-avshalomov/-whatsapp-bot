"""
geocoder.py
===========
מודול מרכזי לגיאוקודינג — Google Maps Geocoding API עם cache מקומי.

שימוש:
    from geocoder import geocode, geocode_batch

    result = geocode("וייצמן 14", "תל אביב")
    # → {"lat": 32.08, "lon": 34.79, "formatted_address": "...", "place_id": "...", "source": "google"}

עיצוב:
    ┌──────────────────────────────────────────────┐
    │  geocode(address, city)                       │
    │       ↓                                       │
    │  1. Cache hit? → return immediately           │
    │  2. Google Maps API → parse result            │
    │  3. Validate: in Israel? city match?          │
    │  4. Save to cache → return result             │
    │  5. Fallback: Nominatim (אם אין API Key)      │
    └──────────────────────────────────────────────┘
"""

import os, json, time, math, logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── הגדרות ─────────────────────────────────────────────────────────────────
CACHE_FILE    = Path(__file__).parent / "geocode_cache.json"
LOG_FILE      = Path(__file__).parent / "geocode_log.txt"
RATE_LIMIT    = 0.05   # שניות בין קריאות Google (20 req/sec בחינמי)
NOM_RATE      = 1.2    # שניות בין קריאות Nominatim (חייב ≥1s)

# גבולות ישראל (lat/lon bounding box) — רחב מעט לכסות אילת + גולן
ISRAEL_BBOX = {"lat_min": 29.0, "lat_max": 33.5, "lon_min": 34.0, "lon_max": 36.0}

# קואורדינטות מרכזי ערים — לזיהוי כשל גיאוקודינג (דיפולט מרכז עיר)
_CITY_CENTER: dict[str, tuple[float, float]] = {
    "תל אביב":       (32.087,  34.780),
    "ירושלים":       (31.768,  35.214),
    "חיפה":          (32.794,  34.989),
    "באר שבע":       (31.244,  34.791),
    "נתניה":         (32.329,  34.857),
    "ראשון לציון":   (31.964,  34.806),
    "הרצליה":        (32.165,  34.843),
    "פתח תקווה":     (32.084,  34.887),
    "אשדוד":         (31.804,  34.649),
    "חולון":         (32.011,  34.779),
    "רמת גן":        (32.082,  34.814),
    "בני ברק":       (32.084,  34.834),
    "רעננה":         (32.184,  34.871),
    "כפר סבא":       (32.175,  34.906),
    "מודיעין":       (31.893,  35.010),
    "הוד השרון":     (32.150,  34.893),
    "כרמיאל":        (32.916,  35.298),
    "נהריה":         (33.007,  35.098),
    "עפולה":         (32.607,  35.289),
    "נצרת":          (32.701,  35.303),
    "אשקלון":        (31.668,  34.572),
    "רחובות":        (31.896,  34.811),
    "חדרה":          (32.434,  34.918),
    "עכו":           (32.926,  35.082),
    "טבריה":         (32.795,  35.531),
    "קרית גת":       (31.606,  34.770),
    "נס ציונה":      (31.929,  34.795),
    "רמלה":          (31.929,  34.872),
    "לוד":           (31.952,  34.898),
}

logging.basicConfig(
    filename=str(LOG_FILE), level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S", encoding="utf-8"
)
log = logging.getLogger(__name__)

# ── Cache ───────────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def _cache_key(address: str, city: str) -> str:
    return f"{address.strip()}|{city.strip()}".lower()

# ── בדיקות תקינות ───────────────────────────────────────────────────────────
def _in_israel(lat: float, lon: float) -> bool:
    b = ISRAEL_BBOX
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]

def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def _is_city_center_default(lat: float, lon: float, city: str,
                             threshold_m: float = 350) -> bool:
    """
    מחזיר True אם הקואורדינטות נמצאות בטווח threshold_m מטרים ממרכז העיר.
    סימן אזהרה: Google דיפולט למרכז עיר במקום כתובת ספציפית.
    """
    for key, (clat, clon) in _CITY_CENTER.items():
        if key in city or city in key:
            return haversine(lat, lon, clat, clon) * 1000 <= threshold_m
    return False


# ── Google Places Text Search ─────────────────────────────────────────────────
def _geocode_places(name: str, city: str, api_key: str) -> dict | None:
    """
    מחפש עסק לפי שם + עיר ב-Google Places Text Search API.
    מדויק יותר מגיאוקודינג רגיל כי מוצא את העסק עצמו.

    query לדוגמה: "שילב נהריה ביג" → מחזיר את המיקום המדויק של הסניף.
    """
    import requests

    query  = f"{name} {city} ישראל".strip()
    url    = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query":    query,
        "language": "he",
        "region":   "il",
        "key":      api_key,
    }

    try:
        r    = requests.get(url, params=params, timeout=10)
        data = r.json()
    except Exception as e:
        log.error(f"Places API error for '{query}': {e}")
        return None

    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        log.error(f"Places API status {data.get('status')} for '{query}'")
        return None

    results = data.get("results", [])
    if not results:
        log.warning(f"Places: no results for '{query}'")
        return None

    # ── נסה למצוא תוצאה בתוך ישראל ──
    for res in results[:3]:
        loc = res["geometry"]["location"]
        lat, lon = loc["lat"], loc["lng"]
        if _in_israel(lat, lon):
            suspected = _is_city_center_default(lat, lon, city)
            if suspected:
                log.warning(f"Places: city-center default suspected for '{query}' → {lat},{lon}")
            return {
                "lat":                  round(lat, 6),
                "lon":                  round(lon, 6),
                "formatted_address":    res.get("formatted_address", ""),
                "place_id":             res.get("place_id", ""),
                "source":               "places",
                "geocoded_at":          datetime.now().strftime("%Y-%m-%d"),
                "city_center_suspected": suspected,
            }

    log.warning(f"Places: all results outside Israel for '{query}'")
    return None


# ── Google Maps Geocoding ─────────────────────────────────────────────────────
def _geocode_google(address: str, city: str, api_key: str) -> dict | None:
    """
    קוראת ל-Google Maps Geocoding API (לפי כתובת).
    מחזירה dict עם lat, lon, formatted_address, place_id
    או None אם נכשל.
    """
    import googlemaps

    gmaps = googlemaps.Client(key=api_key)
    # ── Bulletproof query: always include city + ישראל in Hebrew ──
    query = f"{address}, {city}, ישראל" if city else f"{address}, ישראל"

    try:
        results = gmaps.geocode(query, language="he", region="il")
    except Exception as e:
        log.error(f"Google API error for '{query}': {e}")
        return None

    if not results:
        log.warning(f"Google: no results for '{query}'")
        return None

    r    = results[0]
    loc  = r["geometry"]["location"]
    lat, lon = loc["lat"], loc["lng"]

    if not _in_israel(lat, lon):
        log.warning(f"Google: result outside Israel for '{query}' → {lat},{lon}")
        return None

    suspected = _is_city_center_default(lat, lon, city)
    if suspected:
        log.warning(f"Google: city-center default suspected for '{query}' → {lat},{lon}")

    return {
        "lat":                  round(lat, 6),
        "lon":                  round(lon, 6),
        "formatted_address":    r.get("formatted_address", ""),
        "place_id":             r.get("place_id", ""),
        "source":               "google",
        "geocoded_at":          datetime.now().strftime("%Y-%m-%d"),
        "city_center_suspected": suspected,
    }

# ── Nominatim (fallback) ─────────────────────────────────────────────────────
def _geocode_nominatim(address: str, city: str) -> dict | None:
    """
    Nominatim (OSM) כ-fallback חינמי אם אין Google API Key.
    """
    import requests

    query = f"{address}, {city}, Israel" if city else f"{address}, Israel"
    url   = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1,
              "countrycodes": "il", "accept-language": "he"}
    headers = {"User-Agent": "store-manager-geocoder/2.0"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
    except Exception as e:
        log.error(f"Nominatim error for '{query}': {e}")
        return None

    if not data:
        log.warning(f"Nominatim: no results for '{query}'")
        return None

    lat, lon = float(data[0]["lat"]), float(data[0]["lon"])

    if not _in_israel(lat, lon):
        log.warning(f"Nominatim: result outside Israel for '{query}' → {lat},{lon}")
        return None

    suspected = _is_city_center_default(lat, lon, city)
    if suspected:
        log.warning(f"Nominatim: city-center default suspected for '{query}' → {lat},{lon}")

    return {
        "lat":                  round(lat, 6),
        "lon":                  round(lon, 6),
        "formatted_address":    data[0].get("display_name", ""),
        "place_id":             data[0].get("osm_id", ""),
        "source":               "nominatim",
        "geocoded_at":          datetime.now().strftime("%Y-%m-%d"),
        "city_center_suspected": suspected,
    }

# ── פונקציה ראשית (לפי שם עסק — הכי מדויק) ──────────────────────────────────
def geocode_store(name: str, address: str = "", city: str = "",
                  force: bool = False) -> dict | None:
    """
    מגאוקד חנות לפי שם העסק (Places API) עם fallback לכתובת.

    סדר העדיפויות:
      1. Cache
      2. Google Places Text Search (שם + עיר)  ← הכי מדויק
      3. Google Geocoding (כתובת + עיר)
      4. Nominatim (OSM) — fallback חינמי

    Parameters
    ----------
    name    : str   שם החנות (לדוגמה: "שילב נהריה ביג")
    address : str   כתובת הרחוב (אופציונלי)
    city    : str   שם העיר
    force   : bool  אם True — מתעלם מה-cache

    Returns
    -------
    dict עם:  lat, lon, formatted_address, place_id, source, geocoded_at
    None      אם הגיאוקודינג נכשל לחלוטין
    """
    # cache key כולל שם + כתובת + עיר
    key   = f"store|{name.strip()}|{city.strip()}".lower()
    cache = _load_cache()

    if not force and key in cache:
        log.info(f"Cache hit (store): '{name}, {city}'")
        return cache[key]

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # ── 1. Google Places (לפי שם) ──
    if api_key and name:
        time.sleep(RATE_LIMIT)
        result = _geocode_places(name, city, api_key)
        if result:
            cache[key] = result
            _save_cache(cache)
            log.info(f"Places OK: '{name}, {city}' → {result['lat']},{result['lon']}")
            return result
        log.warning(f"Places failed for '{name}, {city}' — trying Geocoding")

    # ── 2. Google Geocoding (לפי כתובת) ──
    if api_key and address:
        time.sleep(RATE_LIMIT)
        result = _geocode_google(address, city, api_key)
        if result:
            cache[key] = result
            _save_cache(cache)
            log.info(f"Geocoding OK: '{address}, {city}' → {result['lat']},{result['lon']}")
            return result
        log.warning(f"Geocoding failed for '{address}, {city}' — trying Nominatim")

    # ── 3. Nominatim fallback ──
    query_addr = address or name
    time.sleep(NOM_RATE)
    result = _geocode_nominatim(query_addr, city)
    if result:
        cache[key] = result
        _save_cache(cache)
        log.info(f"Nominatim OK: '{query_addr}, {city}' → {result['lat']},{result['lon']}")
        return result

    log.error(f"FAILED all geocoders: '{name}, {city}'")
    return None


# ── פונקציה ראשית (לפי כתובת בלבד) ─────────────────────────────────────────
def geocode(address: str, city: str = "", force: bool = False) -> dict | None:
    """
    מחזיר קואורדינטות מדויקות לכתובת נתונה.

    Parameters
    ----------
    address : str   כתובת הרחוב (ללא עיר)
    city    : str   שם העיר בעברית
    force   : bool  אם True — מתעלם מה-cache ומבצע קריאה חדשה

    Returns
    -------
    dict עם:  lat, lon, formatted_address, place_id, source, geocoded_at
    None      אם הגיאוקודינג נכשל
    """
    key   = _cache_key(address, city)
    cache = _load_cache()

    # ── Cache hit ──
    if not force and key in cache:
        log.info(f"Cache hit: '{address}, {city}'")
        return cache[key]

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # ── Google Maps ──
    if api_key:
        time.sleep(RATE_LIMIT)
        result = _geocode_google(address, city, api_key)
        if result:
            cache[key] = result
            _save_cache(cache)
            log.info(f"Google OK: '{address}, {city}' → {result['lat']},{result['lon']}")
            return result
        log.warning(f"Google failed for '{address}, {city}' — trying Nominatim")

    # ── Nominatim fallback ──
    time.sleep(NOM_RATE)
    result = _geocode_nominatim(address, city)
    if result:
        cache[key] = result
        _save_cache(cache)
        log.info(f"Nominatim OK: '{address}, {city}' → {result['lat']},{result['lon']}")
        return result

    log.error(f"FAILED all geocoders: '{address}, {city}'")
    return None


def geocode_batch(stores: list[dict], force: bool = False,
                  skip_with_coords: bool = True) -> tuple[int, int, int]:
    """
    מריץ geocode על רשימת חנויות ומעדכן lat/lon/formatted_address בכל אחת.

    Parameters
    ----------
    stores           : list[dict]  רשימת חנויות (כל אחת dict עם address, city, lat, lon)
    force            : bool        אם True — מגאוקד מחדש גם חנויות עם קואורדינטות קיימות
    skip_with_coords : bool        אם True — מדלג על חנויות שכבר יש להן lat/lon תקין

    Returns
    -------
    (updated, skipped, failed) : tuple[int, int, int]
    """
    updated = skipped = failed = 0

    for i, store in enumerate(stores, 1):
        name    = store.get("name", "")
        address = store.get("address", "").strip()
        city    = store.get("city", "").strip()

        # ── דלג אם כבר יש קואורדינטות ──
        if skip_with_coords and not force:
            try:
                lat = float(store.get("lat") or 0)
                lon = float(store.get("lon") or 0)
                if lat > 0 and lon > 0:
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                pass

        # ── דלג אם אין כתובת ──
        if not address:
            print(f"[{i:3}] ⚠️  {name[:40]:<40} | אין כתובת — מדלג")
            failed += 1
            continue

        print(f"[{i:3}] 🔍 {name[:40]:<40} | {address[:30]}", end=" ... ", flush=True)
        result = geocode(address, city, force=force)

        if result:
            store["lat"] = str(result["lat"])
            store["lon"] = str(result["lon"])
            # שמור כתובת מנורמלת של Google אם עדיין אין כתובת טובה
            if result.get("formatted_address") and result["source"] == "google":
                store["formatted_address"] = result["formatted_address"]
            updated += 1
            src = "🗺️ Google" if result["source"] == "google" else "🌍 OSM"
            print(f"✅ {src} → {result['lat']:.4f},{result['lon']:.4f}")
        else:
            failed += 1
            print("❌ נכשל")

    return updated, skipped, failed


# ── הרצה ישירה (בדיקה מהירה) ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    tests = [
        ("וייצמן 14", "תל אביב"),
        ("ביג רגבה", "נהריה"),
        ("דרך העלייה 8", "חיפה"),
        ("שמחה גולן 12", "חיפה"),
        ("דרך עכו 192", "קרית ביאליק"),
    ]

    print("🔍 בדיקת Geocoder\n" + "="*50)
    for addr, city in tests:
        r = geocode(addr, city)
        if r:
            print(f"✅ {addr}, {city}")
            print(f"   lat={r['lat']}, lon={r['lon']}")
            print(f"   📍 {r['formatted_address'][:70]}")
            print(f"   מקור: {r['source']}\n")
        else:
            print(f"❌ {addr}, {city} — נכשל\n")
