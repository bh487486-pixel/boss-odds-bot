import os
import time
import random
import logging
from datetime import datetime
import pytz
import requests

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# Variables de Entorno
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

# API URL (API-FOOTBALL)
API_URL = "https://v3.football.api-sports.io/fixtures"

# 🔥 HEADER CORREGIDO
API_HEADERS = {
    "x-apisports-key": FOOTBALL_API_KEY
}

# Tiempos
ENVIO_INTERVALO = 300      # 5 minutos
ACTUALIZAR_API_INTERVALO = 1800  # 30 minutos

# Zona horaria México
TZ_MEXICO = pytz.timezone("America/Mexico_City")

# Cache
cache_partidos = []
ultimo_analisis_api = 0
partidos_enviados = set()

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
        logging.info("Mensaje enviado")
    except Exception as e:
        logging.error(f"Error Telegram: {e}")

def consultar_api_futbol():
    global cache_partidos, ultimo_analisis_api
    
    ahora = time.time()

    if cache_partidos and (ahora - ultimo_analisis_api < ACTUALIZAR_API_INTERVALO):
        logging.info("Usando cache")
        return cache_partidos

    hoy = datetime.now(TZ_MEXICO).strftime("%Y-%m-%d")

    try:
        response = requests.get(API_URL, headers=API_HEADERS, params={"date": hoy}, timeout=15)
        data = response.json()

        partidos = data.get("response", [])

        # Solo partidos que no han iniciado
        partidos = [
            p for p in partidos
            if p["fixture"]["status"]["short"] in ["NS", "TBD"]
        ]

        cache_partidos = partidos
        ultimo_analisis_api = ahora

        logging.info(f"Partidos encontrados: {len(partidos)}")

        return partidos

    except Exception as e:
        logging.error(f"Error API: {e}")
        return cache_partidos

def generar_pick(local, visitante):
    opciones = ["over", "ganador", "handicap", "combinado"]
    tipo = random.choice(opciones)

    picks = []

    if tipo in ["over", "combinado"]:
        linea = random.choice(["1.5", "2.5", "3.5"])
        picks.append(f"• Over {linea} goles")

    if tipo in ["ganador", "combinado"]:
        picks.append(f"• Ganador: {random.choice([local, visitante])}")

    if tipo in ["handicap", "combinado"]:
        linea = random.choice(["-1", "+1", "-1.5"])
        equipo = random.choice([local, visitante])
        picks.append(f"• Hándicap: {equipo} {linea}")

    return "\n".join(picks)

def procesar():
    global partidos_enviados

    partidos = consultar_api_futbol()
    hora = datetime.now(TZ_MEXICO).strftime("%H:%M")

    if not partidos:
        enviar_telegram(f"❌ No hay partidos hoy\n🕒 {hora}")
        return

    # evitar repetir
    disponibles = [p for p in partidos if p["fixture"]["id"] not in partidos_enviados]

    if not disponibles:
        partidos_enviados.clear()
        disponibles = partidos

    partido = random.choice(disponibles)
    partidos_enviados.add(partido["fixture"]["id"])

    # 🔥 FIX AQUÍ
    local = partido["teams"]["home"]["name"]
    visitante = partido["teams"]["away"]["name"]

    liga = partido["league"]["name"]

    pick = generar_pick(local, visitante)
    stake = random.randint(4, 7)

    mensaje = f"""🔥 PICKS AUTOMÁTICOS 🔥
─────────────────────
🎯 Evento: {local} vs {visitante}
🏆 Liga: {liga}

➡️ Pick:
{pick}

➡️ Stake: {stake}/10

🕒 Hora CDMX: {hora}
"""

    enviar_telegram(mensaje)

def main():
    logging.info("Bot iniciado correctamente")

    while True:
        try:
            inicio = time.time()

            procesar()

            duracion = time.time() - inicio
            sleep = max(0, ENVIO_INTERVALO - duracion)

            logging.info(f"Esperando {int(sleep)} segundos...")
            time.sleep(sleep)

        except Exception as e:
            logging.error(f"Error general: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
