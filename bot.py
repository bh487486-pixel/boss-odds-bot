import requests
import time
import os
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def enviar(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

print("🔥 BOT ACTIVO 🔥")

ultimo_minuto = None

while True:
    ahora = datetime.now()
    minuto = ahora.minute

    # Solo ejecutar en múltiplos de 5
    if minuto % 5 == 0:
        # Evitar que mande muchas veces en el mismo minuto
        if ultimo_minuto != minuto:
            hora = ahora.strftime("%H:%M:%S")

            mensaje = f"""🔥 BOT FUNCIONANDO 🔥

Hora exacta: {hora}
Mensaje cada 5 minutos ✔️
"""

            enviar(mensaje)
            print("Mensaje enviado:", hora)

            ultimo_minuto = minuto

    time.sleep(5)
