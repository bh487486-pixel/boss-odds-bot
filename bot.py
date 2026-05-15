import requests
import time
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

tz = ZoneInfo("America/Mexico_City")

def enviar_mensaje(texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": texto
    })

def obtener_partidos():
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"

    fechas = [
        datetime.now(tz).strftime("%Y-%m-%d"),
        (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")
    ]

    headers = {
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }

    partidos = []

    for fecha in fechas:
        try:
            res = requests.get(url, headers=headers, params={"date": fecha})
            data = res.json()
            partidos.extend(data.get("response", []))
        except:
            continue

    return partidos

def elegir_mejor_partido(partidos):
    ligas_buenas = [
        "Premier League",
        "La Liga",
        "Serie A",
        "Bundesliga",
        "Ligue 1",
        "Liga MX",
        "MLS"
    ]

    for partido in partidos:
        liga = partido["league"]["name"]
        estado = partido["fixture"]["status"]["short"]

        if liga in ligas_buenas and estado == "NS":
            return partido

    return None

def generar_pick(partido):
    if not partido:
        return None  # 🔥 CLAVE: ya no manda texto basura

    home = partido["teams"]["home"]["name"]
    away = partido["teams"]["away"]["name"]
    liga = partido["league"]["name"]

    hora = partido["fixture"]["date"]
    hora_local = datetime.fromisoformat(hora.replace("Z", "+00:00")).astimezone(tz)

    return f"""🔥 PICKS AUTOMÁTICOS 🔥
─────────────────────
🎯 Evento: {home} vs {away}
🏆 Liga: {liga}
🕒 Hora: {hora_local.strftime("%H:%M")}

➡️ Pick: Over 2.5 goles
➡️ Stake: 6/10

🤖 Boss Odds Bot"""

print("🤖 BOT PRO CORRIENDO...")

ultimo_minuto = None

while True:
    ahora = datetime.now(tz)

    if ahora.minute % 5 == 0:
        if ultimo_minuto != ahora.minute:

            print(f"⏳ Revisando partidos... {ahora.strftime('%H:%M:%S')}")

            partidos = obtener_partidos()
            partido = elegir_mejor_partido(partidos)
            mensaje = generar_pick(partido)

            if mensaje:
                enviar_mensaje(mensaje)
                print("✅ PICK ENVIADO")
            else:
                print("❌ No hay picks buenos (NO se envía nada)")

            ultimo_minuto = ahora.minute

    time.sleep(1)
