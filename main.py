import os
import requests
import logging

from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==========================
# CONFIG
# ==========================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BASEBALL_API_KEY")

BASE_URL = "https://v1.baseball.api-sports.io"

# ==========================
# API SPORTS
# ==========================

def obtener_juegos(league_id):

    headers = {
        "x-apisports-key": API_KEY
    }

    fecha1 = datetime.utcnow().strftime("%Y-%m-%d")
    fecha2 = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

    juegos = []

    for fecha in [fecha1, fecha2]:

        params = {
            "league": league_id,
            "season": 2026,
            "date": fecha
        }

        try:

            r = requests.get(
                f"{BASE_URL}/games",
                headers=headers,
                params=params,
                timeout=30
            )

            r.raise_for_status()

            data = r.json()

            for game in data.get("response", []):

                status = game.get("status", {}).get("short")

                if status != "NS":
                    continue

                game_id = game["id"]

                home = game["teams"]["home"]["name"]
                away = game["teams"]["away"]["name"]

                partido = f"{away} vs {home}"

                existe = False

                for j in juegos:
                    if j["game_id"] == game_id:
                        existe = True
                        break

                if not existe:

                    juegos.append({
                        "game_id": game_id,
                        "home": home,
                        "away": away,
                        "partido": partido
                    })

        except Exception as e:

            logging.error(f"Error API ({fecha}): {e}")

    return juegos


def obtener_odds(game_id):

    headers = {
        "x-apisports-key": API_KEY
    }

    params = {
        "league": 1,
        "season": 2026,
        "bookmaker": 4,
        "game": game_id
    }

    try:

        r = requests.get(
            f"{BASE_URL}/odds",
            headers=headers,
            params=params,
            timeout=30
        )

        r.raise_for_status()

        data = r.json()

        return data.get("response", [])

    except Exception as e:

        logging.error(f"Error Odds: {e}")
        return []

# ==========================
# COMANDOS
# ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "👋 Bienvenido a Boss Odds MX\n\n"
        "Comandos disponibles:\n"
        "/analizar\n"
        "/odds"
    )


async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    mensaje = await update.message.reply_text(
        "⏳ Analizando jornada..."
    )

    mlb = obtener_juegos(1)
    lmb = obtener_juegos(21)

    texto = "📊 JUEGOS ENCONTRADOS\n\n"

    texto += f"⚾ MLB ({len(mlb)})\n\n"

    for juego in mlb:

        texto += (
            f"🆔 {juego['game_id']}\n"
            f"{juego['partido']}\n\n"
        )

    texto += f"\n⚾ LMB ({len(lmb)})\n\n"

    for juego in lmb:

        texto += (
            f"🆔 {juego['game_id']}\n"
            f"{juego['partido']}\n\n"
        )

    await mensaje.edit_text(texto[:4000])


async def odds(update: Update, context: ContextTypes.DEFAULT_TYPE):

    mensaje = await update.message.reply_text(
        "⏳ Buscando cuotas..."
    )

    juegos = obtener_juegos(1)

    if not juegos:

        await mensaje.edit_text(
            "❌ No se encontraron juegos MLB."
        )
        return

    juego = juegos[0]

    odds_data = obtener_odds(
        juego["game_id"]
    )

    texto = (
        f"🔥 CUOTAS MLB\n\n"
        f"⚾ {juego['partido']}\n"
        f"🆔 {juego['game_id']}\n\n"
    )

    if not odds_data:

        texto += "❌ No se encontraron cuotas."

        await mensaje.edit_text(texto)
        return

    bookmakers = odds_data[0].get(
        "bookmakers",
        []
    )

    if not bookmakers:

        texto += "❌ Sin bookmakers."

        await mensaje.edit_text(texto)
        return

    book = bookmakers[0]

    texto += f"🏦 {book['name']}\n\n"

    for bet in book.get("bets", []):

        nombre = bet.get("name")

        if nombre not in [
            "Home/Away",
            "Over/Under",
            "Over/Under (1st 5 Innings)"
        ]:
            continue

        texto += f"📊 {nombre}\n"

        for valor in bet.get("values", []):

            texto += (
                f"{valor['value']} "
                f"@ {valor['odd']}\n"
            )

        texto += "\n"

    await mensaje.edit_text(texto[:4000])

# ==========================
# MAIN
# ==========================

def main():

    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("analizar", analizar)
    )

    app.add_handler(
        CommandHandler("odds", odds)
    )

    logging.info("🤖 Boss Odds iniciado")

    app.run_polling()


if __name__ == "__main__":
    main()
