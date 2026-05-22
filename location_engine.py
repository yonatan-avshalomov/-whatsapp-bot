"""
location_engine.py
==================
Zero-Tolerance Location & Deduplication Engine

Pipeline
--------
  Step 1 — Deep Deduplication   : fuzzy name + proximity → merge & purge
  Step 2 — Aggressive Verification : Google Places with city-validation retry loop
  Step 3 — Smart Fallback       : chain+address search when name search fails
  Step 4 — Database Overwrite   : only on confirmed high-confidence matches
  Step 5 — Streamlit UI Report  : deleted / updated / critical exceptions

Run standalone:
    streamlit run location_engine.py

Or import into streamlit_app.py:
    from location_engine import render_ui
    render_ui()
"""

import os
import re
import time
import math
import warnings
import requests
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import quote

warnings.filterwarnings("ignore")


# ══════════════════════════════════════════════════════════════════════════════
# ── City normalisation & mapping ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

_CITY_ALIASES_HE = {
    'ת"א': 'תל אביב', 'ת.א.': 'תל אביב', 'ראשל"צ': 'ראשון לציון',
    'ב"ש': 'באר שבע', 'ב"ב': 'בני ברק',
    'ק. אתא': 'קרית אתא',   'ק.אתא': 'קרית אתא',
    'ק. מוצקין': 'קרית מוצקין', 'ק.מוצקין': 'קרית מוצקין',
    'ק. ביאליק': 'קרית ביאליק', 'ק.ביאליק': 'קרית ביאליק',
    'ק. גת': 'קרית גת',     'ק.גת': 'קרית גת',
    'ק. ים': 'קרית ים',     'ק. שמונה': 'קרית שמונה',
    'קריית': 'קרית',
}

# English city name → canonical Hebrew (covers Google's typical spellings)
_EN_TO_HE: dict[str, str] = {
    'tel aviv':           'תל אביב',
    'tel aviv-yafo':      'תל אביב',
    'tel aviv yafo':      'תל אביב',
    'telaviv':            'תל אביב',
    'jaffa':              'תל אביב',
    'yafo':               'יפו',
    'haifa':              'חיפה',
    'jerusalem':          'ירושלים',
    'beer sheva':         'באר שבע',
    "be'er sheva":        'באר שבע',
    "beer-sheva":         'באר שבע',
    'beersheba':          'באר שבע',
    'rishon lezion':      'ראשון לציון',
    "rishon le'zion":     'ראשון לציון',
    "rishon lezi'on":     'ראשון לציון',
    'petah tikva':        'פתח תקווה',
    'petah tiqwa':        'פתח תקווה',
    'bnei brak':          'בני ברק',
    'bene beraq':         'בני ברק',
    'netanya':            'נתניה',
    'ashdod':             'אשדוד',
    'ashkelon':           'אשקלון',
    'bat yam':            'בת ים',
    'holon':              'חולון',
    'rehovot':            'רחובות',
    'herzliya':           'הרצליה',
    "ra'anana":           'רעננה',
    'raanana':            'רעננה',
    'kfar saba':          'כפר סבא',
    'kfar-saba':          'כפר סבא',
    "modi'in":            'מודיעין',
    'modiin':             'מודיעין',
    'maccabim':           'מודיעין',
    'ramat gan':          'רמת גן',
    'givatayim':          'גבעתיים',
    'givat shmuel':       'גבעת שמואל',
    'rosh haayin':        'ראש העין',
    "rosh ha'ayin":       'ראש העין',
    'lod':                'לוד',
    'ramla':              'רמלה',
    'nahariya':           'נהריה',
    'acre':               'עכו',
    'akko':               'עכו',
    'tiberias':           'טבריה',
    'nazareth':           'נצרת',
    'nazareth illit':     'נוף הגליל',
    'nof hagalil':        'נוף הגליל',
    'afula':              'עפולה',
    'karmiel':            'כרמיאל',
    'sderot':             'שדרות',
    'eilat':              'אילת',
    'dimona':             'דימונה',
    'arad':               'ערד',
    'kiryat gat':         'קרית גת',
    'kiryat ata':         'קרית אתא',
    'kiryat motzkin':     'קרית מוצקין',
    'kiryat bialik':      'קרית ביאליק',
    'kiryat yam':         'קרית ים',
    'kiryat shmona':      'קרית שמונה',
    'kiryat shmone':      'קרית שמונה',
    'nesher':             'נשר',
    'tirat carmel':       'טירת כרמל',
    'tirat hacarmel':     'טירת כרמל',
    'yokneam':            'יקנעם',
    'yoqneam':            'יקנעם',
    'hod hasharon':       'הוד השרון',
    'ramat hasharon':     'רמת השרון',
    'even yehuda':        'אבן יהודה',
    'pardes hana':        'פרדס חנה',
    'pardes hannah':      'פרדס חנה',
    'hadera':             'חדרה',
    'caesarea':           'קיסריה',
    'zichron yaakov':     'זכרון יעקב',
    'zichron':            'זכרון יעקב',
    'nes ziona':          'נס ציונה',
    'ness ziona':         'נס ציונה',
    'gedera':             'גדרה',
    'yavne':              'יבנה',
    'rishon':             'ראשון לציון',
    'or yehuda':          'אור יהודה',
    'rosh pinna':         'ראש פינה',
    'safed':              'צפת',
    'zfat':               'צפת',
    'beit shean':         'בית שאן',
    'bet shean':          'בית שאן',
    'migdal haemek':      'מגדל העמק',
    'ma\'alot':           'מעלות',
    'maalot':             'מעלות',
    'nazereth':           'נצרת',
    'natzrat':            'נצרת',
    'carmiel':            'כרמיאל',
    'qiryat':             'קרית',
}

ISRAEL_BOUNDS = {"lat": (29.4, 33.4), "lon": (34.2, 35.9)}


def _norm_city(raw) -> str:
    """Normalise Hebrew city name to canonical form."""
    if not raw or str(raw).strip() in ('', 'nan', 'None', 'NaT'):
        return ''
    city = str(raw).strip()
    for alias, canonical in _CITY_ALIASES_HE.items():
        city = city.replace(alias, canonical)
    city = city.replace('קריית', 'קרית')
    city = re.sub(r'\s+', ' ', city).strip()
    return city


def _city_en_to_he(en: str) -> str:
    """Map English city name → canonical Hebrew, or '' if unknown."""
    return _EN_TO_HE.get(en.lower().strip(), '')


def _sim(a: str, b: str) -> float:
    """Fuzzy similarity 0–1 between two strings (case-insensitive)."""
    a, b = (a or '').strip().lower(), (b or '').strip().lower()
    if not a or not b:
        return 0.0
    seq  = SequenceMatcher(None, a, b).ratio()
    a_s  = ' '.join(sorted(a.split()))
    b_s  = ' '.join(sorted(b.split()))
    sort = SequenceMatcher(None, a_s, b_s).ratio()
    return max(seq, sort)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distance in metres between two lat/lon points."""
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _in_israel(lat, lon) -> bool:
    b = ISRAEL_BOUNDS
    try:
        return b["lat"][0] <= float(lat) <= b["lat"][1] and \
               b["lon"][0] <= float(lon) <= b["lon"][1]
    except (TypeError, ValueError):
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ── Data-classes for results ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DuplicateGroup:
    keep_id:    int
    delete_ids: list[int]
    keep_name:  str
    reason:     str
    all_names:  list[str]
    executed:   bool = False


@dataclass
class VerificationResult:
    store_id:    int
    store_name:  str
    city:        str
    chain:       str
    status:      str        # 'updated' | 'partial' | 'no_change' | 'failed' | 'db_error'
    old_lat:     float | None
    old_lon:     float | None
    old_address: str
    new_lat:     float | None
    new_lon:     float | None
    new_address: str
    confidence:  float      # 0–1
    attempts:    int
    query_used:  str
    reason:      str


@dataclass
class EngineReport:
    duplicate_groups:     list[DuplicateGroup]      = field(default_factory=list)
    verification_results: list[VerificationResult]  = field(default_factory=list)
    errors:               list[str]                 = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# ── Supabase REST thin client ─────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class _DB:
    """Minimal Supabase REST wrapper (no SDK dependency)."""

    def __init__(self, url: str, key: str):
        self._base = f"{url}/rest/v1"
        self._h    = {
            "apikey":        key,
            "Authorization": f"Bearer {key}",
            "Content-Type":  "application/json",
        }

    def select(self, table: str, qs: str = "") -> list[dict]:
        h = {**self._h, "Prefer": "return=representation"}
        sep = "&" if qs else ""
        r = requests.get(f"{self._base}/{table}?{qs}{sep}limit=5000",
                         headers=h, verify=False, timeout=20)
        r.raise_for_status()
        return r.json() or []

    def patch(self, table: str, qs: str, payload: dict) -> bool:
        h = {**self._h, "Prefer": "return=minimal"}
        r = requests.patch(f"{self._base}/{table}?{qs}",
                           headers=h, json=payload, verify=False, timeout=20)
        return r.status_code in (200, 204)

    def delete(self, table: str, qs: str) -> bool:
        h = {**self._h, "Prefer": "return=minimal"}
        r = requests.delete(f"{self._base}/{table}?{qs}",
                            headers=h, verify=False, timeout=20)
        return r.status_code in (200, 204)

    def count(self, table: str, qs: str) -> int:
        h = {**self._h, "Prefer": "count=exact"}
        r = requests.get(f"{self._base}/{table}?{qs}&select=id",
                         headers=h, verify=False, timeout=10)
        try:
            return int(r.headers.get("Content-Range", "0/0").split("/")[1])
        except Exception:
            return 0


# ══════════════════════════════════════════════════════════════════════════════
# ── Step 1: Deep Deduplication ────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class DeduplicationEngine:
    """
    Finds duplicate store rows using two independent signals:

    Signal A — Name similarity ≥ NAME_THRESH within the same city.
    Signal B — Physical distance ≤ PROX_M metres (when lat/lon available).

    Either signal alone triggers a duplicate flag.
    The record with the highest CRM score is kept; the rest are deleted.
    """

    NAME_THRESH = 0.82   # 82 % fuzzy-name similarity
    PROX_M      = 150    # 150 m physical proximity

    def __init__(self, db: _DB):
        self.db = db

    # ── CRM activity score ───────────────────────────────────────────────────

    def _crm_score(self, store: dict) -> int:
        """Higher = more CRM history = preferred in a merge."""
        name = quote(store.get("name", ""), safe="")
        city = quote(store.get("city", ""), safe="")
        visits = self.db.count("manual_visits", f"store=eq.{name}&city=eq.{city}")
        notes  = self.db.count("store_notes",   f"store=eq.{name}&city=eq.{city}")
        coords_bonus = 5  if (store.get("lat") and store.get("lon")) else 0
        addr_bonus   = 3  if store.get("address")                     else 0
        return visits * 3 + notes * 2 + coords_bonus + addr_bonus

    # ── Detection ────────────────────────────────────────────────────────────

    def find_duplicates(self, stores: list[dict]) -> list[DuplicateGroup]:
        """
        Returns list of DuplicateGroup (one per cluster of duplicates).
        Groups are disjoint — each store appears in at most one group.
        """
        # Index by normalised city for O(n) instead of O(n²) across cities
        by_city: dict[str, list[dict]] = {}
        for s in stores:
            c = _norm_city(s.get("city", ""))
            by_city.setdefault(c, []).append(s)

        groups: list[DuplicateGroup] = []
        used:   set[int]             = set()

        for _, city_stores in by_city.items():
            n = len(city_stores)
            if n < 2:
                continue

            for i in range(n):
                s1 = city_stores[i]
                id1 = s1.get("id")
                if id1 in used:
                    continue

                cluster  = [s1]
                reasons  = []

                for j in range(i + 1, n):
                    s2  = city_stores[j]
                    id2 = s2.get("id")
                    if id2 in used:
                        continue

                    matched = False
                    r_parts = []

                    # Signal A — name similarity
                    ns = _sim(s1.get("name", ""), s2.get("name", ""))
                    if ns >= self.NAME_THRESH:
                        matched = True
                        r_parts.append(f"שם דומה {round(ns*100)}%")

                    # Signal B — physical proximity
                    if all(s.get("lat") and s.get("lon") for s in (s1, s2)):
                        try:
                            dist = _haversine_m(
                                float(s1["lat"]), float(s1["lon"]),
                                float(s2["lat"]), float(s2["lon"]),
                            )
                            if dist <= self.PROX_M:
                                matched = True
                                r_parts.append(f"מרחק {round(dist)} מ′")
                        except (TypeError, ValueError):
                            pass

                    if matched:
                        cluster.append(s2)
                        used.add(id2)
                        reasons.extend(r_parts)

                if len(cluster) > 1:
                    used.add(id1)
                    # Score each member to pick the keeper
                    scored = sorted(
                        [(self._crm_score(s), s.get("id"), s) for s in cluster],
                        reverse=True,
                    )
                    keep_score, keep_id, keep_store = scored[0]
                    delete_ids = [x[1] for x in scored[1:]]
                    groups.append(DuplicateGroup(
                        keep_id    = keep_id,
                        delete_ids = delete_ids,
                        keep_name  = keep_store.get("name", ""),
                        reason     = " + ".join(dict.fromkeys(reasons)) or "כפילות",
                        all_names  = [s.get("name", "") for s in cluster],
                    ))

        return groups

    # ── Execution ────────────────────────────────────────────────────────────

    def execute_merges(
        self,
        groups: list[DuplicateGroup],
        progress_cb=None,
    ) -> list[DuplicateGroup]:
        """Delete the losing duplicates in each group. Mutates group.executed."""
        total = len(groups)
        for i, g in enumerate(groups):
            if progress_cb:
                progress_cb(i / max(total, 1),
                            f"מוחק כפילויות קבוצה {i+1}/{total}: {g.keep_name}")
            all_ok = True
            for del_id in g.delete_ids:
                ok = self.db.delete("stores", f"id=eq.{del_id}")
                if not ok:
                    all_ok = False
            g.executed = all_ok
        return groups


# ══════════════════════════════════════════════════════════════════════════════
# ── Step 2 & 3: Aggressive Location Verifier ─────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class LocationVerifier:
    """
    Multi-strategy Google Places verifier with mandatory city validation.

    For each store, up to MAX_ATTEMPTS queries are issued. The returned
    result is REJECTED and a new query is tried whenever:
      • The returned coordinates are outside Israel's bounding box.
      • The city extracted from Google's response does not match the expected
        city (fuzzy threshold CITY_SIM_THRESH).

    Only once a city-validated result is found is a confidence score computed.
    If confidence ≥ CONF_ACCEPT  → status 'updated'   (written to DB).
    If confidence ≥ CONF_PARTIAL → status 'partial'   (written to DB, flagged).
    Otherwise                   → status 'failed'     (Critical Exception).
    """

    MAX_ATTEMPTS  = 4
    CITY_SIM      = 0.72    # fuzzy threshold for city validation
    CONF_ACCEPT   = 0.80    # high-confidence threshold
    CONF_PARTIAL  = 0.60    # acceptable partial match
    RATE_SEC      = 0.13    # inter-request delay (~7.5 req/sec)

    def __init__(self, api_key: str):
        self.api_key    = api_key
        self._last_call = 0.0

    # ── Rate-limiter ─────────────────────────────────────────────────────────

    def _throttle(self):
        wait = self.RATE_SEC - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    # ── Low-level API calls ──────────────────────────────────────────────────

    def _places(self, query: str) -> dict | None:
        """Google Places Text Search → first result dict or None."""
        self._throttle()
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={"query": query, "language": "he",
                        "region": "il", "key": self.api_key},
                timeout=12, verify=False,
            )
            d = r.json()
            if d.get("status") == "OK" and d.get("results"):
                return d["results"][0]
        except Exception:
            pass
        return None

    def _geocode_api(self, query: str) -> dict | None:
        """Google Geocoding API → first result dict or None."""
        self._throttle()
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query, "language": "he",
                        "region": "il", "key": self.api_key},
                timeout=12, verify=False,
            )
            d = r.json()
            if d.get("status") == "OK" and d.get("results"):
                return d["results"][0]
        except Exception:
            pass
        return None

    # ── City extraction ──────────────────────────────────────────────────────

    def _extract_city(self, result: dict) -> str:
        """
        Extract the city name from a Google API result.
        Priority order:
          1. address_components[locality]      ← most reliable
          2. address_components[sublocality]   ← dense urban areas
          3. address_components[admin_area_2]  ← some towns
          4. Parse formatted_address           ← fallback
        """
        for comp in result.get("address_components", []):
            types = comp.get("types", [])
            name  = comp.get("long_name", "")
            if "locality" in types:
                return name
            if "sublocality_level_1" in types:
                return name

        for comp in result.get("address_components", []):
            types = comp.get("types", [])
            name  = comp.get("long_name", "")
            if "administrative_area_level_2" in types:
                return name

        # Fallback: parse formatted_address
        fmt = result.get("formatted_address") or result.get("vicinity", "")
        if fmt:
            parts = [p.strip() for p in fmt.split(",")]
            # Strip Israel / postal-code segments from the end
            clean = [p for p in parts
                     if not re.match(r"^(\d{5,7}|ישראל|israel)$", p, re.I)]
            if len(clean) >= 2:
                return clean[-1]
            elif clean:
                return clean[0]
        return ""

    # ── City validation ──────────────────────────────────────────────────────

    def _city_ok(self, returned: str, expected: str) -> bool:
        """
        True when the city Google returned matches the city we expect.
        Handles Hebrew ↔ English conversion and fuzzy matching.
        """
        if not returned or not expected:
            return False
        exp_norm = _norm_city(expected).lower()

        # Direct Hebrew comparison
        ret_he = _norm_city(returned).lower()
        if ret_he and _sim(ret_he, exp_norm) >= self.CITY_SIM:
            return True

        # English → Hebrew lookup
        ret_he2 = _city_en_to_he(returned).lower()
        if ret_he2 and _sim(ret_he2, exp_norm) >= self.CITY_SIM:
            return True

        # Substring scan through EN→HE map
        ret_lower = returned.lower()
        for en_key, he_val in _EN_TO_HE.items():
            if en_key in ret_lower and _sim(he_val.lower(), exp_norm) >= self.CITY_SIM:
                return True

        return False

    # ── Parse & validate a raw result ───────────────────────────────────────

    def _parse(self, raw: dict, expected_city: str) -> dict | None:
        """
        Returns a clean dict {lat, lon, address, returned_city} if the result
        is inside Israel AND the city validates. Otherwise returns None.
        """
        loc = (raw.get("geometry") or {}).get("location") or {}
        lat, lon = loc.get("lat"), loc.get("lng")
        if lat is None or lon is None:
            return None
        if not _in_israel(lat, lon):
            return None

        returned_city = self._extract_city(raw)
        if not self._city_ok(returned_city, expected_city):
            return None    # ← REJECTED: wrong city

        return {
            "lat":          round(lat, 6),
            "lon":          round(lon, 6),
            "address":      raw.get("formatted_address") or raw.get("vicinity", ""),
            "place_name":   raw.get("name", ""),
            "returned_city": returned_city,
        }

    # ── Build query strategies ───────────────────────────────────────────────

    def _query_strategies(
        self, name: str, city: str, address: str, chain: str
    ) -> list[str]:
        """
        Returns an ordered list of search queries, from most to least specific.
        """
        qs = []
        # 1. Most specific: name + address + city
        if name and address and city:
            qs.append(f"{name}, {address}, {city}, ישראל")
        # 2. Name + city (drops address — good when address is wrong)
        if name and city:
            qs.append(f"{name}, {city}, ישראל")
        # 3. Chain + address + city (Step 3 fallback — good when name is bad)
        if chain and address and city and chain != name:
            qs.append(f"{chain}, {address}, {city}, ישראל")
        # 4. Pure address geocoding (last resort)
        if address and city:
            qs.append(f"{address}, {city}, ישראל")
        # Deduplicate while preserving order
        seen, unique = set(), []
        for q in qs:
            if q not in seen:
                seen.add(q)
                unique.append(q)
        return unique[:self.MAX_ATTEMPTS]

    # ── Main verify entry-point ──────────────────────────────────────────────

    def verify(self, store: dict) -> VerificationResult:
        """
        Run up to MAX_ATTEMPTS queries for one store.
        Returns a fully populated VerificationResult.
        """
        sid     = store.get("id")
        name    = (store.get("name")    or "").strip()
        city    = _norm_city(store.get("city", ""))
        address = (store.get("address") or "").strip()
        chain   = (store.get("chain")   or "").strip()

        base = VerificationResult(
            store_id=sid, store_name=name, city=city, chain=chain,
            status="failed",
            old_lat=store.get("lat"),    old_lon=store.get("lon"),
            old_address=address,
            new_lat=None,                new_lon=None,
            new_address="",
            confidence=0.0, attempts=0, query_used="", reason="",
        )

        queries          = self._query_strategies(name, city, address, chain)
        rejection_log    = []
        best_partial     = None   # best sub-threshold result seen so far

        for attempt, query in enumerate(queries, 1):
            base.attempts = attempt

            # Try Places first, then Geocoding API as backup
            raw = self._places(query)
            if raw is None:
                raw = self._geocode_api(query)
            if raw is None:
                rejection_log.append(f"ניסיון {attempt}: אין תוצאה מה-API")
                continue

            # City validation gate
            returned_city_raw = self._extract_city(raw)
            parsed = self._parse(raw, city)

            if parsed is None:
                loc = (raw.get("geometry") or {}).get("location") or {}
                lat, lon = loc.get("lat", "?"), loc.get("lng", "?")
                rejection_log.append(
                    f"ניסיון {attempt}: עיר '{returned_city_raw}' ≠ '{city}' "
                    f"({lat},{lon}) — נדחה, ממשיך לשאילתה הבאה"
                )
                continue

            # ── Compute confidence (city is already validated) ────────────
            name_sim   = _sim(name,    parsed["place_name"])
            addr_sim   = _sim(address, parsed["address"])
            # City match confirmed → contributes fixed bonus of 0.20
            confidence = name_sim * 0.50 + addr_sim * 0.30 + 0.20
            confidence = min(confidence, 1.0)

            parsed["confidence"] = confidence
            parsed["query"]      = query

            if confidence >= self.CONF_ACCEPT:
                # ── High-confidence hit ───────────────────────────────────
                base.new_lat     = parsed["lat"]
                base.new_lon     = parsed["lon"]
                base.new_address = parsed["address"]
                base.confidence  = confidence
                base.status      = "updated"
                base.query_used  = query
                base.reason      = (
                    f"✅ נמצא בניסיון {attempt} | "
                    f"ביטחון {round(confidence*100)}% | "
                    f"עיר אומתה: {parsed['returned_city']}"
                )
                return base

            # Track best partial result
            if best_partial is None or confidence > best_partial["confidence"]:
                best_partial = parsed

            rejection_log.append(
                f"ניסיון {attempt}: ביטחון נמוך {round(confidence*100)}% "
                f"(שם {round(name_sim*100)}%, כתובת {round(addr_sim*100)}%) — "
                f"ממשיך לשאילתה ספציפית יותר"
            )

        # ── All attempts exhausted ────────────────────────────────────────
        if best_partial and best_partial["confidence"] >= self.CONF_PARTIAL:
            base.new_lat     = best_partial["lat"]
            base.new_lon     = best_partial["lon"]
            base.new_address = best_partial["address"]
            base.confidence  = best_partial["confidence"]
            base.status      = "partial"
            base.query_used  = best_partial["query"]
            base.reason      = (
                f"⚠️ התאמה חלקית {round(best_partial['confidence']*100)}% "
                f"לאחר {base.attempts} ניסיונות\n" +
                "\n".join(rejection_log)
            )
        else:
            base.status = "failed"
            base.reason = (
                f"❌ נכשל לאחר {base.attempts} ניסיונות\n" +
                "\n".join(rejection_log)
            )

        return base


# ══════════════════════════════════════════════════════════════════════════════
# ── Main Engine ───────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class LocationEngine:
    """
    Orchestrates the full pipeline: Deduplication → Verification → DB writes.

    Parameters
    ----------
    supabase_url   : str   SUPABASE_URL env var
    supabase_key   : str   SUPABASE_ANON_KEY env var
    maps_api_key   : str   GOOGLE_MAPS_API_KEY env var
    target_chains  : set   Chains to verify. None = all.
    """

    DEFAULT_CHAINS = {"שילב", "ניצת הדובדבן", "מכבי פארם",
                      "מכבי", "מכבי שירותי בריאות", "מכבי קופת חולים"}

    def __init__(
        self,
        supabase_url:  str,
        supabase_key:  str,
        maps_api_key:  str  = "",
        target_chains: set  = None,
    ):
        self.db       = _DB(supabase_url, supabase_key)
        self.verifier = LocationVerifier(maps_api_key) if maps_api_key else None
        self.chains   = target_chains or self.DEFAULT_CHAINS

    # ── Data loading ─────────────────────────────────────────────────────────

    def load_all_stores(self) -> list[dict]:
        return self.db.select(
            "stores",
            "select=id,name,city,chain,address,lat,lon,updated_at"
        )

    def load_chain_stores(self) -> list[dict]:
        chain_filter = ",".join(self.chains)
        return self.db.select(
            "stores",
            f"select=id,name,city,chain,address,lat,lon,updated_at"
            f"&chain=in.({chain_filter})"
        )

    # ── Step 1 ───────────────────────────────────────────────────────────────

    def scan_duplicates(self, stores: list[dict] | None = None) -> list[DuplicateGroup]:
        """Scan for duplicates. Does NOT delete — call execute_merges() after review."""
        if stores is None:
            stores = self.load_all_stores()
        engine = DeduplicationEngine(self.db)
        return engine.find_duplicates(stores)

    def execute_merges(
        self,
        groups: list[DuplicateGroup],
        progress_cb=None,
    ) -> list[DuplicateGroup]:
        """Execute the deletes for confirmed duplicate groups."""
        engine = DeduplicationEngine(self.db)
        return engine.execute_merges(groups, progress_cb)

    # ── Steps 2 & 3 ──────────────────────────────────────────────────────────

    def verify_and_update(
        self,
        stores:          list[dict] | None = None,
        only_missing:    bool = False,
        progress_cb      = None,
    ) -> list[VerificationResult]:
        """
        Verify coordinates for each store and write confident results to DB.

        Parameters
        ----------
        stores        : override store list (None = load target chains)
        only_missing  : if True, skip stores that already have lat/lon
        progress_cb   : callable(fraction, text) for UI progress bars
        """
        if self.verifier is None:
            raise RuntimeError("GOOGLE_MAPS_API_KEY required for verification")

        if stores is None:
            stores = self.load_chain_stores()

        if only_missing:
            stores = [s for s in stores if not s.get("lat") or not s.get("lon")]

        results: list[VerificationResult] = []

        for i, store in enumerate(stores):
            if progress_cb:
                progress_cb(
                    i / max(len(stores), 1),
                    f"מאמת {i+1}/{len(stores)}: {store.get('name','')} | {store.get('city','')}"
                )

            result = self.verifier.verify(store)

            # Write to DB only on confident results
            if result.status in ("updated", "partial") and result.new_lat:
                payload = {
                    "lat":        result.new_lat,
                    "lon":        result.new_lon,
                    "address":    result.new_address or store.get("address", ""),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                ok = self.db.patch("stores", f"id=eq.{store['id']}", payload)
                if not ok:
                    result.status = "db_error"
                    result.reason += "\n❌ שגיאה בכתיבה ל-Supabase"

            results.append(result)

        return results


# ══════════════════════════════════════════════════════════════════════════════
# ── Streamlit UI ──────────────────────────────────────════════════════════════
# ══════════════════════════════════════════════════════════════════════════════

def render_ui(
    supabase_url:  str = "",
    supabase_key:  str = "",
    maps_api_key:  str = "",
):
    """
    Full Streamlit UI for the Location & Deduplication Engine.
    Call this from streamlit_app.py or run as __main__.
    """
    import streamlit as st

    # Allow env-var fallback when called standalone
    supabase_url  = supabase_url  or os.getenv("SUPABASE_URL",      "")
    supabase_key  = supabase_key  or os.getenv("SUPABASE_ANON_KEY", "")
    maps_api_key  = maps_api_key  or os.getenv("GOOGLE_MAPS_API_KEY","")

    st.header("🎯 מנוע אפס-סובלנות — מיקומים וכפילויות")
    st.caption(
        "מנגנון מובנה-כשל שמבצע אימות מחמיר מול Google Places, "
        "דוחה תוצאות שגויות ומנסה שאילתות חלופיות עד לתוצאה מדויקת."
    )

    if not supabase_url or not supabase_key:
        st.error("⚠️ SUPABASE_URL / SUPABASE_ANON_KEY חסרים")
        return

    engine = LocationEngine(supabase_url, supabase_key, maps_api_key)

    # ── Sidebar config ────────────────────────────────────────────────────────
    with st.sidebar:
        st.subheader("⚙️ הגדרות")
        custom_chains_raw = st.text_area(
            "רשתות לאימות (שורה אחת = רשת אחת)",
            value="\n".join(sorted(LocationEngine.DEFAULT_CHAINS)),
            height=160,
        )
        custom_chains = {c.strip() for c in custom_chains_raw.splitlines() if c.strip()}

        dedup_scope = st.radio(
            "טווח חיפוש כפילויות",
            ["רשתות יעד בלבד", "כל החנויות"],
            index=0,
        )
        verify_scope = st.radio(
            "טווח אימות מיקום",
            ["רשתות יעד בלבד", "חסרות קואורדינטות בלבד"],
            index=0,
        )
        name_thresh  = st.slider("סף דמיון שמות לכפילות", 70, 95, 82, 1)
        prox_m       = st.slider("מרחק פיזי לכפילות (מטר)", 50, 500, 150, 10)
        conf_accept  = st.slider("סף ביטחון גבוה (%)", 70, 95, 80, 5)
        conf_partial = st.slider("סף ביטחון חלקי (%)", 50, 75, 60, 5)

    engine.chains = custom_chains
    DeduplicationEngine.NAME_THRESH   = name_thresh  / 100
    DeduplicationEngine.PROX_M        = prox_m
    if engine.verifier:
        engine.verifier.CONF_ACCEPT   = conf_accept  / 100
        engine.verifier.CONF_PARTIAL  = conf_partial / 100

    # ════════════════════════════════════════════════════════
    # Tab layout
    # ════════════════════════════════════════════════════════
    t_dedup, t_verify, t_report = st.tabs([
        "🔁 שלב 1 — כפילויות",
        "📍 שלב 2 — אימות מיקומים",
        "📋 דוח מלא",
    ])

    # ════════════════════════════════════════════════════════
    # TAB 1 — Deduplication
    # ════════════════════════════════════════════════════════
    with t_dedup:
        st.subheader("🔁 זיהוי ומחיקת כפילויות")
        st.caption(
            "מזהה רשומות כפולות לפי דמיון שמות + קרבה פיזית. "
            "שומר את הרשומה עם היסטוריית CRM עשירה יותר."
        )

        col_a, col_b = st.columns([1, 2])

        with col_a:
            if st.button("🔍 סרוק כפילויות", key="scan_dup", type="secondary",
                          use_container_width=True):
                with st.spinner("טוען חנויות וסורק..."):
                    try:
                        if dedup_scope == "כל החנויות":
                            stores = engine.load_all_stores()
                        else:
                            stores = engine.load_chain_stores()
                        groups = engine.scan_duplicates(stores)
                        st.session_state["dup_groups"]  = groups
                        st.session_state["dup_stores"]  = stores
                        st.session_state["dup_executed"] = False
                    except Exception as e:
                        st.error(f"שגיאה: {e}")

        with col_b:
            if st.session_state.get("dup_groups") is not None:
                g = st.session_state["dup_groups"]
                st.metric("קבוצות כפילויות שנמצאו", len(g),
                          delta=f"{sum(len(x.delete_ids) for x in g)} רשומות למחיקה")

        groups = st.session_state.get("dup_groups")
        if groups is not None:
            if not groups:
                st.success("✅ לא נמצאו כפילויות!")
            else:
                st.divider()
                st.info(
                    f"נמצאו **{len(groups)}** קבוצות כפילויות "
                    f"({sum(len(g.delete_ids) for g in groups)} רשומות ימחקו). "
                    f"סמן קבוצות לאישור ולחץ 'בצע מחיקה'."
                )

                # Show each group with a checkbox
                selected_indices = []
                for idx, g in enumerate(groups):
                    cols = st.columns([0.08, 0.92])
                    with cols[0]:
                        checked = st.checkbox(
                            "", value=True, key=f"dup_chk_{idx}"
                        )
                    with cols[1]:
                        delete_names = [
                            s for s in g.all_names if s != g.keep_name
                        ]
                        st.markdown(
                            f"**שמור:** ✅ `{g.keep_name}`  \n"
                            f"**מחק:** ❌ `{'` | `'.join(delete_names)}`  \n"
                            f"**סיבה:** {g.reason}"
                        )
                    if checked:
                        selected_indices.append(idx)

                st.divider()
                col_exec1, col_exec2 = st.columns([1, 2])
                with col_exec1:
                    exec_btn = st.button(
                        f"🗑️ בצע מחיקה ({len(selected_indices)} קבוצות)",
                        key="exec_dedup",
                        type="primary",
                        disabled=(len(selected_indices) == 0 or
                                  st.session_state.get("dup_executed", False)),
                        use_container_width=True,
                    )
                with col_exec2:
                    if st.session_state.get("dup_executed"):
                        st.success("✅ המחיקה בוצעה")

                if exec_btn:
                    selected_groups = [groups[i] for i in selected_indices]
                    prog = st.progress(0, text="מוחק כפילויות...")
                    try:
                        engine.execute_merges(
                            selected_groups,
                            progress_cb=lambda p, t: prog.progress(p, text=t),
                        )
                        prog.empty()
                        st.session_state["dup_executed"] = True

                        ok_count  = sum(1 for g in selected_groups if g.executed)
                        err_count = len(selected_groups) - ok_count
                        st.success(
                            f"✅ {ok_count} קבוצות נמחקו בהצלחה"
                            + (f" | ❌ {err_count} שגיאות" if err_count else "")
                        )
                        st.session_state["dup_groups"] = None   # force rescan
                    except Exception as e:
                        prog.empty()
                        st.error(f"שגיאה בביצוע מחיקה: {e}")

    # ════════════════════════════════════════════════════════
    # TAB 2 — Verification
    # ════════════════════════════════════════════════════════
    with t_verify:
        st.subheader("📍 אימות מיקומים אגרסיבי")

        if not maps_api_key:
            st.error("⚠️ GOOGLE_MAPS_API_KEY חסר — לא ניתן לאמת מיקומים")
            st.stop()

        st.caption(
            "מריץ עד 4 שאילתות שונות לכל חנות ודוחה כל תוצאה שהעיר שלה אינה "
            "תואמת לעיר שבמסד הנתונים. רק תוצאות מאומתות נכתבות ל-Supabase."
        )

        col_v1, col_v2, col_v3 = st.columns(3)
        with col_v1:
            only_missing = (verify_scope == "חסרות קואורדינטות בלבד")
            run_verify = st.button(
                "🚀 הפעל אימות מיקומים",
                key="run_verify",
                type="primary",
                use_container_width=True,
            )
        with col_v2:
            if st.session_state.get("ver_results"):
                r = st.session_state["ver_results"]
                updated = sum(1 for x in r if x.status == "updated")
                partial = sum(1 for x in r if x.status == "partial")
                failed  = sum(1 for x in r if x.status == "failed")
                st.metric("✅ עודכנו", updated)
        with col_v3:
            if st.session_state.get("ver_results"):
                st.metric("❌ נכשלו", failed)
                if partial:
                    st.metric("⚠️ חלקי", partial)

        if run_verify:
            try:
                stores = engine.load_chain_stores()
                if only_missing:
                    stores = [s for s in stores
                              if not s.get("lat") or not s.get("lon")]
                st.info(f"מאמת {len(stores)} חנויות...")
                prog = st.progress(0, text="מתחיל...")
                results = engine.verify_and_update(
                    stores=stores,
                    only_missing=False,  # already filtered above
                    progress_cb=lambda p, t: prog.progress(p, text=t),
                )
                prog.empty()
                st.session_state["ver_results"] = results
                st.rerun()
            except Exception as e:
                st.error(f"שגיאה: {e}")

        results = st.session_state.get("ver_results")
        if results:
            updated_list = [r for r in results if r.status == "updated"]
            partial_list = [r for r in results if r.status == "partial"]
            failed_list  = [r for r in results
                            if r.status in ("failed", "db_error")]

            if updated_list:
                st.divider()
                with st.expander(
                    f"✅ {len(updated_list)} חנויות עודכנו בהצלחה", expanded=True
                ):
                    st.dataframe(
                        [{
                            "שם":       r.store_name,
                            "עיר":      r.city,
                            "ביטחון":   f"{round(r.confidence*100)}%",
                            "ניסיונות": r.attempts,
                            "כתובת חדשה": r.new_address[:60] if r.new_address else "—",
                            "lat":      r.new_lat,
                            "lon":      r.new_lon,
                        } for r in updated_list],
                        use_container_width=True, height=360,
                    )

            if partial_list:
                st.divider()
                with st.expander(
                    f"⚠️ {len(partial_list)} חנויות עודכנו עם ביטחון חלקי",
                    expanded=False
                ):
                    st.caption(
                        "אלו חנויות שנמצאו אך עם ביטחון נמוך מ-80%. "
                        "מומלץ לאמת ידנית."
                    )
                    st.dataframe(
                        [{
                            "שם":       r.store_name,
                            "עיר":      r.city,
                            "ביטחון":   f"{round(r.confidence*100)}%",
                            "ניסיונות": r.attempts,
                            "שאילתה":   r.query_used[:60] if r.query_used else "—",
                            "lat":      r.new_lat,
                            "lon":      r.new_lon,
                        } for r in partial_list],
                        use_container_width=True,
                    )

            if failed_list:
                st.divider()
                st.error(f"❌ {len(failed_list)} חנויות נכשלו — נדרש טיפול ידני")
                with st.expander("📋 דוח חריגים קריטיים", expanded=True):
                    st.caption(
                        "אלו חנויות שגם לאחר 4 שאילתות שונות לא אומתה "
                        "עיר תואמת. יש לתקן ידנית דרך טאב המפה."
                    )
                    for r in failed_list:
                        with st.container(border=True):
                            st.markdown(
                                f"**{r.store_name}** | {r.city} | {r.chain}  \n"
                                f"כתובת נוכחית: `{r.old_address or '—'}`  \n"
                                f"קואורדינטות נוכחיות: "
                                f"`{r.old_lat}, {r.old_lon}`"
                            )
                            if r.reason:
                                st.caption(r.reason)

    # ════════════════════════════════════════════════════════
    # TAB 3 — Full Report
    # ════════════════════════════════════════════════════════
    with t_report:
        st.subheader("📋 דוח מלא")

        ver_results = st.session_state.get("ver_results", [])
        dup_groups  = st.session_state.get("dup_groups", []) or []

        if not ver_results and not dup_groups:
            st.info("הרץ את שלב 1 ו/או שלב 2 כדי לראות את הדוח כאן.")
        else:
            # ── Summary metrics ────────────────────────────────────────────
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("קבוצות כפילויות", len(dup_groups))
            c2.metric("רשומות שנמחקו",
                      sum(len(g.delete_ids) for g in dup_groups
                          if g.executed))
            if ver_results:
                c3.metric("✅ עודכנו",
                          sum(1 for r in ver_results if r.status == "updated"))
                c4.metric("⚠️ חלקי",
                          sum(1 for r in ver_results if r.status == "partial"))
                c5.metric("❌ נכשלו",
                          sum(1 for r in ver_results
                              if r.status in ("failed", "db_error")))

            # ── Export buttons ─────────────────────────────────────────────
            st.divider()
            col_e1, col_e2 = st.columns(2)

            if ver_results:
                import csv, io
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=[
                    "store_id", "store_name", "city", "chain",
                    "status", "confidence", "attempts",
                    "new_lat", "new_lon", "new_address", "reason"
                ])
                writer.writeheader()
                for r in ver_results:
                    writer.writerow({
                        "store_id":   r.store_id,
                        "store_name": r.store_name,
                        "city":       r.city,
                        "chain":      r.chain,
                        "status":     r.status,
                        "confidence": f"{round(r.confidence*100)}%",
                        "attempts":   r.attempts,
                        "new_lat":    r.new_lat or "",
                        "new_lon":    r.new_lon or "",
                        "new_address": r.new_address or "",
                        "reason":     r.reason.replace("\n", " | "),
                    })
                with col_e1:
                    st.download_button(
                        "⬇️ הורד דוח CSV",
                        data=buf.getvalue().encode("utf-8-sig"),
                        file_name="location_engine_report.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

            # ── Full details table ─────────────────────────────────────────
            if ver_results:
                st.divider()
                st.subheader("פירוט כל החנויות")
                status_emoji = {
                    "updated":  "✅",
                    "partial":  "⚠️",
                    "failed":   "❌",
                    "db_error": "💥",
                    "no_change": "—",
                }
                st.dataframe(
                    [{
                        "סטטוס":    status_emoji.get(r.status, r.status),
                        "שם":       r.store_name,
                        "עיר":      r.city,
                        "רשת":      r.chain,
                        "ביטחון":   f"{round(r.confidence*100)}%" if r.confidence else "—",
                        "ניסיונות": r.attempts,
                        "lat":      r.new_lat or r.old_lat or "—",
                        "lon":      r.new_lon or r.old_lon or "—",
                        "כתובת":    (r.new_address or r.old_address or "—")[:60],
                    } for r in ver_results],
                    use_container_width=True,
                    height=500,
                )


# ══════════════════════════════════════════════════════════════════════════════
# ── Standalone entry-point ────────────────────────────────════════════════════
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import streamlit as st
    from dotenv import load_dotenv

    load_dotenv()

    st.set_page_config(
        page_title="Location Engine",
        page_icon="🎯",
        layout="wide",
    )
    st.markdown("""
        <style>
            body, .stApp { direction: rtl; }
            h1, h2, h3  { text-align: center; }
        </style>
    """, unsafe_allow_html=True)

    try:
        _su = st.secrets.get("SUPABASE_URL",      "") or os.getenv("SUPABASE_URL",      "")
        _sk = st.secrets.get("SUPABASE_ANON_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
        _gk = st.secrets.get("GOOGLE_MAPS_API_KEY","") or os.getenv("GOOGLE_MAPS_API_KEY","")
    except Exception:
        _su = os.getenv("SUPABASE_URL",      "")
        _sk = os.getenv("SUPABASE_ANON_KEY", "")
        _gk = os.getenv("GOOGLE_MAPS_API_KEY","")

    render_ui(_su, _sk, _gk)
