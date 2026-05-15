import requests
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

print("TEST TELEGRAM")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

data = {
    "chat_id": CHAT_ID,
    "text": "🔥 SI VES ESTE MENSAJE, TODO FUNCIONA 🔥"
}

r = requests.post(url, data=data)

print("Status:", r.status_code)
print("Response:", r.text)
