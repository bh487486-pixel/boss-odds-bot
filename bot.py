import requests
import time
from datetime import datetime, timedelta

BOT_TOKEN = "TU_TOKEN"
CHAT_ID = "TU_CHAT_ID"

enviados = set()

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=data)

def obtener_partidos():
    # 🔴 CAMBIA por tu API real
    url = "https://api.sample.com/matches"
    response = requests.get(url)
    return response.json()

def generar_pick(match):
    equipo1 = match.get("home", "Equipo A")
    equipo2 = match.get("away", "Equipo B")

    fecha_str = match.get("date")
    fecha_partido = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S")

    fecha_formateada = fecha_partido.strftime("%d/%m/%Y")
    hora_formateada = fecha_partido.strftime("%I:%M %p")

    return f"""🔥 PICKS VIP 🔥
━━━━━━━━━━━━━━
📅 Fecha: {fecha_formateada}
⏰ Hora: {hora_formateada}

🎯 Pick:
➡️ Evento: {equipo1} vs {equipo2}
➡️ Tipo de apuesta: Over 2.5 goles
➡️ Cuota: 1.85
➡️ Stake: 7/10

Confía en el proceso 💰
"""

def revisar_partidos():
    partidos = obtener_partidos()

    for match in partidos:
        try:
            fecha_str = match.get("date")
            fecha_partido = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S")

            ahora = datetime.now()
            diferencia = fecha_partido - ahora

            # ⏰ Enviar 30 min antes SIN importar el día
            if timedelta(minutes=29) <= diferencia <= timedelta(minutes=31):

                partido_id = f"{match.get('home')}-{match.get('away')}-{fecha_str}"

                if partido_id not in enviados:
                    mensaje = generar_pick(match)
                    enviar_telegram(mensaje)
                    enviados.add(partido_id)

        except:
            continue

def main():
    enviar_telegram("🔥 Boss Odds Bot ACTIVADO 🔥")

    while True:
        revisar_partidos()
        time.sleep(60)  # revisa cada minuto

if __name__ == "__main__":
    main()
