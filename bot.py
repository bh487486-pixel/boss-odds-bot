import requests
import time
import os
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

enviados = set()
avisados = set()

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    requests.post(url, data=data)

def obtener_partidos():
    sports = [
        "soccer_spain_la_liga",
        "soccer_epl",
        "basketball_nba",
        "baseball_mlb"
    ]

    partidos = []

    for sport in sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h,spreads,totals,corner_totals"
        res = requests.get(url)

        if res.status_code != 200:
            continue

        data = res.json()

        for game in data:
            try:
                fecha_utc = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
                fecha_local = fecha_utc - timedelta(hours=6)

                partidos.append({
                    "home": game["home_team"],
                    "away": game["away_team"],
                    "date": fecha_local,
                    "bookmakers": game.get("bookmakers", [])
                })

            except:
                continue

    return partidos

def detectar_valor(match):
    try:
        bookmakers = match["bookmakers"]
        if not bookmakers:
            return None

        markets = bookmakers[0]["markets"]

        mejor = None
        mejor_score = 0

        for market in markets:
            if market["key"] not in ["h2h", "spreads", "totals", "corner_totals"]:
                continue

            for o in market["outcomes"]:
                cuota = o["price"]

                if cuota < 1.60 or cuota > 4.00:
                    continue

                prob = 1 / cuota
                prob_estimada = prob * 1.10
                value = (prob_estimada * cuota) - 1

                if value > mejor_score:
                    mejor_score = value
                    mejor = {
                        "tipo": market["key"],
                        "pick": o["name"],
                        "cuota": cuota,
                        "linea": o.get("point", "")
                    }

        if not mejor:
            return None

        if mejor["tipo"] == "h2h":
            tipo_txt = "Ganador"
        elif mejor["tipo"] == "spreads":
            tipo_txt = "Hándicap"
        elif mejor["tipo"] == "totals":
            tipo_txt = "Over/Under"
        elif mejor["tipo"] == "corner_totals":
            tipo_txt = "Córners"
        else:
            tipo_txt = mejor["tipo"]

        return {
            "tipo": tipo_txt,
            "pick": mejor["pick"],
            "cuota": mejor["cuota"],
            "linea": mejor["linea"]
        }

    except:
        return None

def generar_mensaje(match, pick):
    fecha = match["date"].strftime("%d/%m/%Y")
    hora = match["date"].strftime("%I:%M %p")

    linea = f" ({pick['linea']})" if pick["linea"] else ""

    return f"""🔥 PICKS VIP 🔥
━━━━━━━━━━━━━━
📅 Fecha: {fecha}
⏰ Hora: {hora}

🎯 Pick:
➡️ Evento: {match['home']} vs {match['away']}
➡️ Tipo: {pick['tipo']}
➡️ Pick: {pick['pick']}{linea}
➡️ Cuota: {pick['cuota']}
➡️ Stake: 7/10

Confía en el sistema 💰
"""

def revisar_partidos():
    partidos = obtener_partidos()
    ahora = datetime.now()
    hoy = ahora.date()

    for match in partidos:
        try:
            fecha_partido = match["date"]

            if fecha_partido.date() != hoy:
                continue

            if fecha_partido <= ahora:
                continue

            diferencia = fecha_partido - ahora

            partido_id = f"{match['home']}-{match['away']}-{fecha_partido}"

            # 🔔 AVISO DE PARTIDO DETECTADO (10–60 min antes)
            if timedelta(minutes=10) <= diferencia <= timedelta(minutes=60):
                if partido_id not in avisados:
                    enviar_telegram(
                        f"👀 Partido detectado\n\n"
                        f"{match['home']} vs {match['away']}\n"
                        f"⏰ Empieza en {int(diferencia.total_seconds()//60)} min"
                    )
                    avisados.add(partido_id)

            # 🔥 ENVÍO DEL PICK (0–3 min antes)
            if 0 <= diferencia.total_seconds() <= 180:
                if partido_id not in enviados:

                    pick = detectar_valor(match)

                    if pick:
                        mensaje = generar_mensaje(match, pick)
                        enviar_telegram(mensaje)
                        enviados.add(partido_id)

        except:
            continue

def main():
    while True:
        revisar_partidos()
        time.sleep(60)

if __name__ == "__main__":
    main()
