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

    # PRUEBA DE ZONA HORARIA
    hoy = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

    logging.info(f"Fecha consultada API: {hoy}")

    params = {
        "league": league_id,
        "season": 2026,
        "date": hoy
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

        juegos = []

        for game in data.get("response", []):

            status = game.get("status", {}).get("short")

            if status != "NS":
                continue

            home = game["teams"]["home"]["name"]
            away = game["teams"]["away"]["name"]

            juegos.append(
                f"{away} vs {home}"
            )

        return juegos

    except Exception as e:
        logging.error(f"Error API: {e}")
        return []

# ==========================
# COMANDOS
# ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "👋 Bienvenido a Boss Odds MX\n\n"
        "Comandos disponibles:\n"
        "/analizar"
    )

async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    mensaje = await update.message.reply_text(
        "⏳ Analizando jornada..."
    )

    mlb = obtener_juegos(1)
    lmb = obtener_juegos(21)

    texto = "📊 JUEGOS ENCONTRADOS\n\n"

    texto += f"⚾ MLB: {len(mlb)} juegos\n"

    for juego in mlb[:10]:
        texto += f"• {juego}\n"

    texto += "\n"

    texto += f"⚾ LMB: {len(lmb)} juegos\n"

    for juego in lmb[:10]:
        texto += f"• {juego}\n"

    await mensaje.edit_text(texto)

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

    logging.info("🤖 Boss Odds iniciado")

    app.run_polling()

if __name__ == "__main__":
    main()
