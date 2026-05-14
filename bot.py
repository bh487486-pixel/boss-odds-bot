import time
import requests
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def enviar(texto):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": texto})

# Mensaje inicial
enviar("🔥 Boss Odds Bot ACTIVADO 🔥")

while True:
    pick = """
🔥 PICKS VIP 🔥
─────────────────────
🎯 Pick:
➡️ Tipo de apuesta: Over 2.5 goles
➡️ Evento: Ejemplo FC vs Demo United
➡️ Cuota: 1.85
➡️ Stake: 7/10

Confía en el proceso. 💰
    """

    enviar(pick)

    # espera 6 horas (21600 segundos)
    time.sleep(21600)
