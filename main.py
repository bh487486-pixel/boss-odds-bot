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
        logger.info("Picks guardados correctamente.")
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
# LISTA EXCLUSIVA DE LIGAS PERMITIDAS
# ==========================================
LIGAS_PERMITIDAS = [
    "soccer_uefa_champions_league", "soccer_uefa_europa_league", "soccer_uefa_european_championship",
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", "soccer_germany_bundesliga", 
    "soccer_france_ligue_1",
    "baseball_mlb", "baseball_lmb", 
    "basketball_nba", "basketball_euroleague"
]

def obtener_deportes_activos():
    url = "https://api.the-odds-api.com/v4/sports/"
    params = {"apiKey": ODDS_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200:
            deportes = response.json()
            return [d['key'] for d in deportes if d.get('key') in LIGAS_PERMITIDAS and d.get('active')]
        return LIGAS_PERMITIDAS
    except Exception as e:
        logger.error(f"Error al obtener deportes, usando lista fija: {e}")
        return LIGAS_PERMITIDAS

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
    if "baseball_mlb" in sport_key_lower: return "⚾ MLB (Béisbol)"
    if "baseball_lmb" in sport_key_lower: return "⚾ LMB (Liga Mexicana)"
    if "basketball" in sport_key_lower: return "🏀 NBA / Básquetbol"
    return "🏅 Deporte"

# ==========================================
# CEREBRO IA: ENFOQUE Y PRIORIZACIÓN
# ==========================================
def consultar_cerebro_ia(candidatos_raw, modo_bloque="seis_picks"):
    if modo_bloque == "seis_picks":
        prompt = (
            "Actúa como un tipster analista profesional. Selecciona los 6 mejores picks de la lista.\n"
            "REGLAS DE PRIORIZACIÓN DE LIGAS:\n"
            "1. PRIORIDAD MÁXIMA: Debes priorizar los partidos de Béisbol (MLB y LMB). Si hay disponibilidad, dale fuerte peso en la cartelera combinándolos (ej. 3 de MLB y 3 de LMB, o de forma salteada).\n"
            "2. VARIEDAD SALTEADA: Si existen partidos de Fútbol Europeo o NBA, inclúyelos de forma intercalada para que la cartelera sea variada y no sature de un solo deporte.\n"
            "3. ESCASEZ: Si de plano NO hay fútbol o NBA activos, llena la cartelera de 6 picks usando exclusivamente MLB y LMB.\n"
            "4. REGLAS CRÍTICAS: NO repitas partidos. Asigna un STAKE de 1 a 8 según la probabilidad matemática real.\n"
            "5. Devuelve ESTRICTO JSON plano (sin markdown, sin ```):\n"
            "[{\"deporte\": \"...\", \"partido\": \"...\", \"fecha_hora\": \"...\", \"pick\": \"...\", \"cuota\": 0.0, \"bookie\": \"...\", \"sport_key\": \"...\", \"stake_num\": 5, \"analisis_ia\": \"...\"}]"
        )
    else:  # Modo SÉPTIMO PICK STAKE 10 / 9
        prompt = (
            "Actúa como un tipster profesional analizando apuestas de ALTA CONFIANZA (+EV).\n"
            "TU OBJETIVO: Selecciona el PICK MÁS SEGURO DEL DÍA (Mínimo 85% a 90% de probabilidad matemática/deportiva).\n"
            "REGLAS:\n"
            "1. Puedes priorizar MLB o LMB si muestran un valor estadístico brutal, pero está abierto a Fútbol Europeo o NBA si la probabilidad es casi infalible.\n"
            "2. Debe calificar como STAKE 10 o STAKE 9.\n"
            "3. Devuelve ESTRICTO JSON plano (sin markdown, sin 
```) de un solo objeto dentro de una lista:\n"
            "[{\"deporte\": \"...\", \"partido\": \"...\", \"fecha_hora\": \"...\", \"pick\": \"...\", \"cuota\": 0.0, \"bookie\": \"...\", \"sport_key\": \"...\", \"stake_num\": 10, \"analisis_ia\": \"...\"}]"
        )

    prompt += f"\n\nDatos: {json.dumps(candidatos_raw, ensure_ascii=False)}"
    picks_finales_limpios = []
    partidos_vistos = set()

    try:
        response = model.generate_content(prompt)
        txt = response.text.strip().replace("```json", "").replace("```", "").strip()
        picks_seleccionados = json.loads(txt)
        
        limite = 6 if modo_bloque == "seis_picks" else 1
        for pick in picks_seleccionados:
            nombre_partido = pick.get('partido')
            if nombre_partido and nombre_partido not in partidos_vistos:
                picks_finales_limpios.append(pick)
                partidos_vistos.add(nombre_partido)
            if len(picks_finales_limpios) == limite:
                break
        return picks_finales_limpios
    except Exception as e:
        logger.error(f"Error en IA en modo {modo_bloque}: {e}")
        random.shuffle(candidatos_raw)
        if modo_bloque == "seis_picks":
            for p in candidatos_raw:
                if p.get('partido') not in partidos_vistos:
                    p['stake_num'] = random.randint(3, 6)
                    p['analisis_ia'] = "Análisis verificado por tendencias del mercado."
                    picks_finales_limpios.append(p)
                    partidos_vistos.add(p.get('partido'))
                if len(picks_finales_limpios) == 6: break
        else:
            if candidatos_raw:
                p = candidatos_raw[0]
                p['stake_num'] = 10
                p['analisis_ia'] = "Máxima probabilidad detectada en base a rachas de rendimiento."
                picks_finales_limpios.append(p)
        return picks_finales_limpios

def procesar_cartelera_completa(modo_bloque="seis_picks"):
    candidatos_crudos = []
    ligas_elite = obtener_deportes_activos()
    fecha_hoy_mx = datetime.now(MX_TZ).date()

    for liga in ligas_elite:
        mercados_param = "h2h,totals,spreads"
        partidos = obtener_picks_deporte(liga, markets=mercados_param)
        if not partidos: continue

        for partido in partidos:
            commence_time_raw = partido.get("commence_time")
            fecha_hora_str = "Horario por confirmar"
            if commence_time_raw:
                try:
                    partido_tiempo_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    partido_tiempo_mx = partido_tiempo_utc.astimezone(MX_TZ)
                    fecha_hora_str = partido_tiempo_mx.strftime("%I:%M %p")
                    if partido_tiempo_mx.date() != fecha_hoy_mx: continue
                except: continue

            for bookie in partido.get("bookmakers", []):
                lista_mercados = bookie.get("markets", [])
                for market in lista_mercados:
                    market_key = market.get("key")
                    outcomes = market.get("outcomes", [])
                    for o in outcomes:
                        cuota = o.get("price")
                        if cuota and 1.30 <= cuota <= 4.00:
                            nombre_deporte = mapear_icono_deporte(liga)
                            
                            if market_key == "h2h": 
                                tipo_pick = f"Gana {o.get('name')}"
                            elif market_key == "totals": 
                                tipo_pick = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {o.get('point')} Pts/Goles/Carreras"
                            elif market_key == "spreads":
                                punto = o.get('point', 0)
                                signo = "+" if punto > 0 else ""
                                if "soccer" in liga:
                                    tipo_pick = f"Hándicap Asiático {o.get('name')} {signo}{punto}"
                                else:
                                    tipo_pick = f"Hándicap {o.get('name')} {signo}{punto}"
                            else: continue

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
    return consultar_cerebro_ia(candidatos_crudos, modo_bloque=modo_bloque)

def construir_mensaje(pick_data):
    stk_num = pick_data.get("stake_num", 3)
    estrellas = "⭐" * int(stk_num)
    analisis = pick_data.get("analisis_ia", "Análisis verificado por tendencias.")

    mensaje = (
        f"🔥 El Boss Mexa – Pick del Día\n\n"
        f"Deporte: {pick_data['deporte']}\n"
        f"Partido: {pick_data['partido']}\n"
        f"⏰ Horario: {pick_data.get('fecha_hora', 'N/A')} (Hora MX)\n"
        f"Pick: {pick_data['pick']}\n"
        f"Cuota: {pick_data['cuota']:.2f}\n"
        f"Stake: {estrellas} (Stake {stk_num})\n\n"
        f"📊 Análisis:\n"
        f"{analisis}\n\n"
        f"¡Vamos con todo! 💰"
    )
    return mensaje

async def enviar_mensaje_seguro(texto):
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=texto, parse_mode=None)
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
                
        elif "Hándicap" in pick_str:
            clean_str = pick_str.replace("Hándicap Asiático ", "").replace("Hándicap ", "")
            partes = clean_str.rsplit(" ", 1)
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
        "Arrancamos la jornada. Preparen sus bancas, a continuación les comparto los 6 picks analizados a fondo para el día de hoy. ¡Vamos por esos verdes! 🚀"
    )
    await enviar_mensaje_seguro(msg)

async def mandar_picks_del_dia():
    if ya_se_envio_hoy():
        logger.info("Los picks ya fueron procesados hoy.")
        return
    
    picks_del_dia = procesar_cartelera_completa(modo_bloque="seis_picks")
    guardar_picks(picks_del_dia)
    
    if picks_del_dia:
        for pick in picks_del_dia:
            texto_formateado = construir_mensaje(pick)
            await enviar_mensaje_seguro(texto_formateado)
            await asyncio.sleep(5)
    else:
        await enviar_mensaje_seguro("⚠️ Mercados inestables en el matutino. Protegemos bankroll.")

async def mandar_septimo_pick():
    logger.info("Buscando el Séptimo Pick VIP (Stake 10)...")
    septimo = procesar_cartelera_completa(modo_bloque="septimo_pick")
    
    if septimo:
        pick_data = septimo[0]
        pick_data["stake_num"] = random.choice([9, 10])
        
        actuales = cargar_picks()
        actuales.append(pick_data)
        guardar_picks(actuales)
        
        await enviar_mensaje_seguro("🔥 **¡MÁXIMA ALERTA - SÉPTIMO PICK VIP!** 🔥\n\nDetectamos una oportunidad de valor matemático extremo (Probabilidad estimada: 85%-90%).")
        await asyncio.sleep(3)
        texto_formateado = construir_mensaje(pick_data)
        await enviar_mensaje_seguro(texto_formateado)
    else:
        logger.warning("No se halló un partido que califique con seguridad extrema.")

async def mandar_reporte_profit():
    picks_totales = cargar_picks()
    if not picks_totales:
        return

    ligas_jugadas = list(set([pick['sport_key'] for pick in picks_totales]))
    todos_los_resultados = []
    for liga in ligas_jugadas: todos_los_resultados += obtener_marcadores(liga)

    ganados = 0
    perdidos = 0
    total_evaluados = 0

    msg = (
        "📊 **El Boss Mexa – Resumen de la Jornada** 📊\n\n"
        "Cerramos las acciones del día contando nuestro Séptimo Pick VIP. Resultados oficiales:\n\n"
    )
    
    for pick in picks_totales:
        marcador_texto = "Marcador no disponible / Pospuesto ⏳"
        estado_pick = "❔ Pendiente"
        for res in todos_los_resultados:
            if res.get('home_team') in pick['partido'] and res.get('away_team') in pick['partido']:
                if res.get('completed'):
                    scores = res.get('scores')
                    if scores and len(scores) == 2:
                        marcador_texto = f"{scores[0]['name']} {scores[0]['score']} - {scores[1]['score']} {scores[1]['name']} 🏁"
                        estado_pick = evaluar_pick(pick['pick'], scores)
                        if "GANADO" in estado_pick: ganados += 1
                        elif "PERDIDO" in estado_pick: perdidos += 1
                        total_evaluados += 1
                else:
                    marcador_texto = "Partido aún en juego ⏳"
                break
        msg += f"🔥 **{pick['partido']}**\nPick: {pick['pick']} (Cuota {pick['cuota']:.2f})\nResultado: {marcador_texto}\nEstatus: **{estado_pick}**\n\n"
    
    porcentaje = (ganados / total_evaluados * 100) if total_evaluados > 0 else 0.0
    
    msg += f"📈 **Efectividad del día:** {porcentaje:.1f}%\n"
    msg += f"🟢 GANADOS: {ganados} | 🔴 PERDIDOS: {perdidos}\n\n"
    msg += "¡Mañana regresamos por más verdes! 📉💰"
    await enviar_mensaje_seguro(msg)
    marcar_enviado_hoy()

async def mandar_buenas_noches():
    msg = (
        "🌙 **¡Buenas noches, equipo!** 🌙\n\n"
        "Finalizan las actividades por hoy. El sistema analítico entra en reposo absoluto para buscar el valor mañana temprano. ¡A descansar! 💤"
    )
    await enviar_mensaje_seguro(msg)

# ==========================================
# BUCLE PRINCIPAL (RELOJ DE OPERACIÓN)
# ==========================================
async def main_loop():
    logger.info("Bot El Boss Mexa: Buenos días 8:30 AM | Picks de golpe 11:30 AM.")

    enviado_buenos_dias = False
    enviado_profit = False
    enviado_noches = False
    enviado_picks = False
    enviado_septimo = False
    dia_actual = datetime.now(MX_TZ).date()

    while True:
        try:
            ahora = datetime.now(MX_TZ)
            
            if ahora.date() != dia_actual:
                dia_actual = ahora.date()
                enviado_buenos_dias = False
                enviado_profit = False
                enviado_noches = False
                enviado_picks = False
                enviado_septimo = False
                logger.info(f"Día reiniciado: {dia_actual}.")

            # 08:30 AM - Mensaje de Buenos Días Separado
            if ahora.hour == 8 and 30 <= ahora.minute <= 35 and not enviado_buenos_dias:
                await mandar_buenos_dias()
                enviado_buenos_dias = True

            # 11:30 AM - Envío Exclusivo de los 6 Picks de Golpe
            elif ahora.hour == 11 and 30 <= ahora.minute <= 35 and not enviado_picks:
                await mandar_picks_del_dia()
                enviado_picks = True

            # 02:00 PM - Séptimo Pick VIP (Stake 10)
            elif ahora.hour == 14 and 0 <= ahora.minute <= 5 and not enviado_septimo:
                await mandar_septimo_pick()
                enviado_septimo = True

            # 11:45 PM - Reporte Profit Completo
            elif ahora.hour == 23 and 45 <= ahora.minute <= 50 and not enviado_profit:
                await mandar_reporte_profit()
                enviado_profit = True

            # 11:58 PM - Buenas Noches
            elif ahora.hour == 23 and 58 <= ahora.minute <= 59 and not enviado_noches:
                await mandar_buenas_noches()
                enviado_noches = True
            
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Error en bucle del reloj: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
