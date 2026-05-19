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
    "baseball_mlb",
    "soccer_mexico_ligamx",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga"
]

REGIONS = ["us", "uk", "eu", "au"]
ACTIVE_REGION = None

sent_matches = set()
daily_picks = []

# ==============================
# AUTOCALIBRACIÓN DE REGIÓN
# ==============================

def detect_region():
    global ACTIVE_REGION

    for region in REGIONS:
        try:
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": region,
                    "markets": "h2h"
                },
                timeout=10
            )

            if r.status_code == 200:
                ACTIVE_REGION = region
                logging.info(f"Región detectada: {region}")
                return

        except RequestException:
            continue

    logging.critical("No se pudo detectar región válida.")
    sys.exit(1)

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
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport}/odds/",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": ACTIVE_REGION,
                "markets": market,
                "oddsFormat": "decimal"
            },
            timeout=10
        )

        if r.status_code != 200:
            return []

        data = r.json()
        return data if isinstance(data, list) else []

    except RequestException:
        return []

# ==============================
# LÓGICA TIPSTER
# ==============================

def evaluate_match(match, sport, totals=None):
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

        # FAVORITO BAJO → TOTALS
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

        # MLB → TOTALS
        elif sport == "baseball_mlb" and totals:
            for t in totals:
                if t["id"] == game_id:
                    for book in t["bookmakers"]:
                        for market in book["markets"]:
                            for o in market["outcomes"]:
                                if "Over" in o["name"]:
                                    pick = "Over carreras"
                                    odds = o["price"]
                                    prob = 0.58

        # FAVORITO SOLO SI HAY VALOR
        elif cuota_fav >= 1.70:
            pick = favorito
            odds = cuota_fav
            prob = 0.58

        if not pick or not odds:
            return None

        stake = calculate_stake(prob, odds)

        analysis = (
            f"{home} vs {away}\n"
            f"Cuota detectada: {odds}\n"
            f"Probabilidad estimada: {round(prob*100,1)}%"
        )

        return {
            "id": game_id,
            "match": f"{home} vs {away}",
            "time": format_time(match["commence_time"]),
            "pick": pick,
            "odds": odds,
            "stake": stake,
            "analysis": analysis
        }

    except Exception:
        return None

# ==============================
# TELEGRAM
# ==============================

async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception:
        pass

async def send_pick(p):
    msg = (
        f"{p['match']}\n{p['time']}\n\n"
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

        for match in h2h:
            p = evaluate_match(match, sport, totals)

            if p:
                sent_matches.add(p["id"])
                daily_picks.append(p)
                await send_pick(p)

# ==============================
# RESULTADOS
# ==============================

async def results():
    total = sum(p["stake"] for p in daily_picks)

    await send(
        f"📊 RESULTADO FINAL\n\n"
        f"Picks: {len(daily_picks)}\n"
        f"Unidades: {total}"
    )

# ==============================
# MAIN
# ==============================

async def main():
    detect_region()

    scheduler = AsyncIOScheduler(timezone=TZ)

    scheduler.add_job(scan, "cron", hour=9)
    scheduler.add_job(scan, "cron", hour=22)
    scheduler.add_job(results, "cron", hour=0)

    scheduler.start()

    await scan()

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
