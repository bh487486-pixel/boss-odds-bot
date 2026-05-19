import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
import pytz
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

# ==============================
# CONFIG
# ==============================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TIMEZONE = pytz.timezone("America/Mexico_City")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

if not TELEGRAM_TOKEN or not CHAT_ID or not ODDS_API_KEY or not FOOTBALL_API_KEY:
    logging.critical("Faltan variables de entorno.")
    sys.exit(1)

bot = Bot(token=TELEGRAM_TOKEN)

SPORTS = [
    "soccer_mexico_ligamx",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "baseball_mlb"
]

sent_picks = []
sleep_mode = False

# ==============================
# UTILS
# ==============================

def clean_sport_key(s):
    return s.strip().replace("/", "")

def implied_prob(odds):
    return 1 / odds

def kelly(prob, odds):
    edge = (prob * odds) - 1
    if edge <= 0:
        return 0
    k = edge / (odds - 1)
    return max(1, min(4, round(k * 4)))

# ==============================
# ODDS API (CORREGIDA)
# ==============================

def fetch_odds(sport_key):
    sport_key = clean_sport_key(sport_key)
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal"
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"Error odds: {e}")
        return []

def fetch_scores(sport_key):
    sport_key = clean_sport_key(sport_key)
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"

    params = {
        "apiKey": ODDS_API_KEY,
        "daysFrom": 1
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"Error scores: {e}")
        return []

# ==============================
# FOOTBALL API
# ==============================

def fetch_team_strength(team):
    url = "https://api-football-v1.p.rapidapi.com/v3/teams"

    headers = {
        "X-RapidAPI-Key": FOOTBALL_API_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }

    params = {"search": team}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if data["response"]:
            return 0.55
        return 0.50
    except:
        return 0.50

def calc_prob(home, away):
    h = fetch_team_strength(home)
    a = fetch_team_strength(away)
    prob = h - (a - 0.50)
    return max(0.45, min(0.65, prob))

# ==============================
# EVALUACIÓN
# ==============================

def evaluate(match, sport_key):
    picks = []

    now = datetime.now(pytz.utc)
    game_time = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))

    if not (now <= game_time <= now + timedelta(hours=36)):
        return picks

    home = match["home_team"]
    away = match["away_team"]

    prob_model = calc_prob(home, away)

    for book in match.get("bookmakers", []):
        for market in book.get("markets", []):

            if "baseball_mlb" in sport_key and market["key"] != "h2h":
                continue

            for o in market.get("outcomes", []):
                odds = o["price"]
                prob_imp = implied_prob(odds)

                if prob_model > prob_imp:
                    stake = kelly(prob_model, odds)

                    if stake >= 1:
                        picks.append({
                            "match": f"{home} vs {away}",
                            "pick": o["name"],
                            "odds": odds,
                            "stake": stake
                        })

    return picks

# ==============================
# TELEGRAM
# ==============================

async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def send_picks(picks):
    global sent_picks

    if not picks:
        await send("⚠️ No hay valor detectado.")
        return

    msg = "🔥 PICKS VIP 🔥\n\n"

    for p in picks:
        msg += (
            f"🎯 {p['match']}\n"
            f"➡️ {p['pick']}\n"
            f"Cuota: {p['odds']} | Stake: {p['stake']}\n\n"
        )

    msg += "Disciplina > suerte."

    sent_picks.extend(picks)
    await send(msg)

async def morning():
    await send("🔥 Buenos días.\nHoy se gana con método.")

# ==============================
# SCAN
# ==============================

async def scan():
    global sleep_mode

    if sleep_mode:
        return

    all_picks = []

    for sport in SPORTS:
        odds = fetch_odds(sport)

        for match in odds:
            all_picks.extend(evaluate(match, sport))

    await send_picks(all_picks)

# ==============================
# RESULTADOS
# ==============================

async def results():
    global sent_picks

    wins = 0
    losses = 0

    for sport in SPORTS:
        scores = fetch_scores(sport)

        for game in scores:
            for pick in sent_picks:
                if pick["match"] in f"{game['home_team']} vs {game['away_team']}":
                    if game.get("completed"):
                        winner = game.get("winner", "")
                        if pick["pick"] == winner:
                            wins += pick["stake"]
                        else:
                            losses += pick["stake"]

    balance = wins - losses

    msg = (
        f"📊 RESULTADOS\n\n"
        f"Ganadas: {wins}u\n"
        f"Perdidas: {losses}u\n"
        f"Balance: {balance}u"
    )

    sent_picks = []
    await send(msg)

# ==============================
# SUEÑO
# ==============================

async def sleep_on():
    global sleep_mode
    sleep_mode = True

async def sleep_off():
    global sleep_mode
    sleep_mode = False

# ==============================
# MAIN
# ==============================

async def main():
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    scheduler.add_job(morning, "cron", hour=8, minute=0)
    scheduler.add_job(scan, "cron", hour=8, minute=30)
    scheduler.add_job(scan, "cron", hour=22, minute=0)
    scheduler.add_job(results, "cron", hour=23, minute=0)
    scheduler.add_job(sleep_on, "cron", hour=23, minute=5)
    scheduler.add_job(sleep_off, "cron", hour=7, minute=59)

    scheduler.start()

    # 🔥 TEST ARRANQUE
    await scan()

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
