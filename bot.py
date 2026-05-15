import requests
import time
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# VARIABLES DE ENTORNO
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

# ZONA HORARIA MÉXICO
tz = ZoneInfo("America/Mexico_City")

def enviar_mensaje(texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": texto
    })

def obtener_partidos():
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    
    hoy = datetime.now(tz).strftime("%Y-%m-%d")

    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }

    params = {"date": hoy}

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        return data.get("response", [])
    except:
        return []

def generar_pick(partidos):
    if not partidos:
        return "❌ No hay partidos hoy"

    partido = partidos[0]

    home = partido["teams"]["home"]["name"]
    away = partido["teams"]["away"]["name"]

    mensaje = f"""🔥 PICKS AUTOMÁTICOS 🔥
─────────────────────
🎯 Evento: {home} vs {away}
➡️ Apuesta: Over 2.5 goles
➡️ Stake: 6/10

🤖 Boss Odds Bot"""

    return mensaje

print("🤖 BOT AUTOMÁTICO CORRIENDO...")

ultimo_minuto = None

while True:
    ahora = datetime.now(tz)

    # Ejecutar SOLO en múltiplos de 5 minutos
    if ahora.minute % 5 == 0:
        if ultimo_minuto != ahora.minute:

            partidos = obtener_partidos()
            pick = generar_pick(partidos)

            enviar_mensaje(pick)

            print("✅ Pick enviado:", ahora.strftime("%H:%M:%S"))

            ultimo_minuto = ahora.minute

    time.sleep(1)
