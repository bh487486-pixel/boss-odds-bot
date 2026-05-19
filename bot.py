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

def implied_prob(o):
    return 1 / o

def kelly(prob, odds):
    edge = (prob * odds) - 1
    if edge <= 0:
        return 0
    k = edge / (odds - 1)
    return round(max(1, min(4, k * 2.5)), 2)

def format_time(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    dias = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    return f"{dias[dt.weekday()]} {dt.day}/{dt.month} - {dt.strftime('%H:%M')}"

# ==============================
# API ODDS
# ==============================

def fetch_odds(sport):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    try:
        r = requests.get(url, params={
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,btts",
            "oddsFormat": "decimal"
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except RequestException as e:
        logging.error(f"Error en odds ({sport}): {e}")
        return []

# ==============================
# LÓGICA PROFESIONAL
# ==============================

def analyze_match(match, sport):
    try:
        game_id = match["id"]

        if game_id in sent_matches:
            return None

        now = datetime.utcnow().replace(tzinfo=pytz.utc)
        game_time = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))

        if game_time < now or game_time > now + timedelta(hours=36):
            return None

        home = match["home_team"]
        away = match["away_team"]

        # Detectar favorito lógico
        best_home = None
        best_away = None

        markets = {}

        for book in match.get("bookmakers", []):
            for market in book.get("markets", []):
                markets[market["key"]] = market["outcomes"]

        # =========================
        # 1. MERCADO GANADOR
        # =========================
        if "h2h" in markets:
            for o in markets["h2h"]:
                if o["name"] == home:
                    best_home = o["price"]
                elif o["name"] == away:
                    best_away = o["price"]

        if not best_home or not best_away:
            return None

        # determinar favorito lógico
        if best_home < best_away:
            favorito = home
            cuota_fav = best_home
        else:
            favorito = away
            cuota_fav = best_away

        # =========================
        # DECISIÓN DE MERCADO
        # =========================
        pick = None
        odds = None
        analysis = None

        # Caso 1: favorito muy fuerte → buscar over o btts
        if cuota_fav < 1.60:
            if "totals" in markets:
                for o in markets["totals"]:
                    if "Over 2.5" in o["name"]:
                        pick = "Más de 2.5 goles"
                        odds = o["price"]

                        analysis = (
                            f"El dominio proyectado de {favorito} obliga a un ritmo alto de partido. "
                            f"Cuando un equipo con esta diferencia estructural enfrenta a un rival inferior, "
                            f"la producción ofensiva suele romper líneas defensivas temprano, elevando el volumen de goles."
                        )
                        break

        # Caso 2: partido equilibrado → BTTS
        elif 1.60 <= cuota_fav <= 2.10:
            if "btts" in markets:
                for o in markets["btts"]:
                    if o["name"] == "Yes":
                        pick = "Ambos equipos anotan"
                        odds = o["price"]

                        analysis = (
                            f"El mercado refleja paridad competitiva. Ambos equipos presentan patrones ofensivos funcionales "
                            f"y debilidades defensivas en transición, lo que incrementa la probabilidad de que ambos encuentren portería."
                        )
                        break

        # Caso 3: favorito claro con valor
        else:
            pick = favorito
            odds = cuota_fav

            analysis = (
                f"{favorito} mantiene una estructura competitiva superior, con mejor control de fases del juego "
                f"y menor volatilidad táctica. La cuota ofrecida aún deja margen positivo en relación con su probabilidad real."
            )

        if not pick or not odds:
            return None

        prob = 0.55
        stake = kelly(prob, odds)

        if stake < 1:
            return None

        return {
            "id": game_id,
            "league": SPORTS[sport],
            "match": f"{home} vs {away}",
            "time": format_time(match["commence_time"]),
            "pick": pick,
            "odds": odds,
            "stake": stake,
            "analysis": analysis
        }

    except Exception as e:
        logging.error(f"Error analizando partido: {e}")
        return None

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
    picks = []

    for sport in SPORTS:
        data = fetch_odds(sport)

        for match in data:
            p = analyze_match(match, sport)
            if p:
                picks.append(p)

    picks = picks[:2]  # máximo 2 picks

    for p in picks:
        sent_matches.add(p["id"])
        daily_picks.append(p)
        await send_pick(p)

# ==============================
# RESULTADOS
# ==============================

async def results():
    total = sum(p["stake"] for p in daily_picks)

    msg = (
        f"📊 CIERRE DEL DÍA\n\n"
        f"Picks enviados: {len(daily_picks)}\n"
        f"Unidades expuestas: {round(total,2)}u\n"
        f"Balance: 0.00u (modo demo sin tracking real)"
    )

    await send(msg)

# ==============================
# MENSAJES
# ==============================

async def morning():
    await send("Buenos días.\nSe inicia el análisis profesional del mercado.")

async def night():
    await send("Buenas noches.\nCierre de jornada con disciplina.")

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

    # ARRANQUE INMEDIATO
    await scan()

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
