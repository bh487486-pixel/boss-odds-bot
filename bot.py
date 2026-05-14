import requests
import time
import os
from datetime import datetime, timedelta

# 🔐 VARIABLES DESDE RENDER
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
        "baseball_mlb"
    ]

    partidos = []

    for sport in sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h"
        res = requests.get(url)

        if res.status_code != 200:
            continue

        data = res.json()

        for game in data:
            try:
                home = game["home_team"]
                away = game["away_team"]

                # Convertir hora UTC a México (-6)
                fecha_utc = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
                fecha_local = fecha_utc - timedelta(hours=6)

                partidos.append({
                    "home": home,
                    "away": away,
                    "date": fecha_local,
                    "bookmakers": game.get("bookmakers", [])
                })

            except:
                continue

    return partidos

def generar_pick(match):
    home = match["home"]
    away = match["away"]
    fecha_partido = match["date"]

    fecha = fecha_partido.strftime("%d/%m/%Y")
    hora = fecha_partido.strftime("%I:%M %p")

    try:
        bookmakers = match["bookmakers"]

        if not bookmakers:
            return None

        markets = bookmakers[0]["markets"][0]["outcomes"]

        odds_home = None
        odds_away = None

        for o in markets:
            if o["name"] == home:
                odds_home = o["price"]
            elif o["name"] == away:
                odds_away = o["price"]

        if odds_home is None or odds_away is None:
            return None

        # 🎯 Elegir favorito (cuota más baja)
        if odds_home < odds_away:
            pick = home
            cuota = odds_home
        else:
            pick = away
            cuota = odds_away

        # ❌ Filtrar picks basura
        if cuota < 1.50 or cuota > 3.50:
            return None

        # 🎚 Stake dinámico
        if cuota < 2.0:
            stake = "8/10"
        elif cuota < 2.5:
            stake = "7/10"
        else:
            stake = "6/10"

        return f"""🔥 PICKS VIP 🔥
━━━━━━━━━━━━━━
📅 Fecha: {fecha}
⏰ Hora: {hora}

🎯 Pick:
➡️ Evento: {home} vs {away}
➡️ Pick: {pick}
➡️ Cuota: {cuota}
➡️ Stake: {stake}

Confía en el sistema 💰
"""

    except:
        return None

def revisar_partidos():
    partidos = obtener_partidos()
    ahora = datetime.now()
    hoy = ahora.date()

    for match in partidos:
        try:
            fecha_partido = match["date"]

            # ✅ Solo hoy
            if fecha_partido.date() != hoy:
                continue

            # ❌ Ignorar partidos ya iniciados
            if fecha_partido <= ahora:
                continue

            diferencia = fecha_partido - ahora

            # ⏰ 30 min antes
            if timedelta(minutes=29) <= diferencia <= timedelta(minutes=31):

                partido_id = f"{match['home']}-{match['away']}-{fecha_partido}"

                if partido_id not in enviados:
                    mensaje = generar_pick(match)

                    if mensaje:
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
