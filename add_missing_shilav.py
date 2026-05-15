"""מוסיף סניפי שילב חסרים שזוהו בתעודות הסנזי"""
import csv, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("stores.csv", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

existing = {r["name"] for r in rows}

NEW = [
    # שרונים הוד השרון — מזוהה בסנזי: "שילב שרונים הוד השרון"
    {"chain":"שילב","name":"שילב שרונים הוד השרון","city":"הוד השרון",
     "address":"שרונים", "phone":"","lat":"32.148","lon":"34.887"},
    # טבריה — "שילב טבריה"
    {"chain":"שילב","name":"שילב טבריה","city":"טבריה",
     "address":"","phone":"","lat":"32.795","lon":"35.531"},
    # יוקנעם — "שילב יוקנעם"
    {"chain":"שילב","name":"שילב יוקנעם","city":"יוקנעם",
     "address":"","phone":"","lat":"32.660","lon":"35.100"},
    # זכרון יעקב — "שילב זכרון יעקב"
    {"chain":"שילב","name":"שילב זכרון יעקב","city":"זכרון יעקב",
     "address":"","phone":"","lat":"32.573","lon":"34.952"},
    # שדרות — "שילב שדרות"
    {"chain":"שילב","name":"שילב שדרות","city":"שדרות",
     "address":"","phone":"","lat":"31.524","lon":"34.597"},
    # תל השומר (רמת גן) — "שילב תל השומר"
    {"chain":"שילב","name":"שילב תל השומר","city":"רמת גן",
     "address":"בי\"ח תל השומר","phone":"","lat":"32.037","lon":"34.853"},
    # תלפיות ירושלים — "שילב תלפיות"
    {"chain":"שילב","name":"שילב ירושלים תלפיות","city":"ירושלים",
     "address":"תלפיות","phone":"","lat":"31.752","lon":"35.228"},
    # אום אל פחם — "שילב אום אל פחם"
    {"chain":"שילב","name":"שילב אום אל פחם","city":"אום אל פחם",
     "address":"","phone":"","lat":"32.524","lon":"35.152"},
    # סורוקה ב"ש — "שילב בית חולים סורוקה"
    {"chain":"שילב","name":"שילב בית חולים סורוקה","city":"באר שבע",
     "address":"בי\"ח סורוקה","phone":"","lat":"31.258","lon":"34.800"},
    # שערי צדק ירושלים — "שילב בית חולים שערי צדק ירושלים"
    {"chain":"שילב","name":"שילב בית חולים שערי צדק","city":"ירושלים",
     "address":"בי\"ח שערי צדק","phone":"","lat":"31.789","lon":"35.191"},
    # ראשונים ראשון לציון — "שילב ראשונים"
    {"chain":"שילב","name":"שילב ראשונים ראשון לציון","city":"ראשון לציון",
     "address":"קניון ראשונים","phone":"","lat":"31.971","lon":"34.790"},
    # נמל תל אביב — "שילב נמל תא"
    {"chain":"שילב","name":"שילב נמל תל אביב","city":"תל אביב",
     "address":"נמל תל אביב","phone":"","lat":"32.102","lon":"34.781"},
    # טייבה — "שילב טייבה"
    {"chain":"שילב","name":"שילב טייבה","city":"טייבה",
     "address":"","phone":"","lat":"32.361","lon":"35.008"},
]

added = 0
for s in NEW:
    if s["name"] not in existing:
        rows.append(s)
        existing.add(s["name"])
        print(f"  ➕ {s['name']} ({s['city']})")
        added += 1
    else:
        print(f"  ✓ קיים: {s['name']}")

with open("stores.csv", "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"\n✅ נוספו {added} | סהכ {len(rows)}")
