import streamlit as st
import requests
import csv
import io
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# תמיכה גם ב-Streamlit Cloud secrets וגם ב-.env מקומי
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    GOOGLE_SHEET_ID = st.secrets["GOOGLE_SHEET_ID"]
except Exception:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

# ── הגדרות עמוד ──────────────────────────────────────────
st.set_page_config(
    page_title="ניהול חנויות",
    page_icon="🏪",
    layout="centered"
)

st.markdown("""
    <style>
        body { direction: rtl; }
        .stChatMessage { direction: rtl; text-align: right; }
        h1 { text-align: center; }
    </style>
""", unsafe_allow_html=True)

st.title("🏪 ניהול חנויות")
st.caption("עוזר אישי לניהול רשת החנויות שלך")

# ── פונקציות נתונים ──────────────────────────────────────

@st.cache_data(ttl=300)  # שמור cache למשך 5 דקות
def get_sheets_stores():
    try:
        url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv"
        response = requests.get(url, timeout=10)
        response.encoding = "utf-8"
        stores = []
        reader = csv.reader(io.StringIO(response.text))
        next(reader, None)
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
        return []


@st.cache_data(ttl=600)  # cache למשך 10 דקות
def get_senzey_deliveries():
    try:
        from senzey_scraper import get_deliveries
        return get_deliveries()
    except Exception as e:
        return []


def enrich_stores(stores, deliveries):
    for store in stores:
        name_words = [w for w in store["name"].split() if len(w) > 2]
        best_date = None
        for d in deliveries:
            d_store = d.get("store", "")
            if any(w in d_store for w in name_words):
                if best_date is None or d["date"] > best_date:
                    best_date = d["date"]
        store["last_delivery"] = best_date or store["last_visit"] or "לא ידוע"
    return stores


def build_context(user_msg, stores, deliveries):
    stores = enrich_stores(stores, deliveries)

    # חפש עיר ספציפית בהודעה
    mentioned_city = None
    for s in stores:
        if s["city"] and s["city"] in user_msg:
            mentioned_city = s["city"]
            break

    if mentioned_city:
        relevant = [s for s in stores if s["city"] == mentioned_city]
        lines = [f"חנויות ב{mentioned_city} ({len(relevant)} חנויות):"]
        for s in relevant:
            lines.append(f"• {s['name']} | {s['address']} | ביקור אחרון: {s['last_delivery']}")
    else:
        by_city = {}
        for s in stores:
            by_city.setdefault(s["city"] or "אחר", []).append(s)
        lines = [f"סה\"כ {len(stores)} חנויות ברשת:"]
        for city in sorted(by_city):
            lines.append(f"\n📍 {city}:")
            for s in by_city[city]:
                lines.append(f"  • {s['name']} — ביקור אחרון: {s['last_delivery']}")

    if deliveries:
        lines.append(f"\n\nתעודות משלוח אחרונות ({len(deliveries)}):")
        for d in deliveries[:15]:
            lines.append(f"• {d['date']} — {d['store'][:40]}")

    return "\n".join(lines)[:10000]


def ask_gemini(user_msg, context_text, chat_history):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        today = datetime.now().strftime("%d/%m/%Y")

        system_prompt = f"""אתה עוזר אישי חכם לניהול רשת חנויות בישראל בשם "ניהול חנויות".
ענה תמיד בעברית, בצורה קצרה, ברורה ומקצועית.
השתמש בבוליטים כשיש רשימות. מקסימום 300 מילים לתשובה.
תאריך היום: {today}

כשמישהו שואל על אזור/עיר — הצג את החנויות שם עם תאריך ביקור אחרון.
סמן ⚠️ אם לא בוקרו יותר מחודש.
סמן ✅ אם בוקרו בשבועיים האחרונים.
כשמישהו שואל "מה דחוף" — הצג חנויות שלא בוקרו הכי הרבה זמן.

נתוני הרשת:
{context_text}"""

        # בנה היסטוריית שיחה
        contents = [{"role": "user", "parts": [{"text": system_prompt}]},
                    {"role": "model", "parts": [{"text": "הבנתי, אני מוכן לעזור בניהול החנויות."}]}]

        for msg in chat_history[-6:]:  # 6 הודעות אחרונות בלבד
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        contents.append({"role": "user", "parts": [{"text": user_msg}]})

        body = {"contents": contents}
        response = requests.post(url, json=body, timeout=20)
        data = response.json()

        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            error = data.get("error", {})
            if error.get("code") == 429:
                return "⏳ הגעת למגבלת השימוש הזמנית. נסה שוב בעוד כמה דקות."
            return f"שגיאה: {str(data)[:200]}"
    except Exception as e:
        return f"שגיאה: {str(e)}"


# ── ממשק שיחה ─────────────────────────────────────────────

# אתחול היסטוריה
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.messages.append({
        "role": "assistant",
        "content": "שלום! אני העוזר לניהול החנויות שלך 🏪\n\nאני יכול לעזור לך עם:\n• **מה יש לי ב[עיר]** — רשימת חנויות באזור\n• **מה דחוף** — חנויות שלא בוקרו הרבה זמן\n• **תעודות משלוח** — מה נשלח לאחרונה\n\nמה תרצה לדעת?"
    })

# הצג היסטוריה
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# קלט משתמש
if prompt := st.chat_input("שאל על החנויות שלך..."):

    # הוסף הודעת משתמש
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # קבל תשובה
    with st.chat_message("assistant"):
        with st.spinner("מחפש נתונים..."):
            stores = get_sheets_stores()

            senzey_keywords = ["משלוח", "תעודה", "סחורה", "קיבל", "נשלח", "דחוף", "ב"]
            deliveries = []
            if any(w in prompt for w in senzey_keywords):
                deliveries = get_senzey_deliveries()

            context_text = build_context(prompt, stores, deliveries)
            reply = ask_gemini(prompt, context_text, st.session_state.messages[:-1])

        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
