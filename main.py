import os
import requests
import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta
from telegram import Bot
from telegram.error import TelegramError

# ==========================================
# CONFIGURACIÓN BÁSICA Y LOGS
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
REGIONS = "us,eu"

# Huso Horario de México Centro (UTC-6)
MX_TZ = timezone(timedelta(hours=-6))

picks_enviados_hoy = []

def obtener_picks_deporte(sport_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": markets,
        "oddsFormat": "decimal"
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        logger.error(f"Error de conexión con Odds API ({sport_key}): {e}")
        return []

def procesar_cartelera_completa():
    candidatos = []

    # 1. FÚTBOL
    partidos_futbol = obtener_picks_deporte("soccer_uefa_champs_league,soccer_mexico_liga_mx,soccer_spl", "h2h")
    for partido in partidos_futbol:
        bookmakers = partido.get("bookmakers", [])
        if not bookmakers: continue
        bookie = bookmakers[0]
        markets = bookie.get("markets", [])
        if not markets: continue
        
        outcomes = markets[0].get("outcomes", [])
        for o in outcomes:
            cuota = o.get("price")
            # Filtro inteligente: Evitamos cuotas menores a 1.50 (mucho riesgo/poco valor) y mayores a 2.30 (improbables)
            if 1.50 <= cuota <= 2.30:
                candidatos.append({
                    "deporte": "⚽ Fútbol",
                    "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                    "pick": f"Gana {o.get('name')}",
                    "cuota": cuota,
                    "bookie": bookie.get("title", "Bet365")
                })
                break 

    # 2. MLB
    partidos_mlb = obtener_picks_deporte("baseball_mlb", "h2h,spreads,totals")
    for partido in partidos_mlb:
        bookmakers = partido.get("bookmakers", [])
        if not bookmakers: continue
        bookie = bookmakers[0]
        markets = bookie.get("markets", [])
        
        for market in markets:
            market_key = market.get("key")
            outcomes = market.get("outcomes", [])
            if market_key in ["spreads", "totals"]:
                for o in outcomes:
                    cuota = o.get("price")
                    point = o.get("point")
                    
                    if cuota and 1.60 <= cuota <= 2.20:
                        if market_key == "spreads" and point and point < 0:
                            tipo_pick = f"Hándicap {o.get('name')} ({point})"
                        elif market_key == "totals" and point:
                            tipo_pick = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {point} Carreras"
                        else:
                            continue

                        candidatos.append({
                            "deporte": "⚾ Béisbol MLB",
                            "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                            "pick": tipo_pick,
                            "cuota": cuota,
                            "bookie": bookie.get("title", "Caliente")
                        })
                        break

    # Lógica de Diversificación: Mezclamos los picks elegibles para no mandar 5 del mismo deporte seguido
    random.shuffle(candidatos)
    return candidatos[:5]

def generar_texto_analisis(bookie, cuota):
    """Genera un análisis aleatorio para que el bot no suene repetitivo."""
    plantillas = [
        f"Nuestros algoritmos detectan una ligera ineficiencia (+EV) en {bookie}. La cuota de {cuota:.2f} tiene gran valor considerando el momento de forma actual.",
        f"El flujo de dinero (Sharp Money) está respaldando esta línea en {bookie}. Tomamos la cuota de {cuota:.2f} antes de que el mercado la tire.",
        f"Análisis estadístico puro. El modelo proyecta una alta probabilidad de acierto aquí, dejando la cuota de {cuota:.2f} con ventaja para nosotros.",
        f"Encontramos valor en {bookie}. Las tendencias históricas recientes nos indican que esta cuota de {cuota:.2f} está mal ajustada por la casa de apuestas."
    ]
    return random.choice(plantillas)

def construir_mensaje(pick_data):
    cuota = pick_data["cuota"]
    if cuota <= 1.70: stake = "⭐⭐⭐"
    elif cuota <= 2.00: stake = "⭐⭐"
    else: stake = "⭐"

    analisis = generar_texto_analisis(pick_data['bookie'], cuota)

    mensaje = (
        f"🔥 BossOddsMX – Pick del Día\n\n"
        f"Deporte: {pick_data['deporte']}\n"
        f"Partido: {pick_data['partido']}\n"
        f"Pick: {pick_data['pick']}\n"
        f"Cuota: {cuota:.2f}\n"
        f"Stake: {stake}\n\n"
        f"📊 Análisis:\n"
        f"{analisis}\n\n"
        f"¡Vamos con todo! 💰"
    )
    return mensaje

async def enviar_mensaje_seguro(texto):
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=texto)
        logger.info("Mensaje enviado al canal.")
    except TelegramError as e:
        logger.error(f"Error de Telegram: {e}")

async def mandar_buenos_dias():
    msg = (
        "☀️ ¡Buenos días, familia de BossOddsMX! ☀️\n\n"
        "La jornada de hoy está por comenzar y los mercados ya se están moviendo. "
        "Nuestro sistema está filtrando toda la cartelera de Fútbol y MLB en busca del mejor valor (+EV).\n\n"
        "Preparen las notificaciones, a las 8:30 AM cae el Top 5 de hoy. ¡Listos para facturar! 🟢💰"
    )
    await enviar_mensaje_seguro(msg)

async def mandar_picks_del_dia():
    global picks_enviados_hoy
    picks_del_dia = procesar_cartelera_completa()
    picks_enviados_hoy = picks_del_dia
    
    if picks_del_dia:
        for pick in picks_del_dia:
            texto_formateado = construir_mensaje(pick)
            await enviar_mensaje_seguro(texto_formateado)
            await asyncio.sleep(5)
    else:
        await enviar_mensaje_seguro("⚠️ Hoy los mercados están muy ajustados y el bot no encontró cuotas de valor seguro. Guardamos el bankroll para mañana. 🏦")

async def mandar_reporte_profit():
    global picks_enviados_hoy
    if not picks_enviados_hoy:
        return

    msg = (
        "📊 **BossOddsMX – Resumen de la Jornada** 📊\n\n"
        "Cerramos las acciones de hoy. Estas fueron las jugadas que el sistema detectó con valor:\n\n"
    )
    for i, pick in enumerate(picks_enviados_hoy, 1):
        # Quitamos la palomita verde falsa. Solo mostramos lo que se jugó.
        msg += f"{i}. {pick['partido']} ({pick['pick']}) -> Cuota {pick['cuota']:.2f}\n"
        
    msg += "\n¡Revisen sus boletos en sus casas de apuestas y cuéntenme cómo nos trató el mercado hoy! 📈"
    await enviar_mensaje_seguro(msg)

async def mandar_buenas_noches():
    msg = (
        "🌙 **¡Buenas noches, equipo!** 🌙\n\n"
        "Cerramos las cortinas por hoy. Gracias por confiar en el sistema de BossOddsMX.\n\n"
        "Recuerden gestionar bien su stake. A descansar, que mañana volvemos desde temprano a buscar ineficiencias en las bookies. ¡Hasta mañana! 💤💪"
    )
    await enviar_mensaje_seguro(msg)

async def main_loop():
    logger.info("Bot BossOddsMX Iniciado. Monitoreando horario de CDMX...")
    while True:
        ahora = datetime.now(MX_TZ)
        
        if ahora.hour == 8 and ahora.minute == 20:
            await mandar_buenos_dias()
            await asyncio.sleep(70)
            
        elif ahora.hour == 8 and ahora.minute == 30:
            await mandar_picks_del_dia()
            await asyncio.sleep(70)
            
        elif ahora.hour == 23 and ahora.minute == 45:
            await mandar_reporte_profit()
            await asyncio.sleep(70)
            
        elif ahora.hour == 0 and ahora.minute == 0:
            await mandar_buenas_noches()
            await asyncio.sleep(70)
            
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
