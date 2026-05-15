import csv, sys, math
sys.stdout.reconfigure(encoding="utf-8")

with open("stores.csv", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# כפולים
name_map = {}
for r in rows:
    name_map.setdefault(r["name"], []).append(r)

print("=== כפולים ===")
for name, group in name_map.items():
    if len(group) > 1:
        for r in group:
            print(f"  שם: {r['name']}")
            print(f"  עיר: {r['city']} | כתובת: {r['address']} | רשת: {r['chain']}")
            print()

# GPS חשוד
HOME = (32.150, 34.893)
def dist_deg(s):
    try:
        return abs(float(s["lat"]) - HOME[0]) + abs(float(s["lon"]) - HOME[1])
    except:
        return 999

print("=== חנויות עם GPS קרוב מאוד להוד השרון (חשוד) ===")
for r in rows:
    if r.get("lat") and dist_deg(r) < 0.001 and r["city"] not in ("הוד השרון", "הוד"):
        print(f"  {r['name']} | עיר: {r['city']} | lat={r['lat']} lon={r['lon']}")
