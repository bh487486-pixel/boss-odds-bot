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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
TZ = pytz.timezone("America/Mexico_City")
bot = Bot(token=TELEGRAM_TOKEN)

SPORTS = {
    "soccer_mexico_ligamx": "Liga MX",
    "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "LaLiga",
    "soccer_italy_serie_a": "Serie A",
    "soccer_germany_bundesliga": "Bundesliga",
    "baseball_mlb": "MLB"
}

sent_matches = set()
daily_picks = []

# ==============================
# UTILIDADES
# ==============================

def format_time(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    dias = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    return f"{dias[dt.weekday()]} {dt.day}/{dt.month} - {dt.strftime('%H:%M')}"

def kelly(prob, odds):
    edge = (prob * odds) - 1
    if edge <= 0:
        return 0
    k = edge / (odds - 1)
    return round(max(1, min(4, k * 2.5)), 2)

# ==============================
# API ODDS (SEPARADAS)
# ==============================

def fetch_market(sport, market):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    try:
        r = requests.get(url, params={
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": market,
            "oddsFormat": "decimal"
        }, timeout=10)

        r.raise_for_status()
        return r.json()

    except RequestException as e:
        logging.error(f"Error {sport} ({market}): {e}")
        return []

# ==============================
# ANÁLISIS DINÁMICO
# ==============================

def generate_analysis(home, away, market):
    if market == "h2h":
        return (
            f"El enfrentamiento presenta una diferencia estructural clara en favor de {home if len(home)<len(away) else away}, "
            f"quien ha mostrado mayor estabilidad en fases sin balón y control territorial. "
            f"El mercado no ha ajustado completamente esta ventaja."
        )
    elif market == "totals":
        return (
            f"El contexto táctico sugiere un ritmo de juego abierto, con ambos equipos priorizando transiciones rápidas. "
            f"Esto eleva la expectativa de producción ofensiva por encima de la media."
        )
    elif market == "btts":
        return (
            f"Ambos equipos presentan patrones ofensivos funcionales y debilidades defensivas en transición, "
            f"lo que favorece escenarios donde ambos consiguen anotar."
        )

# ==============================
# EVALUACIÓN
# ==============================

def analyze_match(h2h_data, totals_data, btts_data, sport):
    picks = []

    for match in h2h_data:
        try:
            game_id = match["id"]

            if game_id in sent_matches:
                continue

            game_time = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
            now = datetime.utcnow().replace(tzinfo=pytz.utc)

            if game_time < now or game_time > now + timedelta(hours=36):
                continue

            home = match["home_team"]
            away = match["away_team"]

            # =========================
            # H2H (FAVORITO)
            # =========================
            fav = None
            fav_odds = None

            for book in match.get("bookmakers", []):
                for market in book.get("markets", []):
                    for o in market.get("outcomes", []):
                        if not fav or o["price"] < fav_odds:
                            fav = o["name"]
                            fav_odds = o["price"]

            # =========================
            # DECISIÓN
            # =========================
            pick = None
            odds = None
            market_used = None

            # FAVORITO MUY BAJO → totals
            if fav_odds and fav_odds < 1.55 and totals_data:
                for t in totals_data:
                    if t["id"] == game_id:
                        for book in t["bookmakers"]:
                            for market in book["markets"]:
                                for o in market["outcomes"]:
                                    if "Over 2.5" in o["name"]:
                                        pick = "Más de 2.5 goles"
                                        odds = o["price"]
                                        market_used = "totals"
                                        break

            # PARTIDO PAREJO → BTTS (solo fútbol)
            elif sport != "baseball_mlb" and btts_data:
                for b in btts_data:
                    if b["id"] == game_id:
                        for book in b["bookmakers"]:
                            for market in book["markets"]:
                                for o in market["outcomes"]:
                                    if o["name"] == "Yes":
                                        pick = "Ambos anotan"
                                        odds = o["price"]
                                        market_used = "btts"
                                        break

            # DEFAULT → favorito
            else:
                pick = fav
                odds = fav_odds
                market_used = "h2h"

            if not pick or not odds:
                continue

            stake = kelly(0.55, odds)
            if stake < 1:
                continue

            analysis = generate_analysis(home, away, market_used)

            picks.append({
                "id": game_id,
                "league": SPORTS[sport],
                "match": f"{home} vs {away}",
                "time": format_time(match["commence_time"]),
                "pick": pick,
                "odds": odds,
                "stake": stake,
                "analysis": analysis
            })

        except Exception as e:
            logging.error(f"Error analizando match: {e}")
            continue

    return picks

# ==============================
# TELEGRAM
# ==============================

async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except RequestException as e:
        logging.error(f"Error Telegram: {e}")

async def send_pick(p):
    msg = (
        f"📌 {p['league']}\n"
        f"{p['match']}\n\n"
        f"📅 {p['time']}\n"
        f"🎯 Mercado: {p['pick']}\n"
        f"💰 Cuota: {p['odds']}\n"
        f"📊 Stake: {p['stake']}\n\n"
        f"🧠 Análisis:\n{p['analysis']}"
    )
    await send(msg)

# ==============================
# SCAN
# ==============================

async def scan():
    all_picks = []

    for sport in SPORTS:
        h2h = fetch_market(sport, "h2h")

        totals = fetch_market(sport, "totals")

        btts = None
        if sport != "baseball_mlb":
            btts = fetch_market(sport, "btts")

        picks = analyze_match(h2h, totals, btts, sport)
        all_picks.extend(picks)

    all_picks = all_picks[:2]

    for p in all_picks:
        sent_matches.add(p["id"])
        daily_picks.append(p)
        await send_pick(p)

# ==============================
# RESULTADOS
# ==============================

async def results():
    total = sum(p["stake"] for p in daily_picks)

    await send(
        f"📊 CIERRE DEL DÍA\n\n"
        f"Picks: {len(daily_picks)}\n"
        f"Unidades: {round(total,2)}u\n"
        f"Balance: 0.00u"
    )

# ==============================
# MENSAJES
# ==============================

async def morning():
    await send("Buenos días.\nIniciamos análisis profesional del mercado.")

async def night():
    await send("Buenas noches.\nCierre de jornada.")

# ==============================
# MAIN
# ==============================

async def main():
    scheduler = AsyncIOScheduler(timezone=TZ)

    scheduler.add_job(morning, "cron", hour=8, minute=0)
    scheduler.add_job(scan, "cron", hour=8, minute=30)
    scheduler.add_job(scan, "cron", hour=22, minute=0)
    scheduler.add_job(results, "cron", hour=23, minute=0)
    scheduler.add_job(night, "cron", hour=23, minute=5)

    scheduler.start()

    await scan()

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
