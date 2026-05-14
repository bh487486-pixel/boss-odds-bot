import requests
import time
from datetime import datetime, timedelta

BOT_TOKEN = 8750460017:AAHlOiVn6FSvbVbv0clP9Kbc92eah8eITBg
CHAT_ID = 8463436388

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

    fecha = fecha_partido.strftime("%d/%m/%Y")
    hora = fecha_partido.strftime("%I:%M %p")

    return f"""🔥 PICKS VIP 🔥
━━━━━━━━━━━━━━
📅 Fecha: {fecha}
⏰ Hora: {hora}

🎯 Pick:
➡️ Evento: {equipo1} vs {equipo2}
➡️ Tipo de apuesta: Over 2.5 goles
➡️ Cuota: 1.85
➡️ Stake: 7/10

Confía en el proceso 💰
"""

def revisar_partidos():
    partidos = obtener_partidos()
    ahora = datetime.now()
    hoy = ahora.date()

    for match in partidos:
        try:
            fecha_str = match.get("date")
            fecha_partido = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S")

            # ✅ Solo partidos de HOY
            if fecha_partido.date() != hoy:
                continue

            # ❌ Ignorar partidos ya iniciados o finalizados
            if fecha_partido <= ahora:
                continue

            # ⏰ Calcular tiempo restante
            diferencia = fecha_partido - ahora

            # ✅ Solo enviar 30 min antes
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
        time.sleep(60)

if __name__ == "__main__":
    main()
