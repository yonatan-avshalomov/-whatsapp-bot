"""
field_bot.py
============
Telegram CRM bot for field agents — proactive check-in, voice notes, status queries.

Workflow
--------
  📍 Location  → find nearest store → proactive recall (last note)
  🎤 Voice     → Whisper transcription → save note to active store
  💬 Text      → save note to active store
  /status name → fuzzy-match store → last 3 notes
  /checkin     → show current active store
  /start       → onboarding instructions

Requirements (add to requirements.txt):
  python-telegram-bot>=20.7
  openai>=1.14

.env keys needed:
  TELEGRAM_TOKEN       (already present)
  SUPABASE_URL         (already present)
  SUPABASE_ANON_KEY    (already present)
  OPENAI_API_KEY       (add this — needed for voice transcription)

Run:
  python field_bot.py
"""

import asyncio
import logging
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("field_bot")

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
SUPABASE_URL    = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY    = os.getenv("SUPABASE_ANON_KEY", "")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
ISRAEL_TZ       = timezone(timedelta(hours=3))

# ── In-memory session: telegram user_id → active store dict ──────────────────
# Populated on location check-in.  Resets on bot restart (intentional —
# agents should check in again; for persistence see _checkin_to_db below).
_sessions: dict[int, dict] = {}

# ══════════════════════════════════════════════════════════════════════════════
# Supabase helpers  (sync, wrapped in asyncio.to_thread for async handlers)
# ══════════════════════════════════════════════════════════════════════════════

def _make_db():
    """Create a fresh Supabase client (thread-safe: one per call)."""
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _now_il() -> str:
    """Israeli time as 'DD/MM/YY HH:MM'."""
    return datetime.now(ISRAEL_TZ).strftime("%d/%m/%y %H:%M")


# ── Stores ────────────────────────────────────────────────────────────────────

def _fetch_stores() -> list[dict]:
    """All stores that have valid coordinates."""
    try:
        db  = _make_db()
        res = (db.table("stores")
               .select("id,chain,name,city,address,lat,lon")
               .not_.is_("lat", "null")
               .not_.is_("lon", "null")
               .execute())
        return [
            s for s in (res.data or [])
            if s.get("lat") and s.get("lon")
        ]
    except Exception as exc:
        log.error("_fetch_stores: %s", exc)
        return []


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


def _nearest_store(user_lat: float, user_lon: float) -> tuple[dict | None, float]:
    """Return (closest_store, distance_km)."""
    stores   = _fetch_stores()
    best     = None
    best_km  = float("inf")
    for s in stores:
        try:
            d = _haversine(user_lat, user_lon, float(s["lat"]), float(s["lon"]))
        except (TypeError, ValueError):
            continue
        if d < best_km:
            best, best_km = s, d
    return best, best_km


def _fuzzy_find_store(query: str) -> dict | None:
    """
    Fuzzy-match query against store names.
    Returns best match or None if similarity < 0.35.
    Handles both full-name queries ("שילב רעננה") and partial city
    queries ("רעננה").
    """
    stores = _fetch_stores()
    q = query.strip().lower()
    best, best_score = None, 0.0

    def sim(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    for s in stores:
        name = s.get("name", "").lower()
        city = s.get("city", "").lower()

        # Substring fast-path
        if q in name or q in city:
            score = 0.65 + sim(q, name) * 0.35
        else:
            # Full-name similarity
            score = sim(q, name)
            # Also try city-only part of the name (last word(s))
            tail = " ".join(name.split()[2:]) if len(name.split()) > 2 else name
            score = max(score, sim(q, tail), sim(q, city))

        if score > best_score:
            best, best_score = s, score

    return best if best_score >= 0.35 else None


# ── Notes ─────────────────────────────────────────────────────────────────────

def _get_last_notes(store_name: str, limit: int = 3) -> list[dict]:
    """
    Fetch last N notes for a store, newest first.
    Returns list of dicts with keys: note, date, city.
    """
    try:
        db  = _make_db()
        res = (db.table("store_notes")
               .select("note,date,city,created_at")
               .eq("store", store_name)
               .order("created_at", desc=True)
               .limit(limit)
               .execute())
        return res.data or []
    except Exception as exc:
        log.error("_get_last_notes(%s): %s", store_name, exc)
        return []


def _append_note(store: dict, note_text: str) -> bool:
    """
    Permanently append a note to store_notes.
    Uses INSERT — never UPDATE — so history is always preserved.
    """
    try:
        db = _make_db()
        db.table("store_notes").insert({
            "date":  _now_il(),
            "store": store["name"],
            "city":  store.get("city", ""),
            "note":  note_text.strip(),
        }).execute()
        log.info("Note saved → %s", store["name"])
        return True
    except Exception as exc:
        log.error("_append_note(%s): %s", store["name"], exc)
        return False


# ── Visits ────────────────────────────────────────────────────────────────────

def _record_visit(store: dict) -> None:
    """Log a check-in event to manual_visits (best-effort, non-blocking)."""
    try:
        db = _make_db()
        db.table("manual_visits").insert({
            "date":   _now_il(),
            "store":  store["name"],
            "city":   store.get("city", ""),
            "status": "ביקור",
            "notes":  "צ'ק-אין דרך בוט טלגרם",
        }).execute()
    except Exception as exc:
        log.warning("_record_visit(%s): %s", store["name"], exc)


# ══════════════════════════════════════════════════════════════════════════════
# Whisper transcription
# ══════════════════════════════════════════════════════════════════════════════

async def _transcribe(file_path: str) -> str | None:
    """
    Transcribe a .ogg voice file with OpenAI Whisper.
    Returns transcribed text or None on failure.
    Language hint set to Hebrew for better accuracy.
    """
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
        text = (result.text or "").strip()
        log.info("Whisper transcribed %d chars", len(text))
        return text or None
    except Exception as exc:
        log.error("Whisper error: %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Telegram handlers
# ══════════════════════════════════════════════════════════════════════════════

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Onboarding message."""
    await update.message.reply_text(
        "👋 *ברוך הבא לבוט השטח!*\n\n"
        "📍 שלח *מיקום* — צ'ק-אין לחנות הקרובה\n"
        "🎤 שלח *הודעה קולית* — רשום הערה קולית\n"
        "💬 שלח *טקסט* — רשום הערה כתובה\n"
        "/status \\[שם חנות\\] — 3 הערות אחרונות\n"
        "/checkin — הצג את החנות הפעילה כעת\n\n"
        "_לדוגמה: /status שילב רעננה_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current active store."""
    uid   = update.effective_user.id
    store = _sessions.get(uid)
    if store:
        await update.message.reply_text(
            f"📍 חנות פעילה: *{store['name']}*\n"
            f"🏙️ עיר: {store.get('city', '—')}\n"
            f"📮 כתובת: {store.get('address', '—')}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "⚠️ אין חנות פעילה.\n"
            "שלח מיקום GPS כדי לבצע צ'ק-אין."
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status [store name] — fuzzy-match + last 3 notes."""
    query = " ".join(context.args).strip() if context.args else ""

    if not query:
        await update.message.reply_text(
            "📋 שימוש: /status \\[שם חנות\\]\n"
            "לדוגמה: /status שילב רעננה",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await update.message.reply_text("🔍 מחפש...")

    store = await asyncio.to_thread(_fuzzy_find_store, query)
    if not store:
        await update.message.reply_text(
            f"❌ לא נמצאה חנות תואמת ל: *{query}*\n"
            "נסה שם מלא יותר, לדוגמה: שילב רעננה",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    notes = await asyncio.to_thread(_get_last_notes, store["name"], 3)
    header = (
        f"📋 *{store['name']}*  |  {store.get('city', '')}\n"
        f"📮 {store.get('address', '—')}\n"
        f"{'─' * 28}"
    )

    if not notes:
        await update.message.reply_text(
            f"{header}\n\n_אין הערות שמורות לחנות זו._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = [header]
    for i, n in enumerate(notes, 1):
        date_str = n.get("date", "?")
        note_txt = n.get("note", "").strip()
        lines.append(f"\n*{i}.* _{date_str}_\n{note_txt}")

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Check in to nearest store and do proactive recall of the last note.
    Also logs a visit to manual_visits.
    """
    uid  = update.effective_user.id
    loc  = update.message.location
    ulat, ulon = loc.latitude, loc.longitude

    msg = await update.message.reply_text("🔍 מאתר חנות קרובה...")

    store, dist_km = await asyncio.to_thread(_nearest_store, ulat, ulon)

    if not store:
        await msg.edit_text("❌ לא נמצאו חנויות עם קואורדינטות בבסיס הנתונים.")
        return

    # Register active store for this agent
    _sessions[uid] = store

    # Non-blocking visit logging
    asyncio.create_task(asyncio.to_thread(_record_visit, store))

    # Proactive recall
    notes    = await asyncio.to_thread(_get_last_notes, store["name"], 1)
    has_note = bool(notes)
    last_txt  = notes[0]["note"]  if has_note else "אין הערות קודמות"
    last_date = notes[0]["date"]  if has_note else ""

    dist_str = (
        f"{dist_km * 1000:.0f}מ'"
        if dist_km < 1
        else f"{dist_km:.2f} ק\"מ"
    )

    reply = (
        f"✅ צ'ק-אין: *{store['name']}*\n"
        f"🏙️ {store.get('city', '')}  |  📏 {dist_str}\n"
        f"📮 {store.get('address', '—')}\n\n"
        f"📌 *הערה אחרונה:*"
        + (f" _{last_date}_" if last_date else "")
        + f"\n{last_txt}\n\n"
        f"_שלח טקסט או הקלטה קולית להוסיף הערה לחנות זו._"
    )
    await msg.edit_text(reply, parse_mode=ParseMode.MARKDOWN)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save a text message as a note for the active store."""
    uid   = update.effective_user.id
    text  = (update.message.text or "").strip()

    if not text:
        return

    store = _sessions.get(uid)
    if not store:
        await update.message.reply_text(
            "⚠️ לא נבחרה חנות פעילה.\n"
            "📍 שלח מיקום GPS כדי לבצע צ'ק-אין תחילה."
        )
        return

    ok = await asyncio.to_thread(_append_note, store, text)
    if ok:
        await update.message.reply_text(
            f"💾 הערה נשמרה ל: *{store['name']}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("❌ שגיאה בשמירת ההערה — נסה שוב.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Transcribe a Telegram voice note (OGG/OPUS) via Whisper and
    save it as a note for the active store.
    """
    uid   = update.effective_user.id
    store = _sessions.get(uid)

    if not store:
        await update.message.reply_text(
            "⚠️ לא נבחרה חנות פעילה.\n"
            "📍 שלח מיקום GPS כדי לבצע צ'ק-אין תחילה."
        )
        return

    if not OPENAI_API_KEY:
        await update.message.reply_text(
            "⚠️ מפתח OPENAI_API_KEY לא מוגדר בשרת.\n"
            "נא לפנות למנהל המערכת."
        )
        return

    msg = await update.message.reply_text("🎙️ מתמלל הקלטה...")

    # Download voice file to temp .ogg
    voice    = update.message.voice
    tg_file  = await context.bot.get_file(voice.file_id)

    tmp_path = Path(tempfile.mktemp(suffix=".ogg"))
    try:
        await tg_file.download_to_drive(str(tmp_path))
        transcript = await _transcribe(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    if not transcript:
        await msg.edit_text(
            "❌ התמלול נכשל.\n"
            "נסה שוב, או שלח את ההערה בטקסט."
        )
        return

    ok = await asyncio.to_thread(_append_note, store, transcript)

    if ok:
        await msg.edit_text(
            f"💾 הערה נשמרה ל: *{store['name']}*\n\n"
            f"📝 *תמלול:*\n_{transcript}_",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await msg.edit_text(
            f"⚠️ תמלול הצליח אך השמירה נכשלה:\n\n_{transcript}_",
            parse_mode=ParseMode.MARKDOWN,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Error handler
# ══════════════════════════════════════════════════════════════════════════════

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "❌ אירעה שגיאה פנימית. נסה שוב או פנה למנהל המערכת."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN לא מוגדר — הוסף אותו ל-.env"
        )
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_ANON_KEY לא מוגדרים — בדוק את ה-.env"
        )
    if not OPENAI_API_KEY:
        log.warning(
            "OPENAI_API_KEY לא מוגדר — תמלול קוליות לא יעבוד. "
            "הוסף OPENAI_API_KEY=sk-... ל-.env"
        )

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("checkin", cmd_checkin))
    app.add_handler(CommandHandler("status",  cmd_status))

    # Message types — order matters: most specific first
    app.add_handler(MessageHandler(filters.LOCATION,                handle_location))
    app.add_handler(MessageHandler(filters.VOICE,                   handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Global error handler
    app.add_error_handler(handle_error)

    log.info("🤖 Field bot starting — long-polling...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # skip backlog from offline period
    )


if __name__ == "__main__":
    main()
