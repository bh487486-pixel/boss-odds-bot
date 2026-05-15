import requests
import time
import os
from datetime import datetime
from zoneinfo import ZoneInfo  # viene con Python 3.9+

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def enviar(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    print("POST:", r.status_code, r.text[:100])

print("🚀 BOT INICIADO")

tz = ZoneInfo("America/Mexico_City")

while True:
    ahora = datetime.now(tz)
    print("Loop:", ahora.strftime("%H:%M:%S"))

    # enviar SOLO en 00,05,10,... y exactamente en segundo 00
    if ahora.minute % 5 == 0 and ahora.second == 0:
        hora = ahora.strftime("%H:%M:%S")
        enviar(f"🔥 BOT FUNCIONANDO\n\nHora CDMX: {hora}")
        # evita duplicar en el mismo minuto
        time.sleep(1)

    # revisar dos veces por segundo para no saltarse el segundo 00
    time.sleep(0.5)
