import requests
import time
import os
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

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
    sports = [
        "soccer_spain_la_liga",
        "soccer_epl",
        "baseball_mlb",
        "basketball_nba"
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
                    "bookmakers": game.get("bookmakers", []),
                    "sport": sport
                })

            except:
                continue

    return partidos

def logica_corners(match):
    # 🔥 lógica simple pero útil
    equipos_ofensivos = ["Liverpool", "Man City", "Real Madrid", "Barcelona", "Bayern"]

    if match["home"] in equipos_ofensivos or match["away"] in equipos_ofensivos:
        return {
            "tipo": "Córners",
            "pick": "Over 9.5",
            "cuota": 1.80
        }

    return None

def mejor_pick(match):
    try:
        bookmakers = match["bookmakers"]
        if not bookmakers:
            return None

        markets = bookmakers[0]["markets"]

        mejor = None
        mejor_cuota = 0
        tipo = ""
        linea = ""

        for market in markets:
            nombre = market["key"]

            for outcome in market["outcomes"]:
                cuota = outcome["price"]

                if 1.60 <= cuota <= 3.50:
                    if cuota > mejor_cuota:
                        mejor_cuota = cuota
                        mejor = outcome
                        tipo = nombre
                        linea = outcome.get("point", "")

        # 🎯 SI HAY MERCADO REAL
        if mejor:
            if tipo == "h2h":
                tipo_txt = "Ganador"
            elif tipo == "spreads":
                tipo_txt = "Hándicap"
            elif tipo == "totals":
                tipo_txt = "Over/Under"
            elif tipo == "corner_totals":
                tipo_txt = "Córners"
            else:
                tipo_txt = tipo

            return {
                "tipo": tipo_txt,
                "pick": mejor["name"],
                "cuota": mejor_cuota,
                "linea": linea
            }

        # 🔥 SI NO HAY → lógica de córners
        corners = logica_corners(match)
        if corners:
            return corners

        return None

    except:
        return None

def generar_mensaje(match, pick):
    fecha = match["date"].strftime("%d/%m/%Y")
    hora = match["date"].strftime("%I:%M %p")

    linea = f" ({pick.get('linea','')})" if pick.get("linea") else ""

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

            if timedelta(minutes=29) <= diferencia <= timedelta(minutes=31):

                partido_id = f"{match['home']}-{match['away']}-{fecha_partido}"

                if partido_id not in enviados:

                    pick = mejor_pick(match)

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
