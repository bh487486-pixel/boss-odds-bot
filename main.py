import os
import asyncio
import logging
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Registro de errores
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Qué onda! Soy el bot oficial de BossOddsMX. Solo funciono enviando picks al canal.")

async def enviar_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        texto_recibido = " ".join(context.args)
        if not texto_recibido:
            await update.message.reply_text("Uso correcto: /pick Partido | Apuesta | Cuota | Stake | Análisis")
            return
        
        # Separamos los datos
        partido, apuesta, cuota, stake, analisis = [x.strip() for x in texto_recibido.split("|")]
        
        # Estrellas de stake
        estrellas = "⭐" * int(stake) if stake.isdigit() else stake

        # Formato oficial
        mensaje_final = (
            f"🔥 **BossOddsMX – Pick del Día**\n\n"
            f"Deporte: ⚽ Fútbol\n"
            f"Partido: {partido}\n"
            f"Pick: {apuesta}\n"
            f"Cuota: {cuota}\n"
            f"Stake: {estrellas}\n\n"
            f"📊 **Análisis:**\n"
            f"{analisis}\n\n"
            f"¡Vamos con todo! 💰"
        )
        
        bot = Bot(token=TOKEN)
        await bot.send_message(chat_id=CHANNEL_ID, text=mensaje_final, parse_mode="Markdown")
        await update.message.reply_text("¡Pick enviado al canal con éxito! 🚀")
        
    except ValueError:
        await update.message.reply_text("Error. Recuerda separar los 5 datos con '|'. Ejemplo:\n/pick Real Madrid vs Barca | Gana Madrid | 1.85 | 3 | Tienen mejor plantel.")
    except Exception as e:
        await update.message.reply_text(f"Hubo un error: {e}")

if __name__ == '__main__':
    # Inicializamos la aplicación
    application = Application.builder().token(TOKEN).build()

    # Añadimos comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pick", enviar_pick))

    # Ejecutamos el bot de forma directa y nativa
    application.run_polling(close_loop=False)
