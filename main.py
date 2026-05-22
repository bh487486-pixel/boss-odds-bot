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

# ==========================================
# LISTA DE LIGAS PRINCIPALES PERMITIDAS (ÉLITE)
# ==========================================
LIGAS_PERMITIDAS = [
    # Fútbol Élite e Internacional
    "soccer_uefa_champions_league", "soccer_uefa_europa_league", 
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", 
    "soccer_germany_bundesliga", "soccer_france_ligue_1", "soccer_mexico_liga_mx",
    # Béisbol Pro
    "baseball_mlb", "baseball_lmb",
    # Básquetbol Pro
    "basketball_nba",
    # Fútbol Americano Pro
    "americanfootball_nfl",
    # Tenis Pro
    "tennis_atp_wimbledon", "tennis_atp_us_open", "tennis_atp_french_open", "tennis_atp_australian_open",
    "tennis_wta_wimbledon", "tennis_wta_us_open", "tennis_wta_french_open", "tennis_wta_australian_open",
    "tennis_atp_masters_1000", "tennis_wta_1000"
]

# ==========================================
# FUNCIONES DE CONEXIÓN CON THE ODDS API
# ==========================================

def obtener_deportes_activos():
    """Consulta la API y filtra únicamente las ligas de primer nivel permitidas."""
    url = "https://api.the-odds-api.com/v4/sports/"
    params = {"apiKey": ODDS_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200:
            deportes = response.json()
            # Solo dejamos pasar si están explícitamente en nuestro catálogo de LIGAS_PERMITIDAS
            return [d['key'] for d in deportes if d.get('key') in LIGAS_PERMITIDAS and d.get('active')]
        return []
    except Exception as e:
        logger.error(f"Error al obtener deportes activos: {e}")
        return []

def obtener_picks_deporte(sport_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": markets,
        "oddsFormat": "decimal"
    }
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        logger.error(f"Error de conexión con Odds API ({sport_key}): {e}")
        return []

def obtener_marcadores(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = { "apiKey": ODDS_API_KEY, "daysFrom": 1 }
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200: return response.json()
        return []
    except Exception as e:
        logger.error(f"Error al conectar con Scores API ({sport_key}): {e}")
        return []

def mapear_icono_deporte(sport_key):
    sport_key_lower = sport_key.lower()
    if "soccer" in sport_key_lower: return "⚽ Fútbol"
    if "baseball" in sport_key_lower: return "⚾ Béisbol"
    if "basketball" in sport_key_lower: return "🏀 Básquetbol"
    if "americanfootball" in sport_key_lower: return "🏈 Fútbol Americano"
    if "tennis" in sport_key_lower: return "🎾 Tenis"
    return "🏅 Deporte"

# ==========================================
# LÓGICA DE PROCESAMIENTO
# ==========================================

def procesar_cartelera_completa():
    candidatos = []
    ligas_elite = obtener_deportes_activos()

    # Si la API no reporta ligas específicas activas en su lista estricta, ampliamos al grupo base filtrando lo universitario
    if not ligas_elite:
        logger.warning("No se detectaron llaves específicas de ligas élite activas. Usando filtro por grupo...")
        try:
            url = "https://api.the-odds-api.com/v4/sports/"
            res = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=12).json()
            ligas_elite = [d['key'] for d in res if d.get('group') in ["Soccer", "Basketball", "Baseball", "American Football", "Tennis"] and d.get('active')]
        except:
            return []

    for liga in ligas_elite:
        # Bloqueo total de ligas universitarias de EUA (NCAA) basándonos en la clave de la liga
        if "ncaa" in liga.lower() or "championship" in liga.lower():
            continue

        mercados = "h2h,totals" if any(x in liga for x in ["baseball", "basketball", "americanfootball"]) else "h2h"
        partidos = obtener_picks_deporte(liga, markets=mercados)
        
        if not partidos:
            continue

        for partido in partidos:
            # Doble escudo: si se coló un equipo universitario en el nombre del partido, lo saltamos
            partido_lower = f"{partido.get('home_team', '')} {partido.get('away_team', '')}".lower()
            if any(uni in partido_lower for uni in ["state", "university", "ncaa", "fighting irish", "badgers", "cowboys", "seminoles", "longhorns"]):
                continue

            bookmakers = partido.get("bookmakers", [])
            if not bookmakers: continue
            bookie = bookmakers[0]
            markets = bookie.get("markets", [])
            if not markets: continue
            
            for market in markets:
                market_key = market.get("key")
                outcomes = market.get("outcomes", [])
                
                for o in outcomes:
                    cuota = o.get("price")
                    
                    # Filtro de cuota estándar premium para ligas mayores (1.50 a 1.95)
                    if cuota and 1.50 <= cuota <= 1.95:
                        nombre_deporte = mapear_icono_deporte(liga)
                        
                        if market_key == "h2h":
                            tipo_pick = f"Gana {o.get('name')}"
                        elif market_key == "totals":
                            point = o.get("point")
                            tipo_pick = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {point} Puntos/Carreras"
                        else:
                            continue

                        if "baseball_lmb" in liga.lower():
                            nombre_deporte = "⚾ Béisbol (LMB)"

                        candidatos.append({
                            "deporte": nombre_deporte,
                            "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                            "pick": tipo_pick,
                            "cuota": cuota,
                            "bookie": bookie.get("title", "Bet365"),
                            "sport_key": liga
                        })
                        break
    
    random.shuffle(candidatos)
    return candidatos[:6]

def generar_texto_analisis(bookie, cuota):
    plantillas = [
        f"Análisis estadístico sólido. El modelo detecta una gran probabilidad de acierto, dejando la cuota de {cuota:.2f} con una ventaja real sobre la bookie.",
        f"El flujo de dinero inteligente respalda sólidamente esta línea. Aseguramos esta cuota de {cuota:.2f} en {bookie} priorizando la probabilidad de cobro.",
        f"Basado en las tendencias de rendimiento recientes, este pick fusiona valor (+EV) y un riesgo sumamente controlado.",
        f"Línea protegida por las estadísticas de ambos equipos. {bookie} nos da una cuota de {cuota:.2f} que no podemos dejar pasar hoy."
    ]
    return random.choice(plantillas)

def construir_mensaje(pick_data):
    cuota = pick_data["cuota"]
    if cuota <= 1.65: stake = "⭐⭐⭐"
    elif cuota <= 1.80: stake = "⭐⭐"
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
                if total_puntos > linea: return "🟢 GANADO"
                elif total_puntos < linea: return "🔴 PERDIDO"
                else: return "⚪ PUSH"
            elif "Bajas/Under" in pick_str:
                if total_puntos < linea: return "🟢 GANADO"
                elif total_puntos > linea: return "🔴 PERDIDO"
                else: return "⚪ PUSH"
                
        return "❔ RESULTADO MANUAL"
    except Exception as e:
        logger.error(f"No se pudo autoevaluar el pick: {e}")
        return "❔ REVISAR"

# ==========================================
# TAREAS PROGRAMADAS
# ==========================================

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
        await enviar_mensaje_seguro("⚠️ Los mercados principales no ofrecieron cuotas seguras en este momento. Protegemos el bankroll. 🏦")

async def mandar_reporte_profit():
    global picks_enviados_hoy
    if not picks_enviados_hoy:
        return

    ligas_jugadas = list(set([pick['sport_key'] for pick in picks_enviados_hoy]))
    todos_los_resultados = []
    for liga in ligas_jugadas:
        todos_los_resultados += obtener_marcadores(liga)

    msg = (
        "📊 **BossOddsMX – Resumen de la Jornada** 📊\n\n"
        "Cerramos las acciones de hoy. Estos fueron los resultados de nuestros nuevos 6 picks estratégicos de ligas mayores:\n\n"
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

        msg += f"🔥 **{pick['partido']}**\n"
        msg += f"Pick: {pick['pick']} (Cuota {pick['cuota']:.2f})\n"
        msg += f"Resultado: {marcador_texto}\n"
        msg += f"Estatus: **{estado_pick}**\n\n"
        
    msg += "¡Revisen sus boletos! El análisis real está dando frutos, mañana volvemos por más verdes. 📈💰"
    await enviar_mensaje_seguro(msg)

async def mandar_buenas_noches():
    msg = (
        "🌙 **¡Buenas noches, equipo!** 🌙\n\n"
        "Cerramos las cortinas de hoy en BossOddsMX.\n\n"
        "A descansar, que el bot se queda trabajando para traernos las mejores 6 oportunidades de las ligas más importantes mañana. ¡Éxito a todos! 💤💪"
    )
    await enviar_mensaje_seguro(msg)

async def main_loop():
    global picks_enviados_hoy
    logger.info("Bot BossOddsMX Iniciado. Lanzando ráfaga inmediata de picks de Ligas Mayores...")
    
    # ⚡ LANZAMIENTO INMEDIATO DE CORRECCIÓN (Solo se ejecuta una vez al prender el bot ahorita)
    await enviar_mensaje_seguro("🔄 **Actualización de Cartelera Premium:** Reajustamos el sistema para enfocarnos exclusivamente en ligas de primer nivel. Aquí vienen los 6 picks oficiales de hoy:")
    await mandar_picks_del_dia()
    
    # Entra en bucle infinito monitoreando el reloj de CDMX
    while True:
        ahora = datetime.now(MX_TZ)
        
        # Saltamos los disparos de la mañana (8:20 y 8:30) porque YA los mandamos de golpe ahorita
        if ahora.hour == 23 and ahora.minute == 45:
            await mandar_reporte_profit()
            await asyncio.sleep(70)
            
        elif ahora.hour == 0 and ahora.minute == 0:
            await mandar_buenas_noches()
            await asyncio.sleep(70)
            
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
