"""
field_bot.py
============
Smart Telegram CRM bot for field agents.

Commands
--------
  /start              — help menu + your Telegram ID (for auth setup)
  /checkin [name]     — manual check-in by store name (fuzzy-match)
                        without args → show current active store
  /history [name]     — last 5 notes for any store
                        without args → history for current active store

Messages
--------
  📍 Location         → GPS check-in to nearest store + last note
  💬 Text             → save note to active store (with author)
  🎤 Voice            → Whisper transcription → save note with author

Auth
----
  Add to .env:
    AUTHORIZED_USERS=123456789,987654321
  Get your ID by sending /start — the bot tells you.
  If AUTHORIZED_USERS is empty, the bot warns and allows everyone (dev mode).

Run:
  python field_bot.py
"""

import asyncio
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

# ── SSL bypass (certificate issue on this machine) ────────────────────────────
ssl._create_default_https_context = ssl._create_unverified_context

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("field_bot")

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY   = os.getenv("SUPABASE_ANON_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ISRAEL_TZ      = timezone(timedelta(hours=3))

# ── Auth — parse AUTHORIZED_USERS=123,456 from .env ──────────────────────────
_raw_auth = os.getenv("AUTHORIZED_USERS", "").strip()
AUTHORIZED_IDS: set[int] = set()
if _raw_auth:
    for _part in _raw_auth.split(","):
        try:
            AUTHORIZED_IDS.add(int(_part.strip()))
        except ValueError:
            pass

# ── Sessions: user_id → {store, checkin_time, user_name} ─────────────────────
_sessions: dict[int, dict] = {}

# ══════════════════════════════════════════════════════════════════════════════
# Auth guard
# ══════════════════════════════════════════════════════════════════════════════

async def _check_auth(update, context) -> bool:
    """
    Returns True if the sender is authorized.
    If not authorized, replies 'Access Denied' and returns False.
    If AUTHORIZED_IDS is empty (dev mode), logs a warning and allows everyone.
    """
    uid = update.effective_user.id if update.effective_user else None

    if not AUTHORIZED_IDS:
        log.warning("AUTHORIZED_USERS not set — running in open access mode")
        return True

    if uid in AUTHORIZED_IDS:
        return True

    log.warning("Unauthorized access attempt from user_id=%s", uid)
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

def _fuzzy_find(query: str) -> dict | None:
    """
    Fuzzy-match query against store names + cities.
    Handles partial queries like 'רעננה', 'שילב ת"א', 'מכבי חיפה'.
    """
    q = query.strip().lower()
    best, best_score = None, 0.0

    for s in _fetch_stores():
        name = s.get("name", "").lower()
        city = s.get("city", "").lower()

        # Substring fast-path: 'רעננה' inside 'שילב רעננה'
        if q in name or q in city:
            score = 0.7 + SequenceMatcher(None, q, name).ratio() * 0.3
        else:
            # Compare against full name, city-only, and name-tail (drop chain prefix)
            tail  = " ".join(name.split()[2:]) if len(name.split()) > 2 else name
            score = max(
                SequenceMatcher(None, q, name).ratio(),
                SequenceMatcher(None, q, tail).ratio(),
                SequenceMatcher(None, q, city).ratio(),
            )

        if score > best_score:
            best, best_score = s, score

    return best if best_score >= 0.35 else None

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
    """
    INSERT only — notes are never overwritten.
    Author is embedded in the note text as '[Name] note'.
    """
    try:
        full_text = f"[{author}] {text.strip()}" if author else text.strip()
        _db().table("store_notes").insert({
            "date":  _now_il(),
            "store": store["name"],
            "city":  store.get("city", ""),
            "note":  full_text,
        }).execute()
        log.info("Note saved → %s (%s)", store["name"], author)
        return True
    except Exception as e:
        log.error("_save_note(%s): %s", store["name"], e)
        return False

def _log_visit(store: dict, author: str) -> None:
    try:
        _db().table("manual_visits").insert({
            "date":   _now_il(),
            "store":  store["name"],
            "city":   store.get("city", ""),
            "status": "ביקור",
            "notes":  f"צ'ק-אין דרך בוט טלגרם — {author}",
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
                model="whisper-1",
                file=fh,
                language="he",
            )
        return (result.text or "").strip() or None
    except Exception as e:
        log.error("Whisper: %s", e)
        return None

# ══════════════════════════════════════════════════════════════════════════════
# Shared check-in reply builder
# ══════════════════════════════════════════════════════════════════════════════

def _checkin_reply(store: dict, km: float | None, notes: list[dict]) -> str:
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
    store = _sessions.get(uid)
    active_line = (
        f"📍 חנות פעילה: *{store['store']['name']}*"
        if store else "📍 אין חנות פעילה כרגע"
    )

    await update.message.reply_text(
        f"👋 שלום *{fname}*!\n\n"
        f"{active_line}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📍 *שלח מיקום GPS* — צ'ק-אין אוטומטי\n"
        "✏️ */checkin שם חנות* — צ'ק-אין ידני\n"
        "💬 *שלח טקסט* — רשום הערה לחנות הפעילה\n"
        "🎤 *שלח הקלטה קולית* — הערה קולית\n"
        "📋 */history שם חנות* — 5 הערות אחרונות\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 הטלגרם ID שלך: `{uid}`\n"
        "_שמור את ה-ID הזה כדי להוסיף אותך לרשימת הגישה_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /checkin שילב רעננה  → fuzzy-match + set active store
    /checkin              → show current active store
    """
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"
    query = " ".join(context.args).strip() if context.args else ""

    # ── No args → show active store ──────────────────────────────────────────
    if not query:
        session = _sessions.get(uid)
        if session:
            s = session["store"]
            await update.message.reply_text(
                f"📍 חנות פעילה: *{s['name']}*\n"
                f"🏙️ {s.get('city', '—')}  |  📮 {s.get('address', '—')}\n"
                f"⏱️ צ'ק-אין: {session.get('checkin_time', '—')}",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "⚠️ אין חנות פעילה.\n"
                "שלח מיקום GPS, או: /checkin שם החנות"
            )
        return

    # ── With args → fuzzy-match + set active ─────────────────────────────────
    msg = await update.message.reply_text(f"🔍 מחפש: *{query}*...", parse_mode=ParseMode.MARKDOWN)
    store = await asyncio.to_thread(_fuzzy_find, query)

    if not store:
        await msg.edit_text(
            f"❌ לא נמצאה חנות תואמת ל: *{query}*\n"
            "נסה שם מלא יותר, לדוגמה: שילב רעננה",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    now = _now_il()
    _sessions[uid] = {"store": store, "checkin_time": now, "user_name": fname}
    asyncio.create_task(asyncio.to_thread(_log_visit, store, fname))

    notes = await asyncio.to_thread(_get_notes, store["name"], 1)
    await msg.edit_text(_checkin_reply(store, None, notes), parse_mode=ParseMode.MARKDOWN)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /history שילב רעננה  → last 5 notes for named store
    /history              → last 5 notes for current active store
    """
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    query = " ".join(context.args).strip() if context.args else ""

    # Determine target store
    if query:
        msg = await update.message.reply_text(f"🔍 מחפש: *{query}*...", parse_mode=ParseMode.MARKDOWN)
        store = await asyncio.to_thread(_fuzzy_find, query)
        if not store:
            await msg.edit_text(
                f"❌ לא נמצאה חנות תואמת ל: *{query}*",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
    else:
        session = _sessions.get(uid)
        if not session:
            await update.message.reply_text(
                "⚠️ אין חנות פעילה.\n"
                "שלח /history שם חנות, או בצע צ'ק-אין תחילה."
            )
            return
        store = session["store"]
        msg = await update.message.reply_text("📋 שולף הערות...")

    notes = await asyncio.to_thread(_get_notes, store["name"], 5)
    header = (
        f"📋 *{store['name']}*\n"
        f"🏙️ {store.get('city', '')}  |  📮 {store.get('address', '—')}\n"
        f"{'━' * 28}"
    )

    if not notes:
        await msg.edit_text(
            f"{header}\n\n_אין הערות שמורות לחנות זו._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = [header]
    for i, n in enumerate(notes, 1):
        lines.append(f"\n*{i}.* _{n.get('date', '?')}_\n{n['note']}")

    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """GPS check-in → nearest store → save visit → show last note."""
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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save text message as a note to the active store."""
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"
    text  = (update.message.text or "").strip()
    if not text:
        return

    session = _sessions.get(uid)
    if not session:
        await update.message.reply_text(
            "🤷 לא יודע באיזו חנות אתה נמצא.\n\n"
            "📍 שלח *מיקום GPS* או השתמש ב: /checkin שם חנות",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    store = session["store"]
    ok    = await asyncio.to_thread(_save_note, store, text, fname)

    if ok:
        await update.message.reply_text(
            f"💾 הערה נשמרה ל: *{store['name']}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("❌ שגיאה בשמירה — נסה שוב.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe voice note via Whisper and save to active store."""
    if not await _check_auth(update, context):
        return

    uid   = update.effective_user.id
    fname = update.effective_user.first_name or "Agent"

    session = _sessions.get(uid)
    if not session:
        await update.message.reply_text(
            "🤷 לא יודע באיזו חנות אתה נמצא.\n\n"
            "📍 שלח *מיקום GPS* או השתמש ב: /checkin שם חנות",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not OPENAI_API_KEY:
        await update.message.reply_text(
            "⚠️ תמלול קולי לא זמין — OPENAI_API_KEY לא מוגדר.\n"
            "שלח את ההערה בטקסט."
        )
        return

    msg   = await update.message.reply_text("🎙️ מתמלל הקלטה...")
    store = session["store"]

    # Download OGG to temp file
    tg_file  = await context.bot.get_file(update.message.voice.file_id)
    tmp_path = Path(tempfile.mktemp(suffix=".ogg"))
    try:
        await tg_file.download_to_drive(str(tmp_path))
        transcript = await _transcribe(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    if not transcript:
        await msg.edit_text(
            "❌ התמלול נכשל. שלח את ההערה בטקסט."
        )
        return

    ok = await asyncio.to_thread(_save_note, store, transcript, fname)
    if ok:
        await msg.edit_text(
            f"💾 הערה נשמרה ל: *{store['name']}*\n\n"
            f"📝 *תמלול:*\n_{transcript}_",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await msg.edit_text(
            f"⚠️ תמלול הצליח אך השמירה נכשלה:\n_{transcript}_",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled error: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("❌ שגיאה פנימית. נסה שוב.")

# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN לא מוגדר ב-.env")

    if not AUTHORIZED_IDS:
        log.warning("=" * 60)
        log.warning("AUTHORIZED_USERS not set — bot is open to everyone!")
        log.warning("Add AUTHORIZED_USERS=your_telegram_id to .env")
        log.warning("Send /start to the bot to get your Telegram ID")
        log.warning("=" * 60)
    else:
        log.info("Authorized users: %s", AUTHORIZED_IDS)

    # PTB v20+ needs SSL bypass on both request pools
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(handle_error)

    log.info("🤖 Field bot starting — polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
