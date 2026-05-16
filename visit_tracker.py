"""
visit_tracker.py
================
מודול מרכזי למעקב ביקורים — Rule D.

מחשב "ימים מאז ביקור אחרון" לכל חנות על בסיס:
  1. senzey_data.csv   — תעודות משלוח אמיתיות (id, date, branch)
  2. manual_visits.csv — ביקורים שנרשמו ידנית מהאפליקציה

שימוש:
    from visit_tracker import get_all_visit_stats, urgency_label

    stats = get_all_visit_stats(stores, deliveries, manual_visits)
    # stats["שילב הרצליה"] → {last_date, days_since, visit_count, source}
"""

import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

# ── הגדרות ────────────────────────────────────────────────
MONTHS_BACK   = 3      # כמה חודשים אחורה לנתח
MATCH_THRESH  = 72     # סף דמיון שמות (%) לקשר בין תעודה לחנות

# ── סף ימים להדגשה ────────────────────────────────────────
URGENT_DAYS   = 45     # 🔴 לא בוקר — דחוף
WARNING_DAYS  = 21     # 🟡 שבועיים+ — שים לב
OK_DAYS       = 14     # 🟢 פחות משבועיים — בסדר


# ── עזרים ─────────────────────────────────────────────────
def _parse_date(raw: str) -> datetime | None:
    """מנתח תאריכים בפורמטים שונים → datetime."""
    raw = str(raw).strip()
    for fmt in ("%d/%m/%y %H:%M", "%d/%m/%y", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:len(fmt.replace("%","xx").replace("xx","00"))], fmt)
        except ValueError:
            continue
    # fallback — קח רק DD/MM/YY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return datetime(y, mo, d)
        except ValueError:
            pass
    return None


def _sim(a: str, b: str) -> int:
    """אחוז דמיון בין שתי מחרוזות (0-100)."""
    if not a or not b:
        return 0
    return int(SequenceMatcher(None, a.strip(), b.strip()).ratio() * 100)


def _normalize(name: str) -> str:
    """נרמול שם חנות לצורך השוואה."""
    name = name.strip()
    name = name.replace('״', '"').replace('׳', "'")

    # ── מכבי פארם: נרמל שם רשת ───────────────────────────────
    name = name.replace('מכבי שירותי בריאות', 'מכבי פארם')
    name = name.replace('מכבי קופת חולים', 'מכבי פארם')

    # ── מכבי: טיפול בפורמט "עיר - מכבי פארם - עיר הזמנה-XXXXX"
    # לדוגמה: "כפר סבא הירוקה - מכבי פארם - כפר סבא הירוקה הזמנה-107000840"
    # → "מכבי פארם כפר סבא הירוקה"
    m = re.match(r'^(.+?)\s*-\s*(מכבי[^-]+?)\s*-\s*(.+?)(?:\s+הזמנה.*)?$', name)
    if m:
        brand = m.group(2).strip()   # "מכבי פארם"
        city  = m.group(3).strip()   # "כפר סבא הירוקה"
        # הסר מספר הזמנה מהעיר אם נשאר
        city = re.sub(r'\s+הזמנה.*$', '', city).strip()
        name = f"{brand} {city}"

    # ── הסר מספר הזמנה בכל פורמט ────────────────────────────
    # "הזמנה-107000840" / "הזמנה -107000840" / "הזמנה- 107000840"
    name = re.sub(r'\s*הזמנה\s*[-–]?\s*\d+', '', name)
    # "מספר הזמנה : 106987978" / "מספר הזמנה:106987978"
    name = re.sub(r'\s*מספר\s+הזמנה\s*:?\s*\d*', '', name)
    # ":מספר הזמנה 106987978"
    name = re.sub(r':?\s*מספר\s+הזמנה\s*\d*', '', name)
    # מספר בן 7+ ספרות שנשאר בסוף
    name = re.sub(r'\s+\d{7,}$', '', name)
    name = re.sub(r'^\d{7,}\s*', '', name)

    # ── מקף אחרי "מכבי פארם" ─────────────────────────────────
    name = re.sub(r'(מכבי פארם)\s*-\s*', r'\1 ', name)

    # ── תקנים כלליים ─────────────────────────────────────────
    name = re.sub(r'^ל(?=שילב|מכבי|ניצת)', '', name)
    name = re.sub(r'(?<=[א-ת])-(?=[א-ת])', ' ', name)
    name = re.sub(r'\s*מספר\s*:?\s*$', '', name)
    name = name.replace('ת"א', 'תל אביב').replace('ת.א.', 'תל אביב')
    name = name.replace('ראשל"צ', 'ראשון לציון')
    name = re.sub(r'ק\.\s*יובל', 'קרית יובל', name)
    name = name.replace('קריית', 'קרית')
    name = re.sub(r'\s*-\s*$', '', name)
    name = re.sub(r'\s{2,}', ' ', name).strip()
    return name


def _match_branch_to_store(branch_norm: str,
                            store_names: list[str],
                            cache: dict) -> str | None:
    """
    מחפש את החנות הכי דומה לשם הסניף.
    מחזיר שם החנות אם נמצאה התאמה מעל הסף, אחרת None.
    cache — מילון {branch_norm: store_name} לביצועים.
    """
    if branch_norm in cache:
        return cache[branch_norm]

    best_score = 0
    best_store = None

    for s_name in store_names:
        score = _sim(branch_norm, s_name)
        if score > best_score:
            best_score = score
            best_store = s_name

        # התאמה מלאה — עצור מוקדם
        if best_score == 100:
            break

    result = best_store if best_score >= MATCH_THRESH else None
    cache[branch_norm] = result
    return result


# ── פונקציה ראשית ─────────────────────────────────────────
def get_all_visit_stats(stores:        list[dict],
                         deliveries:    list[dict],
                         manual_visits: list[dict],
                         months_back:   int = MONTHS_BACK,
                         aliases:       dict = None) -> dict:
    """
    מחזיר מילון עם סטטיסטיקות ביקורים לכל חנות.

    Returns
    -------
    {
      "שילב הרצליה": {
        "last_date":    datetime | None,
        "last_date_str": "14/05/26",
        "days_since":   int | None,
        "visit_count":  int,            # מספר ביקורים ב-X חודשים
        "source":       "delivery" | "manual" | None,
        "visits":       [{"date": dt, "note_id": str, "source": str}],
      }
    }
    """
    if aliases is None:
        aliases = {}

    cutoff = datetime.now() - timedelta(days=months_back * 30)

    # ── בנה מילון חנויות ──
    store_names_norm = {_normalize(s["name"]): s["name"] for s in stores}
    store_names_list = list(store_names_norm.keys())
    match_cache = {}

    # אתחל תוצאה
    result = {s["name"]: {
        "last_date": None, "last_date_str": "—",
        "days_since": None, "visit_count": 0,
        "source": None, "visits": []
    } for s in stores}

    # ── עבד תעודות משלוח (senzey) ──
    for row in deliveries:
        branch_raw  = row.get("branch", "").strip()
        date_raw    = row.get("date", "").strip()
        note_id     = str(row.get("id", "")).strip()

        if not branch_raw or not date_raw:
            continue

        dt = _parse_date(date_raw)
        if not dt or dt < cutoff:
            continue

        branch_norm = _normalize(branch_raw)

        # סנן garbage
        GARBAGE = ['בל בוקס','מור סילבר','ביו גאיה','סופרסאפ','ווולט',
                   'תעודת משלוח רכש','הזמנת רכש','פרסום','אתר סחר',
                   'מחסן ','מכירות']
        if any(g in branch_raw for g in GARBAGE):
            continue
        if re.match(r'^\d{2}/\d{2}', branch_raw):
            continue

        # ── בדוק alias (מאושר ידנית) לפני fuzzy match ──
        if branch_norm in aliases:
            store_name = aliases[branch_norm]
        else:
            matched = _match_branch_to_store(branch_norm, store_names_list, match_cache)
            if not matched:
                continue
            store_name = store_names_norm.get(matched, matched)

        if store_name not in result:
            continue

        result[store_name]["visits"].append({
            "date": dt, "note_id": note_id, "source": "delivery"
        })

    # ── עבד ביקורים ידניים ──
    for row in manual_visits:
        store_raw = row.get("store", "").strip()
        date_raw  = row.get("date", "").strip()
        status    = row.get("status", "").strip()

        if not store_raw or not date_raw:
            continue
        if status in ("לא הגעתי", "בוטל"):
            continue

        dt = _parse_date(date_raw)
        if not dt or dt < cutoff:
            continue

        store_norm = _normalize(store_raw)
        matched    = _match_branch_to_store(store_norm, store_names_list, match_cache)
        if not matched:
            continue

        store_name = store_names_norm.get(matched, matched)
        if store_name not in result:
            continue

        result[store_name]["visits"].append({
            "date": dt, "note_id": "", "source": "manual"
        })

    # ── חשב סטטיסטיקות סופיות ──
    now = datetime.now()
    for store_name, data in result.items():
        visits = sorted(data["visits"], key=lambda v: v["date"], reverse=True)
        data["visits"]      = visits
        data["visit_count"] = len(visits)

        if visits:
            last = visits[0]
            data["last_date"]     = last["date"]
            data["last_date_str"] = last["date"].strftime("%d/%m/%y")
            data["days_since"]    = (now - last["date"]).days
            data["source"]        = last["source"]

    return result


def urgency_label(days_since: int | None) -> str:
    """
    מחזיר תווית + אמוג'י לפי ימים מאז ביקור.
    🟢 בסדר | 🟡 שים לב | 🔴 דחוף | ⚫ לא בוקר מעולם
    """
    if days_since is None:
        return "⚫ לא בוקר"
    if days_since <= OK_DAYS:
        return f"🟢 לפני {days_since} ימים"
    if days_since <= WARNING_DAYS:
        return f"🟡 לפני {days_since} ימים"
    if days_since <= URGENT_DAYS:
        return f"🟠 לפני {days_since} ימים"
    return f"🔴 {days_since} ימים!"


def urgency_color_hex(days_since: int | None) -> str:
    """מחזיר צבע HEX לשימוש ב-Excel."""
    if days_since is None:
        return "DDDDDD"   # אפור — לא בוקר מעולם
    if days_since <= OK_DAYS:
        return "D9EAD3"   # ירוק בהיר
    if days_since <= WARNING_DAYS:
        return "FFF2CC"   # צהוב בהיר
    if days_since <= URGENT_DAYS:
        return "FCE5CD"   # כתום בהיר
    return "F4CCCC"       # אדום בהיר


def get_never_visited(stats: dict, stores: list[dict]) -> list[dict]:
    """מחזיר רשימת חנויות שלא בוקרו כלל ב-X חודשים האחרונים."""
    never = []
    for s in stores:
        name = s["name"]
        if stats.get(name, {}).get("days_since") is None:
            never.append(s)
    return never


def get_overdue_stores(stats: dict, stores: list[dict],
                        threshold_days: int = URGENT_DAYS) -> list[dict]:
    """מחזיר רשימת חנויות שעברו X ימים מאז הביקור האחרון."""
    overdue = []
    for s in stores:
        name = s["name"]
        days = stats.get(name, {}).get("days_since")
        if days is not None and days >= threshold_days:
            overdue.append({**s, "days_since": days})
    return sorted(overdue, key=lambda x: x["days_since"], reverse=True)


def get_unmatched_branches(deliveries:    list[dict],
                            stores:        list[dict],
                            aliases:       dict = None,
                            months_back:   int  = MONTHS_BACK) -> list[dict]:
    """
    מחזיר רשימת סניפים בתעודות משלוח שלא ניתן להתאים לחנות קיימת.
    כל פריט: {branch_raw, branch_norm, count, dates, top3}
    top3 = [(store_name, score%), ...]  — 3 ההצעות הטובות ביותר.

    Rule B — Smart Suggestions.
    """
    if aliases is None:
        aliases = {}

    cutoff = datetime.now() - timedelta(days=months_back * 30)
    store_names_norm = {_normalize(s["name"]): s["name"] for s in stores}
    store_names_list = list(store_names_norm.keys())

    GARBAGE = ['בל בוקס','מור סילבר','ביו גאיה','סופרסאפ','ווולט',
               'תעודת משלוח רכש','הזמנת רכש','פרסום','אתר סחר',
               'מחסן ','מכירות']

    unmatched: dict[str, dict] = {}   # branch_norm → info

    for row in deliveries:
        branch_raw = row.get("branch", "").strip()
        date_raw   = row.get("date",   "").strip()

        if not branch_raw or not date_raw:
            continue

        dt = _parse_date(date_raw)
        if not dt or dt < cutoff:
            continue

        if any(g in branch_raw for g in GARBAGE):
            continue
        if re.match(r'^\d{2}/\d{2}', branch_raw):
            continue

        branch_norm = _normalize(branch_raw)

        # כבר יש alias מאושר — לא רלוונטי
        if branch_norm in aliases:
            continue

        # בדוק אם fuzzy match מצליח
        best_score = 0
        for s_name in store_names_list:
            score = _sim(branch_norm, s_name)
            if score > best_score:
                best_score = score
            if best_score == 100:
                break

        if best_score >= MATCH_THRESH:
            continue   # מזוהה אוטומטית — OK

        # לא מזוהה — אסוף
        if branch_norm not in unmatched:
            unmatched[branch_norm] = {
                "branch_raw":  branch_raw,
                "branch_norm": branch_norm,
                "count": 0,
                "dates": [],
            }
        unmatched[branch_norm]["count"] += 1
        unmatched[branch_norm]["dates"].append(dt.strftime("%d/%m/%y"))

    # ── חשב top-3 הצעות לכל סניף לא מזוהה ──
    result = []
    for bn, info in unmatched.items():
        scores = [
            (store_names_norm[sn], _sim(bn, sn))
            for sn in store_names_list
        ]
        top3 = sorted(scores, key=lambda x: x[1], reverse=True)[:3]
        result.append({**info, "top3": top3})

    # מיין לפי מספר תעודות (הכי שכיח קודם)
    return sorted(result, key=lambda x: x["count"], reverse=True)


# ── הרצה ישירה (בדיקה) ────────────────────────────────────
if __name__ == "__main__":
    import csv, sys, requests, io
    sys.stdout.reconfigure(encoding="utf-8")

    def fetch(url):
        r = requests.get(url, timeout=10)
        return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))

    BASE = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main"
    stores   = fetch(f"{BASE}/stores.csv")
    delivery = fetch(f"{BASE}/senzey_data.csv")
    manual   = fetch(f"{BASE}/manual_visits.csv")

    print(f"חנויות: {len(stores)} | תעודות: {len(delivery)} | ידני: {len(manual)}\n")

    stats = get_all_visit_stats(stores, delivery, manual)

    visited  = [n for n, d in stats.items() if d["days_since"] is not None]
    never    = [n for n, d in stats.items() if d["days_since"] is None]
    overdue  = get_overdue_stores(stats, stores)

    print(f"✅ בוקרו ב-3 חודשים: {len(visited)}")
    print(f"⚫ לא בוקרו כלל:     {len(never)}")
    print(f"🔴 דחוף (45+ ימים):  {len(overdue)}\n")

    print("10 האחרונים שבוקרו:")
    visited_sorted = sorted(
        [(n, d) for n, d in stats.items() if d["days_since"] is not None],
        key=lambda x: x[1]["days_since"]
    )
    for name, d in visited_sorted[:10]:
        print(f"  {urgency_label(d['days_since']):<25} {name}")

    print("\n10 הדחופים ביותר:")
    for s in overdue[:10]:
        print(f"  🔴 {s['days_since']} ימים — {s['name']} ({s.get('city','')})")
