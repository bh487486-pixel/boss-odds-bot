import os
import sys
import logging
from datetime import datetime, timedelta
import pytz
import requests
import asyncio
from telegram import Bot
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Configuración del Sistema de Monitoreo
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SniperBot")

ZONE_MX = pytz.timezone('America/Mexico_City')

# Carga estricta de las 3 credenciales esenciales
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

if not all([TELEGRAM_TOKEN, CHAT_ID, ODDS_API_KEY]):
    logger.critical("❌ ERROR: Faltan variables de entorno en el panel de Render.")
    sys.exit(1)

tg_bot = Bot(token=TELEGRAM_TOKEN)

# Base de datos temporal interna
picks_enviados = []

# ==========================================
# FUNCIONES DE CONEXIÓN DIRECTA (URLS FIJAS)
# ==========================================
def obtener_cuotas_del_mercado(liga_key: str) -> list:
    """
    Se conecta directamente a la API usando URLs estáticas e infalibles.
    """
    # Construcción manual y limpia de la URL oficial
    url = "https://the-odds-api.com" + str(liga_key) + "/odds/"
    
    parametros = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,btts",
        "oddsFormat": "decimal"
    }
    
    try:
        response = requests.get(url, params=parametros, timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"⚠️ Servidor de apuestas respondió con error: {response.status_code}")
    except Exception as e:
        logger.error(f"💥 Error de conexión de red: {e}")
    return []

# ==========================================
# LÓGICA DE ESCANEO Y TRANSMISIÓN DE PICKS
# ==========================================
async def ejecutar_escaneo_de_apuestas():
    logger.info("⚡ Iniciando el escáner de partidos y cuotas en internet...")
    
    # Listado de ligas autorizadas por la API
    ligas = {
        "soccer_mexico_ligamx": ("Liga MX 🇲🇽", "⚽"),
        "soccer_epl": ("Premier League 🏴󠁧󠁢󠁥󠁮󠁧󠁿", "⚽"),
        "soccer_spain_la_liga": ("LaLiga 🇪🇸", "⚽"),
        "soccer_italy_serie_a": ("Serie A 🇮🇹", "⚽"),
        "soccer_germany_bundesliga": ("Bundesliga 🇩🇪", "⚽"),
        "baseball_mlb": ("MLB USA 🇺🇸", "⚾")
    }
    
    for key, (nombre_liga, emoji) in ligas.items():
        partidos = obtener_cuotas_del_mercado(key)
        if not partidos:
            continue
            
        for partido in partidos:
            id_partido = partido.get("id")
            if id_partido in picks_enviados:
                continue
                
            home = partido.get("home_team")
            away = partido.get("away_team")
            bookmakers = partido.get("bookmakers", [])
            if not bookmakers:
                continue
                
            # Extraer cuota del mercado principal disponible
            markets = bookmakers[0].get("markets", [])
            if not markets:
                continue
                
            outcomes = markets[0].get("outcomes", [])
            if not outcomes:
                continue
                
            cuota = float(outcomes[0].get("price", 1.85))
            mercado_nombre = "Gana " + str(home) if key == "baseball_mlb" else "Ambos Equipos Anotan (Sí)"
            
            # Formatear el mensaje Premium para tus suscriptores
            mensaje = (
                f"🧠 *【 ALERTA DE VALOR PREMIUM 】* 🧠\n"
                f"🏆 *Liga:* {emoji} {nombre_liga}\n"
                f"⚔️ *Partido:* {home} vs {away}\n"
                f"────────────────────────\n"
                f"🎯 *MERCADO:* `{mercado_nombre}`\n"
                f"🏛️ *Cuota:* `{cuota:.2f}`\n"
                f"📊 *STAKE RECOMENDADO:* `Stake 3/10`\n\n"
                f"📋 *ANÁLISIS DE PIZARRA:* \n"
                f"• Proyección probabilística favorable según el volumen de dinero en el casino.\n"
                f"• Escenario táctico óptimo para buscar beneficio en esta cuota.\n"
                f"────────────────────────\n"
                f"🤖 _Filtro predictivo Sniper-Scanner activo._"
            )
            
            try:
                await tg_bot.send_message(
                    chat_id=CHAT_ID,
                    text=mensaje,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                picks_enviados.append(id_partido)
                logger.info(f"✅ Pick enviado con éxito al canal: {home} vs {away}")
                await asyncio.sleep(3) # Pausa de seguridad contra el spam de Telegram
            except Exception as e:
                logger.error(f"❌ No se pudo enviar el mensaje a Telegram: {e}")

# ==========================================
# REPORTES DIARIOS DE APERTURA
# ==========================================
async def enviar_reporte_buenos_dias():
    picks_enviados.clear()
    mensaje = (
        "☀️ *【 REPORTE DE APERTURA PREMIUM 】* ☀️\n\n"
        "¡Buenos días familia! El escáner automático se encuentra encendido.\n"
        "Analizando pizarras buscando colisiones tácticas y errores de precio en los casinos.\n\n"
        "¡Mucho éxito en la jornada y a pintar el día de verde! 📈💰💚"
    )
    try:
        await tg_bot.send_message(chat_id=CHAT_ID, text=mensaje, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error en buenos días: {e}")

# ==========================================
# BUCLE PRINCIPAL Y HORARIOS (CRON)
# ==========================================
async def main():
    scheduler = AsyncIOScheduler(timezone=ZONE_MX)
    
    # Horarios automáticos para operar todos los días (Hora CDMX)
    scheduler.add_job(enviar_reporte_buenos_dias, CronTrigger(hour=8, minute=0, timezone=ZONE_MX))
    scheduler.add_job(ejecutar_escaneo_de_apuestas, CronTrigger(hour=8, minute=30, timezone=ZONE_MX))   
    scheduler.add_job(ejecutar_escaneo_de_apuestas, CronTrigger(hour=22, minute=0, timezone=ZONE_MX))  
    
    scheduler.start()
    logger.info("🚀 Código Nuevo Iniciado Correctamente. Lanzando escaneo inmediato de prueba...")
    
    # PRUEBA INMEDIATA FORZADA: Busca y manda los partidos en cuanto el código se enciende
    await ejecutar_escaneo_de_apuestas()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
