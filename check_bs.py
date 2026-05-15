import csv, sys, re
sys.stdout.reconfigure(encoding="utf-8")

with open("senzey_data.csv", encoding="utf-8-sig") as f:
    deliveries = list(csv.DictReader(f))

with open("stores.csv", encoding="utf-8-sig") as f:
    stores = list(csv.DictReader(f))

def clean(branch):
    branch = re.sub(r'הזמנה[\s\-]*[\-\s]*\d+', '', branch)
    branch = re.sub(r'\s*-\s*$', '', branch)
    branch = re.sub(r'\s{2,}', ' ', branch).strip()
    branch = branch.replace('מכבי שירותי בריאות', 'מכבי פארם')
    return branch.strip()

store_names = {r["name"] for r in stores}

# כל שמות הסניפים הייחודיים בסנזי (נקיים)
senzey_branches = {}
for d in deliveries:
    cl = clean(d["branch"])
    if cl and cl not in senzey_branches:
        senzey_branches[cl] = d["date"]

print("=== תעודות שלא מתאימות לאף חנות ברשימה ===")
unmatched = []
for branch, date in sorted(senzey_branches.items()):
    found = any(name in branch or branch in name for name in store_names)
    if not found:
        unmatched.append((branch, date))
        print(f"  ❌ {branch} | {date[:8]}")

print(f"\nסהכ {len(unmatched)} תעודות ללא חנות מתאימה")

print("\n=== חנויות מהרשימה שאין להן אף תעודה בסנזי ===")
no_delivery = []
for s in stores:
    name = s["name"]
    found = any(name in b or b in name for b in senzey_branches)
    if not found:
        no_delivery.append(name)

print(f"  {len(no_delivery)} חנויות ללא תעודה (מוצג ראשון 20)")
for n in no_delivery[:20]:
    print(f"  - {n}")
