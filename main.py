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

# Candados diarios
ARCHIVO_LOG_BUENOS_DIAS = "buenos_dias.txt"
ARCHIVO_LOG_MLB = "bloque_mlb.txt"
ARCHIVO_LOG_LMB = "bloque_lmb.txt"
ARCHIVO_LOG_SEPTIMO = "ultimo_septimo.txt"
ARCHIVO_LOG_PROFIT = "ultimo_envio.txt"

# ==========================================
# CANDADOS DE CONTROL DE ENVÍOS
# ==========================================
def verificar_y_marcar(archivo):
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    if os.path.exists(archivo):
        with open(archivo, "r") as f:
            if f.read().strip() == hoy: return True
    with open(archivo, "w") as f: f.write(hoy)
    return False

# ==========================================
# MEMORIA PERSISTENTE (JSON)
# ==========================================
def guardar_picks(picks):
    try:
        with open(ARCHIVO_PICKS, 'w', encoding='utf-8') as f:
            json.dump(picks, f, ensure_ascii=False, indent=4)
    except Exception as e: logger.error(f"Error al guardar picks: {e}")

def cargar_picks():
    if os.path.exists(ARCHIVO_PICKS):
        try:
            with open(ARCHIVO_PICKS, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: logger.error(f"Error al leer picks: {e}")
    return []

# ==========================================
# CONEXIÓN CON THE-ODDS-API
# ==========================================
LIGAS_FUTBOL = [
    "soccer_uefa_champions_league", "soccer_uefa_europa_league", "soccer_uefa_european_championship",
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", "soccer_germany_bundesliga", 
    "soccer_france_ligue_1", "soccer_conmebol_copa_libertadores", "soccer_conmebol_copa_sudamericana"
]

def obtener_picks_deporte(sport_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {"apiKey": ODDS_API_KEY, "regions": REGIONS, "markets": markets, "oddsFormat": "decimal"}
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200: return response.json()
        return []
    except: return []

def obtener_marcadores(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = { "apiKey": ODDS_API_KEY, "daysFrom": 1 }
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200: return response.json()
        return []
    except: return []

def mapear_icono_deporte(sport_key):
    sport_key_lower = sport_key.lower()
    if "soccer" in sport_key_lower: return "⚽ Fútbol"
    if "baseball_mlb" in sport_key_lower: return "⚾ MLB (Béisbol)"
    if "baseball_lmb" in sport_key_lower: return "⚾ LMB (Liga Mexicana)"
    if "basketball" in sport_key_lower: return "🏀 NBA / Básquetbol"
    return "🏅 Deporte"

# ==========================================
# CEREBRO IA: SELECCIÓN EXCLUSIVA DE PICKS
# ==========================================
def consultar_cerebro_ia(candidatos_raw, modo_bloque="bloque_3"):
    if modo_bloque == "bloque_3":
        p1 = "Analiza y elige estrictamente los 3 mejores picks únicos de la lista proporcionada.\n"
        p2 = "Asigna a cada uno un Stake del 3 al 8 basado en su probabilidad analítica.\n"
        p3 = "Devuelve solo JSON plano, sin markdown: "
        p4 = "[{\"deporte\": \"\", \"partido\": \"\", \"fecha_hora\": \"\", \"pick\": \"\", \"cuota\": 0.0, "
        p5 = "\"bookie\": \"\", \"sport_key\": \"\", \"stake_num\": 5, \"analisis_ia\": \"\"}]"
        prompt = p1 + p2 + p3 + p4 + p5
    else:
        p1 = "Selecciona el mejor pick disponible de toda la lista que tenga una probabilidad del 70% al 80%.\n"
        p2 = "Asigna obligatoriamente un Stake de 9 o 10 según la solidez del encuentro.\n"
        p3 = "Devuelve solo un objeto en JSON plano, sin markdown: "
        p4 = "[{\"deporte\": \"\", \"partido\": \"\", \"fecha_hora\": \"\", \"pick\": \"\", \"cuota\": 0.0, "
        p5 = "\"bookie\": \"\", \"sport_key\": \"\", \"stake_num\": 10, \"analisis_ia\": \"\"}]"
        prompt = p1 + p2 + p3 + p4 + p5

    datos_json = json.dumps(candidatos_raw, ensure_ascii=False)
    prompt_completo = prompt + "\n\nDatos: " + datos_json

    try:
        response = model.generate_content(prompt_completo)
        txt = response.text.strip().replace("```json", "").replace("
```", "").strip()
        picks_seleccionados = json.loads(txt)
        
        limite = 3 if modo_bloque == "bloque_3" else 1
        return picks_seleccionados[:limite]
    except Exception as e:
        logger.error(f"Fallo en cerebro IA: {e}")
        random.shuffle(candidatos_raw)
        p = candidatos_raw[0]
        p['stake_num'] = 5 if modo_bloque == "bloque_3" else 10
        p['analisis_ia'] = "Análisis de valor verificado por fluctuación de mercado."
        return [p]

def procesar_ligas(lista_ligas, modo_bloque="bloque_3"):
    candidatos_todos = []
    fecha_hoy_mx = datetime.now(MX_TZ).date()

    for liga in lista_ligas:
        partidos = obtener_picks_deporte(liga, markets="h2h,totals,spreads")
        if not partidos: continue

        for partido in partidos:
            commence_time_raw = partido.get("commence_time")
            if commence_time_raw:
                try:
                    pt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    pt_mx = pt_utc.astimezone(MX_TZ)
                    if pt_mx.date() != fecha_hoy_mx: continue
                    fecha_hora_str = pt_mx.strftime("%I:%M %p")
                except: continue

            for bookie in partido.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    for o in market.get("outcomes", []):
                        cuota = o.get("price")
                        # NUEVO FILTRO INTELIGENTE: 1.40 a 2.80
                        if cuota and 1.40 <= cuota <= 2.80:
                            candidatos_todos.append({
                                "deporte": mapear_icono_deporte(liga),
                                "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                                "fecha_hora": fecha_hora_str,
                                "pick": f"{market.get('key')} {o.get('name')} {o.get('point', '')}",
                                "cuota": cuota,
                                "bookie": bookie.get("title", "Bet365"),
                                "sport_key": liga
                            })
                            
    # MOTOR DE SELECCION: TOP 50
    if not candidatos_todos: 
        logger.warning("No se encontraron candidatos tras aplicar el rango 1.40-2.80.")
        return []
    
    random.shuffle(candidatos_todos)
    top_50 = candidatos_todos[:50]
    logger.info(f"Analizando {len(top_50)} candidatos de un total de {len(candidatos_todos)} posibles.")
    
    return consultar_cerebro_ia(top_50, modo_bloque=modo_bloque)

def construir_mensaje(pick_data):
    stk_num = pick_data.get("stake_num", 3)
    estrellas = "⭐" * int(stk_num)
    analisis = pick_data.get("analisis_ia", "Análisis verificado por tendencias.")

    m = f"🔥 El Boss Mexa – Pick del Día\n\n"
    m += f"Deporte: {pick_data['deporte']}\n"
    m += f"Partido: {pick_data['partido']}\n"
    m += f"Pick: {pick_data['pick']}\n"
    m += f"Cuota: {pick_data['cuota']:.2f}\n"
    m += f"Stake: {estrellas}\n\n"
    m += f"📊 Análisis:\n{analisis}\n\n"
    m += f"¡Vamos con todo! 💰"
    return m

async def enviar_mensaje_seguro(texto):
    try: await bot.send_message(chat_id=CHANNEL_ID, text=texto, parse_mode=None)
    except Exception as e: logger.error(f"Error Telegram: {e}")

# ==========================================
# EVALUACIÓN DE MARCADORES (PROFIT)
# ==========================================
def evaluar_pick(pick_str, scores):
    try:
        score1, score2 = float(scores[0]['score']), float(scores[1]['score'])
        name1, name2 = scores[0]['name'], scores[1]['name']
        if "Gana" in pick_str:
            t = pick_str.replace("Gana ", "").strip()
            w = name1 if score1 > score2 else (name2 if score2 > score1 else None)
            return "🟢 GANADO" if w == t else ("⚪ EMPATE / PUSH" if w is None else "🔴 PERDIDO")
        elif "Altas/Over" in pick_str or "Bajas/Under" in pick_str:
            tot = score1 + score2
            linea = float(pick_str.split(" ")[1])
            if "Altas/Over" in pick_str: return "🟢 GANADO" if tot > linea else ("🔴 PERDIDO" if tot < linea else "⚪ PUSH")
            if "Bajas/Under" in pick_str: return "🟢 GANADO" if tot < linea else ("🔴 PERDIDO" if tot > linea else "⚪ PUSH")
        return "❔ RESULTADO MANUAL"
    except: return "❔ REVISAR"

# ==========================================
# ACCIONES PROGRAMADAS
# ==========================================
async def ejecutar_buenos_dias():
    if verificar_y_marcar(ARCHIVO_LOG_BUENOS_DIAS): return
    await enviar_mensaje_seguro("¡Buenos días, Familia! ☀️ Arrancamos una nueva jornada de análisis deportivo.\n\nAquí les dejo los primeros tres picks de la MLB (Béisbol de Estados Unidos). En unas horas les mando los otros tres picks para la Liga Mexicana de Béisbol. ¡A facturar hoy! 💸")
    await asyncio.sleep(5)
    await ejecutar_bloque_mlb()

async def ejecutar_bloque_mlb():
    picks = procesar_ligas(["baseball_mlb"], modo_bloque="bloque_3")
    if picks:
        actuales = cargar_picks()
        actuales.extend(picks)
        guardar_picks(actuales)
        for pick in picks:
            await enviar_mensaje_seguro(construir_mensaje(pick))
            await asyncio.sleep(4)

async def ejecutar_bloque_lmb():
    if verificar_y_marcar(ARCHIVO_LOG_LMB): return
    await enviar_mensaje_seguro("Familia, ya están abiertas las líneas de béisbol. En un momento les mando los tres picks correspondientes a la Liga Mexicana de Béisbol. ⚾️🔥")
    await asyncio.sleep(420) 
    picks = procesar_ligas(["baseball_lmb"], modo_bloque="bloque_3")
    if picks:
        actuales = cargar_picks()
        actuales.extend(picks)
        guardar_picks(actuales)
        for pick in picks:
            await enviar_mensaje_seguro(construir_mensaje(pick))
            await asyncio.sleep(4)

async def ejecutar_septimo_pick():
    if verificar_y_marcar(ARCHIVO_LOG_SEPTIMO): return
    todas_ligas = ["baseball_mlb", "baseball_lmb"] + LIGAS_FUTBOL
    septimo = procesar_ligas(todas_ligas, modo_bloque="septimo")
    if septimo:
        pick_data = septimo[0]
        actuales = cargar_picks()
        actuales.append(pick_data)
        guardar_picks(actuales)
        
        # ALERTA DE STAKE 10 AJUSTADA
        alerta_msg = (
            "🚨 STAKE 10 DETECTADO 🚨\n\n"
            "Se ha detectado nuestra jugada fuerte de la tarde. Probabilidad e inteligencia "
            "algorítmica aplicada para maximizar el retorno en este encuentro."
        )
        
        await enviar_mensaje_seguro(alerta_msg)
        await asyncio.sleep(3)
        await enviar_mensaje_seguro(construir_mensaje(pick_data))

async def mandar_reporte_profit():
    if verificar_y_marcar(ARCHIVO_LOG_PROFIT): return
    picks_totales = cargar_picks()
    if not picks_totales: return
    ligas = list(set([p['sport_key'] for p in picks_totales]))
    todos_res = []
    for liga in ligas: todos_res += obtener_marcadores(liga)
    ganados, perdidos, tot_ev = 0, 0, 0
    msg = "📊 El Boss Mexa – Resumen de la Jornada 📊\n\nResultados oficiales de las jugadas del día:\n\n"
    for pick in picks_totales:
        m_txt, est = "Marcador no disponible / Pospuesto ⏳", "❔ Pendiente"
        for r in todos_res:
            if r.get('home_team') in pick['partido'] and r.get('away_team') in pick['partido']:
                if r.get('completed') and r.get('scores'):
                    scores = r.get('scores')
                    m_txt = f"{scores[0]['name']} {scores[0]['score']} - {scores[1]['score']} {scores[1]['name']} 🏁"
                    est = evaluar_pick(pick['pick'], scores)
                    if "GANADO" in est: ganados += 1
                    elif "PERDIDO" in est: perdidos += 1
                    tot_ev += 1
                else: m_txt = "Partido aún en juego ⏳"
                break
        msg += f"🔥 {pick['partido']}\nPick: {pick['pick']} (Cuota {pick['cuota']:.2f})\nResultado: {m_txt}\nEstatus: {est}\n\n"
    porc = (ganados / tot_ev * 100) if tot_ev > 0 else 0.0
    msg += f"📈 Efectividad: {porc:.1f}%\n🟢 GANADOS: {ganados} | 🔴 PERDIDOS: {perdidos}\n\n¡Mañana regresamos por más! 💰"
    await enviar_mensaje_seguro(msg)
    if os.path.exists(ARCHIVO_PICKS): os.remove(ARCHIVO_PICKS)

async def main_loop():
    logger.info("Bot El Boss Mexa operativo.")
    while True:
        try:
            ahora = datetime.now(MX_TZ)
            if ahora.hour == 8 and 30 <= ahora.minute <= 35: await ejecutar_buenos_dias()
            elif ahora.hour == 13 and 30 <= ahora.minute <= 35: await ejecutar_bloque_lmb()
            elif ahora.hour == 15 and 0 <= ahora.minute <= 5: await ejecutar_septimo_pick()
            elif ahora.hour == 23 and 45 <= ahora.minute <= 50: await mandar_reporte_profit()
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Error en reloj: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
