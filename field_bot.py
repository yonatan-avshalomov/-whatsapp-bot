"""
field_bot.py — Production Telegram CRM Bot
==========================================
24/7 Render Background Worker.  Stateless bot + stateful Supabase.

Architecture
------------
  Sessions  → bot_sessions table in Supabase (survives restarts)
  Notes     → store_notes table, every row tagged with telegram_user_id
  AI        → Claude claude-haiku-4-5 with 5 tools (search, list, notes, save, checkin)
  Memory    → _sessions dict as L1 cache over Supabase (speed, not truth)

BEFORE FIRST DEPLOY — run this SQL in Supabase SQL Editor:
───────────────────────────────────────────────────────────
  -- 1. Persistent agent sessions
  CREATE TABLE IF NOT EXISTS bot_sessions (
      telegram_user_id  BIGINT PRIMARY KEY,
      store_id          INTEGER,
      store_name        TEXT    NOT NULL,
      store_city        TEXT    DEFAULT '',
      store_address     TEXT    DEFAULT '',
      checkin_time      TEXT    DEFAULT '',
      user_name         TEXT    DEFAULT '',
      updated_at        TIMESTAMPTZ DEFAULT NOW()
  );
  ALTER TABLE bot_sessions ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "anon_all" ON bot_sessions
      USING (true) WITH CHECK (true);

  -- 2. Author ID column on notes (safe — adds only if missing)
  ALTER TABLE store_notes
      ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT;
───────────────────────────────────────────────────────────

Env vars (Render → Environment):
  TELEGRAM_TOKEN       bot token from @BotFather
  SUPABASE_URL         https://xxx.supabase.co
  SUPABASE_ANON_KEY    eyJ...
  ANTHROPIC_API_KEY    sk-ant-...
  OPENAI_API_KEY       sk-...  (optional, for voice transcription)
  AUTHORIZED_USERS     123,456  (empty = open to everyone)
  DISABLE_SSL_VERIFY   true  (local Windows dev only, NOT on Render)

requirements.txt must contain:
  python-telegram-bot>=20.7
  anthropic>=0.25
  openai>=1.14
  supabase
  python-dotenv
"""

# ── stdlib ─────────────────────────────────────────────────────────────────────
import asyncio
import logging
import math
import os
import ssl
import tempfile
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

# ── third-party ────────────────────────────────────────────────────────────────
from dotenv import load_dotenv

load_dotenv()

# Local dev on Windows has broken SSL certs — never set this on Render
if os.getenv("DISABLE_SSL_VERIFY", "").lower() == "true":
    ssl._create_default_https_context = ssl._create_unverified_context  # noqa: S501

# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("field_bot")

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "")
SUPABASE_URL      = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY      = os.getenv("SUPABASE_ANON_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
ISRAEL_TZ         = timezone(timedelta(hours=3))

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTHORIZED_IDS: set[int] = set()
for _p in os.getenv("AUTHORIZED_USERS", "").split(","):
    try:
        AUTHORIZED_IDS.add(int(_p.strip()))
    except ValueError:
        pass

# ── In-memory L1 cache over Supabase ─────────────────────────────────────────
# { telegram_user_id: {store_name, store_city, store_address, checkin_time, ...} }
_sessions: dict[int, dict] = {}
# Conversation history for AI — in-memory only (not worth persisting)
_conversations: dict[int, list] = {}


# ══════════════════════════════════════════════════════════════════════════════
# Auth
# ══════════════════════════════════════════════════════════════════════════════

async def _check_auth(update, context) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if not AUTHORIZED_IDS:
        return True
    if uid in AUTHORIZED_IDS:
        return True
    log.warning("Unauthorized access: uid=%s", uid)
    if update.message:
        await update.message.reply_text("🔒 Access Denied.")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Supabase client
# ══════════════════════════════════════════════════════════════════════════════

def _db():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def _now_il() -> str:
    return datetime.now(ISRAEL_TZ).strftime("%d/%m/%y %H:%M")


# ══════════════════════════════════════════════════════════════════════════════
# Persistent session management  (Supabase-backed)
# ══════════════════════════════════════════════════════════════════════════════

def _load_session(uid: int) -> dict | None:
    """
    Return active session for uid.
    L1: memory cache.  L2: Supabase bot_sessions.
    Returns None if no active session exists.
    """
    if uid in _sessions:
        return _sessions[uid]
    try:
        res = (
            _db().table("bot_sessions")
            .select("*")
            .eq("telegram_user_id", uid)
            .maybe_single()
            .execute()
        )
        if res.data:
            _sessions[uid] = res.data
            return res.data
    except Exception as e:
        log.error("_load_session(%s): %s", uid, e)
    return None


def _save_session(uid: int, store: dict, fname: str) -> None:
    """
    Upsert the agent's active store to both memory and Supabase.
    Called on every check-in (GPS or /checkin command or AI checkin_store tool).
    """
    row = {
        "telegram_user_id": uid,
        "store_id":          store.get("id"),
        "store_name":        store["name"],
        "store_city":        store.get("city", ""),
        "store_address":     store.get("address", ""),
        "checkin_time":      _now_il(),
        "user_name":         fname,
        "updated_at":        datetime.now(ISRAEL_TZ).isoformat(),
    }
    # Always write to memory immediately
    _sessions[uid] = row
    # Write to Supabase (best-effort — don't block the handler)
    try:
        _db().table("bot_sessions").upsert(
            row, on_conflict="telegram_user_id"
        ).execute()
        log.info("Session saved: uid=%s → %s", uid, store["name"])
    except Exception as e:
        log.error("_save_session(%s): %s", uid, e)


# ══════════════════════════════════════════════════════════════════════════════
# Store helpers
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_stores() -> list[dict]:
    try:
        res = (
            _db().table("stores")
            .select("id,chain,name,city,address,lat,lon")
            .not_.is_("lat", "null")
            .not_.is_("lon", "null")
            .execute()
        )
        return [s for s in (res.data or []) if s.get("lat") and s.get("lon")]
    except Exception as e:
        log.error("_fetch_stores: %s", e)
        return []

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))

def _nearest_store(ulat: float, ulon: float) -> tuple[dict | None, float]:
    best, best_km = None, float("inf")
    for s in _fetch_stores():
        try:
            d = _haversine(ulat, ulon, float(s["lat"]), float(s["lon"]))
        except (TypeError, ValueError):
            continue
        if d < best_km:
            best, best_km = s, d
    return best, best_km

def _score(query: str, s: dict) -> float:
    q    = query.strip().lower()
    name = s.get("name", "").lower()
    city = s.get("city", "").lower()
    if q in name or q in city:
        return 0.7 + SequenceMatcher(None, q, name).ratio() * 0.3
    tail = " ".join(name.split()[2:]) if len(name.split()) > 2 else name
    return max(
        SequenceMatcher(None, q, name).ratio(),
        SequenceMatcher(None, q, tail).ratio(),
        SequenceMatcher(None, q, city).ratio(),
    )

def _fuzzy_find(query: str) -> dict | None:
    best, best_score = None, 0.0
    for s in _fetch_stores():
        sc = _score(query, s)
        if sc > best_score:
            best, best_score = s, sc
    return best if best_score >= 0.35 else None

def _search_multi(query: str, limit: int = 6) -> list[dict]:
    scored = [(sc, s) for s in _fetch_stores() if (sc := _score(query, s)) >= 0.3]
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:limit]]

def _list_stores(city: str | None, chain: str | None, limit: int = 15) -> list[dict]:
    try:
        q = _db().table("stores").select("name,city,address,chain")
        if city:
            q = q.ilike("city", f"%{city}%")
        if chain:
            q = q.ilike("chain", f"%{chain}%")
        return q.order("city").limit(limit).execute().data or []
    except Exception as e:
        log.error("_list_stores: %s", e)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# Notes & visits
# ══════════════════════════════════════════════════════════════════════════════

def _get_notes(store_name: str, limit: int = 5) -> list[dict]:
    try:
        res = (
            _db().table("store_notes")
            .select("note,date,created_at")
            .eq("store", store_name)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.error("_get_notes(%s): %s", store_name, e)
        return []

def _save_note(store: dict, text: str, fname: str, uid: int) -> bool:
    """
    INSERT to store_notes — never UPDATE, history is sacred.
    Stores both the author name (readable) and telegram_user_id (stable).
    """
    try:
        _db().table("store_notes").insert({
            "date":             _now_il(),
            "store":            store["name"],
            "city":             store.get("city", ""),
            "note":             f"[{fname}] {text.strip()}",
            "telegram_user_id": uid,
        }).execute()
        log.info("Note saved → %s (uid=%s)", store["name"], uid)
        return True
    except Exception as e:
        log.error("_save_note: %s", e)
        return False

def _log_visit(store: dict, fname: str, uid: int) -> None:
    try:
        _db().table("manual_visits").insert({
            "date":   _now_il(),
            "store":  store["name"],
            "city":   store.get("city", ""),
            "status": "ביקור",
            "notes":  f"[{fname} | uid:{uid}] צ'ק-אין בוט טלגרם",
        }).execute()
    except Exception as e:
        log.warning("_log_visit: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# Voice transcription (Whisper)
# ══════════════════════════════════════════════════════════════════════════════

async def _transcribe(file_path: str) -> str | None:
    if not OPENAI_API_KEY:
        return None
    try:
        import openai
        client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        with open(file_path, "rb") as fh:
            result = await client.audio.transcriptions.create(
                model="whisper-1", file=fh, language="he"
            )
        return (result.text or "").strip() or None
    except Exception as e:
        log.error("Whisper: %s", e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Claude AI agent — tools + agentic loop
# ══════════════════════════════════════════════════════════════════════════════

_TOOLS = [
    {
        "name": "search_stores",
        "description": (
            "חפש חנויות לפי שם, עיר, רשת, כתובת. "
            "השתמש כשהמשתמש שואל על חנות ספציפית או בעיר מסוימת."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_stores_by_city",
        "description": "רשימת כל החנויות בעיר או רשת מסוימת.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city":  {"type": "string"},
                "chain": {"type": "string"},
            },
        },
    },
    {
        "name": "get_store_notes",
        "description": (
            "שלוף הערות שטח אחרונות לחנות. "
            "השתמש כשהמשתמש שואל על מצב חנות, היסטוריה, או מה קרה שם."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_name": {"type": "string"},
                "limit":      {"type": "integer", "default": 5},
            },
            "required": ["store_name"],
        },
    },
    {
        "name": "save_note",
        "description": (
            "שמור הערת שטח לחנות. "
            "קרא לזה מיד כשהמשתמש מדווח מידע — מלאי, פגישה, בעיה, מצב. "
            "אם החנות הפעילה ידועה — השתמש בה ללא שאלה."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_name": {"type": "string"},
                "note_text":  {"type": "string"},
            },
            "required": ["store_name", "note_text"],
        },
    },
    {
        "name": "checkin_store",
        "description": (
            "צ'ק-אין לחנות — הגדר כחנות הפעילה של הסוכן. "
            "קרא לזה כשהסוכן אומר 'אני ב...', 'הגעתי ל...', 'צ'ק-אין'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_name": {"type": "string"},
            },
            "required": ["store_name"],
        },
    },
]


def _build_system(fname: str, uid: int) -> str:
    session = _load_session(uid)  # reads from memory or Supabase
    if session:
        active_line = (
            f"החנות הפעילה כרגע: {session['store_name']} "
            f"({session.get('store_city','')}) — "
            f"צ'ק-אין ב-{session.get('checkin_time','?')}"
        )
    else:
        active_line = "אין חנות פעילה כרגע."

    return f"""אתה עוזר CRM חכם לסוכן שטח בשם {fname} (id: {uid}).
{active_line}
שעה: {_now_il()}

יש לך גישה למאגר מאות חנויות בישראל.

כללים:
- דבר עברית, קצר וממוקד
- כשהסוכן מדווח מידע שטח — קרא ל-save_note מיד ואשר
- כשהסוכן אומר "אני ב-X" — קרא ל-checkin_store
- לאחר save_note: "💾 הערה נשמרה ל: [שם]"
- לאחר checkin_store: "✅ צ'ק-אין: [שם] | [עיר]" + הערה אחרונה
- אל תשאל שאלות מיותרות — פעל"""


async def _run_tool(name: str, inputs: dict, uid: int, fname: str) -> str:
    try:
        if name == "search_stores":
            stores = await asyncio.to_thread(_search_multi, inputs["query"], inputs.get("limit", 5))
            if not stores:
                return "לא נמצאו חנויות."
            return "\n".join(f"• {s['name']} | {s.get('city','')} | {s.get('address','—')}" for s in stores)

        if name == "list_stores_by_city":
            stores = await asyncio.to_thread(_list_stores, inputs.get("city"), inputs.get("chain"))
            if not stores:
                return "לא נמצאו חנויות."
            lines = [f"• {s['name']} | {s.get('city','')} | {s.get('address','—')}" for s in stores]
            return f"{len(stores)} חנויות:\n" + "\n".join(lines)

        if name == "get_store_notes":
            notes = await asyncio.to_thread(_get_notes, inputs["store_name"], inputs.get("limit", 5))
            if not notes:
                return f"אין הערות ל-{inputs['store_name']}."
            return "\n".join(f"[{n.get('date','?')}] {n['note']}" for n in notes)

        if name == "save_note":
            store = await asyncio.to_thread(_fuzzy_find, inputs["store_name"])
            if not store:
                return f"לא נמצאה חנות: {inputs['store_name']}"
            ok = await asyncio.to_thread(_save_note, store, inputs["note_text"], fname, uid)
            return f"נשמר ל-{store['name']}." if ok else "שגיאה בשמירה."

        if name == "checkin_store":
            store = await asyncio.to_thread(_fuzzy_find, inputs["store_name"])
            if not store:
                return f"לא נמצאה חנות: {inputs['store_name']}"
            await asyncio.to_thread(_save_session, uid, store, fname)
            asyncio.create_task(asyncio.to_thread(_log_visit, store, fname, uid))
            notes = await asyncio.to_thread(_get_notes, store["name"], 1)
            last  = notes[0]["note"] if notes else "אין הערות קודמות"
            return (
                f"צ'ק-אין: {store['name']} | {store.get('city','')} | {store.get('address','—')}\n"
                f"הערה אחרונה: {last}"
            )

    except Exception as e:
        log.error("Tool %s error: %s", name, e)
        return f"שגיאה: {e}"

    return "פעולה לא מוכרת."


async def _agent(uid: int, fname: str, user_text: str) -> str:
    """Run Claude agentic loop. Max 5 tool-use rounds per turn."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    if uid not in _conversations:
        _conversations[uid] = []
    _conversations[uid].append({"role": "user", "content": user_text})
    messages = _conversations[uid][-14:]   # last 7 exchanges

    for _ in range(5):
        resp = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=800,
            system=_build_system(fname, uid),
            tools=_TOOLS,
            messages=messages,
        )

        if resp.stop_reason == "end_turn":
            text = " ".join(b.text for b in resp.content if hasattr(b, "text")).strip()
            _conversations[uid].append({"role": "assistant", "content": text})
            return text or "❌ לא הצלחתי לעבד."

        if resp.stop_reason == "tool_use":
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    out = await _run_tool(block.name, block.input, uid, fname)
                    log.info("Tool %-22s → %s", block.name, out[:60])
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            messages = list(messages)
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user",      "content": results})
        else:
            break

    return "לא הצלחתי לסיים. נסה שוב."


# ══════════════════════════════════════════════════════════════════════════════
# Shared check-in reply (used by GPS handler and /checkin command)
# ══════════════════════════════════════════════════════════════════════════════

def _checkin_msg(store: dict, km: float | None, notes: list) -> str:
    last_txt  = notes[0]["note"] if notes else "אין הערות קודמות"
    last_date = f" _{notes[0]['date']}_" if notes else ""
    dist      = (f"📏 {km * 1000:.0f}מ'  |  " if km and km < 1
                 else f"📏 {km:.2f} ק\"מ  |  " if km else "")
    return (
        f"✅ צ'ק-אין: *{store['name']}*\n"
        f"🏙️ {store.get('city','')}  |  {dist}📮 {store.get('address','—')}\n\n"
        f"📌 *הערה אחרונה:*{last_date}\n{last_txt}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Telegram handlers
# ══════════════════════════════════════════════════════════════════════════════

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return

    uid     = update.effective_user.id
    fname   = update.effective_user.first_name or "שלום"
    session = _load_session(uid)   # reads Supabase if not cached
    active  = (
        f"📍 חנות פעילה: *{session['store_name']}*  |  {session.get('store_city','')}\n"
        f"⏱️ {session.get('checkin_time','')}"
        if session else "📍 אין חנות פעילה"
    )

    await update.message.reply_text(
        f"👋 שלום *{fname}*!\n\n"
        f"{active}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💬 *כתוב כל שאלה* — AI מבין עברית\n"
        "📍 *שלח מיקום GPS* — צ'ק-אין אוטומטי\n"
        "✏️ */checkin שם חנות* — צ'ק-אין ידני\n"
        "🎤 *שלח הקלטה* — הערה קולית\n"
        "📋 */history שם חנות* — 5 הערות אחרונות\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 הטלגרם ID שלך: `{uid}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"
    query = " ".join(context.args).strip() if context.args else ""

    # /checkin without args → show active store
    if not query:
        session = _load_session(uid)
        if session:
            await update.message.reply_text(
                f"📍 *{session['store_name']}*  |  {session.get('store_city','—')}\n"
                f"📮 {session.get('store_address','—')}\n"
                f"⏱️ {session.get('checkin_time','—')}",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "⚠️ אין חנות פעילה.\n"
                "שלח מיקום GPS, או: `/checkin שם החנות`",
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    # /checkin [name] → fuzzy find + save session
    msg   = await update.message.reply_text(f"🔍 מחפש *{query}*...", parse_mode=ParseMode.MARKDOWN)
    store = await asyncio.to_thread(_fuzzy_find, query)
    if not store:
        await msg.edit_text(f"❌ לא נמצאה חנות תואמת ל: *{query}*", parse_mode=ParseMode.MARKDOWN)
        return

    await asyncio.to_thread(_save_session, uid, store, fname)
    asyncio.create_task(asyncio.to_thread(_log_visit, store, fname, uid))
    notes = await asyncio.to_thread(_get_notes, store["name"], 1)
    await msg.edit_text(_checkin_msg(store, None, notes), parse_mode=ParseMode.MARKDOWN)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    query = " ".join(context.args).strip() if context.args else ""

    if query:
        msg   = await update.message.reply_text(f"🔍 מחפש *{query}*...", parse_mode=ParseMode.MARKDOWN)
        store = await asyncio.to_thread(_fuzzy_find, query)
        if not store:
            await msg.edit_text(f"❌ לא נמצאה חנות: *{query}*", parse_mode=ParseMode.MARKDOWN)
            return
    else:
        session = _load_session(uid)
        if not session:
            await update.message.reply_text("⚠️ אין חנות פעילה. נסה: `/history שם חנות`", parse_mode=ParseMode.MARKDOWN)
            return
        store = {"name": session["store_name"], "city": session.get("store_city",""),
                 "address": session.get("store_address","")}
        msg = await update.message.reply_text("📋 שולף הערות...")

    notes  = await asyncio.to_thread(_get_notes, store["name"], 5)
    header = f"📋 *{store['name']}*  |  {store.get('city','')}\n{'━'*28}"

    if not notes:
        await msg.edit_text(f"{header}\n\n_אין הערות שמורות._", parse_mode=ParseMode.MARKDOWN)
        return

    lines = [header]
    for i, n in enumerate(notes, 1):
        lines.append(f"\n*{i}.* _{n.get('date','?')}_\n{n['note']}")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"
    loc   = update.message.location
    msg   = await update.message.reply_text("🔍 מאתר חנות קרובה...")

    store, km = await asyncio.to_thread(_nearest_store, loc.latitude, loc.longitude)
    if not store:
        await msg.edit_text("❌ לא נמצאו חנויות עם קואורדינטות בבסיס הנתונים.")
        return

    await asyncio.to_thread(_save_session, uid, store, fname)
    asyncio.create_task(asyncio.to_thread(_log_visit, store, fname, uid))
    notes = await asyncio.to_thread(_get_notes, store["name"], 1)
    await msg.edit_text(_checkin_msg(store, km, notes), parse_mode=ParseMode.MARKDOWN)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"
    msg   = await update.message.reply_text("🎙️ מתמלל...")

    if not OPENAI_API_KEY:
        await msg.edit_text("⚠️ OPENAI_API_KEY לא מוגדר — שלח הערה בטקסט.")
        return

    tg_file  = await context.bot.get_file(update.message.voice.file_id)
    tmp_path = Path(tempfile.mktemp(suffix=".ogg"))
    try:
        await tg_file.download_to_drive(str(tmp_path))
        transcript = await _transcribe(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    if not transcript:
        await msg.edit_text("❌ התמלול נכשל. שלח הערה בטקסט.")
        return

    await msg.edit_text(f"🎙️ _{transcript}_\n\n💭 מעבד...", parse_mode=ParseMode.MARKDOWN)

    if ANTHROPIC_API_KEY:
        reply = await _agent(uid, fname, transcript)
        await msg.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
    else:
        # Fallback: save directly to active store
        session = _load_session(uid)
        if session:
            store = {"name": session["store_name"], "city": session.get("store_city",""),
                     "id": session.get("store_id")}
            ok = await asyncio.to_thread(_save_note, store, transcript, fname, uid)
            await msg.edit_text(
                f"💾 נשמר ל: *{session['store_name']}*\n\n📝 _{transcript}_"
                if ok else "❌ שגיאה בשמירה.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await msg.edit_text(
                f"📝 _{transcript}_\n\n⚠️ אין חנות פעילה — שלח מיקום או /checkin שם",
                parse_mode=ParseMode.MARKDOWN,
            )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"
    text  = (update.message.text or "").strip()
    if not text:
        return

    # AI mode
    if ANTHROPIC_API_KEY:
        msg = await update.message.reply_text("💭")
        try:
            reply = await _agent(uid, fname, text)
            await msg.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            log.error("handle_text AI: %s", e)
            await msg.edit_text("❌ שגיאה. נסה שוב.")
        return

    # Fallback: direct note-save (no AI)
    session = _load_session(uid)
    if not session:
        await update.message.reply_text(
            "⚠️ אין חנות פעילה.\n📍 שלח מיקום GPS או `/checkin שם חנות`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    store = {"name": session["store_name"], "city": session.get("store_city",""),
             "id": session.get("store_id")}
    ok = await asyncio.to_thread(_save_note, store, text, fname, uid)
    await update.message.reply_text(
        f"💾 נשמר ל: *{session['store_name']}*" if ok else "❌ שגיאה בשמירה.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("❌ שגיאה פנימית. נסה שוב.")


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN חסר ב-.env / Render env vars")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY חסרים")
    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY חסר — AI מושבת, מצב בסיסי בלבד")
    if not AUTHORIZED_IDS:
        log.warning("AUTHORIZED_USERS לא מוגדר — הבוט פתוח לכולם (dev mode)")
    else:
        log.info("Authorized users: %s", AUTHORIZED_IDS)

    from telegram.request import HTTPXRequest
    # verify=False needed locally (Windows cert issue). On Render this is a no-op.
    _req_opts = {"verify": False}
    api_req    = HTTPXRequest(connection_pool_size=8, httpx_kwargs=_req_opts)
    update_req = HTTPXRequest(connection_pool_size=4, httpx_kwargs=_req_opts,
                              read_timeout=35, write_timeout=35, connect_timeout=35)

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .request(api_req)
        .get_updates_request(update_req)
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("checkin", cmd_checkin))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(MessageHandler(filters.LOCATION,                handle_location))
    app.add_handler(MessageHandler(filters.VOICE,                   handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(handle_error)

    log.info("🤖 Field bot starting (Supabase sessions, Claude AI)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
