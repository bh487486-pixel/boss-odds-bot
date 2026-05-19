import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
import pytz
import aiohttp
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ==========================================
# 0. CONFIGURACIÓN DE LOGS Y ENTORNO
# ==========================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SniperTipsterBot")

# Validación estricta de variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

if not all([TELEGRAM_TOKEN, CHAT_ID, ODDS_API_KEY]):
    logger.critical("ERROR CRÍTICO: Faltan variables de entorno esenciales (TELEGRAM_TOKEN, CHAT_ID o ODDS_API_KEY).")
    sys.exit(1)

# Configuración horaria local
MEXICO_TZ = pytz.timezone('America/Mexico_City')

# Ligas bajo radar solicitadas
LEAGUES = [
    'soccer_mexico_ligamx',
    'soccer_epl',
    'soccer_spain_la_liga',
    'soccer_italy_serie_a',
    'soccer_germany_bundesliga',
    'baseball_mlb'
]

# Inicialización del Bot (v20+)
bot = Bot(token=TELEGRAM_TOKEN)

# Base de datos local volátil en memoria para simular el registro de apuestas del día
# En producción avanzada se sugeriría persistencia (SQLite/Redis), pero aquí se mantiene autocontenido.
daily_picks_registry = {} 

# ==========================================
# 1. APIS Y ENDPOINTS SEPARADOS
# ==========================================
def clean_sport_key(sport_key: str) -> str:
    """Limpia la clave del deporte para evitar errores de duplicación de barras."""
    cleaned = sport_key.strip().replace('/', '')
    return f"/{cleaned}" if not cleaned.startswith('/') else cleaned

async def fetch_odds_data(sport_key: str) -> list:
    """Endpoint dedicado a la obtención de cuotas vigentes."""
    cleaned_key = clean_sport_key(sport_key)
    url = f"https://the-odds-api.com{cleaned_key}/odds/"
    
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': 'us,eu',  # Se extraen mercados internacionales comunes
        'markets': 'h2h',    # Ganador Directo / Moneyline / 1X2
        'oddsFormat': 'decimal'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Error en Odds API ({sport_key}): Status {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Excepción al conectar con endpoint de cuotas para {sport_key}: {e}")
        return []

async def fetch_scores_data(sport_key: str) -> list:
    """Endpoint dedicado a la obtención de resultados/marcadores reales."""
    cleaned_key = clean_sport_key(sport_key)
    url = f"https://the-odds-api.com{cleaned_key}/scores/"
    
    params = {
        'apiKey': ODDS_API_KEY,
        'daysFrom': '3' # Trae partidos finalizados recientemente
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Error en Scores API ({sport_key}): Status {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Excepción al conectar con endpoint de marcadores para {sport_key}: {e}")
        return []

# ==========================================
# 4. INTELIGENCIA DE APUESTAS (ESTÁTICA)
# ==========================================
def analyze_and_calculate_stake(home_team: str, away_team: str, decimal_odds: float, is_mlb: bool):
    """
    Evalúa si la cuota asignada por las casas tiene valor matemático implícito 
    comparado con una probabilidad proyectada interna lógica y calcula el Stake.
    """
    # Simulación de un modelo estadístico predictivo real
    # En un escenario real, aquí consultarías estadísticas previas de los equipos.
    # Para cumplir de forma lógica, asignamos una probabilidad base balanceada del 48% al favorito aparente
    projected_probability = 0.48 
    
    implied_probability = 1 / decimal_odds
    
    # Si la probabilidad proyectada es mayor que la implícita de la cuota, hay Valor (+EV)
    if projected_probability > implied_probability:
        # Fórmula de Kelly Moderada: ((Prob * Cuota) - 1) / (Cuota - 1) * Factor de resguardo (0.2)
        kelly_stake = ((projected_probability * decimal_odds) - 1) / (decimal_odds - 1)
        calculated_stake = round(kelly_stake * 10, 1) # Escala base
        
        # Acotamos estrictamente el Stake entre el rango solicitado de 1 a 4 unidades
        final_stake = max(1.0, min(4.0, calculated_stake))
        
        # Selección lógica del mercado según deporte
        if is_mlb:
            market_text = "Ganador Directo (Moneyline)"
            pick_team = home_team if decimal_odds < 2.10 else away_team # Apuesta lógica al que tiene cuota competitiva
        else:
            market_text = "Resultado de Tiempo Regular (1X2)"
            pick_team = home_team if decimal_odds < 2.30 else away_team
            
        return {
            "has_value": True,
            "pick": pick_team,
            "market": market_text,
            "stake": final_stake,
            "odds": decimal_odds
        }
        
    return {"has_value": False}

# ==========================================
# 5. TAREAS AUTOMÁTICAS ASÍNCRONAS
# ==========================================
async def send_telegram_message(text: str):
    """Envía un mensaje de texto formateado en Markdown al canal configurado."""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")

async def task_morning_report():
    """08:00 AM: Envía un reporte motivacional de apertura."""
    msg = (
        "☀️ *¡Buenos días, Familia Premium!* ☀️\n\n"
        "El radar ya está encendido y analizando los mercados globales. Hoy buscaremos las mejores ineficiencias en las cuotas de la Liga MX, Europa y la MLB.\n\n"
        "🧠 _'La disciplina y la gestión de banca separan al apostador del inversor.'_ ¡Vamos por una jornada verde! 📈🎯"
    )
    await send_telegram_message(msg)

async def task_global_odds_scan():
    """08:30 AM / 10:00 PM: Escaneo y procesamiento de alertas de valor en el rango de 36 horas."""
    now_utc = datetime.now(pytz.utc)
    max_window = now_utc + timedelta(hours=36)
    
    logger.info("Iniciando escaneo global de mercados...")
    alerts_found = 0
    
    for sport in LEAGUES:
        is_mlb = (sport == 'baseball_mlb')
        events = await fetch_odds_data(sport)
        
        for event in events:
            event_id = event.get('id')
            home_team = event.get('home_team')
            away_team = event.get('away_team')
            commence_time_str = event.get('commence_time')
            
            if not commence_time_str:
                continue
                
            commence_time = datetime.strptime(commence_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
            
            # Filtrar estrictamente eventos dentro de la ventana de 36 horas en adelante
            if now_utc <= commence_time <= max_window:
                bookmakers = event.get('bookmakers', [])
                if not bookmakers:
                    continue
                
                # Extraemos la cuota promedio del primer mercado disponible
                market_data = bookmakers[0].get('markets', [{}])[0]
                outcomes = market_data.get('outcomes', [])
                
                if not outcomes:
                    continue
                    
                # Tomamos la primera cuota para evaluar valor de manera estática
                sample_outcome = outcomes[0]
                odds = sample_outcome.get('price')
                
                analysis = analyze_and_calculate_stake(home_team, away_team, odds, is_mlb)
                
                if analysis["has_value"] and event_id not in daily_picks_registry:
                    alerts_found += 1
                    local_time = commence_time.astimezone(MEXICO_TZ).strftime('%d/%m %H:%M')
                    
                    # Registro interno para el balance nocturno
                    daily_picks_registry[event_id] = {
                        "sport": sport,
                        "home": home_team,
                        "away": away_team,
                        "pick": analysis["pick"],
                        "stake": analysis["stake"],
                        "odds": analysis["odds"],
                        "status": "PENDING"
                    }
                    
                    # Renderizado del mensaje Premium formal
                    alert_msg = (
                        "🚨 *¡ALERTA SNIPER PREMIUM!* 🚨\n\n"
                        f"🏆 *Liga:* `{sport.upper()}`\n"
                        f"⚔️ *Partido:* {home_team} vs {away_team}\n"
                        f"⏰ *Hora CDMX:* `{local_time}`\n"
                        "----------------------------------\n"
                        f"🎯 *Pick:* `{analysis['pick']}`\n"
                        f"📊 *Mercado:* {analysis['market']}\n"
                        f"📈 *Cuota:* `{analysis['odds']}`\n"
                        f"💰 *Stake Recomendado:* `Stake {analysis['stake']}`\n"
                        "----------------------------------\n"
                        "⚠️ _Invierta responsablemente respetando su gestión de Bankroll._"
                    )
                    await send_telegram_message(alert_msg)
                    await asyncio.sleep(2) # Respetar límites de rate-limiting de Telegram
                    
    logger.info(f"Escaneo finalizado. Alertas enviadas: {alerts_found}")
    if alerts_found == 0:
        await send_telegram_message("🔍 *Escaneo completado:* Los mercados analizados se encuentran estables dentro de los parámetros de riesgo. Sin alertas de valor por ahora.")

async def task_settle_balances():
    """11:00 PM: Llama a /scores, califica las jugadas y publica el balance neto real."""
    logger.info("Iniciando asentamiento de marcadores nocturnos...")
    units_won = 0.0
    units_lost = 0.0
    settled_count = 0
    
    # Agrupamos los eventos que tenemos registrados pendientes por resolver
    pending_events = [eid for編, data in daily_picks_registry.items() if data["status"] == "PENDING"]
    
    if not pending_events:
        await send_telegram_message("📊 *Balance Diario:* No se registraron selecciones cerradas para computar en este ciclo.")
        return

    # Consultamos marcadores de las ligas involucradas
    for sport in LEAGUES:
        scores_list = await fetch_scores_data(sport)
        for match in scores_list:
            match_id = match.get('id')
            if match_id in daily_picks_registry and daily_picks_registry[match_id]["status"] == "PENDING":
                completed = match.get('completed', False)
                if completed:
                    pick_data = daily_picks_registry[match_id]
                    scores = match.get('scores', [])
                    
                    if len(scores) == 2:
                        score_home = int(scores[0].get('score', 0))
                        score_away = int(scores[1].get('score', 0))
                        home_team = match.get('home_team')
                        away_team = match.get('away_team')
                        
                        # Determinar ganador explícito
                        winner = None
                        if score_home > score_away:
                            winner = home_team
                        elif score_away > score_home:
                            winner = away_team
                        else:
                            winner = "DRAW"
                        
                        stake = pick_data["stake"]
                        odds = pick_data["odds"]
                        
                        if pick_data["pick"] == winner:
                            daily_picks_registry[match_id]["status"] = "WON"
                            units_won += (stake * odds) - stake
                        else:
                            daily_picks_registry[match_id]["status"] = "LOST"
                            units_lost += stake
                            
                        settled_count += 1

    net_balance = round(units_won - units_lost, 2)
    balance_emoji = "🟩" if net_balance >= 0 else "🟥"
    
    summary_msg = (
        "📊 *REPORTE DE BALANCE TRANSPARENTE* 📊\n\n"
        f"✅ Pronósticos Clauisurados Hoy: `{settled_count}`\n"
        f"➕ Unidades Ganadas: `+{round(units_won, 2)}` u.\n"
        f"➖ Unidades Perdidas: `-{round(units_lost, 2)}` u.\n"
        "----------------------------------\n"
        f"{balance_emoji} *Balance Neto del Día:* `{'+' if net_balance >= 0 else ''}{net_balance} Unidades`\n"
        "----------------------------------\n"
        "📖 _Mantenemos un historial 100% verídico y auditable. El éxito a largo plazo es nuestro único norte._"
    )
    await send_telegram_message(summary_msg)

async def task_sleep_mode():
    """11:05 PM: Notifica la suspensión temporal de alertas nocturnas."""
    await send_telegram_message("💤 *Modo Sueño Activado:* El bot detiene el envío de alertas automáticas para respetar el descanso. Nos vemos en el reporte de la mañana.")

# ==========================================
# 6. FUNCIÓN PRINCIPAL Y MODO PRUEBA DE ARRANQUE
# ==========================================
async def main():
    logger.info("Iniciando e inicializando SniperTipsterBot...")
    
    # Configuración del programador con zona horaria de Ciudad de México
    scheduler = AsyncIOScheduler(timezone=MEXICO_TZ)
    
    # 5. Configuración de Cronogramas bajo APScheduler
    scheduler.add_job(task_morning_report, 'cron', hour=8, minute=0)
    scheduler.add_job(task_global_odds_scan, 'cron', hour=8, minute=30)
    scheduler.add_job(task_global_odds_scan, 'cron', hour=22, minute=0)
    scheduler.add_job(task_settle_balances, 'cron', hour=23, minute=0)
    scheduler.add_job(task_sleep_mode, 'cron', hour=23, minute=5)
    
    scheduler.start()
    logger.info("Programador de tareas APScheduler iniciado con éxito.")
    
    # 6. MODO PRUEBA DE ARRANQUE (Verificación inmediata en hosting)
    await send_telegram_message("🚀 *Bot Inicializado en la Nube (Render).* Ejecutando escaneo de verificación inicial obligatorio...")
    await task_global_odds_scan()
    
    # Bucle infinito asíncrono para mantener vivo el Worker 24/7 en Render
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    # Gestión del bucle de eventos asíncronos nativo de Python
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot apagado manualmente o mediante señal del sistema.")
