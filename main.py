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

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-pro')

bot = Bot(token=TELEGRAM_TOKEN)
REGIONS = "us,eu"
MX_TZ = timezone(timedelta(hours=-6))
ARCHIVO_PICKS = "picks_hoy.json"
# Variable para evitar duplicados al reiniciar
ultimo_envio_dia = None

def guardar_picks(picks):
    try:
        with open(ARCHIVO_PICKS, 'w', encoding='utf-8') as f:
            json.dump(picks, f, ensure_ascii=False, indent=4)
    except: pass

def cargar_picks():
    if os.path.exists(ARCHIVO_PICKS):
        try:
            with open(ARCHIVO_PICKS, 'r', encoding='utf-8') as f: return json.load(f)
        except: return []
    return []

# ==========================================
# LÓGICA DE DATOS
# ==========================================
LIGAS_PERMITIDAS = ["soccer_uefa_champions_league", "soccer_epl", "soccer_spain_la_liga", "soccer_mexico_liga_mx", "baseball_mlb", "baseball_lmb", "basketball_nba"]

def obtener_deportes_activos():
    url = "https://api.the-odds-api.com/v4/sports/"
    try:
        response = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=12)
        if response.status_code == 200:
            return [d['key'] for d in response.json() if d.get('key') in LIGAS_PERMITIDAS and d.get('active')]
        return []
    except: return []

def obtener_picks_deporte(sport_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    try:
        response = requests.get(url, params={"apiKey": ODDS_API_KEY, "regions": REGIONS, "markets": markets, "oddsFormat": "decimal"}, timeout=12)
        return response.json() if response.status_code == 200 else []
    except: return []

def consultar_cerebro_ia(candidatos_raw):
    prompt = (
        "Eres El Boss Mexa, tipster profesional. Selecciona los 6 mejores picks de esta lista con mayor valor. "
        "Devuelve SOLO JSON plano, sin markdown. Formato: [{'deporte': '...', 'partido': '...', 'pick': '...', 'cuota': 0.0, 'analisis_ia': '...'}]\n"
        f"Partidos: {json.dumps(candidatos_raw, ensure_ascii=False)}"
    )
    try:
        response = model.generate_content(prompt)
        txt = response.text.strip().replace(chr(96), "").replace("json", "")
        return json.loads(txt)[:6]
    except: return candidatos_raw[:6]

def procesar_cartelera_completa():
    candidatos_crudos = []
    for liga in obtener_deportes_activos():
        partidos = obtener_picks_deporte(liga, "h2h,totals")
        for partido in partidos:
            for bookie in partido.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    for o in market.get("outcomes", []):
                        cuota = o.get("price")
                        # --- RANGO FLEXIBLE ---
                        if cuota and cuota >= 1.30:
                            candidatos_crudos.append({
                                "deporte": "Deporte", "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                                "pick": f"{o.get('name')} | {market.get('key')}", "cuota": cuota, "sport_key": liga
                            })
    return consultar_cerebro_ia(candidatos_crudos) if candidatos_crudos else []

async def enviar_picks():
    global ultimo_envio_dia
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    if ultimo_envio_dia == hoy: return 
    
    await bot.send_message(chat_id=CHANNEL_ID, text="☀️ **¡Activando cartelera de El Boss Mexa!** ☀️\nAnalizando mercados...")
    picks = procesar_cartelera_completa()
    if picks:
        for p in picks:
            await bot.send_message(chat_id=CHANNEL_ID, text=f"🔥 **Pick del Día**\n{p['partido']}\nPick: {p['pick']}\nCuota: {p['cuota']}\n📊 IA: {p.get('analisis_ia', 'Valor detectado')}")
            await asyncio.sleep(5)
        ultimo_envio_dia = hoy
        guardar_picks(picks)
    else:
        await bot.send_message(chat_id=CHANNEL_ID, text="⚠️ Mercado en ajuste, volvemos en breve.")

async def main_loop():
    logger.info("Bot Iniciado.")
    # Forzar ejecución al arrancar para que mande los picks ahorita
    await enviar_picks() 
    
    while True:
        ahora = datetime.now(MX_TZ)
        if ahora.hour == 8 and ahora.minute == 30: await enviar_picks()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main_loop())
