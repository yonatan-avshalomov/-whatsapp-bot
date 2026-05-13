import os
import csv
import io
import requests
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

logging.basicConfig(level=logging.INFO)


def get_sheets_stores():
    """מושך את כל החנויות מ-Google Sheets"""
    try:
        url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv"
        response = requests.get(url, timeout=10)
        response.encoding = "utf-8"

        stores = []
        reader = csv.reader(io.StringIO(response.text))
        next(reader, None)  # דלג על כותרות

        for row in reader:
            if len(row) >= 2 and row[1].strip():
                stores.append({
                    "last_visit": row[0].strip() if len(row) > 0 else "",
                    "name":       row[1].strip(),
                    "address":    row[2].strip() if len(row) > 2 else "",
                    "city":       row[3].strip() if len(row) > 3 else "",
                })
        return stores
    except Exception as e:
        logging.error(f"שגיאה בטעינת גיליון: {e}")
        return []


def get_senzey_deliveries():
    """מושך תעודות משלוח מ-Senzey"""
    try:
        from senzey_scraper import get_deliveries
        return get_deliveries()
    except Exception as e:
        logging.error(f"שגיאה בטעינת Senzey: {e}")
        return []


def enrich_stores_with_senzey(stores, deliveries):
    """
    לכל חנות — מוצא את תאריך המשלוח האחרון מ-Senzey.
    אם לא נמצא — משאיר את תאריך הביקור מהגיליון.
    """
    for store in stores:
        name_words = [w for w in store["name"].split() if len(w) > 2]
        best_date = None

        for d in deliveries:
            d_store = d.get("store", "")
            # התאמה לפי מילות מפתח בשם + עיר
            city_match = store["city"] and store["city"] in d_store
            name_match = any(w in d_store for w in name_words)

            if name_match or city_match:
                if best_date is None or d["date"] > best_date:
                    best_date = d["date"]

        if best_date:
            store["last_delivery"] = best_date
        else:
            store["last_delivery"] = store["last_visit"] or "לא ידוע"

    return stores


def build_area_context(city_query, stores, deliveries):
    """בונה הקשר לשאלה על אזור מסוים"""
    stores = enrich_stores_with_senzey(stores, deliveries)

    relevant = [
        s for s in stores
        if city_query in s["city"] or city_query in s["address"]
    ]

    if not relevant:
        return f"לא נמצאו חנויות באזור {city_query}"

    lines = [f"חנויות באזור {city_query} ({len(relevant)} חנויות):\n"]
    for s in relevant:
        lines.append(f"• {s['name']} | {s['address']} | ביקור אחרון: {s['last_delivery']}")

    return "\n".join(lines)


def build_full_context(stores, deliveries):
    """בונה הקשר מלא לשאלות כלליות"""
    stores = enrich_stores_with_senzey(stores, deliveries)

    # מיון לפי עיר
    by_city = {}
    for s in stores:
        city = s["city"] or "לא ידוע"
        by_city.setdefault(city, []).append(s)

    lines = [f"רשימת חנויות ({len(stores)} חנויות):\n"]
    for city in sorted(by_city):
        lines.append(f"\n📍 {city}:")
        for s in by_city[city]:
            lines.append(f"  • {s['name']} — ביקור אחרון: {s['last_delivery']}")

    # הוסף תעודות אחרונות
    if deliveries:
        lines.append(f"\n\nתעודות משלוח אחרונות ({len(deliveries)}):")
        for d in deliveries[:20]:
            lines.append(f"• {d['date']} — {d['store'][:40]}")

    full = "\n".join(lines)
    return full[:10000]  # מקסימום 10,000 תווים


def ask_gemini(user_message, context_text):
    """שולח שאלה ל-Gemini עם הקשר"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        today = datetime.now().strftime("%d/%m/%Y")

        prompt = f"""אתה עוזר אישי לניהול רשת חנויות בישראל.
ענה בעברית בלבד, בצורה קצרה ומקצועית.
השתמש בבוליטים. מקסימום 300 מילים.
תאריך היום: {today}

הוראות מיוחדות:
- כשמישהו אומר "אני ב[עיר]" או "מה יש לי ב[עיר]" — הצג חנויות באותה עיר עם תאריך ביקור אחרון.
- סמן ⚠️ אם לא בוקרו יותר מחודש.
- סמן ✅ אם בוקרו בשבועיים האחרונים.
- כשמישהו שואל "מה דחוף" — הצג חנויות שלא בוקרו הכי הרבה זמן.
- כשמישהו שואל על תעודות — הצג מהסנזיי.

נתוני החנויות:
{context_text}

שאלה: {user_message}"""

        body = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(url, json=body, timeout=20)
        data = response.json()

        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"שגיאה מ-Gemini: {str(data)[:200]}"
    except Exception as e:
        return f"שגיאה: {str(e)}"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()

    # הודעת המתנה
    await update.message.reply_text("⏳ מחפש נתונים...")

    # שלב 1: טען חנויות
    stores = get_sheets_stores()

    # שלב 2: טען Senzey אם רלוונטי
    senzey_keywords = ["משלוח", "תעודה", "סחורה", "קיבל", "נשלח",
                       "אזור", "ב", "עיר", "מה יש", "דחוף", "ביקור", "מתי"]
    deliveries = []
    if any(w in msg for w in senzey_keywords):
        deliveries = get_senzey_deliveries()

    # שלב 3: בנה הקשר
    # חפש אם מוזכרת עיר ספציפית
    mentioned_city = None
    for store in stores:
        if store["city"] and store["city"] in msg:
            mentioned_city = store["city"]
            break

    if mentioned_city:
        context_text = build_area_context(mentioned_city, stores, deliveries)
    else:
        context_text = build_full_context(stores, deliveries)

    # שלב 4: שאל את Gemini
    reply = ask_gemini(msg, context_text)
    await update.message.reply_text(reply)


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot is running...")
    app.run_polling()
