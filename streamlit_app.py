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
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
    GOOGLE_SHEET_ID = st.secrets["GOOGLE_SHEET_ID"]
except Exception:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
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
        url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQFvzEaqPb8mnyMwNo40WRFkBMYAnsnGWsnkLmfRZaW0saA92t3moVb9heglVartTfX0MQKOEXHRBF2/pub?output=csv"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, timeout=15, allow_redirects=True, headers=headers)
        response.encoding = "utf-8"
        stores = []
        reader = csv.reader(io.StringIO(response.text))
        next(reader, None)
        for row in reader:
            if len(row) >= 5 and row[4].strip():
                stores.append({
                    "last_visit": row[3].strip() if len(row) > 3 else "",
                    "name":       row[4].strip(),
                    "address":    row[5].strip() if len(row) > 5 else "",
                    "city":       row[6].strip() if len(row) > 6 else "",
                })
        return stores
    except Exception as e:
        return []


@st.cache_data(ttl=3600)  # cache שעה
def get_senzey_deliveries():
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/senzey_data.csv"
        response = requests.get(url, timeout=10)
        response.encoding = "utf-8"
        deliveries = []
        reader = csv.reader(io.StringIO(response.text))
        header = next(reader, None)
        # Support both old format (date, store) and new format (date, customer, branch)
        has_branch = header and len(header) >= 3
        for row in reader:
            if len(row) >= 2:
                entry = {
                    "date": row[0],
                    "customer": row[1],
                    "branch": row[2].strip() if has_branch and len(row) >= 3 else row[1]
                }
                deliveries.append(entry)
        return deliveries
    except Exception as e:
        return []


def enrich_stores(stores, deliveries):
    for store in stores:
        name_words = [w for w in store["name"].split() if len(w) > 2]
        best_date = None
        for d in deliveries:
            # Prefer branch name (specific store), fall back to customer name
            match_text = d.get("branch") or d.get("store", "")
            if any(w in match_text for w in name_words):
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
            branch = d.get("branch") or d.get("store", "")
            lines.append(f"• {d['date']} — {branch[:40]}")

    return "\n".join(lines)[:10000]


def ask_groq(user_msg, context_text, chat_history):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
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

        messages = [{"role": "system", "content": system_prompt}]

        for msg in chat_history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": user_msg})

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        body = {
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "max_tokens": 500
        }

        response = requests.post(url, json=body, headers=headers, timeout=20)
        data = response.json()

        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
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
            reply = ask_groq(prompt, context_text, st.session_state.messages[:-1])

        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
