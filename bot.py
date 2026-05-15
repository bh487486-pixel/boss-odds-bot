import requests
import time
import os
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

def enviar_telegram(mensaje):
    print("Enviando a Telegram...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": mensaje
    }
    requests.post(url, data=data)

def obtener_partidos():
    print("Entrando a obtener_partidos()")

    sports = [
        "soccer_spain_la_liga",
        "soccer_epl",
        "basketball_nba",
        "baseball_mlb"
    ]

    partidos = []

    for sport in sports:
        print(f"Consultando API: {sport}")

        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h,spreads,totals"
        
        try:
            res = requests.get(url)
            print("Status:", res.status_code)

            if res.status_code != 200:
                print("Error API:", res.text)
                continue

            data = res.json()
            print(f"Partidos recibidos: {len(data)}")

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
                except Exception as e:
                    print("Error parseando partido:", e)

        except Exception as e:
            print("Error total en request:", e)

    return partidos

def revisar_partidos():
    print("Ejecutando revisión...")

    partidos = obtener_partidos()
    ahora = datetime.now()

    print(f"TOTAL partidos encontrados: {len(partidos)}")

    for match in partidos:
        print(match["home"], "vs", match["away"], match["date"])

        if match["date"] > ahora:
            enviar_telegram(
                f"👀 Partido detectado\n\n"
                f"{match['home']} vs {match['away']}\n"
                f"{match['date']}"
            )
            break  # solo manda uno para prueba

def main():
    print("BOT INICIADO")

    while True:
        revisar_partidos()
        time.sleep(60)

if __name__ == "__main__":
    main()
