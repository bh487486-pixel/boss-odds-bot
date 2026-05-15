import requests
import time
import os
from datetime import datetime
import pytz

# 🔐 Variables de entorno
TOKEN = os.getenv("TOKEN_BOT")
CHAT_ID = os.getenv("ID_DE_CHAT")
API_KEY = os.getenv("API_FOOTBALL_KEY")

# 🌎 Zona horaria México
zona_mx = pytz.timezone("America/Mexico_City")

# 📩 Función enviar mensaje
def enviar(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": msg
        })
    except Exception as e:
        print("Error enviando:", e)

print("🔥 BOT AUTOMÁTICO INICIADO 🔥")

while True:
    try:
        ahora = datetime.now(zona_mx)
        hora_actual = ahora.strftime("%H:%M:%S")

        print(f"⏳ Buscando partidos... {hora_actual}")

        fecha = ahora.strftime("%Y-%m-%d")

        url = "https://v3.football.api-sports.io/fixtures"

        headers = {
            "x-apisports-key": API_KEY
        }

        params = {
            "date": fecha
        }

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if "response" not in data or len(data["response"]) == 0:
            enviar(f"❌ No hay partidos hoy ({hora_actual})")
        else:
            partido = data["response"][0]  # 🔥 toma el primer partido

            equipo1 = partido["teams"]["home"]["name"]
            equipo2 = partido["teams"]["away"]["name"]
            liga = partido["league"]["name"]

            mensaje = f"""🔥 PICK AUTOMÁTICO 🔥
─────────────────────
🎯 Evento: {equipo1} vs {equipo2}
🏆 Liga: {liga}

➡️ Pick: Over 2.5 goles
➡️ Stake: 5/10

🕒 Hora CDMX: {hora_actual}
"""

            enviar(mensaje)

        # ⏰ Espera 5 minutos reales
        time.sleep(300)

    except Exception as e:
        print("❌ ERROR:", e)
        time.sleep(60)
