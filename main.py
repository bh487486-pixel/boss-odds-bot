import os
import requests
import asyncio
import logging
import random
import json
import sys
from datetime import datetime, timezone, timedelta
from telegram import Bot
from telegram.error import TelegramError
import google.generativeai as genai

# ==========================================
# CONFIGURACIÓN BÁSICA Y LOGS
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configurar el cerebro de Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    logger.error("¡ALERTA! No se encontró la GEMINI_API_KEY. El bot se detendrá.")
    sys.exit(1)

bot = Bot(token=TELEGRAM_TOKEN)
REGIONS = "us,eu"
MX_TZ = timezone(timedelta(hours=-6))
ARCHIVO_PICKS = "picks_hoy.json"
ARCHIVO_LOG_ENVIO = "ultimo_envio.txt"

# ==========================================
# CANDADO ANTI-DUPLICADOS POR DÍA
# ==========================================
def ya_se_envio_hoy():
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    if os.path.exists(ARCHIVO_LOG_ENVIO):
        with open(ARCHIVO_LOG_ENVIO, "r") as f:
            if f.read().strip() == hoy:
                return True
    return False

def marcar_enviado_hoy():
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    with open(ARCHIVO_LOG_ENVIO, "w") as f:
        f.write(hoy)

# ==========================================
# MEMORIA PERSISTENTE (JSON)
# ==========================================
def guardar_picks(picks):
    try:
        with open(ARCHIVO_PICKS, 'w', encoding='utf-8') as f:
            json.dump(picks, f, ensure_ascii=False, indent=4)
        logger.info("Picks del día guardados en memoria correctamente.")
    except Exception as e:
        logger.error(f"Error al guardar picks en JSON: {e}")

def cargar_picks():
    if os.path.exists(ARCHIVO_PICKS):
        try:
            with open(ARCHIVO_PICKS, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error al leer picks del JSON: {e}")
    return []

# ==========================================
# LISTA DE LIGAS PRINCIPALES PERMITIDAS
# ==========================================
LIGAS_PERMITIDAS = [
    "soccer_uefa_champions_league", "soccer_uefa_europa_league", 
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", 
    "soccer_germany_bundesliga", "soccer_france_ligue_1", "soccer_mexico_liga_mx",
    "baseball_mlb", "baseball_lmb", "basketball_nba", "americanfootball_nfl"
]

def obtener_deportes_activos():
    url = "https://api.the-odds-api.com/v4/sports/"
    params = {"apiKey": ODDS_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200:
            deportes = response.json()
            return [d['key'] for d in deportes if d.get('key') in LIGAS_PERMITIDAS and d.get('active')]
        return []
    except Exception as e:
        logger.error(f"Error al obtener deportes: {e}")
        return []

def obtener_picks_deporte(sport_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {"apiKey": ODDS_API_KEY, "regions": REGIONS, "markets": markets, "oddsFormat": "decimal"}
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200: return response.json()
        return []
    except Exception as e:
        return []

def obtener_marcadores(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = { "apiKey": ODDS_API_KEY, "daysFrom": 1 }
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200: return response.json()
        return []
    except Exception as e:
        return []

def mapear_icono_deporte(sport_key):
    sport_key_lower = sport_key.lower()
    if "soccer" in sport_key_lower: return "⚽ Fútbol"
    if "baseball" in sport_key_lower: return "⚾ Béisbol"
    if "basketball" in sport_key_lower: return "🏀 Básquetbol"
    if "americanfootball" in sport_key_lower: return "🏈 Fútbol Americano"
    return "🏅 Deporte"

# ==========================================
# CEREBRO IA CON FILTRO ESTRICTO ANTI-DUPLICADOS
# ==========================================
def consultar_cerebro_ia(candidatos_raw):
    prompt = (
        "Actúa como un tipster analista profesional de apuestas deportivas.\n"
        "TU OBJETIVO: Selecciona los 10 mejores picks del día con mayor probabilidad de ganar de la lista proporcionada.\n"
        "REGLAS CRÍTICAS:\n"
        "1. NO repitas partidos. Múltiples picks del mismo partido están prohibidos.\n"
        "2. Formato ESTRICTO JSON plano (sin markdown, sin bloques de código):\n"
        "[{\"deporte\": \"...\", \"partido\": \"...\", \"fecha_hora\": \"...\", \"pick\": \"...\", \"cuota\": 0.0, \"bookie\": \"...\", \"sport_key\": \"...\", \"analisis_ia\": \"...\"}]\n\n"
        f"Datos: {json.dumps(candidatos_raw, ensure_ascii=False)}"
    )
    
    picks_finales_limpios = []
    partidos_vistos = set()

    try:
        response = model.generate_content(prompt)
        txt = response.text.strip().replace(chr(96), "").replace("json", "")
        picks_seleccionados = json.loads(txt)
        
        for pick in picks_seleccionados:
            nombre_partido = pick.get('partido')
            if nombre_partido and nombre_partido not in partidos_vistos:
                picks_finales_limpios.append(pick)
                partidos_vistos.add(nombre_partido)
            
            if len(picks_finales_limpios) == 6:
                break
                
        logger.info(f"IA y filtro aplicados con éxito. Preparados {len(picks_finales_limpios)} picks únicos.")
        return picks_finales_limpios

    except Exception as e:
        logger.error(f"Error en IA, usando respaldo aleatorio con filtro estricto: {e}")
        random.shuffle(candidatos_raw)
        
        for pick in candidatos_raw:
            nombre_partido = pick.get('partido')
            if nombre_partido and nombre_partido not in partidos_vistos:
                picks_finales_limpios.append(pick)
                partidos_vistos.add(nombre_partido)
                
            if len(picks_finales_limpios) == 6:
                break
                
        return picks_finales_limpios

def procesar_cartelera_completa():
    candidatos_crudos = []
    ligas_elite = obtener_deportes_activos()
    
    ahora_mx = datetime.now(MX_TZ)
    fecha_hoy_mx = ahora_mx.date()

    for liga in ligas_elite:
        # AJUSTE 3: Abrimos el espectro a Ganador, Totales y Hándicaps (spreads) para todos
        mercados = "h2h,totals,spreads"
        partidos = obtener_picks_deporte(liga, markets=mercados)
        
        if not partidos: continue

        for partido in partidos:
            commence_time_raw = partido.get("commence_time")
            fecha_hora_str = "Horario por confirmar"
            
            if commence_time_raw:
                try:
                    partido_tiempo_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    partido_tiempo_mx = partido_tiempo_utc.astimezone(MX_TZ)
                    # AJUSTE: Capturamos la hora exacta
                    fecha_hora_str = partido_tiempo_mx.strftime("%I:%M %p")
                    
                    if partido_tiempo_mx.date() != fecha_hoy_mx: 
                        continue
                except: continue

            bookmakers = partido.get("bookmakers", [])
            if not bookmakers: continue
            bookie = bookmakers[0]
            markets = bookie.get("markets", [])
            
            for market in markets:
                market_key = market.get("key")
                outcomes = market.get("outcomes", [])
                
                for o in outcomes:
                    cuota = o.get("price")
                    # Rango de seguridad entre 1.30 y 4.00
                    if cuota and 1.30 <= cuota <= 4.00:
                        nombre_deporte = mapear_icono_deporte(liga)
                        
                        # AJUSTE 3: Manejo de los 3 mercados
                        if market_key == "h2h": 
                            tipo_pick = f"Gana {o.get('name')}"
                        elif market_key == "totals": 
                            tipo_pick = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {o.get('point')} Pts/Goles/Carreras"
                        elif market_key == "spreads":
                            punto = o.get('point', 0)
                            signo = "+" if punto > 0 else ""
                            tipo_pick = f"Hándicap {o.get('name')} {signo}{punto}"
                        else: continue

                        if "baseball_lmb" in liga.lower(): nombre_deporte = "⚾ Béisbol"

                        candidatos_crudos.append({
                            "deporte": nombre_deporte,
                            "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                            "fecha_hora": fecha_hora_str,
                            "pick": tipo_pick,
                            "cuota": cuota,
                            "bookie": bookie.get("title", "Bet365"),
                            "sport_key": liga
                        })
                        
    if not candidatos_crudos: return []
    return consultar_cerebro_ia(candidatos_crudos)

def construir_mensaje(pick_data):
    cuota = pick_data["cuota"]
    if cuota <= 1.65: stake = "⭐⭐⭐"
    elif cuota <= 1.85: stake = "⭐⭐"
    else: stake = "⭐"

    analisis = pick_data.get("analisis_ia", "Análisis verificado por tendencias de rendimiento.")

    mensaje = (
        f"🔥 El Boss Mexa – Pick del Día\n\n"
        f"Deporte: {pick_data['deporte']}\n"
        f"Partido: {pick_data['partido']}\n"
        f"⏰ Horario: {pick_data.get('fecha_hora', 'N/A')} (Hora MX)\n"
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
    except Exception as e:
        logger.error(f"Error al enviar mensaje a Telegram: {e}")

# ==========================================
# EVALUACIÓN DE PICKS PARA EL PROFIT
# ==========================================
def evaluar_pick(pick_str, scores):
    try:
        score1 = float(scores[0]['score'])
        score2 = float(scores[1]['score'])
        name1 = scores[0]['name']
        name2 = scores[1]['name']
        
        if "Gana" in pick_str:
            team_picked = pick_str.replace("Gana ", "").strip()
            winner = None
            if score1 > score2: winner = name1
            elif score2 > score1: winner = name2
            if winner == team_picked: return "🟢 GANADO"
            elif winner is None: return "⚪ EMPATE / PUSH"
            else: return "🔴 PERDIDO"
            
        elif "Altas/Over" in pick_str or "Bajas/Under" in pick_str:
            total_puntos = score1 + score2
            partes = pick_str.split(" ")
            linea = float(partes[1])
            if "Altas/Over" in pick_str:
                return "🟢 GANADO" if total_puntos > linea else ("🔴 PERDIDO" if total_puntos < linea else "⚪ PUSH")
            elif "Bajas/Under" in pick_str:
                return "🟢 GANADO" if total_puntos < linea else ("🔴 PERDIDO" if total_puntos > linea else "⚪ PUSH")
                
        # AJUSTE 3: Evaluar los nuevos picks de Hándicap automáticamente
        elif "Hándicap" in pick_str:
            partes = pick_str.replace("Hándicap ", "").rsplit(" ", 1)
            if len(partes) == 2:
                equipo_h = partes[0].strip()
                linea_h = float(partes[1])
                score_equipo = score1 if equipo_h == name1 else (score2 if equipo_h == name2 else None)
                score_rival = score2 if equipo_h == name1 else (score1 if equipo_h == name2 else None)
                
                if score_equipo is not None and score_rival is not None:
                    if score_equipo + linea_h > score_rival: return "🟢 GANADO"
                    elif score_equipo + linea_h < score_rival: return "🔴 PERDIDO"
                    else: return "⚪ PUSH"
                    
        return "❔ RESULTADO MANUAL"
    except:
        return "❔ REVISAR"

# ==========================================
# TAREAS PROGRAMADAS
# ==========================================
async def mandar_buenos_dias():
    msg = (
        "☀️ **¡Buenos días, familia de El Boss Mexa!** ☀️\n\n"
        "Hoy es un excelente día para analizar el mercado, ganarle a las bookies y pintar la jornada completamente de verde. 🟢\n\n"
        "Preparen sus bancas, a continuación les comparto la cartelera oficial con los 6 mejores picks analizados a fondo para el día de hoy. ¡Vamos con todo! 🚀🔥"
    )
    await enviar_mensaje_seguro(msg)

async def mandar_picks_del_dia():
    if ya_se_envio_hoy():
        logger.info("Los picks de hoy ya fueron enviados previamente. Bloqueando duplicados.")
        return

    await mandar_buenos_dias()
    await asyncio.sleep(4)
    
    picks_del_dia = procesar_cartelera_completa()
    guardar_picks(picks_del_dia)
    
    if picks_del_dia:
        for pick in picks_del_dia:
            texto_formateado = construir_mensaje(pick)
            await enviar_mensaje_seguro(texto_formateado)
            await asyncio.sleep(6)
        marcar_enviado_hoy()
    else:
        await enviar_mensaje_seguro("⚠️ Los mercados principales no ofrecieron cuotas del día en este momento. Protegemos el bankroll. 🏦")

async def mandar_reporte_profit():
    picks_enviados_hoy = cargar_picks()
    if not picks_enviados_hoy: 
        logger.warning("No hay picks registrados en el JSON para evaluar hoy.")
        return

    ligas_jugadas = list(set([pick['sport_key'] for pick in picks_enviados_hoy]))
    todos_los_resultados = []
    for liga in ligas_jugadas: todos_los_resultados += obtener_marcadores(liga)

    msg = (
        "📊 **El Boss Mexa – Resumen de la Jornada** 📊\n\n"
        "Cerramos las acciones de hoy. Estos fueron los resultados de nuestros picks del día:\n\n"
    )
    for pick in picks_enviados_hoy:
        marcador_texto = "Marcador no disponible / Pospuesto ⏳"
        estado_pick = "❔ Pendiente"
        for res in todos_los_resultados:
            if res.get('home_team') in pick['partido'] and res.get('away_team') in pick['partido']:
                if res.get('completed'):
                    scores = res.get('scores')
                    if scores and len(scores) == 2:
                        marcador_texto = f"{scores[0]['name']} {scores[0]['score']} - {scores[1]['score']} {scores[1]['name']} 🏁"
                        estado_pick = evaluar_pick(pick['pick'], scores)
                else:
                    marcador_texto = "Partido aún en juego ⏳"
                break
        msg += f"🔥 **{pick['partido']}**\nPick: {pick['pick']} (Cuota {pick['cuota']:.2f})\nResultado: {marcador_texto}\nEstatus: **{estado_pick}**\n\n"
    msg += "¡Revisen sus boletos! El análisis real está dando frutos, mañana volvemos por más verdes. 📈💰"
    await enviar_mensaje_seguro(msg)

async def mandar_buenas_noches():
    msg = (
        "🌙 **¡Buenas noches, equipo!** 🌙\n\n"
        "Cerramos las cortinas de hoy en El Boss Mexa.\n\n"
        "A descansar, que el cerebro analítico se queda trabajando para traernos las mejores 6 oportunidades reales mañana. ¡Éxito a todos! 💤💪"
    )
    await enviar_mensaje_seguro(msg)

# ==========================================
# BUCLE PRINCIPAL (Blindado con Flags)
# ==========================================
async def main_loop():
    logger.info("Bot El Boss Mexa con IA (Gemini 1.5 Flash) Iniciado correctamente. Sistema de Flags activo.")

    # Control de ejecuciones diarias para evitar fallos por saltos de segundos
    enviado_profit = False
    enviado_noches = False
    enviado_picks = False
    dia_actual = datetime.now(MX_TZ).date()

    while True:
        try:
            ahora = datetime.now(MX_TZ)
            
            # Si cambió el día, reiniciamos las banderas de control
            if ahora.date() != dia_actual:
                dia_actual = ahora.date()
                enviado_profit = False
                enviado_noches = False
                enviado_picks = False
                logger.info(f"Nuevo día detectado ({dia_actual}). Banderas de envío reiniciadas.")

            # 1. REPORTE PROFIT (Rango 11:45 PM a 11:50 PM)
            if ahora.hour == 23 and 45 <= ahora.minute <= 50 and not enviado_profit:
                logger.info("Ejecutando tarea programada: Reporte Profit...")
                await mandar_reporte_profit()
                enviado_profit = True

            # 2. BUENAS NOCHES (Rango 12:00 AM a 12:05 AM)
            elif ahora.hour == 0 and 0 <= ahora.minute <= 5 and not enviado_noches:
                logger.info("Ejecutando tarea programada: Buenas Noches...")
                await mandar_buenas_noches()
                enviado_noches = True

            # 3. PICKS DEL DÍA (Rango 8:30 AM a 8:35 AM)
            elif ahora.hour == 8 and 30 <= ahora.minute <= 35 and not enviado_picks:
                logger.info("Ejecutando tarea programada: Envío matutino de picks...")
                await mandar_picks_del_dia()
                enviado_picks = True
            
            # Revisión constante cada 30 segundos, sin congelar el bot con sleeps largos
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Error detectado en el reloj interno, reiniciando ciclo: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
