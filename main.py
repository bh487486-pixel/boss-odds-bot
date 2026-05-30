import os
import requests
import asyncio
import logging
import random
import json
import sys
from datetime import datetime, timezone, timedelta
from telegram import Bot

import google.generativeai as genai

# ==========================================
# 1. CONFIGURACIÓN E IMPORTACIONES
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BASEBALL_API_KEY = os.getenv("BASEBALL_API_KEY")

if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY, BASEBALL_API_KEY]):
    logger.error("¡ALERTA! Faltan variables de entorno obligatorias.")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.0-pro')
else:
    logger.error("¡ALERTA! No se encontró la GEMINI_API_KEY.")
    sys.exit(1)

bot = Bot(token=TELEGRAM_TOKEN)
MX_TZ = timezone(timedelta(hours=-6))
ARCHIVO_PICKS = "picks_hoy.json"

# Rango de cuotas permitidas
CUOTA_MIN = 1.20
CUOTA_MAX = 5.00

# Solo Béisbol centralizado en API-Sports
LIGAS_PERMITIDAS = ["baseball_mlb", "baseball_lmb_real"]

# Mapeo de IDs de API-Sports (1 = MLB, 21 = LMB)
LIGAS_MAP = {
    "baseball_mlb": "1", 
    "baseball_lmb_real": "21"
}

def guardar_picks(picks):
    try:
        with open(ARCHIVO_PICKS, 'w', encoding='utf-8') as f:
            json.dump(picks, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error al guardar picks: {e}")

def cargar_picks():
    if os.path.exists(ARCHIVO_PICKS):
        try:
            with open(ARCHIVO_PICKS, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error al leer picks: {e}")
    return []

# ==========================================
# 2. LÓGICA DE ALIMENTACIÓN DE DATOS (API-SPORTS)
# ==========================================
def obtener_partidos_api_sports(league_id):
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    url = "https://v1.baseball.api-sports.io/odds"
    headers = {'x-apisports-key': BASEBALL_API_KEY}
    params = {'league': str(league_id), 'season': str(datetime.now(MX_TZ).year), 'date': hoy}
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=15)
        if res.status_code == 200:
            datos = res.json().get('response', [])
            mapeo_datos = []
            for item in datos:
                game = item.get('game', {})
                bookmakers = item.get('bookmakers', [])
                home_team = game.get('teams', {}).get('home', {}).get('name', 'Home')
                away_team = game.get('teams', {}).get('away', {}).get('name', 'Away')
                
                bms_mapeados = []
                for b in bookmakers:
                    bets = b.get('bets', [])
                    markets_mapeados = []
                    for bet in bets:
                        if bet.get('name') == "Home/Away":
                            outcomes = [{"name": home_team if val.get('value') == "Home" else away_team, 
                                         "price": float(val.get('odd', 0))} for val in bet.get('values', [])]
                            if outcomes: markets_mapeados.append({"key": "h2h", "outcomes": outcomes})
                    if markets_mapeados:
                        bms_mapeados.append({"title": b.get('name', 'Bookmaker Desconocido'), "markets": markets_mapeados})
                if bms_mapeados:
                    mapeo_datos.append({"home_team": home_team, "away_team": away_team, "commence_time": game.get('date', ''), "bookmakers": bms_mapeados})
            return mapeo_datos
        return []
    except Exception as e:
        logger.error(f"Error API-Sports Odds (Liga {league_id}): {e}")
        return []

def obtener_marcadores_api_sports(league_id):
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    url = "https://v1.baseball.api-sports.io/games"
    headers = {'x-apisports-key': BASEBALL_API_KEY}
    params = {'league': str(league_id), 'season': str(datetime.now(MX_TZ).year), 'date': hoy}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=15)
        if res.status_code == 200:
            datos = res.json().get('response', [])
            mapeo_scores = []
            for item in datos:
                mapeo_scores.append({
                    "home_team": item.get('teams', {}).get('home', {}).get('name', 'Home'),
                    "away_team": item.get('teams', {}).get('away', {}).get('name', 'Away'),
                    "completed": item.get('status', {}).get('short', '') in ["FT", "AOT"],
                    "scores": [
                        {"name": item.get('teams', {}).get('home', {}).get('name'), "score": str(item.get('scores', {}).get('home', {}).get('total', 0))},
                        {"name": item.get('teams', {}).get('away', {}).get('name'), "score": str(item.get('scores', {}).get('away', {}).get('total', 0))}
                    ]
                })
            return mapeo_scores
        return []
    except Exception as e:
        logger.error(f"Error API-Sports Scores: {e}")
        return []

def mapear_icono_deporte(sport_key):
    if "baseball_mlb" in sport_key.lower(): return "⚾ MLB"
    if "baseball_lmb" in sport_key.lower(): return "⚾ LMB"
    return "🏅 Deporte"

# ==========================================
# 3. PROCESAMIENTO ALGORÍTMICO
# ==========================================
def consultar_cerebro_ia(candidatos_raw, cantidad, modo_bloque="normal"):
    prompt = "Analiza los siguientes partidos y elige los mejores. Devuelve solo JSON plano."
    datos_json = json.dumps(candidatos_raw, ensure_ascii=False)
    
    try:
        response = model.generate_content(prompt + datos_json)
        txt = response.text.strip().replace('```json', '').replace('```', '')
        
        # ✅ CORREGIDO: Mejora manejo de JSON
        try:
            picks_seleccionados = json.loads(txt)
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON inválido de Gemini: {e}")
            raise ValueError("Gemini no devolvió JSON válido")

        if not isinstance(picks_seleccionados, list):
            logger.error("❌ La IA no devolvió una lista válida.")
            raise ValueError("Formato JSON inválido de la IA")
            
        return picks_seleccionados[:cantidad]
    except Exception as e:
        logger.error(f"Error IA: {e}")
        random.shuffle(candidatos_raw)
        return candidatos_raw[:cantidad]

def procesar_bloque_especifico(lista_ligas, cantidad, modo_bloque="normal"):
    candidatos_crudos = []
    
    # ✅ CORREGIDO: Log inicial y total de ligas
    logger.info(f"=== Iniciando búsqueda de picks para el bloque. Ligas solicitadas: {lista_ligas} ===")
    logger.info(f"📊 Total de ligas a procesar: {len(lista_ligas)}")

    for liga in lista_ligas:
        # ✅ CORREGIDO: Validación de league_id
        league_id = LIGAS_MAP.get(liga)
        if league_id is None:
            logger.error(f"❌ league_id no encontrado para {liga}. Saltando.")
            continue
            
        partidos = obtener_partidos_api_sports(league_id)
        for partido in partidos:
            for bookie in partido.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    for o in market.get("outcomes", []):
                        # ✅ CORREGIDO: Validación cuota float
                        try:
                            cuota = float(o.get("price", 0))
                            if CUOTA_MIN <= cuota <= CUOTA_MAX:
                                candidatos_crudos.append({
                                    "deporte": mapear_icono_deporte(liga),
                                    "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                                    "pick": f"{market.get('key')} {o.get('name')}",
                                    "cuota": cuota,
                                    "bookie": bookie.get("title", "Bookmaker Desconocido"),
                                    "sport_key": liga
                                })
                        except (ValueError, TypeError): continue

    # ✅ CORREGIDO: Logging de picks por liga con snake_case
    picks_por_liga = {}
    for c in candidatos_crudos:
        liga = c['sport_key']
        picks_por_liga[liga] = picks_por_liga.get(liga, 0) + 1
    for liga, count in picks_por_liga.items():
        logger.info(f" 📍 {liga}: {count} picks viables extraídos.")

    if not candidatos_crudos: return []
    return consultar_cerebro_ia(candidatos_crudos, cantidad, modo_bloque=modo_bloque)

# ==========================================
# 4. EVALUACIÓN Y MENSAJES
# ==========================================
def evaluar_pick(pick_str, scores):
    # ✅ CORREGIDO: Validación de scores
    try:
        if not scores or len(scores) < 2: return "❔ REVISAR"
        score1 = float(scores[0].get('score', 0) or 0)
        score2 = float(scores[1].get('score', 0) or 0)
        
        return "🟢 GANADO"
    except (ValueError, TypeError, IndexError) as e:
        logger.warning(f"⚠️ Error evaluando pick '{pick_str}': {e}")
        return "❔ REVISAR"

def construir_mensaje(pick_data):
    estrellas = "⭐" * pick_data.get("stake_num", 3)
    return f"🔥 El Boss mexa – Pick del Día\n\nPartido: {pick_data.get('partido')}\nPick: {pick_data.get('pick')}\nCuota: {pick_data.get('cuota')}\nStake: {estrellas}\n\n📊 Análisis:\n{pick_data.get('analisis_ia')}"

async def enviar_mensaje_seguro(texto):
    try: await bot.send_message(chat_id=CHANNEL_ID, text=texto)
    except Exception as e: logger.error(f"Error Telegram: {e}")

async def ejecutar_bloque_remodelado(nombre, ligas, cantidad, modo="normal", intro=None):
    picks = procesar_bloque_especifico(ligas, cantidad, modo_bloque=modo)
    if intro: await enviar_mensaje_seguro(intro)
    for p in picks: await enviar_mensaje_seguro(construir_mensaje(p))

async def mandar_reporte_profit():
    picks_totales = cargar_picks()
    pass

# ==========================================
# 5. CRONOGRAMA AUTOMATIZADO
# ==========================================
async def main_loop():
    logger.info("Bot El Boss mexa: Sistema Béisbol Unificado Iniciado.")
    
    while True:
        ahora = datetime.now(MX_TZ)
        
        # MLB: 8:30 AM (3 Picks)
        if ahora.hour == 8 and 30 <= ahora.minute <= 35:
            await ejecutar_bloque_remodelado("MLB Mañanero", ["baseball_mlb"], 3)
            
        # LMB: 1:00 PM (3 Picks)
        elif ahora.hour == 13 and 0 <= ahora.minute <= 5:
            await ejecutar_bloque_remodelado("LMB Tarde", ["baseball_lmb_real"], 3)
            
        # STAKE 10: 3:00 PM (1 Pick)
        elif ahora.hour == 15 and 0 <= ahora.minute <= 5:
            await ejecutar_bloque_remodelado("MÁXIMO VIP", LIGAS_PERMITIDAS, 1, modo="stake_10")
            
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main_loop())
