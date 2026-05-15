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

while True:
    ahora = datetime.now(zona)

    # ⏰ calcular segundos para el siguiente múltiplo de 5 minutos
    minutos = ahora.minute
    segundos = ahora.second

    minutos_para_siguiente = (5 - (minutos % 5)) % 5
    if minutos_para_siguiente == 0 and segundos > 0:
        minutos_para_siguiente = 5

    tiempo_espera = (minutos_para_siguiente * 60) - segundos

    time.sleep(tiempo_espera)

    ahora = datetime.now(zona)
    hora = ahora.strftime("%H:%M:%S")

    mensaje = f"""🔥 BOT FUNCIONANDO 🔥

Hora exacta: {hora}
Mensaje cada 5 minutos ✅
"""

    enviar(mensaje)
    print("Enviado:", hora)
