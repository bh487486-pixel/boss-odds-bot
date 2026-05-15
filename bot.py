import requests
import time
import os
from datetime import datetime
import pytz

# 🔐 Variables de entorno
TOKEN = os.getenv("TOKEN_BOT")
CHAT_ID = os.getenv("ID_DE_CHAT")
API_KEY = os.getenv("API_FOOTBALL_KEY")

# 🌎 Zona horaria México
zona_mx = pytz.timezone("America/Mexico_City")

# 🔥 Función para enviar mensaje
def enviar(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg
    })

print("🔥 BOT INICIADO 🔥")

ultimo_minuto = None
ultimo_partido_enviado = None

while True:
    try:
        ahora = datetime.now(zona_mx)
        minuto = ahora.minute

        print(f"⏳ Revisando... {ahora.strftime('%H:%M:%S')}")

        # Ejecutar cada 5 minutos exactos
        if minuto % 5 == 0 and minuto != ultimo_minuto:

            ultimo_minuto = minuto

            hora_actual = ahora.strftime("%H:%M:%S")

            # 🔎 Consultar partidos de hoy
            fecha = ahora.strftime("%Y-%m-%d")

            url = "https://v3.football.api-sports.io/fixtures"

            headers = {
                "x-apisports-key": API_KEY
            }

            params = {
                "date": fecha
            }

            response = requests.get(url, headers=headers, params=params)
            data = response.json()

            if "response" not in data or len(data["response"]) == 0:
                enviar(f"❌ No hay partidos hoy ({hora_actual})")
            else:
                enviado = False

                for partido in data["response"]:
                    liga = partido["league"]["name"]
                    equipo1 = partido["teams"]["home"]["name"]
                    equipo2 = partido["teams"]["away"]["name"]

                    id_partido = partido["fixture"]["id"]

                    # Evitar repetir el mismo pick
                    if id_partido == ultimo_partido_enviado:
                        continue

                    # 🎯 FILTRO (puedes mejorarlo luego)
                    if "Friendly" not in liga:

                        mensaje = f"""🔥 PICK DETECTADO 🔥

{equipo1} vs {equipo2}
Liga: {liga}

Hora CDMX: {hora_actual}
"""

                        enviar(mensaje)
                        ultimo_partido_enviado = id_partido
                        enviado = True
                        break

                if not enviado:
                    enviar(f"❌ No hay partidos buenos disponibles ({hora_actual})")

        time.sleep(30)

    except Exception as e:
        print("❌ ERROR:", e)
        time.sleep(60)
