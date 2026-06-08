"""
field_bot.py
============
Smart conversational CRM bot for field agents — powered by Claude AI.

All text messages are routed to Claude, which has tools to:
  • search and list stores
  • look up notes and visit history
  • save field notes
  • check in to a store

Commands (still work as shortcuts)
-----------------------------------
  /start              — help + your Telegram ID
  /checkin [name]     — manual GPS-free check-in
  /history [name]     — last 5 notes for a store

Messages
--------
  📍 Location → GPS check-in (nearest store)
  🎤 Voice    → Whisper transcription → AI processes it
  💬 Text     → Claude AI agent (understands Hebrew, uses tools)

Run:
  python field_bot.py
"""

import asyncio
import json
import logging
import math
import os
import ssl
import tempfile
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── SSL bypass (broken certs on this machine) ─────────────────────────────────
ssl._create_default_https_context = ssl._create_unverified_context

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("field_bot")

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "")
SUPABASE_URL      = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY      = os.getenv("SUPABASE_ANON_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ISRAEL_TZ         = timezone(timedelta(hours=3))

# ── Auth ──────────────────────────────────────────────────────────────────────
_raw_auth = os.getenv("AUTHORIZED_USERS", "").strip()
AUTHORIZED_IDS: set[int] = set()
for _p in _raw_auth.split(","):
    try:
        AUTHORIZED_IDS.add(int(_p.strip()))
    except ValueError:
        pass

# ── State ─────────────────────────────────────────────────────────────────────
# user_id → {store, checkin_time, user_name}
_sessions: dict[int, dict] = {}
# user_id → list of {role, content} for Claude conversation history
_conversations: dict[int, list] = {}

# ══════════════════════════════════════════════════════════════════════════════
# Auth guard
# ══════════════════════════════════════════════════════════════════════════════

async def _check_auth(update, context) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if not AUTHORIZED_IDS:
        return True
    if uid in AUTHORIZED_IDS:
        return True
    log.warning("Unauthorized: user_id=%s", uid)
    if update.message:
        await update.message.reply_text("🔒 Access Denied.")
    return False

# ══════════════════════════════════════════════════════════════════════════════
# DB helpers
# ══════════════════════════════════════════════════════════════════════════════

def _db():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def _now_il() -> str:
    return datetime.now(ISRAEL_TZ).strftime("%d/%m/%y %H:%M")

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

def _score_store(query: str, s: dict) -> float:
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
        sc = _score_store(query, s)
        if sc > best_score:
            best, best_score = s, sc
    return best if best_score >= 0.35 else None

def _search_stores_multi(query: str, limit: int = 6) -> list[dict]:
    """Return top N stores matching the query (for AI tool use)."""
    scored = [
        (sc, s)
        for s in _fetch_stores()
        if (sc := _score_store(query, s)) >= 0.3
    ]
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:limit]]

def _list_stores(city: str | None = None, chain: str | None = None,
                 limit: int = 15) -> list[dict]:
    try:
        q = _db().table("stores").select("name,city,address,chain,lat,lon")
        if city:
            q = q.ilike("city", f"%{city}%")
        if chain:
            q = q.ilike("chain", f"%{chain}%")
        res = q.order("city").limit(limit).execute()
        return res.data or []
    except Exception as e:
        log.error("_list_stores: %s", e)
        return []

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

def _save_note(store: dict, text: str, author: str) -> bool:
    """INSERT only — notes are never overwritten."""
    try:
        full = f"[{author}] {text.strip()}" if author else text.strip()
        _db().table("store_notes").insert({
            "date":  _now_il(),
            "store": store["name"],
            "city":  store.get("city", ""),
            "note":  full,
        }).execute()
        log.info("Note → %s (%s)", store["name"], author)
        return True
    except Exception as e:
        log.error("_save_note: %s", e)
        return False

def _log_visit(store: dict, author: str) -> None:
    try:
        _db().table("manual_visits").insert({
            "date":   _now_il(),
            "store":  store["name"],
            "city":   store.get("city", ""),
            "status": "ביקור",
            "notes":  f"צ'ק-אין דרך בוט — {author}",
        }).execute()
    except Exception as e:
        log.warning("_log_visit: %s", e)

# ══════════════════════════════════════════════════════════════════════════════
# Whisper transcription
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

# Tool schemas for Claude
_TOOLS = [
    {
        "name": "search_stores",
        "description": (
            "חיפוש חנויות לפי שם, עיר, רשת או כל מחרוזת. "
            "השתמש כשהמשתמש שואל 'יש חנות ב...', 'כמה סניפים ב...', 'מצא את...'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "מחרוזת חיפוש — עיר, שם חנות, רשת, כתובת"
                },
                "limit": {
                    "type": "integer",
                    "description": "מספר תוצאות מקסימלי (ברירת מחדל: 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_stores_by_city",
        "description": (
            "רשימת כל החנויות בעיר מסוימת ו/או רשת מסוימת. "
            "השתמש כשהמשתמש רוצה לראות את כל הסניפים ב-X."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city":  {"type": "string", "description": "שם עיר (אופציונלי)"},
                "chain": {"type": "string", "description": "שם רשת: שילב / מכבי פארם / ניצת הדובדבן (אופציונלי)"}
            }
        }
    },
    {
        "name": "get_store_notes",
        "description": (
            "שולף הערות שטח אחרונות לחנות. "
            "השתמש כשהמשתמש שואל 'מה קרה ב...', 'מה הסטטוס של...', 'הערות על...'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_name": {"type": "string", "description": "שם החנות המדויק"},
                "limit":      {"type": "integer", "default": 5}
            },
            "required": ["store_name"]
        }
    },
    {
        "name": "save_note",
        "description": (
            "שומר הערת שטח לחנות. "
            "קרא לזה כשהמשתמש מדווח על מידע מהשטח — מלאי, פגישה, מצב חנות, לקוח, בעיה. "
            "אם החנות הפעילה ידועה — השתמש בה אוטומטית."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_name": {"type": "string", "description": "שם החנות"},
                "note_text":  {"type": "string", "description": "תוכן ההערה"}
            },
            "required": ["store_name", "note_text"]
        }
    },
    {
        "name": "checkin_store",
        "description": (
            "מגדיר חנות כ'פעילה' עבור הסוכן ורושם ביקור. "
            "קרא לזה כשהמשתמש אומר 'אני ב...', 'הגעתי ל...', 'צ'ק-אין ל...'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_name": {"type": "string"}
            },
            "required": ["store_name"]
        }
    }
]


def _build_system_prompt(fname: str, uid: int) -> str:
    session = _sessions.get(uid)
    if session:
        s = session["store"]
        active = (
            f"החנות הפעילה כרגע: *{s['name']}* ({s.get('city', '')}), "
            f"צ'ק-אין ב-{session.get('checkin_time', '?')}"
        )
    else:
        active = "אין חנות פעילה כרגע."

    return f"""אתה עוזר CRM חכם לסוכן שטח בשם {fname}.

{active}
שעה נוכחית (ישראל): {_now_il()}

יש לך גישה למאגר מאות חנויות בישראל — שילב, מכבי פארם, ניצת הדובדבן ועוד.

## כיצד לפעול:
- ענה תמיד בעברית, קצר וממוקד
- כשהסוכן מדווח מידע שטח (מלאי, פגישה, מצב, בעיה) — שמור הערה מיד עם save_note ואשר לו
- כשהסוכן אומר "אני ב-X" / "הגעתי ל-X" — בצע checkin_store
- כשנשאלת על חנות ספציפית — חפש עם search_stores לפני שאתה עונה
- לאחר save_note: ענה "💾 הערה נשמרה ל: [שם החנות]"
- לאחר checkin_store: ענה "✅ צ'ק-אין: [שם] | [עיר]" ואחזר הערה אחרונה
- אם אין מספיק מידע — שאל שאלה קצרה אחת
"""


async def _execute_tool(name: str, inputs: dict, uid: int, fname: str) -> str:
    """Execute a single tool call and return a string result."""
    try:
        # ── search_stores ──────────────────────────────────────────────────────
        if name == "search_stores":
            stores = await asyncio.to_thread(
                _search_stores_multi, inputs["query"], inputs.get("limit", 5)
            )
            if not stores:
                return "לא נמצאו חנויות תואמות."
            lines = [
                f"• {s['name']} | {s.get('city','')} | {s.get('address','—')}"
                for s in stores
            ]
            return f"{len(stores)} חנויות נמצאו:\n" + "\n".join(lines)

        # ── list_stores_by_city ────────────────────────────────────────────────
        elif name == "list_stores_by_city":
            stores = await asyncio.to_thread(
                _list_stores, inputs.get("city"), inputs.get("chain")
            )
            if not stores:
                return "לא נמצאו חנויות."
            lines = [
                f"• {s['name']} | {s.get('city','')} | {s.get('address','—')}"
                for s in stores
            ]
            return f"{len(stores)} חנויות:\n" + "\n".join(lines)

        # ── get_store_notes ────────────────────────────────────────────────────
        elif name == "get_store_notes":
            notes = await asyncio.to_thread(
                _get_notes, inputs["store_name"], inputs.get("limit", 5)
            )
            if not notes:
                return f"אין הערות שמורות לחנות {inputs['store_name']}."
            lines = [f"[{n.get('date','?')}] {n['note']}" for n in notes]
            return "\n".join(lines)

        # ── save_note ──────────────────────────────────────────────────────────
        elif name == "save_note":
            store = await asyncio.to_thread(_fuzzy_find, inputs["store_name"])
            if not store:
                return f"לא נמצאה חנות: {inputs['store_name']}"
            ok = await asyncio.to_thread(_save_note, store, inputs["note_text"], fname)
            return (
                f"הערה נשמרה בהצלחה ל-{store['name']}."
                if ok else "שגיאה בשמירת ההערה."
            )

        # ── checkin_store ──────────────────────────────────────────────────────
        elif name == "checkin_store":
            store = await asyncio.to_thread(_fuzzy_find, inputs["store_name"])
            if not store:
                return f"לא נמצאה חנות: {inputs['store_name']}"
            _sessions[uid] = {
                "store": store,
                "checkin_time": _now_il(),
                "user_name": fname,
            }
            asyncio.create_task(asyncio.to_thread(_log_visit, store, fname))
            # Fetch last note to include in response
            notes = await asyncio.to_thread(_get_notes, store["name"], 1)
            last  = notes[0]["note"] if notes else "אין הערות קודמות"
            return (
                f"צ'ק-אין בוצע: {store['name']} | {store.get('city','')} "
                f"| {store.get('address','—')}\n"
                f"הערה אחרונה: {last}"
            )

    except Exception as e:
        log.error("Tool %s error: %s", name, e)
        return f"שגיאה: {e}"

    return "פעולה לא מוכרת."


async def _run_agent(uid: int, fname: str, user_text: str) -> str:
    """
    Run the Claude agentic loop for one user turn.
    Maintains conversation history per user (last 12 messages).
    Returns the final text reply to send to Telegram.
    """
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    # Maintain conversation history
    if uid not in _conversations:
        _conversations[uid] = []
    _conversations[uid].append({"role": "user", "content": user_text})

    # Keep last 12 messages (6 exchanges) to control token cost
    messages = _conversations[uid][-12:]
    system   = _build_system_prompt(fname, uid)

    # Agentic loop — max 5 rounds of tool use
    for _round in range(5):
        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=800,
            system=system,
            tools=_TOOLS,
            messages=messages,
        )

        # ── Final text response ────────────────────────────────────────────────
        if response.stop_reason == "end_turn":
            text = " ".join(
                block.text for block in response.content
                if hasattr(block, "text")
            ).strip()
            _conversations[uid].append({"role": "assistant", "content": text})
            return text or "לא הצלחתי לעבד את הבקשה."

        # ── Tool use ───────────────────────────────────────────────────────────
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = await _execute_tool(block.name, block.input, uid, fname)
                    log.info("Tool %s → %s", block.name, result[:80])
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })
            # Append assistant tool-use turn and results
            messages = list(messages)  # copy
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",      "content": tool_results})
        else:
            break

    return "לא הצלחתי לסיים את הפעולה. נסה שוב."


# ══════════════════════════════════════════════════════════════════════════════
# Shared check-in reply builder
# ══════════════════════════════════════════════════════════════════════════════

def _checkin_reply(store: dict, km: float | None, notes: list) -> str:
    last_txt  = notes[0]["note"] if notes else "אין הערות קודמות"
    last_date = f" _{notes[0]['date']}_" if notes else ""
    dist_line = ""
    if km is not None:
        dist_str  = f"{km * 1000:.0f}מ'" if km < 1 else f"{km:.2f} ק\"מ"
        dist_line = f"📏 {dist_str}  |  "
    return (
        f"✅ צ'ק-אין: *{store['name']}*\n"
        f"🏙️ {store.get('city', '')}  |  {dist_line}📮 {store.get('address', '—')}\n\n"
        f"📌 *הערה אחרונה:*{last_date}\n{last_txt}\n\n"
        f"_שלח טקסט, מיקום, או הקלטה קולית כדי לרשום הערה._"
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

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "שלום"
    session = _sessions.get(uid)
    active  = (
        f"📍 חנות פעילה: *{session['store']['name']}*"
        if session else "📍 אין חנות פעילה"
    )

    await update.message.reply_text(
        f"👋 שלום *{fname}*!\n\n"
        f"{active}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💬 *כתוב כל שאלה* — אני מבין עברית\n"
        "📍 *שלח מיקום GPS* — צ'ק-אין אוטומטי\n"
        "✏️ */checkin שם חנות* — צ'ק-אין ידני\n"
        "🎤 *שלח הקלטה קולית* — הערה קולית\n"
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

    if not query:
        session = _sessions.get(uid)
        if session:
            s = session["store"]
            await update.message.reply_text(
                f"📍 חנות פעילה: *{s['name']}*\n"
                f"🏙️ {s.get('city', '—')}  |  📮 {s.get('address', '—')}\n"
                f"⏱️ {session.get('checkin_time', '—')}",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "⚠️ אין חנות פעילה.\n"
                "שלח מיקום GPS או: /checkin שם החנות"
            )
        return

    msg   = await update.message.reply_text(f"🔍 מחפש: *{query}*...", parse_mode=ParseMode.MARKDOWN)
    store = await asyncio.to_thread(_fuzzy_find, query)

    if not store:
        await msg.edit_text(
            f"❌ לא נמצאה חנות תואמת ל: *{query}*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    _sessions[uid] = {"store": store, "checkin_time": _now_il(), "user_name": fname}
    asyncio.create_task(asyncio.to_thread(_log_visit, store, fname))
    notes = await asyncio.to_thread(_get_notes, store["name"], 1)
    await msg.edit_text(_checkin_reply(store, None, notes), parse_mode=ParseMode.MARKDOWN)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    query = " ".join(context.args).strip() if context.args else ""

    if query:
        msg   = await update.message.reply_text(f"🔍 מחפש: *{query}*...", parse_mode=ParseMode.MARKDOWN)
        store = await asyncio.to_thread(_fuzzy_find, query)
        if not store:
            await msg.edit_text(f"❌ לא נמצאה חנות תואמת ל: *{query}*", parse_mode=ParseMode.MARKDOWN)
            return
    else:
        session = _sessions.get(uid)
        if not session:
            await update.message.reply_text(
                "⚠️ אין חנות פעילה. שלח /history שם חנות"
            )
            return
        store = session["store"]
        msg   = await update.message.reply_text("📋 שולף הערות...")

    notes  = await asyncio.to_thread(_get_notes, store["name"], 5)
    header = (
        f"📋 *{store['name']}*\n"
        f"🏙️ {store.get('city', '')}  |  📮 {store.get('address', '—')}\n"
        f"{'━' * 28}"
    )

    if not notes:
        await msg.edit_text(f"{header}\n\n_אין הערות שמורות._", parse_mode=ParseMode.MARKDOWN)
        return

    lines = [header]
    for i, n in enumerate(notes, 1):
        lines.append(f"\n*{i}.* _{n.get('date', '?')}_\n{n['note']}")
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
        await msg.edit_text("❌ לא נמצאו חנויות בבסיס הנתונים.")
        return

    _sessions[uid] = {"store": store, "checkin_time": _now_il(), "user_name": fname}
    asyncio.create_task(asyncio.to_thread(_log_visit, store, fname))
    notes = await asyncio.to_thread(_get_notes, store["name"], 1)
    await msg.edit_text(_checkin_reply(store, km, notes), parse_mode=ParseMode.MARKDOWN)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"
    msg   = await update.message.reply_text("🎙️ מתמלל הקלטה...")

    if not OPENAI_API_KEY:
        await msg.edit_text(
            "⚠️ תמלול קולי לא זמין — OPENAI_API_KEY לא מוגדר.\n"
            "שלח את ההערה בטקסט."
        )
        return

    tg_file  = await context.bot.get_file(update.message.voice.file_id)
    tmp_path = Path(tempfile.mktemp(suffix=".ogg"))
    try:
        await tg_file.download_to_drive(str(tmp_path))
        transcript = await _transcribe(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    if not transcript:
        await msg.edit_text("❌ התמלול נכשל. שלח את ההערה בטקסט.")
        return

    await msg.edit_text(f"🎙️ תמלול: _{transcript}_\n\n💭 מעבד...", parse_mode=ParseMode.MARKDOWN)

    # Route transcription through AI (same as text)
    if ANTHROPIC_API_KEY:
        reply = await _run_agent(uid, fname, transcript)
        await msg.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
    else:
        # Fallback: save directly if active store
        session = _sessions.get(uid)
        if session:
            ok = await asyncio.to_thread(_save_note, session["store"], transcript, fname)
            store_name = session["store"]["name"]
            await msg.edit_text(
                (f"💾 הערה נשמרה ל: *{store_name}*\n\n📝 _{transcript}_"
                 if ok else "❌ שגיאה בשמירה."),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await msg.edit_text(
                f"📝 תמלול: _{transcript}_\n\n"
                "⚠️ אין חנות פעילה. שלח מיקום או /checkin שם חנות.",
                parse_mode=ParseMode.MARKDOWN,
            )


async def handle_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route all text messages through Claude AI agent."""
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"
    text  = (update.message.text or "").strip()
    if not text:
        return

    if not ANTHROPIC_API_KEY:
        # Fallback: simple note-saving without AI
        session = _sessions.get(uid)
        if session:
            ok = await asyncio.to_thread(_save_note, session["store"], text, fname)
            await update.message.reply_text(
                f"💾 הערה נשמרה ל: *{session['store']['name']}*"
                if ok else "❌ שגיאה בשמירה.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "⚠️ אין חנות פעילה ו-ANTHROPIC_API_KEY לא מוגדר.\n"
                "שלח מיקום GPS או /checkin שם חנות."
            )
        return

    msg = await update.message.reply_text("💭")
    try:
        reply = await _run_agent(uid, fname, text)
        # Telegram message limit is 4096 chars
        if len(reply) > 4000:
            reply = reply[:3997] + "..."
        await msg.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        log.error("AI chat error: %s", e)
        await msg.edit_text("❌ שגיאה. נסה שוב.")


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Error: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("❌ שגיאה פנימית. נסה שוב.")

# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN לא מוגדר ב-.env")
    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — AI chat disabled, basic mode only")
    if not AUTHORIZED_IDS:
        log.warning("AUTHORIZED_USERS not set — bot open to everyone (dev mode)")
    else:
        log.info("Authorized users: %s", AUTHORIZED_IDS)

    from telegram.request import HTTPXRequest
    _no_ssl    = {"verify": False}
    api_req    = HTTPXRequest(connection_pool_size=8, httpx_kwargs=_no_ssl)
    update_req = HTTPXRequest(connection_pool_size=4, httpx_kwargs=_no_ssl,
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_chat))
    app.add_error_handler(handle_error)

    log.info("🤖 Field bot (AI mode) starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
