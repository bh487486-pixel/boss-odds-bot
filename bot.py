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

TZ = pytz.timezone("America/Mexico_City")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

if not TELEGRAM_TOKEN or not CHAT_ID or not ODDS_API_KEY:
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
# UTILIDADES
# ==============================

def clean_sport_key(key):
    return key.strip().replace("/", "")

def implied_prob(odds):
    return 1 / odds

def kelly(prob, odds):
    edge = (prob * odds) - 1
    if edge <= 0:
        return 0
    k = edge / (odds - 1)
    stake = max(1, min(4, round(k * 3, 2)))
    return stake

# ==============================
# API ODDS (FORMATO REQUERIDO)
# ==============================

def fetch_odds(sport_key):
    sport_key = clean_sport_key(sport_key)
    url = f"https://the-odds-api.com/{sport_key}/odds/"

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h",
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
# MODELO TIPSTER (REALISTA)
# =================
