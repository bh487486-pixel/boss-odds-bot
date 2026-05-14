import requests
import time
import os
from datetime import datetime, timedelta

# 🔐 VARIABLES (desde Render)
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

# Evita repetir picks
enviados = set()

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=data)

def obtener_partidos():
    sports = [
        "soccer_spain_la_liga",
        "soccer_epl",
        "basketball_nba",
        "baseball_mlb"
    ]

    partidos = []

    for sport in sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h"
        res = requests.get(url)

        if res.status_code != 200:
            continue

        data = res.json()

        for game in data:
            try:
                home = game["home_team"]
                away = game["away_team"]

                # Hora del partido (UTC → México aprox -6h)
                fecha_utc = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
                fecha_local = fecha_utc - timedelta(hours=6)

                partidos.append({
                    "home": home,
                    "away": away,
                    "date": fecha_local
                })

            except:
                continue

    return partidos

def generar_pick(match):
    fecha = match["date"].strftime("%d/%m/%Y")
    hora = match["date"].strftime("%I:%M %p")

    return f"""🔥 PICKS VIP 🔥
━━━━━━━━━━━━━━
📅 Fecha: {fecha}
⏰ Hora: {hora}

🎯 Pick:
➡️ Evento: {match['home']} vs {match['away']}
➡️ Tipo de apuesta: Ganador (local)
➡️ Cuota: 1.80
➡️ Stake: 7/10

Confía en el proceso 💰
"""

def revisar_partidos():
    partidos = obtener_partidos()
    ahora = datetime.now()
    hoy = ahora.date()

    for match in partidos:
        try:
            fecha_partido = match["date"]

            # ✅ Solo partidos de HOY
            if fecha_partido.date() != hoy:
                continue

            # ❌ Ignorar partidos ya iniciados
            if fecha_partido <= ahora:
                continue

            diferencia = fecha_partido - ahora

            # ⏰ 30 min antes
            if timedelta(minutes=29) <= diferencia <= timedelta(minutes=31):

                partido_id = f"{match['home']}-{match['away']}-{fecha_partido}"

                if partido_id not in enviados:
                    mensaje = generar_pick(match)
                    enviar_telegram(mensaje)
                    enviados.add(partido_id)

        except:
            continue

def main():
    enviar_telegram("🔥 Boss Odds Bot ACTIVADO 🔥")

    while True:
        revisar_partidos()
        time.sleep(60)

if __name__ == "__main__":
    main()
