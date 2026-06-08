import os
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# ==========================
# CONFIGURACIÓN
# ==========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise ValueError("Falta TELEGRAM_TOKEN en Render")

# ==========================
# COMANDOS
# ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = (
        "👋 Bienvenido a Boss Odds MX\n\n"
        "Comandos disponibles:\n\n"
        "/analizar - Analiza MLB y LMB del día"
    )

    await update.message.reply_text(mensaje)


async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⏳ Analizando MLB y LMB...\n\n"
        "Esta es la V1 de prueba."
    )

# ==========================
# MAIN
# ==========================

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analizar", analizar))

    logger.info("🤖 Boss Odds Bot iniciado")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
