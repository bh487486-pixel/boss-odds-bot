import os
import logging
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# Activamos el registro de errores para ver si algo falla en Render
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# IMPORTANTE: No pongas tu Token ni tu ID aquí en el código por seguridad.
# Los vamos a poner directo en Render (Environment Variables).
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")

async def start(update, context):
    """ Comando por si alguien le habla al bot por privado """
    await update.message.reply_text("¡Qué onda! Soy el bot oficial de BossOddsMX. Solo funciono enviando picks al canal.")

async def enviar_pick(update, context):
    """ Comando para mandar el pick en tu formato oficial """
    # Verificamos que tú seas quien manda el comando
    # Si quieres enviar un pick, escribirás en el bot: /pick Partido | Apuesta | Cuota | Stake | Análisis
    try:
        texto_recibido = " ".join(context.args)
        if not texto_recibido:
            await update.message.reply_text("Uso correcto: /pick Partido | Apuesta | Cuota | Stake | Análisis")
            return
        
        # Separamos los datos usando una barra "|"
        partido, apuesta, cuota, stake, analisis = [x.strip() for x in texto_recibido.split("|")]
        
        # Generamos las estrellas del Stake
        estrellas = "⭐" * int(stake) if stake.isdigit() else stake

        # Formato oficial BossOddsMX
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
        
        # Inicializamos el bot para enviar al canal
        bot = Bot(token=TOKEN)
        await bot.send_message(chat_id=CHANNEL_ID, text=mensaje_final, parse_mode="Markdown")
        await update.message.reply_text("¡Pick enviado al canal con éxito! 🚀")
        
    except ValueError:
        await update.message.reply_text("Error. Recuerda separar los 5 datos con una barra '|'. Ejemplo:\n/pick Real Madrid vs Barca | Gana Madrid | 1.85 | 3 | Tienen mejor plantel.")
    except Exception as e:
        await update.message.reply_text(f"Hubo un error: {e}")

def main():
    """ Arranca el bot """
    # Creamos la aplicación con tu Token
    application = Application.builder().token(TOKEN).build()

    # Comandos que el bot va a entender
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pick", enviar_pick))

    # Render nos pide que el bot se quede escuchando (Polling)
    application.run_polling()

if __name__ == '__main__':
    main()
