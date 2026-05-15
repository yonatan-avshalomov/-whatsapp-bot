"""
test_bot.py — בדיקת תקינות מלאה של הבוט
"""
import csv, io, re, math, sys, requests
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")

ISRAEL_TZ = timezone(timedelta(hours=3))
PASS, FAIL, WARN = "✅", "❌", "⚠️ "

results = []

def check(name, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, name, detail))
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))

def warn(name, detail=""):
    results.append((WARN, name, detail))
    print(f"  {WARN}{name}" + (f" — {detail}" if detail else ""))

GITHUB_RAW = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main"
HOME = (32.150, 34.893)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def clean_senzey_branch(branch):
    branch = re.sub(r'הזמנה[\s\-]*[\-\s]*\d+', '', branch)
    branch = re.sub(r'\s*-\s*$', '', branch)
    branch = re.sub(r'\s{2,}', ' ', branch).strip()
    branch = branch.replace('מכבי שירותי בריאות', 'מכבי פארם')
    return branch.strip()

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("1️⃣  טעינת קבצים מ-GitHub")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# stores.csv
stores = []
try:
    r = requests.get(f"{GITHUB_RAW}/stores.csv", timeout=15)
    text = r.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    stores = rows
    check("stores.csv נטען", True, f"{len(rows)} חנויות")
except Exception as e:
    check("stores.csv נטען", False, str(e))

# senzey_data.csv
deliveries = []
try:
    r = requests.get(f"{GITHUB_RAW}/senzey_data.csv", timeout=15)
    text = r.content.decode("utf-8-sig")
    deliveries = list(csv.DictReader(io.StringIO(text)))
    check("senzey_data.csv נטען", True, f"{len(deliveries)} תעודות")
except Exception as e:
    check("senzey_data.csv נטען", False, str(e))

# store_notes.csv
try:
    r = requests.get(f"{GITHUB_RAW}/store_notes.csv", timeout=10)
    notes = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    check("store_notes.csv נטען", True, f"{len(notes)} הערות")
except Exception as e:
    check("store_notes.csv נטען", False, str(e))

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("2️⃣  תאריך ושעון ישראל")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

now_utc = datetime.now(timezone.utc)
now_il  = datetime.now(ISRAEL_TZ)
today   = now_il.strftime("%d/%m/%y")
check("שעון ישראל", True, f"עכשיו: {now_il.strftime('%d/%m/%Y %H:%M')} (UTC: {now_utc.strftime('%H:%M')})")
check("פורמט תאריך", today.count("/") == 2, f"today='{today}'")

# תעודות היום
today_del = [d for d in deliveries if d.get("date","").startswith(today)]
check("תעודות היום מזוהות", True, f"{len(today_del)} תעודות עם תאריך {today}")
if today_del:
    for d in today_del[:3]:
        print(f"     → {d['date']} | {clean_senzey_branch(d['branch'])}")

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("3️⃣  עמודות ונתוני GPS ב-stores.csv")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

if stores:
    cols = list(stores[0].keys())
    check("עמודת lat קיימת", "lat" in cols)
    check("עמודת lon קיימת", "lon" in cols)

    with_gps = [s for s in stores if s.get("lat") and s.get("lon")]
    no_gps   = [s for s in stores if not s.get("lat") or not s.get("lon")]
    check("חנויות עם GPS", len(with_gps) > 300, f"{len(with_gps)}/{len(stores)}")
    if no_gps:
        warn("חנויות ללא GPS", f"{len(no_gps)} חנויות — לדוגמה: {no_gps[0]['name']}")

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("4️⃣  מיון לפי מרחק מהוד השרון")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

if stores:
    def dist(s):
        try:
            return haversine(HOME[0], HOME[1], float(s["lat"]), float(s["lon"]))
        except:
            return 999

    sorted_s = sorted([s for s in stores if s.get("lat")], key=dist)
    closest = sorted_s[:5]
    farthest = sorted_s[-3:]
    check("מיון לפי GPS", True, "5 קרובות:")
    for s in closest:
        print(f"     {dist(s):.1f}ק\"מ — {s['name']} ({s['city']})")
    print("  רחוקות ביותר:")
    for s in farthest:
        print(f"     {dist(s):.0f}ק\"מ — {s['name']} ({s['city']})")

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("5️⃣  התאמת תעודות לחנויות (ניקוי + מיקום)")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# בנה מיפוי branch_last_date
branch_last: dict[str,str] = {}
for d in deliveries:
    cl = clean_senzey_branch(d.get("branch",""))
    dt = d.get("date","")
    if cl and (cl not in branch_last or dt > branch_last[cl]):
        branch_last[cl] = dt

def last_del(store_name):
    best = None
    for cl, dt in branch_last.items():
        if store_name in cl or cl in store_name:
            if best is None or dt > best:
                best = dt
    return best

# בדוק כמה חנויות מוצאות תעודה
matched = [(s["name"], last_del(s["name"])) for s in stores if last_del(s["name"])]
check("חנויות עם תעודה מזוהה", len(matched) > 50, f"{len(matched)}/{len(stores)}")

# בדוק שאין false-positive: שילב ראש העין לא מתאים לשילב חיפה
test_cases = [
    ("שילב ראש העין",  "שילב עפולה",      False),  # לא אמור להתאים
    ("שילב נצרת",      "שילב נצרת",       True),   # אמור להתאים
    ("שילב נתניה עיר ימים", "שילב נתניה פולג", False),  # לא אמור
    ("מכבי פארם ראש העין הציונות", "מכבי פארם חיפה חורב", False),
]
all_ok = True
for store_name, branch, expected in test_cases:
    cl = clean_senzey_branch(branch)
    got = store_name in cl or cl in store_name
    ok  = (got == expected)
    if not ok:
        all_ok = False
        print(f"  ❌ '{store_name}' vs '{branch}' → התאים={got} אבל צפוי={expected}")
check("אין false-positive בהתאמות", all_ok)

# דוגמאות התאמות טובות
print("  דוגמאות תעודות אחרונות לחנויות:")
sample_stores = ["שילב נצרת", "שילב עפולה", "מכבי פארם ראש העין הציונות",
                 "ניצת הדובדבן הוד השרון", "שילב נתניה עיר ימים"]
for name in sample_stores:
    ld = last_del(name)
    status = f"אחרון: {ld}" if ld else "אין תעודה"
    print(f"     {name}: {status}")

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("6️⃣  ניקוי שמות מסנזי")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

clean_tests = [
    ("מכבי קריית טבעון הזמנה-107011388",         "מכבי קריית טבעון"),
    ("מכבי פארם ראשון לציון נחלת הזמנה-106891820","מכבי פארם ראשון לציון נחלת"),
    ("מכבי פארם אום אל פחם הזמנה- -106878225",   "מכבי פארם אום אל פחם"),
    ("מכבי שירותי בריאות",                        "מכבי פארם"),
    ("שילב עפולה",                                 "שילב עפולה"),
]
clean_ok = True
for raw, expected in clean_tests:
    got = clean_senzey_branch(raw)
    ok  = (got == expected)
    if not ok:
        clean_ok = False
        print(f"  ❌ '{raw}' → '{got}' (צפוי: '{expected}')")
check("ניקוי שמות סנזי", clean_ok)

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("7️⃣  שמות כפולים / בעייתיים בחנויות")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

from collections import Counter
name_counts = Counter(s["name"] for s in stores)
dupes = [(n, c) for n, c in name_counts.items() if c > 1]
check("אין שמות כפולים", len(dupes) == 0, f"{len(dupes)} כפולים" if dupes else "")
for n, c in dupes[:10]:
    print(f"     ⚠️  '{n}' מופיע {c}x")

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("8️⃣  סיכום רשתות")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

by_chain = Counter(s.get("chain","פרטי") or "פרטי" for s in stores)
for chain, cnt in sorted(by_chain.items(), key=lambda x: -x[1]):
    print(f"     {chain}: {cnt}")
check("ניצת הדובדבן > 70", by_chain.get("ניצת הדובדבן",0) >= 70)
check("שילב > 50",         by_chain.get("שילב",0) >= 50)
check("מכבי פארם > 80",    by_chain.get("מכבי פארם",0) >= 80)

# ══════════════════════════════════════════════════════════
print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("🏁 סיכום בדיקות")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
warned = sum(1 for r in results if r[0] == WARN)
total  = len(results)
print(f"  עברו: {passed}/{total}  |  נכשלו: {failed}  |  אזהרות: {warned}")
if failed == 0:
    print("\n  🎉 הבוט תקין!")
else:
    print("\n  🔧 יש בעיות לתיקון:")
    for icon, name, detail in results:
        if icon == FAIL:
            print(f"     ❌ {name}: {detail}")
