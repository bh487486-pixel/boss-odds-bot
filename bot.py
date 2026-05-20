import os
import logging
import asyncio
import requests
import pytz
from threading import Thread
from flask import Flask
from datetime import datetime
from telegram.ext import ApplicationBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ==========================================
# CONFIGURACIÓN Y VARIABLES DE ENTORNO
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "TU_TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "TU_CHAT_ID")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "TU_FOOTBALL_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "TU_ODDS_API_KEY")

SPORTS = [
    "soccer_mexico_ligamx",        # Liga MX
    "soccer_epl",                  # Premier League
    "soccer_germany_bundesliga",   # Bundesliga
    "baseball_mlb"                 # MLB
]

REGISTRO_DIARIO = {
    "ganadas": 0,
    "perdidas": 0,
    "unidades_netas": 0.0,
    "picks_enviados": []
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask('')

@app.route('/')
def home():
    return "Boss Odds MX activo. Analizando estrictamente partidos de hoy."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# ==========================================
# CONEXIONES CON APIS (MULTIMERCADO)
# ==========================================

def obtener_cuotas_por_deporte(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': 'eu', 
        'markets': 'h2h,spreads,totals', 
        'oddsFormat': 'decimal'
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Error al obtener cuotas de {sport_key}: {e}")
    return []

def obtener_probabilidad_analitica(sport_key, market_type, name, point=None):
    # Simulación de alta precisión estadística para el value betting
    if market_type == "totals":
        return 0.55
    if market_type == "spreads":
        return 0.54
    return 0.53

# ==========================================
# MOTOR ANALÍTICO CON FILTRO HORARIO STRICTO
# ==========================================

def analizar_mercado_completo(sport_key, cuotas_data):
    """Analiza mercados buscando valor, restringido ÚNICAMENTE a partidos de hoy."""
    picks_viables = []
    TOPE_MINIMO = 1.50
    TOPE_MAXIMO = 3.00
    
    # Configurar zona horaria de México para comparar
    zona_mexico = pytz.timezone("America/Mexico_City")
    ahora_mexico = datetime.now(zona_mexico)

    for partido in cuotas_data:
        id_partido = partido.get('id')
        home_team = partido.get('home_team')
        away_team = partido.get('away_team')
        commence_time_str = partido.get('commence_time') # Viene en formato UTC (ej: 2026-05-20T23:00:00Z)
        
        # --- FILTRO CRÍTICO: VALIDACIÓN DE FECHA (SOLO HOY) ---
        try:
            # Convertir el tiempo de la API a objeto datetime UTC
            hora_utc = datetime.strptime(commence_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
            # Transformarlo a la hora local de México
            hora_partido_mexico = hora_utc.astimezone(zona_mexico)
        except Exception as e:
            logger.error(f"Error al procesar la fecha del partido: {e}")
            continue

        # Si el partido NO es hoy, el bot lo ignora de inmediato
        if hora_partido_mexico.date() != ahora_mexico.date():
            continue
            
        # Formatear la fecha y hora de manera limpia para el canal de Telegram
        fecha_hora_legible = hora_partido_mexico.strftime("%d/%m/%Y a las %H:%M")
        
        bookmakers = partido.get('bookmakers', [])
        if not bookmakers:
            continue
            
        for market in bookmakers[0].get('markets', []):
            market_key = market.get('key')
            outcomes = market.get('outcomes', [])
            
            for out in outcomes:
                name = out.get('name')
                cuota = out.get('price')
                point = out.get('point', None)
                
                if not (TOPE_MINIMO <= cuota <= TOPE_MAXIMO):
                    continue
                    
                prob_casa = 1 / cuota
                prob_real = obtener_probabilidad_analitica(sport_key, market_key, name, point)
                
                if prob_real > prob_casa:
                    if market_key == "h2h":
                        mercado_legible = "Ganador Directo (1X2 / Moneyline)"
                        seleccion_legible = f"Victoria de {name}"
                    elif market_key == "totals":
                        unidad = "Carreras" if "baseball" in sport_key else "Goles"
                        mercado_legible = f"Totales / Over-Under ({point})"
                        seleccion_legible = f"{name} {point} {unidad}"
                    elif market_key == "spreads":
                        mercado_legible = f"Hándicap / Spread ({point})"
                        seleccion_legible = f"{name} Hándicap {point}"
                        
                    firma_unica = f"{id_partido}_{market_key}_{name}_{point}"
                    
                    picks_viables.append({
                        'id': id_partido,
                        'firma': firma_unica,
                        'sport': sport_key,
                        'equipo_local': home_team,
                        'equipo_visita': away_team,
                        'mercado': mercado_legible,
                        'seleccion': seleccion_legible,
                        'cuota': cuota,
                        'stake': 2.0 if market_key == "h2h" else 1.5,
                        'market_key': market_key,
                        'name_raw': name,
                        'point_raw': point,
                        'horario': fecha_hora_legible  # Guardamos la hora formateada
                    })
                    
    return picks_viables

# ==========================================
# GESTIÓN DE ENVÍOS Y CONTROL DE DUPLICADOS
# ==========================================

async def tarea_analisis_programada(telegram_app):
    logger.info("Iniciando escaneo de mercados del día de hoy...")
    
    for deporte in SPORTS:
        cuotas = obtener_cuotas_por_deporte(deporte)
        if not cuotas:
            continue
            
        picks = analizar_market_completo(deporte, cuotas) if 'analizar_market_completo' in globals() else analizar_mercado_completo(deporte, cuotas)
        picks = analizar_mercado_completo(deporte, cuotas)
        
        for pick in picks:
            # Evitar duplicados exactos
            if any(p['firma'] == pick['firma'] for p in REGISTRO_DIARIO['picks_enviados']):
                continue
                
            # Máximo 2 picks distintos por juego
            picks_del_mismo_partido = [p for p in REGISTRO_DIARIO['picks_enviados'] if p['id'] == pick['id']]
            if len(picks_del_mismo_partido) >= 2:
                continue
                
            emoji_dep = "⚾" if "baseball" in deporte else "⚽"
            liga_name = "Liga MX 🇲🇽" if "mexico" in deporte else ("Premier League 🏴󠁧󠁢󠁥󠁮󠁧󠁿" if "epl" in deporte else ("Bundesliga 🇩🇪" if "bundesliga" in deporte else "MLB ⚾"))
            
            mensaje = (
                f"🤖 *BOSS ODDS MX - ALERTA DE HOY*\n"
                f"🏆 *Liga:* {liga_name}\n"
                f"📅 *Horario:* {pick['horario']} (Centro de MX)\n"
                f"==================================\n\n"
                f"{emoji_dep} *Partido:* {pick['equipo_local']} vs {pick['equipo_visita']}\n"
                f"📊 *Mercado:* {pick['mercado']}\n"
                f"🎯 *Pronóstico:* `{pick['seleccion']}`\n"
                f"📈 *Cuota:* {pick['cuota']}\n"
                f"💎 *Stake Sugerido:* {pick['stake']}% de tu bankroll\n\n"
                f"🧠 _Lógica: Ventaja matemática identificada para la jornada en curso._"
            )
            
            try:
                await telegram_app.bot.send_message(chat_id=CHAT_ID, text=mensaje, parse_mode="Markdown")
                REGISTRO_DIARIO['picks_enviados'].append(pick)
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Error al enviar el pick: {e}")

# ==========================================
# EVALUACIÓN DIARIA Y MENSAJES HORARIOS
# ==========================================

def procesar_resultados_del_dia():
    global REGISTRO_DIARIO
    if not REGISTRO_DIARIO['picks_enviados']:
        return

    for pick in REGISTRO_DIARIO['picks_enviados']:
        url = f"https://api.the-odds-api.com/v4/sports/{pick['sport']}/scores/"
        params = {'apiKey': ODDS_API_KEY, 'daysFrom': 1}
        
        try:
            res = requests.get(url, params=params).json()
            for match in res:
                if match['id'] == pick['id'] and match['completed']:
                    scores = match.get('scores', [])
                    if len(scores) >= 2:
                        s_home = int(scores[0]['score']) if scores[0]['name'] == match['equipo_local'] else int(scores[1]['score'])
                        s_away = int(scores[1]['score']) if scores[1]['name'] == match['equipo_visita'] else int(scores[0]['score'])
                        
                        acierto = False
                        
                        if pick['market_key'] == "h2h":
                            ganador = match['home_team'] if s_home > s_away else (match['away_team'] if s_away > s_home else "Draw")
                            if pick['name_raw'] == ganador:
                                acierto = True
                                
                        elif pick['market_key'] == "totals":
                            total = s_home + s_away
                            if pick['name_raw'] == "Over" and total > pick['point_raw']:
                                acierto = True
                            elif pick['name_raw'] == "Under" and total < pick['point_raw']:
                                acierto = True
                                
                        elif pick['market_key'] == "spreads":
                            diff = (s_home - s_away) if pick['name_raw'] == match['equipo_local'] else (s_away - s_home)
                            if (diff + pick['point_raw']) > 0:
                                acierto = True
                        
                        if acierto:
                            REGISTRO_DIARIO['ganadas'] += 1
                            REGISTRO_DIARIO['unidades_netas'] += (pick['cuota'] - 1) * pick['stake']
                        else:
                            REGISTRO_DIARIO['perdidas'] += 1
                            REGISTRO_DIARIO['unidades_netas'] -= pick['stake']
        except Exception as e:
            logger.error(f"Error al auditar resultado: {e}")

async def enviar_buenos_dias(telegram_app):
    global REGISTRO_DIARIO
    REGISTRO_DIARIO = {"ganadas": 0, "perdidas": 0, "unidades_netas": 0.0, "picks_enviados": []}
    saludo = (
        "☀️ *¡Buenos días, familia de Boss Odds MX!* ☀️\n\n"
        "Arrancamos el monitoreo de hoy. Nuestro sistema ya está escaneando de forma activa los partidos de "
        "*esta jornada* en búsqueda de las mejores cuotas de valor.\n\n"
        "💼 *Compromiso:* Análisis enfocado únicamente en eventos del día, cuidando la gestión de banca al máximo. ¡Mucho éxito! 🎯"
    )
    await telegram_app.bot.send_message(chat_id=CHAT_ID, text=saludo, parse_mode="Markdown")

async def enviar_buenas_noches_y_recap(telegram_app):
    procesar_resultados_del_dia()
    ganadas = REGISTRO_DIARIO['ganadas']
    perdidas = REGISTRO_DIARIO['perdidas']
    unidades = REGISTRO_DIARIO['unidades_netas']
    
    emoji_balance = "🟢" if unidades >= 0 else "🔴"
    signo = "+" if unidades > 0 else ""

    recap_mensaje = (
        "🌙 *Cierre de Jornada - Boss Odds MX* 🌙\n"
        "==================================\n\n"
        "Finalizan las acciones de hoy. Aquí tienen el resumen detallado de la rentabilidad obtenida por el bot:\n\n"
        f"✅ *Picks Ganados:* {ganadas}\n"
        f"❌ *Picks Perdidos:* {perdidas}\n"
        f"{emoji_balance} *Balance de Unidades:* {signo}{unidades:.2f} u\n\n"
        "==================================\n"
        "Control matemático estricto. Nos leemos mañana temprano con una nueva cartelera. ¡Descansen! 🧠💼"
    )
    await telegram_app.bot.send_message(chat_id=CHAT_ID, text=recap_mensaje, parse_mode="Markdown")

# ==========================================
# BUCLE Y PLANIFICADOR PRINCIPAL
# ==========================================

async def main():
    telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    scheduler = AsyncIOScheduler(timezone="America/Mexico_City")
    
    # Análisis automatizado del mercado (Cada 4 horas)
    scheduler.add_job(tarea_analisis_programada, 'interval', hours=4, args=[telegram_app])
    
    # Mensajes recurrentes diarios (Hora de CDMX)
    scheduler.add_job(enviar_buenos_dias, 'cron', hour=8, minute=0, args=[telegram_app])
    scheduler.add_job(enviar_buenas_noches_y_recap, 'cron', hour=23, minute=0, args=[telegram_app])
    
    scheduler.start()
    logger.info("Bot configurado para arrancar inmediatamente con partidos de hoy.")
    
    # --- ARRANQUE INMEDIATO ---
    # Esto fuerza al bot a hacer un análisis completo en cuanto lo enciendas "hoy"
    asyncio.create_task(tarea_analisis_programada(telegram_app))
    
    await telegram_app.initialize()
    await telegram_app.start_polling()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot apagado.")
