import os
import telebot

# Jalamos tus variables de Render
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")

# Inicializamos el bot
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "¡Qué onda! Soy el bot oficial de BossOddsMX. Solo funciono enviando picks al canal.")

@bot.message_handler(commands=['pick'])
def enviar_pick(message):
    try:
        # Obtenemos el texto después del comando /pick
        texto_recibido = message.text.replace('/pick', '').strip()
        
        if not texto_recibido:
            bot.reply_to(message, "Uso correcto:\n/pick Partido | Apuesta | Cuota | Stake | Análisis")
            return
        
        # Separamos los 5 datos por la barra |
        partido, apuesta, cuota, stake, analisis = [x.strip() for x in texto_recibido.split("|")]
        
        # Convertimos el número de stake en estrellitas
        estrellas = "⭐" * int(stake) if stake.isdigit() else stake

        # Armamos tu formato oficial
        mensaje_final = (
            f"🔥 *BossOddsMX – Pick del Día*\n\n"
            f"Deporte: ⚽ Fútbol\n"
            f"Partido: {partido}\n"
            f"Pick: {apuesta}\n"
            f"Cuota: {cuota}\n"
            f"Stake: {estrellas}\n\n"
            f"📊 *Análisis:*\n"
            f"{analisis}\n\n"
            f"¡Vamos con todo! 💰"
        )
        
        # Mandamos el mensaje directo al canal usando formato Markdown
        bot.send_message(chat_id=CHANNEL_ID, text=mensaje_final, parse_mode="Markdown")
        bot.reply_to(message, "¡Pick enviado al canal con éxito! 🚀")
        
    except ValueError:
        bot.reply_to(message, "Error. Recuerda separar los 5 datos con una barra '|'.\nEjemplo:\n/pick Real Madrid vs Barca | Gana Madrid | 1.85 | 3 | Tienen mejor plantel.")
    except Exception as e:
        bot.reply_to(message, f"Hubo un error al enviar: {e}")

if __name__ == '__main__':
    print("El bot de BossOddsMX está encendido...")
    # El bot se queda escuchando de forma simple y estable
    bot.infinity_polling()
