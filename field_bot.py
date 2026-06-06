"""
field_bot.py
============
Telegram CRM bot for field agents.

Workflow
--------
  📍 Location  → nearest store → proactive recall (last note)
  💬 Text      → save note to active store
  /status name → fuzzy-match store → last 3 notes
  /checkin     → show current active store
  /start       → instructions

Run:
  python field_bot.py
"""

import asyncio
import logging
import math
import os
import ssl
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from dotenv import load_dotenv

load_dotenv()

# SSL certificates are broken on this machine — disable verification globally
# (same workaround used throughout the project for Google Maps / Supabase)
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
ISRAEL_TZ      = timezone(timedelta(hours=3))

# In-memory session: user_id → active store dict
_sessions: dict[int, dict] = {}

# ══════════════════════════════════════════════════════════════════════════════
# Supabase helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_db():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def _now_il() -> str:
    return datetime.now(ISRAEL_TZ).strftime("%d/%m/%y %H:%M")

def _fetch_stores() -> list[dict]:
    try:
        res = (
            _make_db().table("stores")
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
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
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

def _fuzzy_find_store(query: str) -> dict | None:
    q = query.strip().lower()
    best, best_score = None, 0.0
    for s in _fetch_stores():
        name = s.get("name", "").lower()
        city = s.get("city", "").lower()
        if q in name or q in city:
            score = 0.65 + SequenceMatcher(None, q, name).ratio() * 0.35
        else:
            tail  = " ".join(name.split()[2:]) if len(name.split()) > 2 else name
            score = max(
                SequenceMatcher(None, q, name).ratio(),
                SequenceMatcher(None, q, tail).ratio(),
                SequenceMatcher(None, q, city).ratio(),
            )
        if score > best_score:
            best, best_score = s, score
    return best if best_score >= 0.35 else None

def _get_last_notes(store_name: str, limit: int = 3) -> list[dict]:
    try:
        res = (
            _make_db().table("store_notes")
            .select("note,date,city,created_at")
            .eq("store", store_name)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.error("_get_last_notes(%s): %s", store_name, e)
        return []

def _append_note(store: dict, text: str) -> bool:
    """INSERT only — history is never overwritten."""
    try:
        _make_db().table("store_notes").insert({
            "date":  _now_il(),
            "store": store["name"],
            "city":  store.get("city", ""),
            "note":  text.strip(),
        }).execute()
        log.info("Note saved → %s", store["name"])
        return True
    except Exception as e:
        log.error("_append_note(%s): %s", store["name"], e)
        return False

def _record_visit(store: dict) -> None:
    try:
        _make_db().table("manual_visits").insert({
            "date":   _now_il(),
            "store":  store["name"],
            "city":   store.get("city", ""),
            "status": "ביקור",
            "notes":  "צ'ק-אין דרך בוט טלגרם",
        }).execute()
    except Exception as e:
        log.warning("_record_visit(%s): %s", store["name"], e)

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
    await update.message.reply_text(
        "👋 *ברוך הבא לבוט השטח!*\n\n"
        "📍 שלח *מיקום* — צ'ק-אין לחנות הקרובה\n"
        "💬 שלח *טקסט* — רשום הערה לחנות הפעילה\n"
        "/status שם חנות — 3 הערות אחרונות\n"
        "/checkin — הצג את החנות הפעילה כעת",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = _sessions.get(update.effective_user.id)
    if store:
        await update.message.reply_text(
            f"📍 חנות פעילה: *{store['name']}*\n"
            f"🏙️ {store.get('city', '—')}  |  📮 {store.get('address', '—')}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "⚠️ אין חנות פעילה. שלח מיקום GPS לצ'ק-אין."
        )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "📋 שימוש: /status שם חנות\nלדוגמה: /status שילב רעננה"
        )
        return

    await update.message.reply_text("🔍 מחפש...")

    store = await asyncio.to_thread(_fuzzy_find_store, query)
    if not store:
        await update.message.reply_text(
            f"❌ לא נמצאה חנות תואמת ל: *{query}*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    notes = await asyncio.to_thread(_get_last_notes, store["name"], 3)
    header = (
        f"📋 *{store['name']}*  |  {store.get('city', '')}\n"
        f"{'─' * 30}"
    )
    if not notes:
        await update.message.reply_text(
            f"{header}\n\n_אין הערות שמורות לחנות זו._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = [header]
    for i, n in enumerate(notes, 1):
        lines.append(f"\n*{i}.* _{n.get('date', '?')}_\n{n['note']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid       = update.effective_user.id
    loc       = update.message.location
    msg       = await update.message.reply_text("🔍 מאתר חנות קרובה...")
    store, km = await asyncio.to_thread(_nearest_store, loc.latitude, loc.longitude)

    if not store:
        await msg.edit_text("❌ לא נמצאו חנויות בבסיס הנתונים.")
        return

    _sessions[uid] = store
    asyncio.create_task(asyncio.to_thread(_record_visit, store))

    notes     = await asyncio.to_thread(_get_last_notes, store["name"], 1)
    last_txt  = notes[0]["note"] if notes else "אין הערות קודמות"
    last_date = f" _{notes[0]['date']}_" if notes else ""
    dist_str  = f"{km * 1000:.0f}מ'" if km < 1 else f"{km:.2f} ק\"מ"

    await msg.edit_text(
        f"✅ צ'ק-אין: *{store['name']}*\n"
        f"🏙️ {store.get('city', '')}  |  📏 {dist_str}\n"
        f"📮 {store.get('address', '—')}\n\n"
        f"📌 *הערה אחרונה:*{last_date}\n{last_txt}\n\n"
        f"_שלח טקסט כדי להוסיף הערה לחנות זו._",
        parse_mode=ParseMode.MARKDOWN,
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid   = update.effective_user.id
    text  = (update.message.text or "").strip()
    store = _sessions.get(uid)

    if not store:
        await update.message.reply_text(
            "⚠️ אין חנות פעילה.\n📍 שלח מיקום GPS לצ'ק-אין תחילה."
        )
        return

    ok = await asyncio.to_thread(_append_note, store, text)
    if ok:
        await update.message.reply_text(
            f"💾 הערה נשמרה ל: *{store['name']}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("❌ שגיאה בשמירה — נסה שוב.")

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Error: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("❌ שגיאה פנימית. נסה שוב.")

# ══════════════════════════════════════════════════════════════════════════════
# Entry point — SSL bypass for this machine
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN לא מוגדר ב-.env")

    # PTB v20+ uses two separate HTTP connections:
    #   .request()             → regular API calls (getMe, sendMessage, etc.)
    #   .get_updates_request() → long-polling getUpdates (different timeout pool)
    # Both must have verify=False on this machine.
    from telegram.request import HTTPXRequest
    _no_ssl = {"verify": False}
    api_req     = HTTPXRequest(connection_pool_size=8,   httpx_kwargs=_no_ssl)
    update_req  = HTTPXRequest(connection_pool_size=4,   httpx_kwargs=_no_ssl,
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
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(MessageHandler(filters.LOCATION,                handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(handle_error)

    log.info("🤖 Bot starting — polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
