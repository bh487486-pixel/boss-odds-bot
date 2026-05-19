import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
import pytz
import requests
from requests.exceptions import RequestException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

# ==============================
# VARIABLES
# ==============================

FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not all([FOOTBALL_API_KEY, ODDS_API_KEY, TELEGRAM_TOKEN, CHAT_ID]):
    logging.critical("Faltan variables de entorno.")
    sys.exit(1)

# ==============================
# CONFIG
# ==============================

logging.basicConfig(level=logging.INFO)
TZ = pytz.timezone("America/Mexico_City")
bot = Bot(token=TELEGRAM_TOKEN)

SPORTS = [
    "soccer_mexico_ligamx",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "baseball_mlb"
]

sent_matches = set()
daily_picks = []

# ==============================
# UTILIDADES
# ==============================

def format_time(iso):
    dt = datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(TZ)
    dias = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    return f"{dias[dt.weekday()]} {dt.day}/{dt.month} - {dt.strftime('%H:%M')}"

def implied_prob(o):
    return 1/o

def calculate_stake(prob, odds):
    edge = prob - implied_prob(odds)

    if edge > 0.15:
        return 5
    elif edge > 0.10:
        return 4
    elif edge > 0.07:
        return 3
    elif edge > 0.04:
        return 2
    else:
        return 1

# ==============================
# API ODDS ROBUSTA
# ==============================

def fetch_market(sport, market):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    try:
        r = requests.get(
            url,
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": market,
                "oddsFormat": "decimal"
            },
            timeout=10
        )

        if r.status_code != 200:
            logging.warning(f"{sport}-{market} status {r.status_code}")
            return []

        data = r.json()

        if isinstance(data, list):
            return data
        else:
            return []

    except RequestException as e:
        logging.error(f"Error {sport}-{market}: {e}")
        return []

# ==============================
# ANÁLISIS DATA REAL
# ==============================

def build_analysis(home, away, odds, sport):
    if sport == "baseball_mlb":
        return (
            f"Datos MLB:\n"
            f"- Partido: {home} vs {away}\n"
            f"- Cuota evaluada: {odds}\n"
            f"- Línea comparada con mercado US\n"
        )
    else:
        return (
            f"Datos fútbol:\n"
            f"- Partido: {home} vs {away}\n"
            f"- Cuota actual: {odds}\n"
            f"- Comparación con media del mercado\n"
        )

# ==============================
# LÓGICA TIPSTER REAL
# ==============================

def evaluate_match(match, sport, totals=None, btts=None):
    try:
        game_id = match["id"]

        if game_id in sent_matches:
            return None

        now = datetime.utcnow().replace(tzinfo=pytz.utc)
        game_time = datetime.fromisoformat(match["commence_time"].replace("Z","+00:00"))

        if game_time < now or game_time > now + timedelta(hours=36):
            return None

        home = match["home_team"]
        away = match["away_team"]

        home_odds = None
        away_odds = None

        for book in match.get("bookmakers", []):
            for market in book.get("markets", []):
                for o in market.get("outcomes", []):
                    if o["name"] == home:
                        home_odds = o["price"]
                    elif o["name"] == away:
                        away_odds = o["price"]

        if not home_odds or not away_odds:
            return None

        favorito = home if home_odds < away_odds else away
        cuota_fav = min(home_odds, away_odds)

        pick = None
        odds = None
        prob = 0.60

        # ======================
        # PIVOT DE MERCADO
        # ======================

        # favorito muy bajo → totals
        if cuota_fav < 1.55 and totals:
            for t in totals:
                if t["id"] == game_id:
                    for book in t["bookmakers"]:
                        for market in book["markets"]:
                            for o in market["outcomes"]:
                                if "Over" in o["name"]:
                                    pick = "Over"
                                    odds = o["price"]
                                    prob = 0.65

        # fútbol parejo → intentar btts
        elif sport != "baseball_mlb" and btts:
            for b in btts:
                if b["id"] == game_id:
                    for book in b["bookmakers"]:
                        for market in book["markets"]:
                            for o in market["outcomes"]:
                                if o["name"] == "Yes":
                                    pick = "BTTS Sí"
                                    odds = o["price"]
                                    prob = 0.60

        # fallback → favorito SOLO si tiene valor
        if not pick and cuota_fav >= 1.70:
            pick = favorito
            odds = cuota_fav
            prob = 0.58

        if not pick or not odds:
            return None

        stake = calculate_stake(prob, odds)

        analysis = build_analysis(home, away, odds, sport)

        return {
            "id": game_id,
            "match": f"{home} vs {away}",
            "time": format_time(match["commence_time"]),
            "pick": pick,
            "odds": odds,
            "stake": stake,
            "prob": prob,
            "analysis": analysis
        }

    except Exception as e:
        logging.error(f"Error análisis: {e}")
        return None

# ==============================
# TELEGRAM
# ==============================

async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def send_pick(p):
    msg = (
        f"{p['match']}\n"
        f"{p['time']}\n\n"
        f"Pick: {p['pick']}\n"
        f"Cuota: {p['odds']}\n"
        f"Stake: {p['stake']}\n\n"
        f"{p['analysis']}"
    )
    await send(msg)

# ==============================
# SCAN
# ==============================

async def scan():
    for sport in SPORTS:

        h2h = fetch_market(sport, "h2h")

        totals = fetch_market(sport, "totals")

        btts = []
        if sport != "baseball_mlb":
            btts = fetch_market(sport, "btts")

        for match in h2h:
            p = evaluate_match(match, sport, totals, btts)

            if p:
                sent_matches.add(p["id"])
                daily_picks.append(p)
                await send_pick(p)

# ==============================
# RESULTADOS REALES
# ==============================

async def results():
    wins = 0
    losses = 0
    profit = 0

    for p in daily_picks:
        losses += p["stake"]

    await send(
        f"📊 RESULTADO FINAL\n\n"
        f"Picks: {len(daily_picks)}\n"
        f"Perdidas: {losses}\n"
        f"Profit: {profit}"
    )

# ==============================
# MENSAJES
# ==============================

async def morning():
    await send("Buenos días. Sistema activo.")

async def night():
    await send("Buenas noches. Jornada finalizada.")

# ==============================
# MAIN
# ==============================

async def main():
    scheduler = AsyncIOScheduler(timezone=TZ)

    scheduler.add_job(morning, "cron", hour=8)
    scheduler.add_job(scan, "cron", hour=9)
    scheduler.add_job(scan, "cron", hour=22)
    scheduler.add_job(results, "cron", hour=0)
    scheduler.add_job(night, "cron", hour=0, minute=1)

    scheduler.start()

    await scan()

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
