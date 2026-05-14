import time
import requests
import os
import random

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def enviar(texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": texto})

equipos = [
    "Real Madrid vs Barcelona",
    "PSG vs Bayern",
    "Manchester City vs Liverpool",
    "Inter vs Milan",
    "Juventus vs Napoli",
    "Dodgers vs Yankees",
    "Astros vs Red Sox"
]

apuestas = [
    "Over 2.5 goles",
    "Under 2.5 goles",
    "Ambos anotan",
    "Gana local",
    "Gana visitante"
]

def generar_pick():
    partido = random.choice(equipos)
    apuesta = random.choice(apuestas)
    cuota = round(random.uniform(1.5, 3.5), 2)
    stake = random.randint(5, 10)

    return f"""
🔥 PICKS VIP 🔥
─────────────────────
🎯 Pick:
➡️ Tipo de apuesta: {apuesta}
➡️ Evento: {partido}
➡️ Cuota: {cuota}
➡️ Stake: {stake}/10

Confía en el proceso. 💰
"""

# mensaje inicial
enviar("🔥 Boss Odds Bot AUTOMÁTICO ACTIVADO 🔥")

while True:
    pick = generar_pick()
    enviar(pick)

    # cada 4 horas
    time.sleep(14400)
