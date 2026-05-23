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
# CEREBRO DE INTELIGENCIA ARTIFICIAL
# ==========================================
def consultar_cerebro_ia(candidatos_raw):
    # Ajuste: Instrucción directa para que devuelva 6 picks sin repetir partidos
    prompt = (
        "Actúa como un tipster analista profesional. Te doy una lista de partidos con cuotas.\n"
        "TU OBJETIVO: Selecciona EXACTAMENTE los 6 mejores picks del día con mayor probabilidad de ganar.\n"
        "REGLAS CRÍTICAS:\n"
        "1. NO repitas partidos. Si un partido tiene varios mercados, elige solo el más valioso.\n"
        "2. Debes devolver 6 picks en total.\n"
        "3. Formato ESTRICTO JSON plano (sin markdown, sin bloques de código, solo la lista):\n"
        "[{\"deporte\": \"...\", \"partido\": \"...\", \"pick\": \"...\", \"cuota\": 0.0, \"bookie\": \"...\", \"sport_key\": \"...\", \"analisis_ia\": \"...\"}]\n\n"
        f"Datos: {json.dumps(candidatos_raw, ensure_ascii=False)}"
    )
    
    try:
        response = model.generate_content(prompt)
        txt = response.text.strip().replace(chr(96), "").replace("json", "")
        picks_seleccionados = json.loads(txt)
        logger.info(f"IA seleccionó {len(picks_seleccionados)} picks.")
        return picks_seleccionados[:6]
    except Exception as e:
        logger.error(f"Error en IA, usando respaldo: {e}")
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
            for market in bookie.get("markets", []):
                for o in market.get("outcomes", []):
                    cuota = o.get("price")
                    # Filtro base
                    if cuota and cuota >= 1.30:
                        nombre_deporte = mapear_icono_deporte(liga)
                        tipo_pick = f"Gana {o.get('name')}" if market.get('key') == "h2h" else f"{'Over' if o.get('name') == 'Over' else 'Under'} {o.get('point')}"
                        
                        candidatos_crudos.append({
                            "deporte": nombre_deporte,
                            "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                            "pick": tipo_pick,
                            "cuota": cuota,
                            "bookie": bookie.get("title", "Bet365"),
                            "sport_key": liga
                        })
                        
    return consultar_cerebro_ia(candidatos_crudos) if candidatos_crudos else []

def construir_mensaje(pick_data):
    cuota = pick_data["cuota"]
    stake = "⭐⭐⭐" if cuota <= 1.65 else ("⭐⭐" if cuota <= 1.85 else "⭐")
    return (
        f"🔥 **El Boss Mexa – Pick del Día**\n\n"
        f"Deporte: {pick_data['deporte']}\n"
        f"Partido: {pick_data['partido']}\n"
        f"Pick: {pick_data['pick']}\n"
        f"Cuota: {cuota:.2f}\n"
        f"Stake: {stake}\n\n"
        f"📊 Análisis:\n{pick_data.get('analisis_ia', 'Valor detectado.')}\n\n"
        f"¡Vamos con todo! 💰"
    )

async def enviar_mensaje_seguro(texto):
    try: await bot.send_message(chat_id=CHANNEL_ID, text=texto)
    except TelegramError as e: logger.error(f"Error: {e}")

# ==========================================
# EVALUACIÓN Y TAREAS (REPORTES)
# ==========================================
def evaluar_pick(pick_str, scores):
    try:
        s1, s2 = float(scores[0]['score']), float(scores[1]['score'])
        if "Gana" in pick_str:
            team_picked = pick_str.replace("Gana ", "").strip()
            if s1 > s2 and scores[0]['name'] == team_picked: return "🟢 GANADO"
            if s2 > s1 and scores[1]['name'] == team_picked: return "🟢 GANADO"
            return "🔴 PERDIDO"
        return "⚪ PUSH"
    except: return "❔ REVISAR"

async def mandar_picks_del_dia():
    await enviar_mensaje_seguro("☀️ **¡Buenos días, familia de El Boss Mexa!** ☀️\n\nAnalizando los mejores 6 picks...")
    await asyncio.sleep(4)
    picks = procesar_cartelera_completa()
    guardar_picks(picks)
    for p in picks:
        await enviar_mensaje_seguro(construir_mensaje(p))
        await asyncio.sleep(6)

async def mandar_reporte_profit():
    picks = cargar_picks()
    if not picks: return
    msg = "📊 **El Boss Mexa – Resumen de la Jornada** 📊\n\n"
    for pick in picks:
        msg += f"🔥 **{pick['partido']}**\nPick: {pick['pick']}\nEstatus: Pendiente\n\n"
    await enviar_mensaje_seguro(msg)

# ==========================================
# BUCLE PRINCIPAL
# ==========================================
async def main_loop():
    logger.info("Bot Iniciado.")
    while True:
        ahora = datetime.now(MX_TZ)
        if ahora.hour == 23 and ahora.minute == 45:
            await mandar_reporte_profit()
            await asyncio.sleep(70)
        elif ahora.hour == 8 and ahora.minute == 30:
            await mandar_picks_del_dia()
            await asyncio.sleep(70)
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
