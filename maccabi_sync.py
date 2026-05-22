"""
maccabi_sync.py
===============
כלי סנכרון נתוני מכבי פארם:
  Report.xlsx  ↔  Supabase stores table

שימוש:
    from maccabi_sync import load_excel_branches, cross_reference
"""

import re
import pandas as pd
from difflib import SequenceMatcher

# ── נרמול עיר ────────────────────────────────────────────────
_CITY_ALIASES = {
    'ת"א':       'תל אביב',
    'ת.א.':      'תל אביב',
    'ראשל"צ':    'ראשון לציון',
    'ב"ש':       'באר שבע',
    'ב"ב':       'בני ברק',
    'ק. אתא':    'קרית אתא',
    'ק.אתא':     'קרית אתא',
    'ק. מוצקין': 'קרית מוצקין',
    'ק.מוצקין':  'קרית מוצקין',
    'ק. ביאליק': 'קרית ביאליק',
    'ק.ביאליק':  'קרית ביאליק',
    'ק. גת':     'קרית גת',
    'ק.גת':      'קרית גת',
    'ק. ים':     'קרית ים',
    'ק. יובל':   'קרית יובל',
    'קריית':     'קרית',
}

_MACCABI_CHAINS = {'מכבי פארם', 'מכבי', 'מכבי שירותי בריאות', 'מכבי קופת חולים'}


def _norm_city(raw) -> str:
    """נרמול שם עיר לצורך השוואה."""
    if not raw or str(raw).strip() in ('', 'nan', 'None', 'NaT'):
        return ''
    city = str(raw).strip()
    for alias, canonical in _CITY_ALIASES.items():
        city = city.replace(alias, canonical)
    city = city.replace('קריית', 'קרית')
    city = re.sub(r'\s+', ' ', city).strip()
    return city


def _norm_address(street, number) -> str:
    """בנייה + נרמול כתובת מרחוב + מספר."""
    s = str(street).strip() if street and str(street) not in ('nan', 'None', '') else ''
    n = str(number).strip() if number and str(number) not in ('nan', 'None', '') else ''
    if n:
        try:
            n = str(int(float(n)))
        except (ValueError, TypeError):
            pass  # שמור כמחרוזת (קומה 1, 1530, ...)
        return f"{s} {n}".strip() if s else n
    return s


def _sim(a: str, b: str) -> float:
    """אחוז דמיון בין שתי מחרוזות (0.0–1.0)."""
    a, b = (a or '').strip(), (b or '').strip()
    if not a or not b:
        return 0.0
    seq  = SequenceMatcher(None, a, b).ratio()
    # גם דמיון לפי מילים ממוינות (עמיד לסדר שונה)
    a_s  = ' '.join(sorted(a.split()))
    b_s  = ' '.join(sorted(b.split()))
    sort = SequenceMatcher(None, a_s, b_s).ratio()
    return max(seq, sort)


# ── טעינת Excel ──────────────────────────────────────────────

def load_excel_branches(file_obj) -> pd.DataFrame:
    """
    קורא Report.xlsx ומחזיר DataFrame נקי של סניפי מכבי פארם.

    עמודות בפלט:
        branch_code, city, street, number, address  (כתובת מלאה)
    """
    df = pd.read_excel(file_obj, sheet_name='Sheet1', engine='openpyxl')

    # ── שנה שמות עמודות לאנגלית (robust לשגיאות encoding) ──
    cols = list(df.columns)
    rename = {}
    for c in cols:
        cs = str(c)
        if 'EDI' in cs or 'EDI' in cs.encode('utf-8', errors='replace').decode():
            rename[c] = 'edi_code'
        elif 'סניף' in cs or 'סניף' in cs:
            rename[c] = 'branch_name'
        elif 'קוד' in cs and len(cs) < 10:
            rename[c] = 'branch_code'
        elif 'עיר' in cs:
            rename[c] = 'city'
        elif 'רחוב' in cs:
            rename[c] = 'street'
        elif 'מספר' in cs:
            rename[c] = 'number'
        elif 'טלפון' in cs:
            rename[c] = 'phone'

    # fallback — לפי מיקום
    col_map = {0: 'edi_code', 1: 'branch_code', 2: 'branch_name',
               3: 'city', 4: 'street', 5: 'number', 6: 'phone', 7: 'yerpa_code'}
    for i, c in enumerate(cols):
        if c not in rename:
            rename[c] = col_map.get(i, f'col{i}')

    df = df.rename(columns=rename)

    # ── סנן: רק שורות עם עיר ──
    df['city'] = df['city'].apply(_norm_city)
    df = df[df['city'] != ''].copy()

    # ── בנה כתובת מלאה ──
    df['address'] = df.apply(
        lambda r: _norm_address(r.get('street', ''), r.get('number', '')), axis=1
    )
    df = df[df['address'] != ''].copy()

    # ── נקה branch_code ──
    df['branch_code'] = df.get('branch_code', pd.Series(dtype=str)).apply(
        lambda x: str(int(float(x))) if pd.notna(x) and str(x) not in ('nan','') else ''
    )

    return df[['branch_code', 'city', 'address']].reset_index(drop=True)


# ── Cross-Reference ───────────────────────────────────────────

def cross_reference(
    csv_df: pd.DataFrame,
    db_stores: list[dict],
    address_threshold: float = 0.55,
) -> list[dict]:
    """
    מצליב CSV branches עם DB stores.

    Returns list[dict]:
        branch_code  : קוד סניף מה-CSV
        city         : עיר (מנורמל)
        csv_address  : כתובת רשמית מה-CSV
        db_store     : dict רשומת Supabase (None אם לא נמצא)
        db_address   : כתובת נוכחית ב-DB
        match_score  : ציון דמיון כתובות (0-100)
        status       : 'ok' | 'mismatch' | 'missing'
    """
    # ── בנה index DB לפי עיר מנורמלת ──
    db_by_city: dict[str, list[dict]] = {}
    for s in db_stores:
        c = _norm_city(s.get('city', ''))
        db_by_city.setdefault(c, []).append(s)

    used_ids: set = set()
    results: list[dict] = []

    for _, row in csv_df.iterrows():
        city       = row['city']
        csv_addr   = row['address']
        b_code     = row['branch_code']

        candidates = [s for s in db_by_city.get(city, [])
                      if s.get('id') not in used_ids]

        best_store  = None
        best_score  = 0.0

        for s in candidates:
            db_addr = s.get('address', '') or ''
            score   = _sim(csv_addr, db_addr)
            if score > best_score:
                best_score = score
                best_store = s

        # ── קבע סטטוס ──
        if best_store is None:
            status = 'missing'
        else:
            used_ids.add(best_store['id'])
            db_addr    = best_store.get('address', '') or ''
            # "ok" — הרחוב הראשי של הכתובת זהה
            csv_first  = csv_addr.split()[0] if csv_addr.split() else ''
            db_first   = db_addr.split()[0]  if db_addr.split()  else ''
            addr_match = (
                best_score >= 0.75 or
                (csv_first and csv_first == db_first)
            )
            status = 'ok' if addr_match else 'mismatch'

        results.append({
            'branch_code': b_code,
            'city':        city,
            'csv_address': csv_addr,
            'db_store':    best_store,
            'db_address':  best_store.get('address', '') if best_store else '—',
            'db_name':     best_store.get('name', '')    if best_store else '—',
            'db_id':       best_store.get('id')          if best_store else None,
            'match_score': round(best_score * 100),
            'status':      status,
        })

    return results


# ── Geocode via Google Places ─────────────────────────────────

def geocode_address(address: str, city: str, api_key: str) -> dict | None:
    """
    Reverse-geocodes כתובת → lat/lon + formatted_address.
    מחזיר dict עם lat, lon, formatted_address, או None אם נכשל.
    """
    import requests
    import time

    query  = f"{address}, {city}, ישראל"
    url    = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": query, "language": "he", "region": "il", "key": api_key}

    try:
        time.sleep(0.06)        # rate limit ≤ 20 req/sec
        r    = requests.get(url, params=params, timeout=10, verify=False)
        data = r.json()
    except Exception as e:
        return None

    if data.get("status") != "OK" or not data.get("results"):
        # fallback: Geocoding API
        try:
            g_url    = "https://maps.googleapis.com/maps/api/geocode/json"
            g_params = {"address": query, "language": "he", "region": "il", "key": api_key}
            time.sleep(0.06)
            r    = requests.get(g_url, params=g_params, timeout=10, verify=False)
            data = r.json()
        except Exception:
            return None
        if data.get("status") != "OK" or not data.get("results"):
            return None
        loc = data["results"][0]["geometry"]["location"]
        fmt = data["results"][0].get("formatted_address", "")
    else:
        loc = data["results"][0]["geometry"]["location"]
        fmt = data["results"][0].get("formatted_address", "")

    lat, lon = loc["lat"], loc["lng"]
    # בדיקת גבולות ישראל
    if not (29.4 <= lat <= 33.4 and 34.2 <= lon <= 35.9):
        return None

    return {
        "lat":               round(lat, 6),
        "lon":               round(lon, 6),
        "formatted_address": fmt,
    }
