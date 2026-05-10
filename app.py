from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
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

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")


def get_sheets_data():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_file("google_credentials.json", scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
        return sheet.get_all_records()
    except Exception as e:
        return f"שגיאה בטעינת נתוני החנויות: {str(e)}"


def ask_gemini(user_message, sheets_data):
    prompt = f"""אתה עוזר אישי לניהול רשת חנויות.
ענה בעברית בלבד, בצורה קצרה ומקצועית כמו הודעת וואטסאפ.
השתמש בבוליטים כשרלוונטי. מקסימום 300 מילים.

נתוני החנויות:
{sheets_data}

שאלת המשתמש: {user_message}"""

    response = model.generate_content(prompt)
    return response.text


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
