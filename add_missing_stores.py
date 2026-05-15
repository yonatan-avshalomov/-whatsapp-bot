"""מוסיף חנויות חסרות ישירות ל-stores.csv"""
import csv, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("stores.csv", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

existing_names = {r["name"] for r in rows}

# חנויות חדשות להוסיף עם GPS
NEW_STORES = [
    # מכבי פארם באר שבע — סניפים חסרים
    {"chain": "מכבי פארם", "name": "מכבי פארם באר שבע גרנד קניון",
     "city": "באר שבע", "address": "גרנד קניון, טוביהו דוד 125", "phone": "",
     "lat": "31.2560", "lon": "34.7956"},
    {"chain": "מכבי פארם", "name": "מכבי פארם באר שבע קרית הממשלה",
     "city": "באר שבע", "address": "קרית הממשלה, תקווה 4", "phone": "",
     "lat": "31.2460", "lon": "34.7900"},
    {"chain": "מכבי פארם", "name": "מכבי פארם באר שבע רמות",
     "city": "באר שבע", "address": "שכונת רמות", "phone": "",
     "lat": "31.2700", "lon": "34.8100"},
    # מכבי פארם אשקלון — סניף נוסף
    {"chain": "מכבי פארם", "name": "מכבי פארם אשקלון עזריאלי",
     "city": "אשקלון", "address": "עזריאלי אשקלון", "phone": "",
     "lat": "31.6590", "lon": "34.5700"},
    # ניצת הדובדבן באר שבע — מול 7 (חנות פיזית)
    {"chain": "ניצת הדובדבן", "name": "ניצת הדובדבן באר שבע מול 7",
     "city": "באר שבע", "address": "מרכז מסחרי מול 7", "phone": "",
     "lat": "31.2440", "lon": "34.7920"},
]

added = 0
for s in NEW_STORES:
    if s["name"] not in existing_names:
        rows.append(s)
        existing_names.add(s["name"])
        print(f"  ➕ {s['name']} ({s['city']})")
        added += 1
    else:
        print(f"  ✓ כבר קיים: {s['name']}")

with open("stores.csv", "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"\n✅ נוספו {added} חנויות | סה\"כ: {len(rows)}")
