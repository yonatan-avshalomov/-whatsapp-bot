import streamlit as st
import requests
import csv
import io
import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── מפתחות ───────────────────────────────────────────────
try:
    ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
    GOOGLE_SHEET_ID   = st.secrets["GOOGLE_SHEET_ID"]
    GITHUB_TOKEN      = st.secrets.get("GITHUB_TOKEN", "")
except Exception:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    GOOGLE_SHEET_ID   = os.getenv("GOOGLE_SHEET_ID", "")
    GITHUB_TOKEN      = os.getenv("GITHUB_TOKEN", "")

GITHUB_REPO  = "yonatan-avshalomov/-whatsapp-bot"
NOTES_FILE   = "store_notes.csv"
VISITS_FILE  = "manual_visits.csv"

# ── הגדרות עמוד ──────────────────────────────────────────
st.set_page_config(
    page_title="ניהול חנויות",
    page_icon="🏪",
    layout="centered"
)

st.markdown("""
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="ניהול חנויות">
    <meta name="theme-color" content="#1f77b4">
    <style>
        body, .stApp { direction: rtl; }
        .stChatMessage { direction: rtl; text-align: right; }
        h1, h2, h3 { text-align: center; }
        .stTextInput input, .stTextArea textarea, .stSelectbox select {
            direction: rtl; text-align: right;
        }
        .stButton button { width: 100%; }
        .note-card {
            background: #f0f2f6; border-radius: 10px;
            padding: 10px; margin: 5px 0; direction: rtl;
        }
    </style>
""", unsafe_allow_html=True)

# ── נרמול שמות ───────────────────────────────────────────
def normalize_store_name(name):
    fixes = {
        "ניצתץ":       "ניצת",
        "ניצתהדובדבן": "ניצת הדובדבן",
        "הדבדובן":     "הדובדבן",
        "הדובדבהן":    "הדובדבן",
        "הדודבן":      "הדובדבן",
    }
    for wrong, correct in fixes.items():
        name = name.replace(wrong, correct)
    return re.sub(r"\s{2,}", " ", name).strip()

# ── טעינת נתונים ─────────────────────────────────────────
@st.cache_data(ttl=300)
def get_stores():
    """
    קורא חנויות מ-stores.csv (מסקריפר האתרים) — מקיף יותר.
    אם לא זמין, נופל חזרה ל-Google Sheets.
    """
    stores, seen = [], set()

    # ── ראשון: stores.csv מהרפו (ניצת + שילב + מכבי + פרטי) ──────────────
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/stores.csv"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            text = r.content.decode("utf-8-sig")
            for row in csv.DictReader(io.StringIO(text)):
                name = normalize_store_name(row.get("name", "").strip())
                city = row.get("city", "").strip()
                if not name:
                    continue
                key = (name, city)
                if key not in seen:
                    seen.add(key)
                    stores.append({
                        "name":    name,
                        "city":    city,
                        "address": row.get("address", "").strip(),
                        "chain":   row.get("chain", "").strip(),
                        "phone":   row.get("phone", "").strip(),
                    })
            if stores:
                return stores
    except Exception:
        pass

    # ── גיבוי: Google Sheets ────────────────────────────────────────────────
    try:
        url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQFvzEaqPb8mnyMwNo40WRFkBMYAnsnGWsnkLmfRZaW0saA92t3moVb9heglVartTfX0MQKOEXHRBF2/pub?output=csv"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "utf-8"
        for row in csv.reader(io.StringIO(r.text)):
            if len(row) >= 5 and row[4].strip():
                name = normalize_store_name(row[4].strip())
                city = row[6].strip() if len(row) > 6 else ""
                key  = (name, city)
                if key not in seen:
                    seen.add(key)
                    stores.append({"name": name, "city": city,
                                   "address": row[5].strip() if len(row) > 5 else "",
                                   "chain": "", "phone": ""})
    except Exception:
        pass

    return stores


@st.cache_data(ttl=120)
def get_deliveries():
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/senzey_data.csv"
        r = requests.get(url, timeout=10)
        text = r.content.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        return rows
    except:
        return []


@st.cache_data(ttl=60)
def get_notes():
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/store_notes.csv"
        r = requests.get(url, timeout=10)
        text = r.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    except:
        return []


@st.cache_data(ttl=60)
def get_manual_visits():
    try:
        url = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main/manual_visits.csv"
        r = requests.get(url, timeout=10)
        text = r.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    except:
        return []


def save_note_to_github(date, store, city, note):
    """שומר הערה חדשה לקובץ store_notes.csv בגיטהאב."""
    if not GITHUB_TOKEN:
        return False
    try:
        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{NOTES_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

        # קבל תוכן נוכחי
        r = requests.get(api, headers=headers)
        data = r.json()
        current = ""
        sha = ""
        if "content" in data:
            import base64
            current = base64.b64decode(data["content"]).decode("utf-8-sig")
            sha = data["sha"]

        # הוסף שורה
        new_line = f'\n{date},{store},{city},"{note}"'
        updated = current.rstrip() + new_line + "\n"

        import base64
        payload = {
            "message": f"הערה חדשה: {store}",
            "content": base64.b64encode(updated.encode("utf-8")).decode(),
            "sha": sha
        }
        r = requests.put(api, headers=headers, json=payload)
        return r.status_code in [200, 201]
    except:
        return False


def save_visit_to_github(date, store, city, status, notes=""):
    """שומר ביקור ידני לקובץ manual_visits.csv בגיטהאב."""
    if not GITHUB_TOKEN:
        return False
    try:
        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{VISITS_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

        r = requests.get(api, headers=headers)
        data = r.json()
        current, sha = "", ""
        if "content" in data:
            import base64
            current = base64.b64decode(data["content"]).decode("utf-8-sig")
            sha = data["sha"]

        new_line = f'\n{date},{store},{city},{status},{notes}'
        updated = current.rstrip() + new_line + "\n"

        import base64
        payload = {
            "message": f"ביקור: {store}",
            "content": base64.b64encode(updated.encode("utf-8")).decode(),
            "sha": sha
        }
        r = requests.put(api, headers=headers, json=payload)
        return r.status_code in [200, 201]
    except:
        return False


# ── בניית הקשר לשיחה ─────────────────────────────────────
def build_context(user_msg, stores, deliveries, notes, visits):
    today = datetime.now().strftime("%d/%m/%y")
    lines = []

    # חפש עיר בהודעה
    mentioned_city = next((s["city"] for s in stores if s["city"] and s["city"] in user_msg), None)

    # חנויות
    def last_delivery(store):
        name_words = [w for w in store["name"].split() if len(w) > 2]
        best = None
        for d in deliveries:
            branch = d.get("branch", "")
            if any(w in branch for w in name_words):
                if best is None or d["date"] > best:
                    best = d["date"]
        return best

    if mentioned_city:
        relevant = [s for s in stores if s["city"] == mentioned_city]
        lines.append(f"חנויות ב{mentioned_city} ({len(relevant)}):")
        for s in relevant:
            ld = last_delivery(s) or "לא ידוע"
            lines.append(f"• {s['name']} | {s['address']} | אחרון: {ld}")
    else:
        by_city = {}
        for s in stores:
            by_city.setdefault(s["city"] or "אחר", []).append(s)
        lines.append(f"סה\"כ {len(stores)} חנויות:")
        for city in sorted(by_city):
            lines.append(f"\n📍 {city}:")
            for s in by_city[city][:5]:
                ld = last_delivery(s) or "לא ידוע"
                lines.append(f"  • {s['name']} — {ld}")

    # תעודות משלוח היום
    today_deliveries = [d for d in deliveries if d.get("date","").startswith(today)]
    if today_deliveries:
        lines.append(f"\n🚚 תעודות משלוח היום — ירידת סחורה מהמחסן (לא ביקור אישי!) ({len(today_deliveries)}):")
        for d in today_deliveries:
            lines.append(f"• {d['date']} — {d.get('branch','')[:40]}")
    else:
        lines.append(f"\n🚚 תעודות משלוח היום: אין עדיין")

    # תעודות אחרונות (כל הזמן)
    if deliveries:
        lines.append(f"\n📦 תעודות משלוח אחרונות (ירידת סחורה מהמחסן, לא ביקורים אישיים):")
        for d in deliveries[:8]:
            lines.append(f"• {d['date']} — {d.get('branch','')[:40]}")

    # ביקורים ידניים היום
    today_visits = [v for v in visits if v.get("date","").startswith(today)]
    if today_visits:
        lines.append(f"\n👣 ביקורים ידניים היום ({len(today_visits)}):")
        for v in today_visits:
            lines.append(f"• {v.get('store','')} — {v.get('status','')}")
    else:
        lines.append(f"\n👣 ביקורים ידניים היום: אין — המשתמש לא הזין ביקורים להיום")

    # הערות
    if notes:
        lines.append(f"\nהערות שטח אחרונות:")
        for n in notes[-10:]:
            lines.append(f"• {n.get('date','')} | {n.get('store','')} — {n.get('note','')}")

    return "\n".join(lines)[:12000]


# ── שאל את Claude ─────────────────────────────────────────
def ask_claude(user_msg, context_text, chat_history):
    try:
        today = datetime.now().strftime("%d/%m/%Y")
        system_prompt = f"""אתה עוזר אישי חכם לניהול רשת חנויות בישראל.
ענה תמיד בעברית, קצר וברור. השתמש בבוליטים כשיש רשימות.
תאריך היום: {today}

⛔ חוקים קשיחים:
1. אסור להמציא נתונים — ענה רק על מה שכתוב בהקשר למטה
2. אם אין מידע — אמור "אין מידע" ואל תנחש
3. הבדל קריטי בין שני סוגי נתונים:
   • "תעודות משלוח" (סנזי) = סחורה שירדה לחנות מהמחסן — זה לא ביקור של המשתמש!
   • "ביקורים ידניים" = רק כשרשום במפורש בסעיף "ביקורים היום"
4. אל תגיד "ביקרת" אם רק יש תעודת משלוח — אלו דברים שונים לגמרי
5. כשמישהו שואל "איפה היית" — הסתמך רק על ביקורים ידניים, לא תעודות

כללים נוספים:
- ⚠️ = לא בוקר יותר מחודש
- ✅ = בוקר בשבועיים האחרונים
- כשמישהו שואל "מה דחוף" — הצג חנויות שלא בוקרו הכי הרבה זמן
- כשמישהו שואל על עיר — הצג רק אותה עיר עם תאריכים
- כל ניצת הדובדבן = לקוחות סופר סאפ (הפצה דרכם, אבל כדאי לבקר)

--- נתונים אמיתיים בלבד ---
{context_text}
--- סוף נתונים ---"""

        messages = []
        for msg in chat_history[-8:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_msg})

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": messages
            },
            timeout=30
        )
        data = r.json()
        if "content" in data:
            return data["content"][0]["text"]
        return f"שגיאה: {str(data)[:200]}"
    except Exception as e:
        return f"שגיאה: {str(e)}"


# ══════════════════════════════════════════════════════════
# ── ממשק ראשי ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════

st.title("🏪 ניהול חנויות")

tab1, tab2, tab3 = st.tabs(["💬 שיחה", "📝 הוסף הערה", "📊 סיכום יום"])


# ════════════════════════════
# לשונית 1 — שיחה
# ════════════════════════════
with tab1:
    if "messages" not in st.session_state:
        st.session_state.messages = [{
            "role": "assistant",
            "content": "שלום! אני העוזר לניהול החנויות שלך 🏪\n\n• **מה יש לי ב[עיר]** — רשימת חנויות\n• **מה דחוף** — מה לא בוקר הרבה זמן\n• **סיכום היום** — מה יצא היום\n\nמה תרצה לדעת?"
        }]

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("שאל על החנויות שלך..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("מחפש..."):
                stores     = get_stores()
                deliveries = get_deliveries()
                notes      = get_notes()
                visits     = get_manual_visits()
                context    = build_context(prompt, stores, deliveries, notes, visits)
                reply      = ask_claude(prompt, context, st.session_state.messages[:-1])
            st.markdown(reply)

        st.session_state.messages.append({"role": "assistant", "content": reply})


# ════════════════════════════
# לשונית 2 — הוסף הערה
# ════════════════════════════
with tab2:
    st.subheader("📝 הוסף הערה על חנות")

    stores = get_stores()
    store_names = sorted(set(s["name"] for s in stores))
    cities      = sorted(set(s["city"] for s in stores if s["city"]))

    col1, col2 = st.columns(2)
    with col1:
        selected_store = st.selectbox("חנות", [""] + store_names, key="note_store")
    with col2:
        selected_city = st.selectbox("עיר", [""] + cities, key="note_city")

    note_text = st.text_area("הערה", placeholder="לדוגמה: המנהל ביקש עוד מוס, המדף דליל...", key="note_text")

    note_type = st.radio("סוג", ["הערה כללית", "ביקרתי היום", "לא הגעתי", "צריך הזמנה"], horizontal=True)

    if st.button("💾 שמור הערה", type="primary"):
        if selected_store and note_text:
            today_str = datetime.now().strftime("%d/%m/%y")
            city_val  = selected_city or next((s["city"] for s in stores if s["name"] == selected_store), "")
            full_note = f"[{note_type}] {note_text}"

            ok = save_note_to_github(today_str, selected_store, city_val, full_note)
            if ok:
                st.success(f"✅ נשמר! הערה על {selected_store}")
                get_notes.clear()
            else:
                st.warning("⚠️ לא ניתן לשמור לענן כרגע — ההערה נשמרה בסשן")
                if "local_notes" not in st.session_state:
                    st.session_state.local_notes = []
                st.session_state.local_notes.append({
                    "date": today_str, "store": selected_store,
                    "city": city_val, "note": full_note
                })
        else:
            st.error("נא לבחור חנות ולכתוב הערה")

    # הצג הערות אחרונות
    st.divider()
    st.subheader("הערות אחרונות")
    all_notes = get_notes()
    local     = st.session_state.get("local_notes", [])
    combined  = (all_notes + local)[-15:][::-1]

    if combined:
        for n in combined:
            st.markdown(f"""<div class='note-card'>
                <b>{n.get('store','')}</b> — {n.get('city','')}<br>
                <small>{n.get('date','')}</small><br>
                {n.get('note','')}
            </div>""", unsafe_allow_html=True)
    else:
        st.info("אין הערות עדיין")


# ════════════════════════════
# לשונית 3 — סיכום יום
# ════════════════════════════
with tab3:
    st.subheader("📊 סיכום היום")

    today_str  = datetime.now().strftime("%d/%m/%y")
    deliveries = get_deliveries()
    visits     = get_manual_visits()
    notes      = get_notes()

    today_del = [d for d in deliveries if d.get("date","").startswith(today_str)]
    today_vis = [v for v in visits    if v.get("date","") == today_str or v.get("date","").startswith(today_str)]
    today_not = [n for n in notes     if n.get("date","") == today_str or n.get("date","").startswith(today_str)]

    col1, col2, col3 = st.columns(3)
    col1.metric("תעודות משלוח", len(today_del))
    col2.metric("ביקורים ידניים", len(today_vis))
    col3.metric("הערות", len(today_not))

    if today_del:
        st.subheader("🚚 תעודות משלוח")
        for d in today_del:
            st.markdown(f"• **{d.get('date','')[6:]}** — {d.get('branch','')}")

    if today_vis:
        st.subheader("👣 ביקורים")
        for v in today_vis:
            icon = "✅" if v.get("status") == "ביקור" else "⚠️"
            st.markdown(f"{icon} {v.get('store','')} — {v.get('status','')}")

    if today_not:
        st.subheader("📝 הערות")
        for n in today_not:
            st.markdown(f"• **{n.get('store','')}** — {n.get('note','')}")

    if not today_del and not today_vis and not today_not:
        st.info("אין נתונים להיום עדיין")

    st.divider()
    if st.button("🔄 רענן נתונים"):
        get_deliveries.clear()
        get_notes.clear()
        get_manual_visits.clear()
        st.rerun()
