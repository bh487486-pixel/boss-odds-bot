import time
import requests
import os
import random

API_KEY = os.getenv("API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SPORTS = [
    "soccer_spain_la_liga",
    "soccer_epl",
    "basketball_nba",
    "baseball_mlb"
]

def enviar(texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": texto})

def obtener_partidos():
    partidos = []

    for sport in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h"
        res = requests.get(url)

        if res.status_code != 200:
            continue

        data = res.json()

        for game in data:
            home = game["home_team"]
            away = game["away_team"]

            if not game["bookmakers"]:
                continue

            odds = game["bookmakers"][0]["markets"][0]["outcomes"]

            for o in odds:
                partidos.append({
                    "match": f"{home} vs {away}",
                    "team": o["name"],
                    "price": o["price"]
                })

    return partidos

def generar_pick():
    partidos = obtener_partidos()

    if not partidos:
        return "⚠️ No hay partidos disponibles"

    pick = random.choice(partidos)

    stake = random.randint(5, 10)

    return f"""
🔥 PICKS VIP 🔥
─────────────────────
🎯 Pick:
➡️ Tipo de apuesta: Ganador
➡️ Evento: {pick['match']}
➡️ Pick: {pick['team']}
➡️ Cuota: {pick['price']}
➡️ Stake: {stake}/10

Confía en el sistema. 💰
"""

enviar("🔥 Boss Odds MX AUTOMÁTICO ACTIVADO 🔥")

while True:
    mensaje = generar_pick()
    enviar(mensaje)

    time.sleep(10800)  # cada 3 horas
