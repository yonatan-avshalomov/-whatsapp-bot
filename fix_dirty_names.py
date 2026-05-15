"""מנקה שמות מלוכלכים ב-stores.csv"""
import csv, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("stores.csv", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

before = len(rows)

# מיפוי שמות מלוכלכים לשם נקי / מחיקה
FIXES = {
    "שילב לפגישה אישית עם יועצ/ת הזמנות לידה יש ליצור קשר בטלפון עם": None,  # מחק
    "מכבי תא בלפור מספר":        "מכבי פארם תל אביב בלפור",
    "מכבי פארם ראשל״צ מערב מספר": "מכבי פארם ראשון לציון מערב",
    "מכבי תא השלה :מספר הזמנה":  "מכבי פארם תל אביב השלה",
    "מכבי פארם בלפור ת״א מספר":   "מכבי פארם תל אביב בלפור",
}

# תיקונים לעיר
CITY_FIXES = {
    "מכבי פארם תל אביב בלפור":   "תל אביב",
    "מכבי פארם ראשון לציון מערב": "ראשון לציון",
    "מכבי פארם תל אביב השלה":    "תל אביב",
}

CITY_COORDS_PARTIAL = {
    "תל אביב":     ("32.0853", "34.7818"),
    "ראשון לציון": ("31.9642", "34.8066"),
}

new_rows = []
fixed = 0
removed = 0

# בדוק אם שם נקי כבר קיים ברשימה
existing_names = set(r["name"] for r in rows)

for r in rows:
    name = r["name"]

    if name in FIXES:
        replacement = FIXES[name]
        if replacement is None:
            print(f"  🗑️  מסיר: '{name}'")
            removed += 1
            continue
        # בדוק אם הגרסה הנקייה כבר קיימת
        if replacement in existing_names:
            print(f"  🗑️  מסיר כפיל מלוכלך: '{name}' (קיים: '{replacement}')")
            removed += 1
            continue
        # תיקון
        print(f"  ✅ '{name}' → '{replacement}'")
        r["name"] = replacement
        city = CITY_FIXES.get(replacement, "")
        if city:
            r["city"] = city
            coords = CITY_COORDS_PARTIAL.get(city)
            if coords and not r.get("lat"):
                r["lat"], r["lon"] = coords
        fixed += 1

    new_rows.append(r)

with open("stores.csv", "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(new_rows)

print(f"\n✅ תוקנו: {fixed} | הוסרו: {removed} | סה\"כ: {len(new_rows)} (היה: {before})")
