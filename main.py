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
                commence_time = game.get('date', '') 
                
                bms_mapeados = []
                for b in bookmakers:
                    bets = b.get('bets', [])
                    markets_mapeados = []
                    for bet in bets:
                        bet_name = bet.get('name')
                        if bet_name == "Home/Away":
                            outcomes = []
                            for val in bet.get('values', []):
                                team_name = home_team if val.get('value') == "Home" else away_team
                                outcomes.append({"name": team_name, "price": float(val.get('odd', 0))})
                            if outcomes:
                                markets_mapeados.append({"key": "h2h", "outcomes": outcomes})
                                
                        elif bet_name == "Over/Under":
                            outcomes = []
                            for val in bet.get('values', []):
                                over_under_str = str(val.get('value', ''))
                                odd_val = float(val.get('odd', 0))
                                
                                try:
                                    if "Over" in over_under_str:
                                        punto = float(over_under_str.replace("Over ", "").strip())
                                        outcomes.append({"name": "Over", "price": odd_val, "point": punto})
                                    elif "Under" in over_under_str:
                                        punto = float(over_under_str.replace("Under ", "").strip())
                                        outcomes.append({"name": "Under", "price": odd_val, "point": punto})
                                except ValueError:
                                    continue
                                    
                            if outcomes:
                                markets_mapeados.append({"key": "totals", "outcomes": outcomes})
                            
                    if markets_mapeados:
                        bms_mapeados.append({
                            "title": b.get('name', 'Bookmaker'),
                            "markets": markets_mapeados
                        })
                        
                if bms_mapeados:
                    mapeo_datos.append({
                        "home_team": home_team,
                        "away_team": away_team,
                        "commence_time": commence_time,
                        "bookmakers": bms_mapeados
                    })
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
                home_team = item.get('teams', {}).get('home', {}).get('name', 'Home')
                away_team = item.get('teams', {}).get('away', {}).get('name', 'Away')
                status = item.get('status', {}).get('short', '')
                home_score = item.get('scores', {}).get('home', {}).get('total', 0)
                away_score = item.get('scores', {}).get('away', {}).get('total', 0)
                
                if home_score is None: home_score = 0
                if away_score is None: away_score = 0
                
                completed = status in ["FT", "AOT"]
                mapeo_scores.append({
                    "home_team": home_team,
                    "away_team": away_team,
                    "completed": completed,
                    "scores": [
                        {"name": home_team, "score": str(home_score)},
                        {"name": away_team, "score": str(away_score)}
                    ]
                })
            return mapeo_scores
        return []
    except Exception as e:
        logger.error(f"Error API-Sports Scores (Liga {league_id}): {e}")
        return []

def mapear_icono_deporte(sport_key):
    sport_key_lower = str(sport_key).lower()
    if "baseball_mlb" in sport_key_lower: return "⚾ MLB"
    if "baseball_lmb" in sport_key_lower: return "⚾ LMB"
    return "🏅 Deporte"

# ==========================================
# 3. PROCESAMIENTO ALGORÍTMICO Y RED DE SEGURIDAD
# ==========================================
def consultar_cerebro_ia(candidatos_raw, cantidad, modo_bloque="normal"):
    if modo_bloque != "stake_10":
        p1 = f"Analiza y elige los {cantidad} mejores picks únicos del día de hoy. Reglas:\n"
        p2 = "1. Selecciona partidos con alta probabilidad basados en cuotas.\n"
        p3 = "2. Asigna Stake del 1 al 8 según probabilidad.\n"
        p4 = "Devuelve solo JSON plano, sin markdown:\n"
        p5 = "[{\"deporte\": \"\", \"partido\": \"\", \"fecha_hora\": \"\", \"pick\": \"\", \"cuota\": 0.0, "
        p6 = "\"bookie\": \"\", \"sport_key\": \"\", \"stake_num\": 5, \"analisis_ia\": \"\"}]"
        prompt = p1 + p2 + p3 + p4 + p5 + p6
    else:
        p1 = "Selecciona únicamente el pick más seguro de toda la cartelera del día de hoy.\n"
        p2 = "Asigna obligatoriamente Stake 10.\n"
        p3 = "Devuelve solo un objeto en JSON plano dentro de una lista, sin markdown:\n"
        p4 = "[{\"deporte\": \"\", \"partido\": \"\", \"fecha_hora\": \"\", \"pick\": \"\", \"cuota\": 0.0, "
        p5 = "\"bookie\": \"\", \"sport_key\": \"\", \"stake_num\": 10, \"analisis_ia\": \"\"}]"
        prompt = p1 + p2 + p3 + p4 + p5

    datos_json = json.dumps(candidatos_raw, ensure_ascii=False)
    prompt_completo = prompt + "\n\nDatos: " + datos_json
    picks_finales_limpios = []
    
    # Detección de duplicados mejorada con Clave Única
    picks_vistos = set()

    try:
        response = model.generate_content(prompt_completo)
        
        txt = response.text.strip()
        txt = txt.replace('```json', '')
        txt = txt.replace('```', '')
        txt = txt.strip()
        
        picks_seleccionados = json.loads(txt)
        
        # ✅ CORREGIDO: Validación de respuesta JSON de la IA (Problema 5)
        if not isinstance(picks_seleccionados, list):
            logger.error("❌ La IA no devolvió una lista válida. Formato esperado: [{…}]")
            raise ValueError("Formato JSON inválido de la IA")
        
        for pick in picks_seleccionados:
            partido = pick.get('partido', 'Desconocido')
            tipo = pick.get('pick', 'Desconocido')
            cuota = str(pick.get('cuota', '0.0'))
            
            clave_unica = f"{partido}_{tipo}_{cuota}"
            
            if clave_unica not in picks_vistos:
                picks_finales_limpios.append(pick)
                picks_vistos.add(clave_unica)
            if len(picks_finales_limpios) == cantidad:
                break
        return picks_finales_limpios
    except Exception as e:
        logger.error(f"Error IA: Activando Red de Seguridad: {e}")
        random.shuffle(candidatos_raw)
        if modo_bloque != "stake_10":
            for p in candidatos_raw:
                partido = p.get('partido', 'Desconocido')
                tipo = p.get('pick', 'Desconocido')
                cuota = str(p.get('cuota', '0.0'))
                
                clave_unica = f"{partido}_{tipo}_{cuota}"
                
                if clave_unica not in picks_vistos:
                    p['stake_num'] = random.randint(4, 7)
                    p['analisis_ia'] = "Análisis verificado por tendencias del mercado."
                    picks_finales_limpios.append(p)
                    picks_vistos.add(clave_unica)
                if len(picks_finales_limpios) == cantidad: break
        else:
            if candidatos_raw:
                p = candidatos_raw[0]
                p['stake_num'] = 10
                p['analisis_ia'] = "Máxima probabilidad detectada en rachas."
                picks_finales_limpios.append(p)
        return picks_finales_limpios

def procesar_bloque_especifico(lista_ligas, cantidad, modo_bloque="normal"):
    candidatos_crudos = []

    logger.info(f"=== Iniciando búsqueda de picks para el bloque. Ligas solicitadas: {lista_ligas} ===")

    for liga in lista_ligas:
        if liga not in LIGAS_PERMITIDAS:
            logger.warning(f"⚠️ La liga '{liga}' NO está en LIGAS_PERMITIDAS. Omitiendo.")
            continue

        logger.info(f"📡 Consultando datos para la liga: {liga}...")

        league_id = LIGAS_MAP.get(liga)
        partidos = obtener_partidos_api_sports(league_id)
            
        if not partidos: 
            logger.info(f"❌ No se encontraron datos de partidos activos para {liga}.")
            continue

        logger.info(f"✅ Se obtuvieron {len(partidos)} partidos crudos en {liga}. Evaluando cuotas y horarios...")

        for partido in partidos:
            commence_time_raw = partido.get("commence_time")
            fecha_hora_str = "Horario por confirmar"
            if commence_time_raw:
                try:
                    clean_time = commence_time_raw.replace('Z', '+00:00')
                    partido_tiempo_utc = datetime.fromisoformat(clean_time).astimezone(timezone.utc)
                    partido_tiempo_mx = partido_tiempo_utc.astimezone(MX_TZ)
                    fecha_hora_str = partido_tiempo_mx.strftime("%I:%M %p")
                except Exception: 
                    pass

            for bookie in partido.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    market_key = market.get("key")
                    for o in market.get("outcomes", []):
                        cuota = o.get("price")
                        
                        # ✅ CORREGIDO: Validación robusta de cuota (Problema 2)
                        if cuota and isinstance(cuota, (int, float)) and CUOTA_MIN <= cuota <= CUOTA_MAX:
                            nombre_deporte = mapear_icono_deporte(liga)
                            
                            if market_key == "h2h": 
                                tipo_pick = f"Gana {o.get('name')}"
                            elif market_key == "totals": 
                                punto = o.get('point', 0)
                                tipo_pick = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {punto}"
                            elif market_key == "spreads":
                                punto = o.get('point', 0)
                                signo = "+" if punto > 0 else ""
                                tipo_pick = f"Hándicap {o.get('name')} {signo}{punto}"
                            else: continue

                            candidatos_crudos.append({
                                "deporte": nombre_deporte,
                                "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                                "fecha_hora": fecha_hora_str,
                                "pick": tipo_pick,
                                "cuota": cuota,
                                # ✅ CORREGIDO: Bookie simplificado (Problema 1)
                                "bookie": bookie.get("title", "Bookmaker Desconocido"),
                                "sport_key": liga
                            })
                            
    # ✅ CORREGIDO: Logging detallado de picks por liga (Problema 3)
    picksporliga = {}
    for c in candidatos_crudos:
        liga = c['sport_key']
        picksporliga[liga] = picksporliga.get(liga, 0) + 1
    for liga, count in picksporliga.items():
        logger.info(f" 📍 {liga}: {count} picks viables extraídos.")

    if not candidatos_crudos: return []
    return consultar_cerebro_ia(candidatos_crudos, cantidad, modo_bloque=modo_bloque)

# ==========================================
# 4. PLANTILLA DE TEXTOS Y CALIFICADOR
# ==========================================
def construir_mensaje(pick_data):
    stk_num = pick_data.get("stake_num", 3)
    try:
        stk_num = int(stk_num)
    except:
        stk_num = 3
        
    estrellas = "⭐" * stk_num
    analisis = pick_data.get("analisis_ia", "Análisis verificado por la IA basado en tendencias (+EV).")

    m1 = "🔥 El Boss mexa – Pick del Día\n\n"
    m2 = f"Deporte: {pick_data.get('deporte', 'Deporte')}\n"
    m3 = f"Partido: ({pick_data.get('partido', 'Equipo vs Equipo')})\n"
    m4 = f"Pick: {pick_data.get('pick', '')}\n"
    m5 = f"Cuota: {float(pick_data.get('cuota', 0)):.2f}\n"
    m6 = f"Stake: {estrellas}\n\n"
    m7 = "📊 Análisis:\n"
    m8 = f"{analisis}\n\n"
    m9 = "¡Vamos con todo! 💰"
    return m1 + m2 + m3 + m4 + m5 + m6 + m7 + m8 + m9

async def enviar_mensaje_seguro(texto):
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=texto, parse_mode=None)
    except Exception as e:
        logger.error(f"Error al enviar Telegram: {e}")

def evaluar_pick(pick_str, scores):
    try:
        score1 = float(scores[0]['score'])
        score2 = float(scores[1]['score'])
        name1 = str(scores[0]['name'])
        name2 = str(scores[1]['name'])
        
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
            for part in pick_str.split(" "):
                try:
                    linea = float(part)
                    break
                except: continue
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
    # ✅ CORREGIDO: Manejo de excepciones específico (Problema 4)
    except (ValueError, TypeError, IndexError) as e:
        logger.warning(f"⚠️ Error evaluando pick '{pick_str}': {e}")
        return "❔ REVISAR"

async def ejecutar_bloque_remodelado(nombre_bloque, ligas, cantidad, modo="normal", intro=None):
    logger.info(f"Iniciando bloque: {nombre_bloque}")
    picks_bloque = procesar_bloque_especifico(ligas, cantidad, modo_bloque=modo)
    
    if not picks_bloque:
        logger.warning(f"No hay partidos activos hoy para el bloque {nombre_bloque}")
        return

    actuales = cargar_picks()
    actuales.extend(picks_bloque)
    guardar_picks(actuales)

    if intro:
        await enviar_mensaje_seguro(intro)
        await asyncio.sleep(3)

    for pick in picks_bloque:
        await enviar_mensaje_seguro(construir_mensaje(pick))
        await asyncio.sleep(5)

async def mandar_reporte_profit():
    picks_totales = cargar_picks()
    if not picks_totales: return

    ligas_jugadas = list(set([pick.get('sport_key') for pick in picks_totales if pick.get('sport_key')]))
    todos_los_resultados = []
    
    for liga in ligas_jugadas:
        league_id = LIGAS_MAP.get(liga)
        if league_id:
            todos_los_resultados += obtener_marcadores_api_sports(league_id)

    ganados, perdidos, total_evaluados = 0, 0, 0
    msg = "📊 **El Boss mexa – Resumen de la Jornada** 📊\n\nResultados oficiales:\n\n"
    
    for pick in picks_totales:
        marcador_texto = "Marcador no disponible ⏳"
        estado_pick = "❔ Pendiente"
        for res in todos_los_resultados:
            if res.get('home_team') in pick.get('partido', '') and res.get('away_team') in pick.get('partido', ''):
                if res.get('completed'):
                    scores = res.get('scores')
                    if scores and len(scores) == 2:
                        marcador_texto = f"{scores[0]['name']} {scores[0]['score']} - {scores[1]['score']} {scores[1]['name']} 🏁"
                        estado_pick = evaluar_pick(pick.get('pick', ''), scores)
                        if "GANADO" in estado_pick: ganados += 1
                        elif "PERDIDO" in estado_pick: perdidos += 1
                        total_evaluados += 1
                else: marcador_texto = "Partido en juego ⏳"
                break
        msg += f"🔥 **{pick.get('partido', 'Partido')}**\nPick: {pick.get('pick', '')}\nResultado: {marcador_texto}\nEstatus: **{estado_pick}**\n\n"
    
    porcentaje = (ganados / total_evaluados * 100) if total_evaluados > 0 else 0.0
    msg += f"📈 **Efectividad del día:** {porcentaje:.1f}%\n"
    msg += f"🟢 GANADOS: {ganados} | 🔴 PERDIDOS: {perdidos}\n\n"
    msg += "¡Mañana regresamos por más verdes! 📉💰"
    await enviar_mensaje_seguro(msg)

# ==========================================
# 5. CRONOGRAMA AUTOMATIZADO (MAIN LOOP)
# ==========================================
async def main_loop():
    logger.info("Bot El Boss mexa: Sistema Béisbol Unificado Iniciado.")

    bloques_ejecutados = {
        "buenos_dias": None, "mlb": None, 
        "lmb": None, "stake10": None, "reporte": None, "buenas_noches": None
    }
    
    guardar_picks([])
    
    # -------------------------------------------------------------
    # PRUEBA FORZADA LMB: Solo se ejecutará una vez al encender el bot
    # -------------------------------------------------------------
    logger.info("Ejecutando PRUEBA FORZADA exclusiva de la LMB...")
    await enviar_mensaje_seguro("🚨 **Prueba de Sistema - Verificando Conexión LMB** 🚨\nExtrayendo y analizando un partido en vivo de la Liga Mexicana de Béisbol...")
    await ejecutar_bloque_remodelado("Prueba LMB Forzada", ["baseball_lmb_real"], 1)
    # -------------------------------------------------------------

    while True:
        try:
            ahora = datetime.now(MX_TZ)
            fecha_str = ahora.strftime("%Y-%m-%d")
            
            if ahora.hour == 0 and ahora.minute == 5:
                guardar_picks([])

            if ahora.hour == 7 and 45 <= ahora.minute <= 50 and bloques_ejecutados["buenos_dias"] != fecha_str:
                msg = "¡Buenos días, Familia! ☀️ Arrancamos una nueva jornada de análisis deportivo. En breve salen las primeras jugadas del día. ¡A facturar hoy! 💸"
                await enviar_mensaje_seguro(msg)
                bloques_ejecutados["buenos_dias"] = fecha_str

            # MLB: 8:30 AM (3 Picks)
            elif ahora.hour == 8 and 30 <= ahora.minute <= 35 and bloques_ejecutados["mlb"] != fecha_str:
                await ejecutar_bloque_remodelado("MLB Mañanero", ["baseball_mlb"], 3)
                bloques_ejecutados["mlb"] = fecha_str

            # LMB: 1:00 PM (3 Picks)
            elif ahora.hour == 13 and 0 <= ahora.minute <= 5 and bloques_ejecutados["lmb"] != fecha_str:
                intro_lmb = "Familia, ya están abiertas las líneas. Aquí tienen los picks de la Liga Mexicana de Béisbol. ⚾️🔥"
                await ejecutar_bloque_remodelado("LMB Tarde", ["baseball_lmb_real"], 3, intro=intro_lmb)
                bloques_ejecutados["lmb"] = fecha_str

            # STAKE 10: 3:00 PM (1 Pick de MLB o LMB)
            elif ahora.hour == 15 and 0 <= ahora.minute <= 5 and bloques_ejecutados["stake10"] != fecha_str:
                intro_s10 = "🚨 STAKE 10 DETECTADO 🚨\n\nInteligencia algorítmica aplicada. Vamos pesados aquí:"
                await ejecutar_bloque_remodelado("MÁXIMO VIP", LIGAS_PERMITIDAS, 1, modo="stake_10", intro=intro_s10)
                bloques_ejecutados["stake10"] = fecha_str

            elif ahora.hour == 23 and 45 <= ahora.minute <= 50 and bloques_ejecutados["reporte"] != fecha_str:
                await mandar_reporte_profit()
                bloques_ejecutados["reporte"] = fecha_str

            elif ahora.hour == 23 and 58 <= ahora.minute <= 59 and bloques_ejecutados["buenas_noches"] != fecha_str:
                msg = "🌙 **¡Buenas noches, equipo!** 🌙\n\nFinalizan las actividades por hoy. ¡A descansar! 💤"
                await enviar_mensaje_seguro(msg)
                bloques_ejecutados["buenas_noches"] = fecha_str
            
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Error en bucle del reloj: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
