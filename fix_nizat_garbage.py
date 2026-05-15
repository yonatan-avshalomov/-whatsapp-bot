"""מנקה ערכי סניף משלוחים וזבל מניצת הדובדבן ב-stores.csv"""
import csv, re, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("stores.csv", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

before = len(rows)
clean_rows = []

for r in rows:
    name = r.get("name", "")
    addr = r.get("address", "")
    city = r.get("city", "")

    # הסר ערכי סניף משלוחים — אלה לא חנויות פיזיות שביקרנו בהן
    if "סניף משלוחים" in name or "סניף משלוחים" in addr or "סניף משלוחים" in city:
        print(f"  🗑️  מסיר: {name[:60]}")
        continue

    # נקה שם עיר שנדבק אליו "סניף משלוחים" (כבר מנוקה משם, אבל בדוק עיר)
    city_clean = re.sub(r'סניף משלוחים.*', '', city).strip()
    if city_clean != city:
        r["city"] = city_clean

    # הסר שעות פתיחה שנשארו בכתובת
    addr_clean = re.sub(r'שעות פתיחה.*', '', addr).strip()
    addr_clean = re.sub(r'חניה חינם.*', '', addr_clean).strip()
    addr_clean = re.sub(r'אזורי חלוקת.*', '', addr_clean).strip()
    if addr_clean != addr:
        r["address"] = addr_clean

    clean_rows.append(r)

with open("stores.csv", "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(clean_rows)

print(f"\n✅ הוסרו {before - len(clean_rows)} ערכי סניף משלוחים | נשארו {len(clean_rows)} חנויות")
