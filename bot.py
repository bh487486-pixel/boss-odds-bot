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

# Zona horaria México
zona = pytz.timezone("America/Mexico_City")

ultimo_minuto = None

while True:
    ahora = datetime.now(zona)
    minuto = ahora.minute

    # Solo cada 5 minutos exactos
    if minuto % 5 == 0 and minuto != ultimo_minuto:
        hora = ahora.strftime("%H:%M:%S")

        mensaje = f"""🔥 BOT FUNCIONANDO 🔥

Hora exacta: {hora}
Mensaje cada 5 minutos ✅
"""

        enviar(mensaje)
        print("Enviado:", hora)

        ultimo_minuto = minuto

    time.sleep(1)
