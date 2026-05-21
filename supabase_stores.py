"""
supabase_stores.py
==================
Task 3: החלפת קריאת GitHub CSV בשאילתות Supabase ישירות.

SQL ליצירת הטבלאות — הרץ פעם אחת ב-Supabase SQL Editor:
─────────────────────────────────────────────────────────

    -- טבלת חנויות
    CREATE TABLE IF NOT EXISTS stores (
        id          BIGSERIAL PRIMARY KEY,
        chain       TEXT,
        name        TEXT NOT NULL,
        city        TEXT,
        address     TEXT,
        phone       TEXT,
        lat         DOUBLE PRECISION,
        lon         DOUBLE PRECISION,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_stores_name_city ON stores(name, city);
    CREATE INDEX        IF NOT EXISTS idx_stores_chain     ON stores(chain);
    CREATE INDEX        IF NOT EXISTS idx_stores_city      ON stores(city);

    -- Row Level Security: קריאה פתוחה, כתיבה רק עם service_role
    ALTER TABLE stores ENABLE ROW LEVEL SECURITY;
    CREATE POLICY "anon_read" ON stores FOR SELECT USING (true);

    -- טבלת תעודות סנזי
    CREATE TABLE IF NOT EXISTS senzey_deliveries (
        id          BIGINT PRIMARY KEY,
        date_str    TEXT,           -- "14/05/26 13:31"
        customer    TEXT,
        branch      TEXT,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_senzey_created ON senzey_deliveries(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_senzey_date    ON senzey_deliveries(date_str);

    -- RLS
    ALTER TABLE senzey_deliveries ENABLE ROW LEVEL SECURITY;
    CREATE POLICY "anon_read" ON senzey_deliveries FOR SELECT USING (true);

    -- פונקציית ניקוי אוטומטי — מוחקת תעודות ישנות מ-3 חודשים+
    CREATE OR REPLACE FUNCTION purge_old_deliveries(months_back INT DEFAULT 3)
    RETURNS INT LANGUAGE plpgsql AS $$
    DECLARE deleted INT;
    BEGIN
      DELETE FROM senzey_deliveries
      WHERE created_at < NOW() - (months_back || ' months')::INTERVAL;
      GET DIAGNOSTICS deleted = ROW_COUNT;
      RETURN deleted;
    END;
    $$;

    -- פונקציית מחיקת כפילויות לפי id (שומרת את השורה הראשונה)
    CREATE OR REPLACE FUNCTION deduplicate_deliveries()
    RETURNS INT LANGUAGE plpgsql AS $$
    DECLARE deleted INT;
    BEGIN
      DELETE FROM senzey_deliveries a
      USING senzey_deliveries b
      WHERE a.ctid > b.ctid AND a.id = b.id;
      GET DIAGNOSTICS deleted = ROW_COUNT;
      RETURN deleted;
    END;
    $$;

─────────────────────────────────────────────────────────

SQL ל-Task 6: visit_stats_view — הרץ ב-Supabase SQL Editor:
─────────────────────────────────────────────────────────

    -- פונקציה: ממיר תאריך ישראלי (DD/MM/YY HH:MI) ל-timestamptz
    CREATE OR REPLACE FUNCTION parse_il_date(dt_str text)
    RETURNS timestamptz
    LANGUAGE plpgsql IMMUTABLE AS $$
    BEGIN
      IF dt_str IS NULL OR trim(dt_str) = '' THEN RETURN NULL; END IF;
      IF dt_str ~ '^\d{1,2}/\d{1,2}/\d{2} \d{2}:\d{2}' THEN
        RETURN to_timestamp(trim(dt_str), 'DD/MM/YY HH24:MI');
      END IF;
      IF dt_str ~ '^\d{1,2}/\d{1,2}/\d{4} \d{2}:\d{2}' THEN
        RETURN to_timestamp(trim(dt_str), 'DD/MM/YYYY HH24:MI');
      END IF;
      IF dt_str ~ '^\d{1,2}/\d{1,2}/\d{2}$' THEN
        RETURN to_timestamp(trim(dt_str), 'DD/MM/YY');
      END IF;
      IF dt_str ~ '^\d{1,2}/\d{1,2}/\d{4}$' THEN
        RETURN to_timestamp(trim(dt_str), 'DD/MM/YYYY');
      END IF;
      RETURN NULL;
    EXCEPTION WHEN others THEN RETURN NULL;
    END;
    $$;

    -- View: סטטיסטיקות ביקורים לכל חנות
    -- מחבר: stores + manual_visits (ישיר) + senzey_deliveries (דרך store_aliases)
    CREATE OR REPLACE VIEW visit_stats_view AS
    WITH
    -- ביקורים ידניים — שם החנות ישיר
    manual_v AS (
      SELECT store          AS store_name,
             parse_il_date(date) AS visit_dt
      FROM   manual_visits
      WHERE  date IS NOT NULL AND date <> ''
    ),
    -- תעודות משלוח — רק מה שכבר אושר ב-store_aliases
    delivery_v AS (
      SELECT sa.store_name,
             parse_il_date(sd.date) AS visit_dt
      FROM   senzey_deliveries sd
      JOIN   store_aliases sa
        ON   sa.branch_norm = lower(trim(sd.branch))
          OR sa.branch_norm = sd.branch
      WHERE  sd.date IS NOT NULL AND sd.date <> ''
    ),
    -- כל הביקורים ביחד
    all_v AS (
      SELECT store_name, visit_dt FROM manual_v   WHERE visit_dt IS NOT NULL
      UNION ALL
      SELECT store_name, visit_dt FROM delivery_v WHERE visit_dt IS NOT NULL
    ),
    -- אגרגציה: ביקור אחרון + ספירה
    agg AS (
      SELECT store_name,
             MAX(visit_dt)  AS last_visit_dt,
             COUNT(*)::int  AS visit_count
      FROM   all_v
      GROUP  BY store_name
    )
    SELECT
      s.name,
      s.city,
      s.chain,
      s.lat::float,
      s.lon::float,
      agg.last_visit_dt,
      TO_CHAR(agg.last_visit_dt AT TIME ZONE 'Asia/Jerusalem', 'DD/MM/YY') AS last_date_str,
      agg.visit_count,
      CASE
        WHEN agg.last_visit_dt IS NULL THEN NULL
        ELSE EXTRACT(
          DAY FROM (
            NOW() AT TIME ZONE 'Asia/Jerusalem'
            - agg.last_visit_dt AT TIME ZONE 'Asia/Jerusalem'
          )
        )::int
      END AS days_since
    FROM stores s
    LEFT JOIN agg ON agg.store_name = s.name;

    -- הרשאות קריאה ל-anon
    GRANT SELECT ON visit_stats_view TO anon;

─────────────────────────────────────────────────────────
"""

import os
import csv
import io
import streamlit as st
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

ISRAEL_TZ   = timezone(timedelta(hours=3))
MONTHS_BACK = 3   # כמה חודשים אחורה לטעון תעודות סנזי


# ── Supabase client (singleton) ────────────────────────────────────────────

def _get_supabase():
    """מחזיר Supabase client עם ה-credentials מה-environment."""
    from supabase import create_client
    url = key = ""
    try:
        url = st.secrets.get("SUPABASE_URL", "") or ""
        key = st.secrets.get("SUPABASE_ANON_KEY", "") or ""
    except Exception:
        pass
    url = url or os.getenv("SUPABASE_URL", "")
    key = key or os.getenv("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY לא מוגדרים")
    return create_client(url, key)


# ══════════════════════════════════════════════════════════════════
# Task 3A — חנויות ישירות מ-Supabase (מחליף get_stores מ-GitHub CSV)
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def get_stores_supabase() -> list[dict]:
    """
    טוען את כל החנויות מ-Supabase.
    Cache: שעה אחת (חנויות לא משתנות לעיתים קרובות).
    Fallback: GitHub CSV אם Supabase לא זמין.
    """
    try:
        client = _get_supabase()
        res    = (client.table("stores")
                  .select("chain,name,city,address,phone,lat,lon")
                  .order("chain")
                  .order("name")
                  .execute())

        if not res.data:
            raise ValueError("אין נתונים בטבלת stores — מריץ migration?")

        stores = []
        seen   = set()
        for row in res.data:
            name = row.get("name", "").strip()
            city = row.get("city", "").strip()
            if not name or (name, city) in seen:
                continue
            seen.add((name, city))
            stores.append({
                "name":    name,
                "city":    city,
                "address": row.get("address", "").strip() or "",
                "chain":   row.get("chain",   "").strip() or "",
                "phone":   row.get("phone",   "").strip() or "",
                "lat":     str(row.get("lat", "") or ""),
                "lon":     str(row.get("lon", "") or ""),
            })
        return stores

    except Exception as e:
        st.warning(f"⚠️ Supabase לא זמין ({e}) — נופל ל-GitHub CSV")
        return _get_stores_github_fallback()


def _get_stores_github_fallback() -> list[dict]:
    """Fallback: קורא stores.csv מ-GitHub אם Supabase לא עובד."""
    import requests
    try:
        url  = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/stores.csv"
        r    = requests.get(url, timeout=10)
        text = r.content.decode("utf-8-sig")
        rows, seen, stores = list(csv.DictReader(io.StringIO(text))), set(), []
        for row in rows:
            name = row.get("name", "").strip()
            city = row.get("city", "").strip()
            if not name or (name, city) in seen:
                continue
            seen.add((name, city))
            stores.append({
                "name":    name,   "city":    city,
                "address": row.get("address", "").strip(),
                "chain":   row.get("chain",   "").strip(),
                "phone":   row.get("phone",   "").strip(),
                "lat":     row.get("lat",     "").strip(),
                "lon":     row.get("lon",     "").strip(),
            })
        return stores
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════
# Task 3B — תעודות סנזי ישירות מ-Supabase
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=900, show_spinner=False)
def get_deliveries_supabase(months_back: int = MONTHS_BACK) -> list[dict]:
    """
    טוען תעודות משלוח מ-Supabase (3 חודשים אחרונים בלבד).
    Cache: 15 דקות.
    """
    try:
        client   = _get_supabase()
        cutoff   = (datetime.now(ISRAEL_TZ) - timedelta(days=months_back * 30)).isoformat()

        res = (client.table("senzey_deliveries")
               .select("id,date_str,customer,branch")
               .gte("created_at", cutoff)
               .order("created_at", desc=True)
               .limit(2000)
               .execute())

        return [
            {
                "id":       str(r.get("id", "")),
                "date":     r.get("date_str", ""),
                "customer": r.get("customer", ""),
                "branch":   r.get("branch",   ""),
            }
            for r in (res.data or [])
        ]
    except Exception as e:
        st.warning(f"⚠️ Supabase לא זמין ({e}) — נופל ל-GitHub CSV")
        return _get_deliveries_github_fallback()


def _get_deliveries_github_fallback() -> list[dict]:
    import requests
    try:
        url  = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/senzey_data.csv"
        r    = requests.get(url, timeout=10)
        return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════
# Task 4 — ניקוי ומיחזור נתונים (Data Cleanup / GC)
# ══════════════════════════════════════════════════════════════════

def migrate_stores_csv_to_supabase(csv_path: str = "stores.csv") -> dict:
    """
    Migration חד-פעמי: מעביר stores.csv ל-Supabase.
    הרץ מהמחשב המקומי פעם אחת בלבד.

    python -c "from supabase_stores import migrate_stores_csv_to_supabase; migrate_stores_csv_to_supabase()"
    """
    client  = _get_supabase()
    ok = err = 0

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    batch = []
    for row in rows:
        name = row.get("name", "").strip()
        if not name:
            continue
        try:
            lat = float(row["lat"]) if row.get("lat") else None
            lon = float(row["lon"]) if row.get("lon") else None
        except ValueError:
            lat = lon = None

        batch.append({
            "chain":   row.get("chain",   "").strip() or None,
            "name":    name,
            "city":    row.get("city",    "").strip() or None,
            "address": row.get("address", "").strip() or None,
            "phone":   row.get("phone",   "").strip() or None,
            "lat":     lat,
            "lon":     lon,
        })

        if len(batch) == 50:   # upsert בבאצ'ים של 50
            try:
                client.table("stores").upsert(
                    batch, on_conflict="name,city"
                ).execute()
                ok += len(batch)
            except Exception as e:
                err += len(batch)
                print(f"  ⚠️ batch error: {e}")
            batch = []

    if batch:
        try:
            client.table("stores").upsert(
                batch, on_conflict="name,city"
            ).execute()
            ok += len(batch)
        except Exception as e:
            err += len(batch)

    print(f"✅ migration הושלמה: {ok} חנויות | {err} שגיאות")
    return {"ok": ok, "errors": err}


def migrate_senzey_csv_to_supabase(csv_path: str = "senzey_data.csv",
                                    months_back: int = 3) -> dict:
    """
    Migration חד-פעמי: מעביר senzey_data.csv ל-Supabase.
    מוגבל ל-N חודשים אחרונים.
    """
    from datetime import datetime
    client = _get_supabase()
    cutoff = datetime.now() - timedelta(days=months_back * 30)
    ok = skip = err = 0

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # מיחזור כפילויות לפי id לפני העלאה
    seen_ids = {}
    for row in rows:
        rid = row.get("id", "")
        if rid and rid not in seen_ids:
            seen_ids[rid] = row

    batch = []
    for row in seen_ids.values():
        date_str = row.get("date", "")
        try:
            dt = datetime.strptime(date_str[:14], "%d/%m/%y %H:%M")
            if dt < cutoff:
                skip += 1
                continue
        except Exception:
            pass

        try:
            rid = int(row["id"]) if row.get("id", "").isdigit() else None
        except Exception:
            rid = None
        if not rid:
            skip += 1
            continue

        batch.append({
            "id":       rid,
            "date":     date_str,
            "customer": row.get("customer", ""),
            "branch":   row.get("branch",   ""),
        })

        if len(batch) == 100:
            try:
                client.table("senzey_deliveries").upsert(
                    batch, on_conflict="id"
                ).execute()
                ok += len(batch)
            except Exception as e:
                err += len(batch)
                print(f"  ⚠️ batch error: {e}")
            batch = []

    if batch:
        try:
            client.table("senzey_deliveries").upsert(
                batch, on_conflict="id"
            ).execute()
            ok += len(batch)
        except Exception as e:
            err += len(batch)

    print(f"✅ senzey migration: {ok} תעודות | {skip} דולגו | {err} שגיאות")
    return {"ok": ok, "skipped": skip, "errors": err}


def run_data_cleanup(months_back: int = 3) -> dict:
    """
    Task 4: מנקה נתונים ישנים וכפולים מ-Supabase.
    מחזיר סיכום של מה שנמחק.

    ניתן לקרוא מ-Streamlit דרך כפתור "🗑️ ניקוי נתונים" בלשונית ביקורים.
    """
    client  = _get_supabase()
    results = {}

    # ── 1. מחק כפילויות בתעודות ──
    try:
        res = client.rpc("deduplicate_deliveries").execute()
        results["duplicates_deleted"] = res.data or 0
    except Exception as e:
        results["duplicates_error"] = str(e)

    # ── 2. מחק תעודות ישנות (> N חודשים) ──
    try:
        res = client.rpc("purge_old_deliveries",
                         {"months_back": months_back}).execute()
        results["old_records_deleted"] = res.data or 0
    except Exception as e:
        results["purge_error"] = str(e)

    # ── 3. נקה cache של Streamlit ──
    st.cache_data.clear()
    results["cache_cleared"] = True

    return results


def cleanup_senzey_csv_local(csv_path: str = "senzey_data.csv",
                               months_back: int = 3) -> dict:
    """
    Task 4 (גרסת CSV): מנקה senzey_data.csv המקומי מכפילויות ורשומות ישנות.
    שימושי לפני migration ולתחזוקת הקובץ.
    """
    cutoff   = datetime.now() - timedelta(days=months_back * 30)
    seen_ids = {}
    skipped  = 0

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    original_count = len(rows)

    for row in rows:
        rid      = row.get("id", "")
        date_str = row.get("date", "")

        # סנן ישנות
        try:
            dt = datetime.strptime(date_str[:14], "%d/%m/%y %H:%M")
            if dt < cutoff:
                skipped += 1
                continue
        except Exception:
            pass

        # סנן כפילויות — שמור רק הראשונה לפי id
        if rid and rid in seen_ids:
            skipped += 1
            continue

        if rid:
            seen_ids[rid] = row

    clean_rows = list(seen_ids.values())
    # מיין: חדש → ישן
    def sort_key(r):
        try:
            return datetime.strptime(r.get("date","")[:14], "%d/%m/%y %H:%M")
        except Exception:
            return datetime.min

    clean_rows.sort(key=sort_key, reverse=True)

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "date", "customer", "branch"])
        w.writeheader()
        w.writerows(clean_rows)

    result = {
        "original":  original_count,
        "kept":      len(clean_rows),
        "removed":   original_count - len(clean_rows),
        "cutoff":    cutoff.strftime("%d/%m/%Y"),
    }
    print(f"✅ senzey cleanup: {result['removed']} הוסרו, {result['kept']} נשמרו (מ-{result['original']})")
    return result


# ── הרצה ישירה לצורך migration ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "migrate-stores":
        migrate_stores_csv_to_supabase()

    elif cmd == "migrate-senzey":
        months = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        migrate_senzey_csv_to_supabase(months_back=months)

    elif cmd == "cleanup-csv":
        months = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        cleanup_senzey_csv_local(months_back=months)

    elif cmd == "cleanup-db":
        months = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        # הרצה מחוץ ל-Streamlit — צריך mock
        import streamlit as st
        result = run_data_cleanup(months_back=months)
        print(result)

    else:
        print("""
שימוש:
  python supabase_stores.py migrate-stores        # העבר stores.csv → Supabase
  python supabase_stores.py migrate-senzey [3]   # העבר senzey_data.csv → Supabase (N חודשים)
  python supabase_stores.py cleanup-csv [3]       # נקה senzey_data.csv מקומי
  python supabase_stores.py cleanup-db [3]        # נקה Supabase מרשומות ישנות/כפולות
""")
