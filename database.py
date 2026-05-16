"""
database.py
===========
שכבת גישה ל-Supabase — מחליפה את קריאות GitHub CSV
עבור store_notes ו-manual_visits.

שימוש:
    from database import db

    db.add_note(date, store, city, note)
    db.get_notes()
    db.get_notes_for_store("שילב הרצליה")
    db.add_visit(date, store, city, status, notes)
    db.get_visits()
    db.migrate_from_github(notes_list, visits_list)
"""

import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL     = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")


def _get_client():
    """מחזיר Supabase client."""
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


class StoreDatabase:
    """
    ממשק מרכזי ל-Supabase.
    כל המתודות מחזירות list[dict] או bool.
    """

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = _get_client()
        return self._client

    # ══════════════════════════════════════
    # Store Notes
    # ══════════════════════════════════════

    def get_notes(self, limit: int = 200) -> list[dict]:
        """כל ההערות, ממיין מהחדש לישן."""
        try:
            res = (self.client.table("store_notes")
                   .select("*")
                   .order("created_at", desc=True)
                   .limit(limit)
                   .execute())
            return res.data or []
        except Exception as e:
            print(f"[DB] get_notes error: {e}")
            return []

    def get_notes_for_store(self, store_name: str) -> list[dict]:
        """כל ההערות לחנות ספציפית."""
        try:
            res = (self.client.table("store_notes")
                   .select("*")
                   .eq("store", store_name)
                   .order("created_at", desc=True)
                   .execute())
            return res.data or []
        except Exception as e:
            print(f"[DB] get_notes_for_store error: {e}")
            return []

    def add_note(self, date: str, store: str, city: str, note: str) -> bool:
        """מוסיף הערה חדשה."""
        try:
            self.client.table("store_notes").insert({
                "date":  date,
                "store": store,
                "city":  city,
                "note":  note,
            }).execute()
            return True
        except Exception as e:
            print(f"[DB] add_note error: {e}")
            return False

    # ══════════════════════════════════════
    # Manual Visits
    # ══════════════════════════════════════

    def get_visits(self, limit: int = 500) -> list[dict]:
        """כל הביקורים, ממיין מהחדש לישן."""
        try:
            res = (self.client.table("manual_visits")
                   .select("*")
                   .order("created_at", desc=True)
                   .limit(limit)
                   .execute())
            return res.data or []
        except Exception as e:
            print(f"[DB] get_visits error: {e}")
            return []

    def get_visits_for_store(self, store_name: str) -> list[dict]:
        """כל הביקורים לחנות ספציפית."""
        try:
            res = (self.client.table("manual_visits")
                   .select("*")
                   .eq("store", store_name)
                   .order("created_at", desc=True)
                   .execute())
            return res.data or []
        except Exception as e:
            print(f"[DB] get_visits_for_store error: {e}")
            return []

    def add_visit(self, date: str, store: str, city: str,
                  status: str = "ביקור", notes: str = "") -> bool:
        """מוסיף ביקור חדש."""
        try:
            self.client.table("manual_visits").insert({
                "date":   date,
                "store":  store,
                "city":   city,
                "status": status,
                "notes":  notes,
            }).execute()
            return True
        except Exception as e:
            print(f"[DB] add_visit error: {e}")
            return False

    # ══════════════════════════════════════
    # Migration — GitHub CSV → Supabase
    # ══════════════════════════════════════

    def migrate_from_github(self,
                             notes_list:  list[dict],
                             visits_list: list[dict]) -> dict:
        """
        מעביר נתונים קיימים מ-GitHub CSV ל-Supabase.
        מריץ פעם אחת בלבד.

        Returns: {"notes": int, "visits": int, "errors": list}
        """
        errors   = []
        n_notes  = 0
        n_visits = 0

        # ── העבר הערות ──
        for n in notes_list:
            try:
                self.client.table("store_notes").insert({
                    "date":  n.get("date", ""),
                    "store": n.get("store", ""),
                    "city":  n.get("city", ""),
                    "note":  n.get("note", ""),
                }).execute()
                n_notes += 1
            except Exception as e:
                errors.append(f"note: {n.get('store','')} — {e}")

        # ── העבר ביקורים ──
        for v in visits_list:
            try:
                self.client.table("manual_visits").insert({
                    "date":   v.get("date", ""),
                    "store":  v.get("store", ""),
                    "city":   v.get("city", ""),
                    "status": v.get("status", "ביקור"),
                    "notes":  v.get("notes", ""),
                }).execute()
                n_visits += 1
            except Exception as e:
                errors.append(f"visit: {v.get('store','')} — {e}")

        return {"notes": n_notes, "visits": n_visits, "errors": errors}

    # ══════════════════════════════════════
    # Store Aliases (Rule B)
    # ══════════════════════════════════════

    def get_aliases(self) -> dict:
        """
        מחזיר מילון aliasים: {branch_norm: store_name}
        מאפשר התאמה אוטומטית לתעודות שאושרו ידנית.
        """
        try:
            res = (self.client.table("store_aliases")
                   .select("branch_norm,store_name")
                   .execute())
            return {row["branch_norm"]: row["store_name"] for row in (res.data or [])}
        except Exception as e:
            print(f"[DB] get_aliases error: {e}")
            return {}

    def save_alias(self, branch_raw: str, store_name: str) -> bool:
        """
        שומר alias חדש (upsert לפי branch_norm).
        branch_raw — שם הסניף הגולמי מהתעודה
        store_name — שם החנות הקנוני מ-stores.csv
        """
        try:
            from visit_tracker import _normalize
            branch_norm = _normalize(branch_raw)
            self.client.table("store_aliases").upsert({
                "branch_norm": branch_norm,
                "store_name":  store_name,
            }, on_conflict="branch_norm").execute()
            return True
        except Exception as e:
            print(f"[DB] save_alias error: {e}")
            return False

    def delete_alias(self, branch_norm: str) -> bool:
        """מוחק alias לפי branch_norm."""
        try:
            self.client.table("store_aliases").delete().eq("branch_norm", branch_norm).execute()
            return True
        except Exception as e:
            print(f"[DB] delete_alias error: {e}")
            return False

    def is_connected(self) -> bool:
        """בדיקת חיבור לDB."""
        try:
            self.client.table("store_notes").select("id").limit(1).execute()
            return True
        except Exception:
            return False


# ── singleton ──────────────────────────────────────────────
db = StoreDatabase()


# ── הרצה ישירה (בדיקה + מיגרציה) ─────────────────────────
if __name__ == "__main__":
    import sys, csv, io, requests
    sys.stdout.reconfigure(encoding="utf-8")

    print("🔌 מתחבר ל-Supabase...")
    if not db.is_connected():
        print("❌ חיבור נכשל — בדוק SUPABASE_URL ו-SUPABASE_ANON_KEY")
        sys.exit(1)
    print("✅ מחובר!\n")

    # ── טען נתונים קיימים מ-GitHub ──
    BASE = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main"

    def fetch(url):
        r = requests.get(url, timeout=10)
        return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))

    print("📥 טוען נתונים מ-GitHub...")
    notes  = fetch(f"{BASE}/store_notes.csv")
    visits = fetch(f"{BASE}/manual_visits.csv")
    print(f"   הערות: {len(notes)} | ביקורים: {len(visits)}\n")

    # ── בדוק אם כבר בוצעה מיגרציה ──
    existing_notes  = db.get_notes(limit=1)
    existing_visits = db.get_visits(limit=1)
    if existing_notes or existing_visits:
        print("⚠️  כבר יש נתונים ב-Supabase — מדלג על מיגרציה")
    else:
        print("🚀 מבצע מיגרציה מ-GitHub ל-Supabase...")
        result = db.migrate_from_github(notes, visits)
        print(f"✅ הועברו: {result['notes']} הערות | {result['visits']} ביקורים")
        if result["errors"]:
            print(f"⚠️  שגיאות ({len(result['errors'])}):")
            for e in result["errors"]:
                print(f"   {e}")

    # ── בדיקת קריאה ──
    print("\n📋 3 הערות אחרונות ב-Supabase:")
    for n in db.get_notes(limit=3):
        print(f"  • {n['date']} | {n['store']} — {n['note'][:50]}")

    print("\n👣 3 ביקורים אחרונים ב-Supabase:")
    for v in db.get_visits(limit=3):
        print(f"  • {v['date']} | {v['store']} — {v['status']}")
