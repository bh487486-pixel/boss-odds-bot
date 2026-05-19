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
# CONFIGURACIÓN
# ==============================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TIMEZONE = pytz.timezone("America/Mexico_City")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

if not TELEGRAM_TOKEN or not CHAT_ID or not ODDS_API_KEY or not FOOTBALL_API_KEY:
    logging.critical("Faltan variables de entorno obligatorias.")
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
# UTILIDADES
# ==============================

def clean_sport_key(sport_key):
    return sport_key.strip().replace("/", "")

def implied_probability(odds):
    return 1 / odds

def kelly_stake(prob, odds):
    edge = (prob * odds) - 1
    if edge <= 0:
        return 0
    kelly = edge / (odds - 1)
    return max(1, min(4, round(kelly * 4)))

# ==============================
# API ODDS
# ==============================

def fetch_odds(sport_key):
    sport_key = clean_sport_key(sport_key)
    url = f"https://the-odds-api.com/{sport_key}/odds/"

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
    url = f"https://the-odds-api.com/{sport_key}/scores/"

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
# FOOTBALL API (INTELIGENCIA)
# ==============================

def fetch_team_form(team_name):
    url = "https://api-football-v1.p.rapidapi.com/v3/teams"

    headers = {
        "X-RapidAPI-Key": FOOTBALL_API_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }

    params = {"search": team_name}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if data["response"]:
            return 0.55  # base mejorada
        return 0.50
    except:
        return 0.50

def calculate_probability(home, away):
    home_strength = fetch_team_form(home)
    away_strength = fetch_team_form(away)

    prob = home_strength - (away_strength - 0.50)

    return max(0.45, min(0.65, prob))

# ==============================
# EVALUACIÓN
# ==============================

def evaluate_match(match, sport_key):
    picks = []

    now = datetime.now(pytz.utc)
    game_time = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))

    if not (now <= game_time <= now + timedelta(hours=36)):
        return picks

    home = match["home_team"]
    away = match["away_team"]

    try:
        prob_model = calculate_probability(home, away)

        for bookmaker in match["bookmakers"]:
            for market in bookmaker["markets"]:

                if "baseball_mlb" in sport_key and market["key"] != "h2h":
                    continue

                for outcome in market["outcomes"]:
                    odds = outcome["price"]
                    prob_implied = implied_probability(odds)

                    if prob_model > prob_implied:
                        stake = kelly_stake(prob_model, odds)

                        if stake >= 1:
                            picks.append({
                                "match": f"{home} vs {away}",
                                "pick": outcome["name"],
                                "odds": odds,
                                "stake": stake
                            })

        return picks

    except Exception as e:
        logging.error(f"Error evaluando: {e}")
        return []

# ==============================
# TELEGRAM
# ==============================

async def send_message(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

async def send_picks(picks):
    global sent_picks

    if not picks:
        await send_message("⚠️ Sin valor detectado.")
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
    await send_message(msg)

async def send_morning():
    await send_message("🔥 Nuevo día, nuevas oportunidades.\nMétodo > emoción.")

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
            picks = evaluate_match(match, sport)
            all_picks.extend(picks)

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
                    if game["completed"]:
                        winner = game.get("winner", "")
                        if pick["pick"] == winner:
                            wins += pick["stake"]
                        else:
                            losses += pick["stake"]

    balance = wins - losses

    msg = (
        "📊 RESULTADOS\n\n"
        f"Ganadas: {wins}u\n"
        f"Perdidas: {losses}u\n"
        f"Balance: {balance}u"
    )

    sent_picks = []
    await send_message(msg)

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

    scheduler.add_job(send_morning, "cron", hour=8, minute=0)
    scheduler.add_job(scan, "cron", hour=8, minute=30)
    scheduler.add_job(scan, "cron", hour=22, minute=0)
    scheduler.add_job(results, "cron", hour=23, minute=0)
    scheduler.add_job(sleep_on, "cron", hour=23, minute=5)
    scheduler.add_job(sleep_off, "cron", hour=7, minute=59)

    scheduler.start()

    # 🔥 PRUEBA INMEDIATA
    await scan()

    while True:
        await asyncio.sleep(60)

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    asyncio.run(main())
