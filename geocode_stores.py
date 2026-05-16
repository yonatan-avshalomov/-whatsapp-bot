"""
geocode_stores.py
מבצע reverse geocoding לכל החנויות ב-stores.csv (lat/lon -> כתובת רחוב)
משתמש ב-Nominatim (OSM) — חינמי, ללא API key.
"""
import csv, sys, time, requests
sys.stdout.reconfigure(encoding="utf-8")

INPUT  = "stores.csv"
OUTPUT = "stores_with_addr.csv"

HEADERS = {"User-Agent": "StoreManager/1.0 (nitzat-bot@gmail.com)"}

def reverse_geocode(lat, lon):
    """lat/lon -> כתובת רחוב עברית מ-Nominatim."""
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat}&lon={lon}&format=json&accept-language=he&addressdetails=1"
        )
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        a = data.get("address", {})

        road    = a.get("road") or a.get("pedestrian") or a.get("path") or ""
        house   = a.get("house_number", "")
        quarter = a.get("suburb") or a.get("neighbourhood") or ""
        city    = a.get("city") or a.get("town") or a.get("village") or ""

        parts = []
        if road:
            parts.append(road + (" " + house if house else ""))
        if quarter and quarter not in (road or ""):
            parts.append(quarter)

        return ", ".join(parts) if parts else city
    except Exception as e:
        return ""


with open(INPUT, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    fieldnames = list(reader.fieldnames)
    stores = list(reader)

if "address" not in fieldnames:
    fieldnames.append("address")

total   = len(stores)
updated = 0

for i, s in enumerate(stores):
    lat = s.get("lat","").strip()
    lon = s.get("lon","").strip()

    existing = s.get("address","").strip()
    looks_like_hours    = any(kw in existing for kw in ["ימים", "שעות", "א'-ה'", "א-ה", "סייל", "פעילות"])
    looks_like_city_only = existing in (s.get("city","").strip(), "")
    needs_geocode = (not existing) or looks_like_hours or looks_like_city_only

    if not needs_geocode:
        print(f"[{i+1}/{total}] skip  {s['name'][:40]}")
        continue

    if not lat or not lon or lat in ("0","0.0") or lon in ("0","0.0"):
        print(f"[{i+1}/{total}] no GPS {s['name'][:40]}")
        continue

    addr = reverse_geocode(lat, lon)
    if addr:
        s["address"] = addr
        updated += 1
        print(f"[{i+1}/{total}] OK  {s['name'][:35]:35s}  ->  {addr}")
    else:
        print(f"[{i+1}/{total}] fail  {s['name'][:40]}")

    time.sleep(1.1)

with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(stores)

print(f"\nנשמר: {OUTPUT}")
print(f"עודכנו: {updated} / {total}")
