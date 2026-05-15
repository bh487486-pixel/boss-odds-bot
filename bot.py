import requests
import time
import os
from datetime import datetime, timezone
import random

print("BOT BOSS ODDS ACTIVO 🔥")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

enviados = set()
ultimo_update = 0
cache_partidos = []

# ⏱️ actualizar API cada 10 min
TIEMPO_CACHE = 600  

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": mensaje
    }
    requests.post(url, data=data)

def obtener_partidos():
    global ultimo_update, cache_partidos

    ahora = time.time()

    # 🔥 usar cache para no gastar créditos
    if ahora - ultimo_update < TIEMPO_CACHE and cache_partidos:
        print("Usando cache...")
        return cache_partidos

    print("Consultando API...")

    sports = [
        "soccer_epl",
        "soccer_spain_la_liga",
        "basketball_nba",
        "baseball_mlb"
    ]

    partidos = []

    for sport in sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h"

        try:
            res = requests.get(url)

            if res.status_code != 200:
                print("Error API:", sport)
                continue

            data = res.json()

            for game in data:
                fecha = datetime.fromisoformat(
                    game["commence_time"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)

                partidos.append({
                    "home": game["home_team"],
                    "away": game["away_team"],
                    "date": fecha
                })

        except:
            continue

    cache_partidos = partidos
    ultimo_update = ahora

    print("Partidos guardados:", len(partidos))

    return partidos

def generar_pick():
    tipos = [
        "Ganador",
        "Over 2.5",
        "Under 2.5",
        "Hándicap +1.5",
        "Hándicap -1.5"
    ]

    pick = random.choice(tipos)
    cuota = round(random.uniform(1.5, 3.0), 2)
    stake = random.choice(["5/10", "6/10", "7/10"])

    return pick, cuota, stake

def revisar_partidos():
    partidos = obtener_partidos()
    ahora = datetime.now(timezone.utc)

    print("Revisando partidos...")

    for match in partidos:
        try:
            fecha = match["date"]

            if fecha <= ahora:
                continue

            minutos = (fecha - ahora).total_seconds() / 60

            partido_id = f"{match['home']}-{match['away']}-{fecha}"

            print(match["home"], "vs", match["away"], "| faltan:", int(minutos), "min")

            # 🔥 partidos en próximas 2 horas
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

        except:
            continue

def main():
    while True:
        revisar_partidos()
        time.sleep(120)  # 🔥 cada 2 minutos (NO 1 min)

if __name__ == "__main__":
    main()
