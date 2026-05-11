from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
MY_WHATSAPP_NUMBER = os.getenv("MY_WHATSAPP_NUMBER")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")


def get_sheets_data():
    try:
        url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv"
        response = requests.get(url, timeout=10)
        response.encoding = "utf-8"
        return response.text[:3000]
    except Exception as e:
        return f"שגיאה בטעינת נתונים: {str(e)}"


def ask_gemini(user_message, sheets_data):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        prompt = f"""אתה עוזר אישי לניהול רשת חנויות.
ענה בעברית בלבד, בצורה קצרה ומקצועית.
השתמש בבוליטים כשרלוונטי. מקסימום 300 מילים.

נתוני החנויות:
{sheets_data}

שאלת המשתמש: {user_message}"""

        body = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        response = requests.post(url, json=body, timeout=15)
        data = response.json()
        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"תשובת API: {str(data)[:200]}"
    except Exception as e:
        return f"שגיאה טכנית: {str(e)}"


@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sheets_data = get_sheets_data()
    reply = ask_gemini(incoming_msg, sheets_data)
    resp = MessagingResponse()
    resp.message(reply)
    return str(resp)


def send_proactive_message(message):
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(
        from_=f"whatsapp:{TWILIO_WHATSAPP_NUMBER}",
        to=f"whatsapp:{MY_WHATSAPP_NUMBER}",
        body=message
    )


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
