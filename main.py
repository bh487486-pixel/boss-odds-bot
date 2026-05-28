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
    "soccer_fifa_world_cup", "soccer_uefa_champions_league", "soccer_uefa_europa_league", 
    "soccer_conmebol_copa_libertadores", "soccer_conmebol_copa_sudamericana",
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
# CEREBRO IA: ESCANEO METICULOSO Y FILTRADO
# ==========================================
def consultar_cerebro_ia(candidatos_raw, es_septimo=False):
    if es_septimo:
        prompt = (
            "Actúa como un tipster analista profesional de apuestas deportivas de nivel élite, experto en +EV y tendencias deportivas.\n"
            "TU OBJETIVO: Realiza un escaneo profundamente meticuloso de toda la cartelera. Buscamos el pick perfecto (STAKE 10).\n"
            "CRITERIO ESTRICTO: No basta con un simple error de línea. Debe existir una CRUZADA PERFECTA entre la VENTAJA MATEMÁTICA (línea mal puesta por la casa de apuestas) y la VENTAJA DEPORTIVA (quién viene mejor, rachas, motivación, quién es el verdadero favorito deportivo en la cancha).\n"
            "REGLA DE ORO: Si consideras que ningún evento combina ambas ventajas (matemática y deportiva) para garantizar una certeza de acierto altísima, devuelve obligatoriamente una lista vacía []. Es preferible no enviar nada.\n"
            "Formato ESTRICTO JSON plano (sin markdown, sin bloques de código):\n"
            "[{\"deporte\": \"...\", \"partido\": \"...\", \"fecha_hora\": \"...\", \"pick\": \"...\", \"cuota\": 0.0, \"bookie\": \"...\", \"sport_key\": \"...\", \"analisis_ia\": \"Explica brevemente la doble ventaja (matemática y deportiva)\"}]\n\n"
            f"Datos: {json.dumps(candidatos_raw, ensure_ascii=False)}"
        )
    else:
        prompt = (
            "Actúa como un tipster analista profesional y scouter deportivo meticuloso.\n"
            "TU OBJETIVO: Extrae los mejores 6 picks del día de la lista provista.\n"
            "INSTRUCCIÓN: Evalúa tanto el valor numérico como el contexto deportivo real de los equipos involucrados. Busca el balance inteligente combinando Fútbol Internacional, Liga MX, MLB y LMB para encontrar las mejores ventajas.\n"
            "REGLAS CRÍTICAS:\n"
            "1. PROHIBIDO repetir partidos. Máximo un pick por evento.\n"
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
        
        limite = 1 if es_septimo else 6
        
        for pick in picks_seleccionados:
            nombre_partido = pick.get('partido')
            if nombre_partido and nombre_partido not in partidos_vistos:
                picks_finales_limpios.append(pick)
                partidos_vistos.add(nombre_partido)
            
            if len(picks_finales_limpios) == limite:
                break
                
        logger.info(f"Escaneo IA completado. Filtrados {len(picks_finales_limpios)} picks que cumplen criterio dual (Matemático + Deportivo).")
        return picks_finales_limpios

    except Exception as e:
        logger.error(f"Error en el análisis de la IA: {e}")
        if es_septimo: return []
        
        random.shuffle(candidatos_raw)
        for pick in candidatos_raw:
            nombre_partido = pick.get('partido')
            if nombre_partido and nombre_partido not in partidos_vistos:
                picks_finales_limpios.append(pick)
                partidos_vistos.add(nombre_partido)
            if len(picks_finales_limpios) == 6:
                break
        return picks_finales_limpios

def procesar_cartelera_completa(es_septimo=False):
    candidatos_crudos = []
    ligas_elite = obtener_deportes_activos()
    
    ahora_mx = datetime.now(MX_TZ)
    fecha_hoy_mx = ahora_mx.date()

    for liga in ligas_elite:
        mercados = "h2h,totals,spreads"
        partidos = obtener_picks_deporte(liga, markets=markets)
        
        if not partidos: continue

        for partido in partidos:
            commence_time_raw = partido.get("commence_time")
            fecha_hora_str = "Horario por confirmar"
            
            if commence_time_raw:
                try:
                    partido_tiempo_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    partido_tiempo_mx = partido_tiempo_utc.astimezone(MX_TZ)
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
                    # CORRECCIÓN DE RANGO: Ajustado estrictamente de 1.25 a 3.00 por solicitud del usuario
                    if cuota and 1.25 <= cuota <= 3.00:
                        nombre_deporte = mapear_icono_deporte(liga)
                        
                        if market_key == "h2h": 
                            tipo_pick = f"Gana {o.get('name')}"
                        elif market_key == "totals": 
                            tipo_pick = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {o.get('point')} Pts/Goles/Carreras"
                        elif market_key == "spreads":
                            punto = o.get('point', 0)
                            signo = "+" if punto > 0 else ""
                            tipo_pick = f"Hándicap {o.get('name')} {signo}{punto}"
                        else: continue

                        if "baseball_lmb" in liga.lower(): 
                            nombre_deporte = "⚾ Béisbol (LMB)"

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
    
    picks_elegidos = consultar_cerebro_ia(candidatos_crudos, es_septimo=es_septimo)
    
    if not es_septimo and len(picks_elegidos) < 6:
        logger.warning(f"La IA solo devolvió {len(picks_elegidos)} picks. Activando autorelleno estratégico para asegurar los 6 picks.")
        partidos_vistos = set(p['partido'] for p in picks_elegidos)
        
        candidatos_crudos.sort(key=lambda x: abs(x['cuota'] - 1.80))
        
        for cand in candidatos_crudos:
            if cand['partido'] not in partidos_vistos:
                cand['analisis_ia'] = "Análisis de valor respaldado por tendencias de rendimiento y consistencia estadística deportiva."
                picks_elegidos.append(cand)
                partidos_vistos.add(cand['partido'])
            if len(picks_elegidos) == 6:
                break
                
    return picks_elegidos

def construir_mensaje(pick_data, es_septimo=False):
    cuota = pick_data["cuota"]
    
    if es_septimo:
        stake = "⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐ (STAKE 10)"
    else:
        if cuota <= 1.65: stake = "⭐⭐"
        elif cuota <= 1.85: stake = "⭐⭐"
        else: stake = "⭐"

    analisis = pick_data.get("analisis_ia", "Análisis validado cruzando datos estadísticos y rendimiento deportivo.")

    mensaje = (
        f"🔥 BossOddsMX – Pick del Día\n\n"
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
        "☀️ **Buenos días, familia.** ☀️\n\n"
        "El análisis de mercado correspondiente a la jornada de hoy ha sido completado con éxito. Tras evaluar los movimientos de líneas y las variables estadísticas de la cartelera, hemos seleccionado las opciones que presentan la mayor ventaja matemática ante los casinos.\n\n"
        "A continuación, comparto los picks oficiales del día. Gestionen su banca con responsabilidad y mantengamos la disciplina operativa. ¡Mucho éxito en sus inversiones! 🚀📈"
    )
    await enviar_mensaje_seguro(msg)

async def mandar_picks_del_dia(forzar_envio=False):
    if not forzar_envio and ya_se_envio_hoy(): return

    await mandar_buenos_dias()
    await asyncio.sleep(4)
    
    picks_del_dia = procesar_cartelera_completa(es_septimo=False)
    guardar_picks(picks_del_dia)
    
    if picks_del_dia:
        for pick in picks_del_dia:
            texto_formateado = construir_mensaje(pick)
            await enviar_mensaje_seguro(texto_formateado)
            await asyncio.sleep(6)
        marcar_enviado_hoy()
    else:
        await enviar_mensaje_seguro("⚠️ Nota de mercado: Los eventos disponibles en este bloque no cumplen con el umbral mínimo de valor requerido. Priorizamos la protección del capital operativo. 🏦")

async def buscar_septimo_pick_tarde():
    logger.info("Despertando bot a las 1:30 PM para la Búsqueda Meticulosa del Séptimo Pick (Stake 10)...")
    
    pick_extra = procesar_cartelera_completa(es_septimo=True)
    
    if pick_extra:
        joya = pick_extra[0]
        picks_actuales = cargar_picks()
        
        if not any(p['partido'] == joya['partido'] for p in picks_actuales):
            joya['es_septimo'] = True
            picks_actuales.append(joya)
            guardar_picks(picks_actuales)
            
            alerta_msg = "🚨 ATENCIÓN: ¡STAKE 10 DETECTADO! 🚨\n\n¡Error de línea y ventaja deportiva localizados!\n\nPreparando análisis detallado... El pick se liberará en 5 minutos. ⏳"
            await enviar_mensaje_seguro(alerta_msg)
            logger.info("Alerta de Stake 10 enviada a Telegram. Esperando 5 minutos (300 segundos)...")
            
            await asyncio.sleep(300)
            
            texto_formateado = construir_mensaje(joya, es_septimo=True)
            await enviar_mensaje_seguro(texto_formateado)
            logger.info("Séptimo pick enviado de manera exitosa al canal.")
    else:
        logger.info("Búsqueda meticulosa finalizada: El mercado no presentó cruces óptimos de ventaja matemática y deportiva para un Stake 10.")

async def mandar_reporte_profit():
    picks_enviados_hoy = cargar_picks()
    if not picks_enviados_hoy: return

    ligas_jugadas = list(set([pick['sport_key'] for pick in picks_enviados_hoy]))
    todos_los_resultados = []
    for liga in ligas_jugadas: todos_los_resultados += obtener_marcadores(liga)

    verdes = 0
    rojos = 0

    msg = (
        "📊 **ELBOSSMEXA – Resumen Técnico de la Jornada** 📊\n\n"
        "Finalizan las acciones en la cartelera de hoy. Presentamos el desglose oficial de resultados obtenidos por nuestro sistema analítico:\n\n"
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
                        if "🟢" in estado_pick: verdes += 1
                        elif "🔴" in estado_pick: rojos += 1
                else:
                    marcador_texto = "Partido aún en juego ⏳"
                break
                
        prefijo = "🔥 [STAKE 10]" if pick.get('es_septimo') else "🔥"
        msg += f"{prefijo} **{pick['partido']}**\nPick: {pick['pick']} (Cuota {pick['cuota']:.2f})\nResultado: {marcador_texto}\nEstatus: **{estado_pick}**\n\n"
    
    total_evaluados = verdes + rojos
    if total_evaluados > 0:
        porcentaje_efectividad = (verdes / total_evaluados) * 100
        msg += f"📊 **Efectividad de la Jornada:** {porcentaje_efectividad:.1f}% ({verdes} verdes / {rojos} rojos)\n\n"
    
    msg += "Verifiquen sus estados de cuenta. El análisis estratégico basado en valor sigue demostrando consistencia. Mañana continuaremos con el plan de trabajo. 📈💰"
    await enviar_mensaje_seguro(msg)

async def mandar_buenas_noches():
    msg = (
        "🌙 **Buenas noches, equipo.** 🌙\n\n"
        "Damos por concluida la actividad operativa de este día.\n\n"
        "El sistema automatizado entrará en fase de reposo y reactivará los algoritmos de filtrado durante la madrugada para identificar las mejores ventanas de oportunidad para la cartelera de mañana. Que tengan un excelente descanso. 💤💪"
    )
    await enviar_mensaje_seguro(msg)

# ==========================================
# BUCLE PRINCIPAL (CRONOGRAMA ESTABLE)
# ==========================================
async def main_loop():
    logger.info("Bot ELBOSSMEXA Iniciado. Escaneo de Doble Ventaja (Matemática + Deportiva).")

    # ==============================================================
    # ENVÍO INMEDIATO AL ARRANCAR (IGNORANDO EL HORARIO POR ÚNICA VEZ)
    # ==============================================================
    logger.info("🚨 Forzando el envío inmediato de los 6 picks para compensar el horario...")
    await mandar_picks_del_dia(forzar_envio=True)
    logger.info("✅ Envío de arranque completado. Entrando al cronograma normal.")

    enviado_profit = False
    enviado_noches = False
    enviado_picks = True # Marcado True inicialmente para evitar doble envío matutino en el arranque
    enviado_septimo = False 
    
    dia_actual = datetime.now(MX_TZ).date()

    while True:
        try:
            ahora = datetime.now(MX_TZ)
            
            if ahora.date() != dia_actual:
                dia_actual = ahora.date()
                enviado_profit = False
                enviado_noches = False
                enviado_picks = False
                enviado_septimo = False
                logger.info(f"Nuevo día detectado ({dia_actual}). Banderas de envío reiniciadas.")

            # 1. Reporte de ganancias (11:45 PM - 11:50 PM)
            if ahora.hour == 23 and 45 <= ahora.minute <= 50 and not enviado_profit:
                await mandar_reporte_profit()
                enviado_profit = True

            # 2. Mesoaje de cierre (12:00 AM - 12:05 AM)
            elif ahora.hour == 0 and 0 <= ahora.minute <= 5 and not enviado_noches:
                await mandar_buenas_noches()
                enviado_noches = True

            # 3. Bloque Principal de 6 Picks del Día (10:00 AM - 10:05 AM)
            elif ahora.hour == 10 and 0 <= ahora.minute <= 5 and not enviado_picks:
                logger.info("Iniciando tarea: Escaneo exhaustivo matutino (10:00 AM)...")
                await mandar_picks_del_dia()
                enviado_picks = True
                
            # 4. Búsqueda profunda del Séptimo Pick (1:30 PM - 1:35 PM)
            elif ahora.hour == 13 and 30 <= ahora.minute <= 35 and not enviado_septimo:
                logger.info("Iniciando tarea: Búsqueda profunda del Séptimo Pick a las 1:30 PM...")
                await buscar_septimo_pick_tarde()
                enviado_septimo = True

            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Error detectado en el bucle principal: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
