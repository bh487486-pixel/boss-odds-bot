import requests
import time
import os
from datetime import datetime, timezone
import random

print("🚀 BOT BOSS ODDS INICIADO")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

enviados = set()
ultimo_update = 0
cache_partidos = []

TIEMPO_CACHE = 600  # 10 minutos

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": mensaje
        }
        requests.post(url, data=data)
    except Exception as e:
        print("Error Telegram:", e)

def obtener_partidos():
    global ultimo_update, cache_partidos

    ahora = time.time()

    if ahora - ultimo_update < TIEMPO_CACHE and cache_partidos:
        print("🟡 Usando cache...")
        return cache_partidos

    print("🔵 Consultando API...")

    sports = [
        "soccer_epl",
        "soccer_spain_la_liga",
        "basketball_nba",
        "baseball_mlb"
    ]

    partidos = []

    for sport in sports:
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h"
            res = requests.get(url)

            print(f"{sport} status:", res.status_code)

            if res.status_code != 200:
                continue

            data = res.json()

            for game in data:
                fecha = datetime.fromisoformat(
                    game["commence_time"].replace("Z", "+00:00")
                )

                partidos.append({
                    "home": game["home_team"],
                    "away": game["away_team"],
                    "date": fecha
                })

        except Exception as e:
            print("Error sport:", sport, e)

    cache_partidos = partidos
    ultimo_update = ahora

    print("✅ Partidos encontrados:", len(partidos))

    return partidos

def generar_pick():
    tipos = [
        "Ganador",
        "Over 2.5",
        "Under 2.5",
        "Hándicap +1.5",
        "Hándicap -1.5"
    ]

    return (
        random.choice(tipos),
        round(random.uniform(1.5, 3.0), 2),
        random.choice(["5/10", "6/10", "7/10"])
    )

def revisar_partidos():
    print("🔍 Revisando partidos...")

    partidos = obtener_partidos()
    ahora = datetime.now(timezone.utc)

    for match in partidos:
        try:
            fecha = match["date"]

            # ignorar pasados
            if fecha <= ahora:
                continue

            minutos = (fecha - ahora).total_seconds() / 60

            partido_id = f"{match['home']}-{match['away']}-{fecha}"

            print(match["home"], "vs", match["away"], "|", int(minutos), "min")

            # 🔥 ventana de 2 horas
            if 0 < minutos <= 120:

                if partido_id in enviados:
                    continue

                tipo, cuota, stake = generar_pick()

                mensaje = f"""🔥 PICKS VIP 🔥

{match['home']} vs {match['away']}

⏰ Empieza en {int(minutos)} min

➡️ Tipo: {tipo}
➡️ Cuota: {cuota}
➡️ Stake: {stake}

Confía en el sistema 💰
"""

                enviar_telegram(mensaje)
                enviados.add(partido_id)

        except Exception as e:
            print("Error match:", e)

def main():
    print("🟢 BOT CORRIENDO...")

    while True:
        revisar_partidos()
        time.sleep(120)  # cada 2 minutos

if __name__ == "__main__":
    main()
