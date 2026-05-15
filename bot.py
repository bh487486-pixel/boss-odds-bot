import requests
import time
import os
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

enviados = set()
avisados = set()

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": mensaje
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
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h,spreads,totals"
        
        try:
            res = requests.get(url)

            if res.status_code != 200:
                print("Error API:", sport)
                continue

            data = res.json()

            for game in data:
                try:
                    # 🔥 TODO en UTC (esto arregla el error)
                    fecha_partido = datetime.fromisoformat(
                        game["commence_time"].replace("Z", "+00:00")
                    ).astimezone(timezone.utc)

                    partidos.append({
                        "home": game["home_team"],
                        "away": game["away_team"],
                        "date": fecha_partido,
                        "bookmakers": game.get("bookmakers", [])
                    })
                except:
                    continue

        except Exception as e:
            print("Error request:", e)

    return partidos

def detectar_valor(match):
    try:
        bookmakers = match["bookmakers"]

        if not bookmakers:
            return None

        markets = bookmakers[0]["markets"]

        for market in markets:
            for o in market["outcomes"]:
                cuota = o["price"]

                if 1.40 <= cuota <= 4.50:
                    return {
                        "tipo": market["key"],
                        "pick": o["name"],
                        "cuota": cuota
                    }

        return None
    except:
        return None

def generar_mensaje(match, pick):
    fecha = match["date"].strftime("%d/%m/%Y")
    hora = match["date"].strftime("%I:%M %p")

    return f"""🔥 PICKS VIP 🔥

📅 {fecha}
⏰ {hora}

{match['home']} vs {match['away']}

➡️ {pick['tipo']}
➡️ {pick['pick']}
➡️ Cuota: {pick['cuota']}

Confía en el sistema 💰
"""

def revisar_partidos():
    partidos = obtener_partidos()
    ahora = datetime.now(timezone.utc)  # 🔥 MISMO FORMATO QUE LOS PARTIDOS

    print(f"TOTAL partidos encontrados: {len(partidos)}")

    for match in partidos:
        try:
            fecha_partido = match["date"]

            # 🔥 YA NO FALLA
            if fecha_partido <= ahora:
                continue

            diferencia = fecha_partido - ahora
            partido_id = f"{match['home']}-{match['away']}-{fecha_partido}"

            print(match["home"], "vs", match["away"], fecha_partido)

            # 👀 DETECTAR PARTIDO
            if timedelta(minutes=5) <= diferencia <= timedelta(hours=6):
                if partido_id not in avisados:
                    enviar_telegram(
                        f"👀 Partido detectado\n\n"
                        f"{match['home']} vs {match['away']}\n"
                        f"Empieza en {int(diferencia.total_seconds()/60)} min"
                    )
                    avisados.add(partido_id)

            # 🔥 ENVIAR PICK
            if 0 <= diferencia.total_seconds() <= 600:
                if partido_id not in enviados:

                    pick = detectar_valor(match)

                    if pick:
                        mensaje = generar_mensaje(match, pick)
                        enviar_telegram(mensaje)
                        enviados.add(partido_id)

        except Exception as e:
            print("Error:", e)
            continue

def main():
    print("BOT INICIADO 🔥")

    while True:
        revisar_partidos()
        time.sleep(60)

if __name__ == "__main__":
    main()
