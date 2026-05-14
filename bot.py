import requests
import asyncio
import time
import os
from telegram import Bot
from datetime import datetime, timezone, timedelta

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("API_KEY")

sports = [
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_epl",
    "basketball_nba",
    "baseball_mlb"
]

TOTAL_BET = 1000

sent_picks = set()

def traducir_deporte(sport):
    return {
        "soccer_mexico_ligamx": "⚽ Liga MX",
        "soccer_spain_la_liga": "⚽ LaLiga",
        "soccer_epl": "⚽ Premier League",
        "basketball_nba": "🏀 NBA",
        "baseball_mlb": "⚾ Béisbol MLB"
    }.get(sport, sport)

def convert_time(utc_time):
    dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
    return dt - timedelta(hours=6)

async def find_arbitrage():
    bot = Bot(token=TOKEN)

    for sport in sports:

        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={API_KEY}&regions=us&markets=h2h,totals"
        data = requests.get(url).json()

        if not isinstance(data, list):
            continue

        for game in data:

            game_time = convert_time(game["commence_time"])
            now = datetime.now(timezone.utc) - timedelta(hours=6)

            minutes_to_start = (game_time - now).total_seconds() / 60

            # 🔥 SOLO juegos entre 45 min y 24 horas
            if minutes_to_start < 45 or minutes_to_start > 1440:
                continue

            home = game["home_team"]
            away = game["away_team"]

            match_id = f"{home}-{away}-{game_time}"

            outcomes_by_market = {}

            for book in game["bookmakers"]:
                for market in book["markets"]:
                    key = market["key"]

                    if key not in outcomes_by_market:
                        outcomes_by_market[key] = []

                    for outcome in market["outcomes"]:
                        outcomes_by_market[key].append({
                            "name": outcome["name"],
                            "price": outcome["price"],
                            "point": outcome.get("point", ""),
                            "book": book["title"]
                        })

            best_arb = None
            best_profit = 0

            for market_key, outcomes in outcomes_by_market.items():

                if market_key == "h2h" and len(outcomes) >= 3:
                    continue

                for i in range(len(outcomes)):
                    for j in range(i+1, len(outcomes)):

                        o1 = outcomes[i]
                        o2 = outcomes[j]

                        if o1["name"] == o2["name"]:
                            continue

                        if market_key == "totals":
                            if not (("Over" in o1["name"] and "Under" in o2["name"]) or
                                    ("Under" in o1["name"] and "Over" in o2["name"])):
                                continue

                        if o1["point"] != o2["point"]:
                            continue

                        if o1["price"] < 1.20 or o2["price"] < 1.20:
                            continue

                        arb_value = (1/o1["price"]) + (1/o2["price"])
                        profit = (1 - arb_value) * 100

                        # 🔥 FILTRO PRO
                        if arb_value < 1 and 2 <= profit <= 12:

                            if profit > best_profit:
                                best_profit = profit
                                best_arb = (o1, o2)

            if best_arb and match_id not in sent_picks:

                sent_picks.add(match_id)

                o1, o2 = best_arb
                arb_value = (1/o1["price"]) + (1/o2["price"])

                stake1 = TOTAL_BET / (o1["price"] * arb_value)
                stake2 = TOTAL_BET / (o2["price"] * arb_value)
                gain = TOTAL_BET * (best_profit / 100)

                deporte = traducir_deporte(sport)

                message = f"""
🔥 BOSS ODDS MX | VIP

📊 Sistema detectó oportunidad

{deporte}

⚔️ {home} vs {away}
🕒 {game_time.strftime('%d/%m %I:%M %p')}

━━━━━━━━━━━━━━━

➡️ {o1['name']} {o1['point']}
📈 {o1['price']} | {o1['book']}
💰 ${round(stake1,2)}

➡️ {o2['name']} {o2['point']}
📈 {o2['price']} | {o2['book']}
💰 ${round(stake2,2)}

━━━━━━━━━━━━━━━
💵 Ganancia: ${round(gain,2)}
📊 ROI: {round(best_profit,2)}%

⚠️ Ejecutar rápido
"""

                await bot.send_message(chat_id=CHAT_ID, text=message)

async def main():
    while True:
        try:
            await find_arbitrage()
            print("Buscando picks...")
            await asyncio.sleep(300)
        except Exception as e:
            print("Error:", e)
            await asyncio.sleep(60)

asyncio.run(main())
import asyncio
import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

async def prueba():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": "Bot activo 🚀"
    }
    requests.post(url, data=data)

asyncio.run(prueba())
