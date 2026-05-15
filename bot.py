import requests
import time
import os
from datetime import datetime
import pytz

TOKEN = os.getenv("TOKEN_BOT")
CHAT_ID = os.getenv("ID_DE_CHAT")

def enviar(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": mensaje})

print("🔥 BOT ACTIVO 🔥")

zona = pytz.timezone("America/Mexico_City")

# 🔥 SINCRONIZAR AL SEGUNDO EXACTO
while True:
    ahora = datetime.now(zona)
    segundos_restantes = 60 - ahora.second
    time.sleep(segundos_restantes)

    ahora = datetime.now(zona)
    minuto = ahora.minute

    if minuto % 5 == 0:
        hora = ahora.strftime("%H:%M:%S")

        mensaje = f"""🔥 BOT FUNCIONANDO 🔥

Hora exacta: {hora}
Mensaje cada 5 minutos ✅
"""

        enviar(mensaje)
        print("Enviado:", hora)
