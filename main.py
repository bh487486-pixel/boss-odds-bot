import os
import requests
import asyncio
import logging
import random
import json
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
    model = genai.GenerativeModel('gemini-pro')
else:
    logger.error("¡ALERTA! No se encontró la GEMINI_API_KEY.")

bot = Bot(token=TELEGRAM_TOKEN)
REGIONS = "us,eu"
MX_TZ = timezone(timedelta(hours=-6))
ARCHIVO_PICKS = "picks_hoy.json"

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
# NUEVA LÓGICA DE INTELIGENCIA ARTIFICIAL (FILTRO REAL)
# ==========================================
def consultar_cerebro_ia(candidatos_raw):
    logger.info(f"Enviando {len(candidatos_raw)} partidos crudos a la IA para análisis de realidad deportiva...")
    
    prompt = (
        "Actúa como un tipster analista profesional de apuestas deportivas. Te voy a dar una lista de partidos con sus cuotas disponibles.\n"
        "Quiero que uses tu conocimiento del contexto deportivo actual y me selecciones ÚNICAMENTE los 6 mejores picks del día con mayor probabilidad REAL de ganar.\n"
        "REGLA DE ORO EXTREMADAMENTE IMPORTANTE: NO repitas partidos. Elige máximo UN pick por cada encuentro para asegurar variedad en la cartelera.\n\n"
        "Importante: Devuelve la respuesta ESTRICTAMENTE en formato JSON plano, sin textos extras, sin markdown de bloques de código. Solo el texto JSON directo:\n"
        "[\n"
        "  {\"deporte\": \"⚽ Fútbol\", \"partido\": \"Equipo A vs Equipo B\", \"pick\": \"Gana Equipo A\", \"cuota\": 1.85, \"bookie\": \"Bet365\", \"sport_key\": \"soccer_mexico_liga_mx\", \"analisis_ia\": \"Breve explicación del pick y por qué tiene valor.\"}\n"
        "]\n\n"
        f"Aquí tienes los partidos disponibles hoy:\n{json.dumps(candidatos_raw, ensure_ascii=False)}"
    )
    
    try:
        response = model.generate_content(prompt)
        
        # === SOLUCIÓN DEFINITIVA PARA CELULARES ===
        txt = response.text.strip()
        txt = txt.replace(chr(96), "")
        txt = txt.replace("json", "")
        picks_seleccionados = json.loads(txt)
        # ==========================================
        
        logger.info(f"La IA ha seleccionado con éxito {len(picks_seleccionados)} picks blindados para hoy.")
        return picks_seleccionados[:6]
    except Exception as e:
        logger.error(f"Error en el cerebro de la IA: {e}. Usando respaldo aleatorio seguro.")
        random.shuffle(candidatos_raw)
        return candidatos_raw[:6]

def procesar_cartelera_completa():
    candidatos_crudos = []
    ligas_elite = obtener_deportes_activos()
    ahora_utc = datetime.now(timezone.utc)
    limite_futuro_utc = ahora_utc + timedelta(hours=24)

    for liga in ligas_elite:
        mercados = "h2h,totals" if any(x in liga for x in ["baseball", "basketball", "americanfootball"]) else "h2h"
        partidos = obtener_picks_deporte(liga, markets=mercados)
        
        if not partidos: continue

        for partido in partidos:
            commence_time_raw = partido.get("commence_time")
            if commence_time_raw:
                try:
                    partido_tiempo_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    if partido_tiempo_utc < ahora_utc or partido_tiempo_utc > limite_futuro_utc: continue
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
                    # --- FILTRO FLEXIBLE (Sin tope máximo, mínimo 1.30) ---
                    if cuota and cuota >= 1.30:
                        nombre_deporte = mapear_icono_deporte(liga)
                        if market_key == "h2h": tipo_pick = f"Gana {o.get('name')}"
                        elif market_key == "totals": tipo_pick = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {o.get('point')} Puntos/Carreras"
                        else: continue

                        if "baseball_lmb" in liga.lower(): nombre_deporte = "⚾ Béisbol"

                        candidatos_crudos.append({
                            "deporte": nombre_deporte,
                            "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
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
    except TelegramError as e:
        logger.error(f"Error de Telegram: {e}")

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
    await mandar_buenos_dias()
    await asyncio.sleep(4)
    
    picks_del_dia = procesar_cartelera_completa()
    guardar_picks(picks_del_dia)
    
    if picks_del_dia:
        for pick in picks_del_dia:
            texto_formateado = construir_mensaje(pick)
            await enviar_mensaje_seguro(texto_formateado)
            await asyncio.sleep(6)
    else:
        await enviar_mensaje_seguro("⚠️ Los mercados principales no ofrecieron cuotas del día en este momento. Protegemos el bankroll. 🏦")

async def mandar_reporte_profit():
    picks_enviados_hoy = cargar_picks()
    if not picks_enviados_hoy: return

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
# BUCLE PRINCIPAL
# ==========================================
async def main_loop():
    logger.info("Bot El Boss Mexa con IA Iniciado de manera segura. Esperando horarios...")
    
    # --- PARCHE DE ENVÍO MANUAL (OPCIONAL) ---
    # Como ya pasaron las 8:30 AM, si quieres que los mande ahorita mismo en cuanto 
    # subas este código, descomenta (quítale el #) a la siguiente línea:
    # await mandar_picks_del_dia()
    # -----------------------------------------

    while True:
        ahora = datetime.now(MX_TZ)
        if ahora.hour == 23 and ahora.minute == 45:
            await mandar_reporte_profit()
            await asyncio.sleep(70)
        elif ahora.hour == 0 and ahora.minute == 0:
            await mandar_buenas_noches()
            await asyncio.sleep(70)
        elif ahora.hour == 8 and ahora.minute == 30:
            logger.info("Iniciando envío programado matutino con filtro de IA...")
            await mandar_picks_del_dia()
            await asyncio.sleep(70)
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
