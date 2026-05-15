"""בודק התאמות בדיוק כפי שעושה streamlit_app.py (מסונכרן עם הגרסה הנוכחית)"""
import csv, sys, re
sys.stdout.reconfigure(encoding="utf-8")

with open("senzey_data.csv", encoding="utf-8-sig") as f:
    deliveries = list(csv.DictReader(f))
with open("stores.csv", encoding="utf-8-sig") as f:
    stores = list(csv.DictReader(f))

def clean_senzey_branch(branch: str) -> str:
    branch = branch.replace('״', '"').replace('׳', "'")
    branch = re.sub(r'הזמנה[\s\-:]*\d+', '', branch)
    branch = re.sub(r'מספר הזמנה\s*:?\s*\d+', '', branch)
    branch = re.sub(r':מספר הזמנה\s*\d*', '', branch)
    branch = re.sub(r'\s+\d{6,}\s*:?\s*מספר.*$', '', branch)
    branch = re.sub(r'\bהזמנת רכש[\s\-]*[\d]+', '', branch)
    branch = re.sub(r'^\d{7,}\s*', '', branch)
    branch = re.sub(r'\s+\d{7,}$', '', branch)
    branch = re.sub(r'\s+10[0-9]{7,}', '', branch)
    branch = re.sub(r'\s*מספר\s*:?\s*$', '', branch)
    branch = branch.replace('ת"א', 'תל אביב').replace('ת.א.', 'תל אביב')
    branch = re.sub(r'(?<!\S)תא(?!\S)', 'תל אביב', branch)
    branch = branch.replace('ראשל"צ', 'ראשון לציון')
    branch = re.sub(r'ק\.\s*יובל', 'קרית יובל', branch)
    branch = branch.replace('קריית', 'קרית')
    branch = branch.replace('מודיעים', 'מודיעין')
    branch = branch.replace('השלה', 'השלום')
    branch = re.sub(r'\s*[-–]\s*הזמנה\s*$', '', branch)
    branch = branch.replace('מכבי שירותי בריאות', 'מכבי פארם')
    branch = re.sub(r'(מכבי פארם)\s*-\s*', r'\1 ', branch)
    branch = re.sub(r'\s*-\s*$', '', branch)
    branch = re.sub(r'\s{2,}', ' ', branch).strip()
    GARBAGE_KEYWORDS = [
        'בל בוקס', 'מור סילבר', 'ביו גאיה', 'סופרסאפ', 'ווולט',
        'תעודת משלוח רכש', 'הזמנת רכש', 'פרסום ושיווק', 'פרסום ומכירות',
        'שמן אמבט', 'שמן עיסוי', 'קרם החתלה', 'קרטון משלוחים',
        'אתר סחר', 'אתר חודש', 'מבצע חודש', 'מבצע באתר',
        'תחליב גוף', 'שמפו', 'החתלה/', '/קרם',
        'מחסן ', 'מוס /', 'סבון החתלה', 'מכירות ווולט',
    ]
    if any(g in branch for g in GARBAGE_KEYWORDS):
        return ""
    if re.match(r'^\d{2}/\d{2}(/\d{2,4})?', branch):
        return ""
    return branch.strip()

SENZEY_ALIASES = {
    "שילב גלילות":                   "שילב רמת השרון",
    "שילב קריון":                    "שילב קרית ביאליק",
    "שילב רגבה":                     "שילב נהריה ביג",
    "שילב שבעת הכוכבים הרצליה":     "שילב הרצליה",
    "שילב דיזינגוף סנטר":           "שילב תל אביב דיזנגוף",
    "שילב דיזינגוף":                "שילב תל אביב דיזנגוף",
    "שילב בית חולים בלינסון":       "שילב פתח תקווה בילינסון",
    "שילב בית חולים ברזילי":        "שילב אשקלון ברזילי",
    "שילב נמל תא":                  "שילב נמל תל אביב",
    'שילב נמל ת"א':                 "שילב נמל תל אביב",
    "שילב נמל ת׳א":                 "שילב נמל תל אביב",
    "שילב פולג":                     "שילב נתניה פולג",
    "שילב קניון הזהב":              "שילב ראשון לציון",
    "שילב קניון הזהב ראשון-לציון":  "שילב ראשון לציון",
    "שילב קניון הזהב ראשון לציון":  "שילב ראשון לציון",
    "שילב ביג יהוד":                "שילב יהוד",
    "שילב ביג אשדוד":               "שילב אשדוד ביג",
    "שילב ביג באר שבע":             "שילב באר שבע ביג",
    "ביג באר שבע שילב":             "שילב באר שבע ביג",
    "שילב גרנד באר שבע":            "שילב באר שבע גרנד קניון",
    "שילב גרנד ברר שבע":            "שילב באר שבע גרנד קניון",
    "שילב גרנד חיפה":               "שילב חיפה גרנד קניון",
    "שילב גרנד קניון חיפה":         "שילב חיפה גרנד קניון",
    "שילב עזריאלי חיפה":            "שילב חיפה עזריאלי",
    "שילב חוצות חיפה":              "שילב חיפה חוצות המפרץ",
    "שילב שער הצפון קרית אתא":      "שילב קרית אתא",
    "שילב תלפיות":                  "שילב ירושלים תלפיות",
    "שילב ויצמן":                   "שילב כפר סבא קניון ערים",
    "שילב כפר סבא g":               "שילב כפר סבא קניון G",
    "שילב אבנת פתח תקווה":          "שילב פתח תקווה אבנת",
    "שילב גלובל פתח תקווה":         "שילב פתח תקווה גלובל",
    "שילב שרונים":                  "שילב שרונים הוד השרון",
    "שילב ראשונים":                 "שילב ראשונים ראשון לציון",
    "שילב רמת אביב":                "שילב תל אביב רמת אביב",
    "שילב גן העיר":                 "שילב תל אביב גן העיר",
    "שילב אסותא אשדוד":             "שילב אשדוד אסותא",
    "שילב אסף הרופא":               "שילב באר יעקב אסף הרופא",
    "שילב עיר ימים":                "שילב נתניה עיר ימים",
    "שילב פולג נתניה":              "שילב נתניה פולג",
    "שילב מבשרת":                   "שילב מבשרת ציון",
    "שילב אשדוד סטאר":             "שילב אשדוד סטאר סנטר",
    "שילב אשקלון סילבר":           "שילב אשקלון סילבר",
    'שילב ג׳י כפס':               "שילב כפר סבא קניון G",
    "שילב ג'י כפס":               "שילב כפר סבא קניון G",
    "שילב רננים":                  "שילב רעננה קניון רננים",
    "שילב שער ראשון":              "שילב שער ראשון",
    "בית שילב":                    "שילב בני ברק אילון",
    "בית שילב אילון":              "שילב בני ברק אילון",
    "שילב גן העיק":                  "שילב תל אביב גן העיר",
    "ראש העין הציונות מכבי פארם":   "מכבי פארם ראש העין הציונות",
    "ראשון לציון מזרח - מכבי פארם ראשון לציון מזרח": "מכבי פארם ראשון לציון מזרח",
    "ראשון לציון מזרח - מכבי שירותי בריאות - ראשון לציון מזרח": "מכבי פארם ראשון לציון מזרח",
    "כפר סבא הירוקה - מכבי פארם - כפר סבא הירוקה": "מכבי פארם כפר סבא הירוקה",
    "עקיבא - מכבי פארם בני ברק - עקיבא": "מכבי פארם בני ברק עקיבא",
    "נוף הגליל - מכבי פארם נצרת נוף הגליל": "מכבי פארם נצרת נוף הגליל",
    "מכבי הרצליה":                   "מכבי פארם הרצליה",
    "מכבי פארם חיפה-הדר":            "מכבי פארם חיפה הדר",
    "מכבי פארם יד אליהו":            "מכבי פארם תל אביב יד אליהו",
    "מכבי פארם תל אביב- התקומה":    "מכבי פארם תל אביב התקומה",
    "מכבי פארם מודיעים עלית":        "מכבי פארם מודיעין עילית",
    "מכבי פארם ק. יובל ירושלים":    "מכבי פארם קרית יובל ירושלים",
    "מכבי פארם ק. יובל":             "מכבי פארם קרית יובל ירושלים",
    "מכבי פארם מ.פ. ק.יובל ירושלים": "מכבי פארם קרית יובל ירושלים",
    "מכבי פארם גני ראשון ראשון לציון": "מכבי פארם גני ראשון ראשון לציון",
    "מכבי פארם קרית מוצקין":           "מכבי פארם קריית מוצקין- גושן",
    "מכבי קרית טבעון":                 "מכבי פארם קרית טבעון",
    "מכבי פארם גבעתיים":               "מכבי גבעתיים",
    "מכבי פארם מבשרת":                 "מכבי פארם מבשרת ציון",
    "מכבי פארם השלום תל אביב":         "מכבי פארם תל אביב השלום",
    "מכבי תל אביב השלום":              "מכבי פארם תל אביב השלום",
    "שקדייה גבעתיים":               "שקדיה גבעתיים",
    "שקדייה הוד השרון":             "שקדיה הוד השרון",
    "שקדייה רמת גן":                "שקדיה רמת גן",
}

STOP_WORDS = {"שילב", "מכבי", "פארם", "ניצת", "הדובדבן", "בית", "חולים",
              "קניון", "מרכז", "ביג", "פארק", "סניף", "סנטר", "שירותי", "בריאות"}

def get_chain(text):
    if "שילב" in text: return "שילב"
    if "מכבי" in text: return "מכבי"
    if "ניצת" in text or "הדובדבן" in text: return "ניצת"
    return ""

def norm_word(w: str) -> str:
    return w.replace('קריית', 'קרית').replace('מודיעים', 'מודיעין')

def words_overlap(a: str, b: str) -> int:
    wa = {norm_word(w) for w in a.split() if len(w) > 1 and w not in STOP_WORDS}
    wb = {norm_word(w) for w in b.split() if len(w) > 1 and w not in STOP_WORDS}
    return len(wa & wb)

def names_match(store_name, branch):
    aliased = SENZEY_ALIASES.get(branch, branch)
    if aliased == store_name: return True
    sc, bc = get_chain(store_name), get_chain(branch)
    if sc and bc and sc != bc: return False
    if store_name in branch or branch in store_name: return True
    if words_overlap(store_name, branch) >= 2: return True
    return False

store_names = [r["name"] for r in stores]

branches = {}
for d in deliveries:
    cl = clean_senzey_branch(d["branch"])
    if cl and cl not in branches:
        branches[cl] = d["date"]

real_branches = {b: d for b, d in branches.items() if len(b) > 4}

matched, unmatched = [], []
for branch in real_branches:
    found = next((s for s in store_names if names_match(s, branch)), None)
    if found:
        matched.append((branch, found))
    else:
        unmatched.append(branch)

pct = len(matched) / len(real_branches) * 100
print(f"התאמות: {len(matched)}/{len(real_branches)} ({pct:.0f}%)\n")

print(f"❌ עדיין לא מתאים ({len(unmatched)}):")
for b in sorted(unmatched):
    print(f"  {b}")

print("\n⚠️ התאמות חשודות (cross-chain):")
for branch, store in matched:
    bc = get_chain(branch)
    sc = get_chain(store)
    if bc and sc and bc != sc:
        print(f"  {branch} ← {store}")
