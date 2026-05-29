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
    "soccer_france_ligue_1", "soccer_mexico_ligamx", "soccer_usa_mls",
    "baseball_mlb", "baseball_lmb", 
    "basketball_nba", "basketball_euroleague"
]

def obtener_picks_deporte(sport_key, markets):
    url = f"[https://api.the-odds-api.com/v4/sports/](https://api.the-odds-api.com/v4/sports/){sport_key}/odds/"
    params = {"apiKey": ODDS_API_KEY, "regions": REGIONS, "markets": markets, "oddsFormat": "decimal"}
    try:
        response = requests.get(url, params=params, timeout=12)
        if response.status_code == 200: return response.json()
        return []
    except Exception as e:
        return []

def obtener_marcadores(sport_key):
    url = f"[https://api.the-odds-api.com/v4/sports/](https://api.the-odds-api.com/v4/sports/){sport_key}/scores/"
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
# CEREBRO IA: CON TU FALLBACK INTACTO
# ==========================================
def consultar_cerebro_ia(candidatos_raw, cantidad, modo_bloque="normal"):
    if modo_bloque != "stake_10":
        p1 = f"Analiza y elige los {cantidad} mejores picks únicos del día de hoy. Reglas estrictas:\n"
        p2 = "1. Selecciona partidos con alta probabilidad basados en las cuotas.\n"
        p3 = "2. Asigna Stake del 1 al 8 según probabilidad.\n"
        p4 = "Devuelve solo JSON plano, sin markdown: "
        p5 = "[{\"deporte\": \"\", \"partido\": \"\", \"fecha_hora\": \"\", \"pick\": \"\", \"cuota\": 0.0, "
        p6 = "\"bookie\": \"\", \"sport_key\": \"\", \"stake_num\": 5, \"analisis_ia\": \"\"}]"
        prompt = p1 + p2 + p3 + p4 + p5 + p6
    else:
        p1 = "Selecciona únicamente el pick más seguro de toda la cartelera del día de hoy (Confianza extrema).\n"
        p2 = "Asigna obligatoriamente Stake 10.\n"
        p3 = "Devuelve solo un objeto en JSON plano dentro de una lista, sin markdown: "
        p4 = "[{\"deporte\": \"\", \"partido\": \"\", \"fecha_hora\": \"\", \"pick\": \"\", \"cuota\": 0.0, "
        p5 = "\"bookie\": \"\", \"sport_key\": \"\", \"stake_num\": 10, \"analisis_ia\": \"\"}]"
        prompt = p1 + p2 + p3 + p4

    datos_json = json.dumps(candidatos_raw, ensure_ascii=False)
    prompt_completo = prompt + "\n\nDatos: " + datos_json
    picks_finales_limpios = []
    partidos_vistos = set()

    try:
        response = model.generate_content(prompt_completo)
        # ==============================================================
        # AQUÍ ESTÁ LA LÍNEA REPARADA: TODO EN UNA SOLA LÍNEA SIN SALTOS
        # ==============================================================
        txt = response.text.strip().replace("```json", "").replace("```", "").strip()
        picks_seleccionados = json.loads(txt)
        
        for pick in picks_seleccionados:
            nombre_partido = pick.get('partido')
            if nombre_partido and nombre_partido not in partidos_vistos:
                picks_finales_limpios.append(pick)
                partidos_vistos.add(nombre_partido)
            if len(picks_finales_limpios) == cantidad:
                break
        return picks_finales_limpios
    except Exception as e:
        logger.error(f"Error en IA (Modo {modo_bloque}). Activando Red de Seguridad de El Boss: {e}")
        random.shuffle(candidatos_raw)
        if modo_bloque != "stake_10":
            for p in candidatos_raw:
                if p.get('partido') not in partidos_vistos:
                    p['stake_num'] = random.randint(4, 7)
                    p['analisis_ia'] = "Análisis verificado por tendencias del mercado."
                    picks_finales_limpios.append(p)
                    partidos_vistos.add(p.get('partido'))
                if len(picks_finales_limpios) == cantidad: break
        else:
            if candidatos_raw:
                p = candidatos_raw[0]
                p['stake_num'] = 10
                p['analisis_ia'] = "Máxima probabilidad detectada en base a rachas de rendimiento."
                picks_finales_limpios.append(p)
        return picks_finales_limpios

# TU EXTRACCIÓN ORIGINAL REFORMADA PARA SEPARAR POR LIGAS
def procesar_bloque_especifico(lista_ligas, cantidad, modo_bloque="normal"):
    candidatos_crudos = []
    fecha_hoy_mx = datetime.now(MX_TZ).date()

    for liga in lista_ligas:
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
                                tipo_pick = f"Hándicap {o.get('name')} {signo}{punto}"
                            else: continue

                            candidatos_crudos.append({
                                "deporte": name_dep := nombre_deporte,
                                "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                                "fecha_hora": fecha_hora_str,
                                "pick": tipo_pick,
                                "cuota": cuota,
                                "bookie": bookie.get("title", "Bet365"),
                                "sport_key": liga
                            })
                            
    if not candidatos_crudos: return []
    return consultar_cerebro_ia(candidatos_crudos, cantidad, modo_bloque=modo_bloque)

# TU PLANTILLA DE TEXTO ORIGINAL CORREGIDA
def construir_mensaje(pick_data):
    stk_num = pick_data.get("stake_num", 3)
    estrellas = "⭐" * int(stk_num)
    analisis = pick_data.get("analisis_ia", "Análisis verificado por tendencias.")

    m1 = "🔥 El Boss mexa – Pick del Día\n\n"
    m2 = f"Deporte: {pick_data['deporte']}\n"
    m3 = f"Partido: {pick_data['partido']}\n"
    m4 = f"⏰ Horario: {pick_data.get('fecha_hora', 'N/A')} (Hora MX)\n"
    m5 = f"Pick: {pick_data['pick']}\n"
    m6 = f"Cuota: {pick_data['cuota']:.2f}\n"
    m7 = f"Stake: {estrellas} (Stake {stk_num})\n\n"
    m8 = "📊 Análisis:\n"
    m9 = f"{analisis}\n\n"
    m10 = "¡Vamos con todo! 💰"
    return m1 + m2 + m3 + m4 + m5 + m6 + m7 + m8 + m9 + m10

async def enviar_mensaje_seguro(texto):
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=texto, parse_mode=None)
    except Exception as e:
        logger.error(f"Error al enviar mensaje a Telegram: {e}")

# ==========================================
# TU FUNCIÓN DE EVALUACIÓN ORIGINAL
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
    except:
        return "❔ REVISAR"

# ==========================================
# CONTROLADOR DE BLOQUES MODERNOS
# ==========================================
async def ejecutar_bloque_remodelado(nombre_bloque, ligas, cantidad, modo="normal", intro=None):
    logger.info(f"Iniciando bloque: {nombre_bloque}")
    picks_bloque = procesar_bloque_especifico(ligas, cantidad, modo_bloque=modo)
    
    if not picks_bloque:
        logger.warning(f"No se encontraron partidos activos hoy para el bloque {nombre_bloque}")
        return

    # Guardar en memoria para la calificación nocturna sin borrar los anteriores
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

    ligas_jugadas = list(set([pick['sport_key'] for pick in picks_totales]))
    todos_los_resultados = []
    for liga in ligas_jugadas: todos_los_resultados += obtener_marcadores(liga)

    ganados, perdidos, total_evaluados = 0, 0, 0
    msg = "📊 **El Boss mexa – Resumen de la Jornada** 📊\n\nResultados oficiales de las jugadas enviadas hoy:\n\n"
    
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
                else: marcador_texto = "Partido aún en juego ⏳"
                break
        msg += f"🔥 **{pick['partido']}**\nPick: {pick['pick']} (Cuota {pick['cuota']:.2f})\nResultado: {marcador_texto}\nEstatus: **{estado_pick}**\n\n"
    
    porcentaje = (ganados / total_evaluados * 100) if total_evaluados > 0 else 0.0
    msg += f"📈 **Efectividad del día:** {porcentaje:.1f}%\n"
    msg += f"🟢 GANADOS: {ganados} | 🔴 PERDIDOS: {perdidos}\n\n"
    msg += "¡Mañana regresamos por más verdes! 📉💰"
    await enviar_mensaje_seguro(msg)

# ==========================================
# BUCLE PRINCIPAL (CRONOGRAMA DE BLOQUES NUEVOS)
# ==========================================
async def main_loop():
    logger.info("Bot El Boss Mexa: Sistema Híbrido Iniciado y esperando bloques.")

    bloques_ejecutados = {
        "buenos_dias": None, "mlb": None, "futbol": None, 
        "lmb": None, "stake10": None, "reporte": None, "buenas_noches": None
    }
    
    # Al arrancar, limpiamos el JSON para la cartelera del nuevo día
    guardar_picks([])

    while True:
        try:
            ahora = datetime.now(MX_TZ)
            fecha_str = ahora.strftime("%Y-%m-%d")
            
            if ahora.hour == 0 and ahora.minute == 5:
                guardar_picks([]) # Limpieza de seguridad a la medianoche

            # 07:45 AM - Buenos Días
            if ahora.hour == 7 and 45 <= ahora.minute <= 50 and bloques_ejecutados["buenos_dias"] != fecha_str:
                msg = "¡Buenos días, Familia! ☀️ Arrancamos una nueva jornada de análisis deportivo. En breve salen las primeras jugadas del día. ¡A facturar hoy! 💸"
                await enviar_mensaje_seguro(msg)
                bloques_ejecutados["buenos_dias"] = fecha_str

            # 08:00 AM - Bloque MLB (2 Picks)
            elif ahora.hour == 8 and 0 <= ahora.minute <= 5 and bloques_ejecutados["mlb"] != fecha_str:
                await ejecutar_bloque_remodelado("MLB Mañanero", ["baseball_mlb"], 2)
                bloques_ejecutados["mlb"] = fecha_str

            # 09:00 AM - Bloque Fútbol Europeo (2 Picks)
            elif ahora.hour == 9 and 0 <= ahora.minute <= 5 and bloques_ejecutados["futbol"] != fecha_str:
                ligas_soccer = [l for l in LIGAS_PERMITIDAS if "soccer" in l]
                await ejecutar_bloque_remodelado("Fútbol Europeo", ligas_soccer, 2)
                bloques_ejecutados["futbol"] = fecha_str

            # 01:30 PM - Bloque LMB / Liga Mexicana (2 Picks)
            elif ahora.hour == 13 and 30 <= ahora.minute <= 35 and bloques_ejecutados["lmb"] != fecha_str:
                intro_lmb = "Familia, ya están abiertas las líneas. Aquí tienen los picks de la Liga Mexicana de Béisbol. ⚾️🔥"
                await ejecutar_bloque_remodelado("LMB Tarde", ["baseball_lmb", "baseball_mlb"], 2, intro=intro_lmb)
                bloques_ejecutados["lmb"] = fecha_str

            # 03:00 PM - Bloque Máxima Alerta STAKE 10 (1 Pick Único)
            elif ahora.hour == 15 and 0 <= ahora.minute <= 5 and bloques_ejecutados["stake10"] != fecha_str:
                intro_s10 = "🚨 STAKE 10 DETECTADO 🚨\n\nInteligencia algorítmica aplicada para maximizar el retorno. Vamos pesados aquí:"
                await ejecutar_bloque_remodelado("MÁXIMO VIP", LIGAS_PERMITIDAS, 1, modo="stake_10", intro=intro_s10)
                bloques_ejecutados["stake10"] = fecha_str

            # 11:45 PM - Reporte Calificador Profit
            elif ahora.hour == 23 and 45 <= ahora.minute <= 50 and bloques_ejecutados["reporte"] != fecha_str:
                await mandar_reporte_profit()
                bloques_ejecutados["reporte"] = fecha_str

            # 11:58 PM - Buenas Noches
            elif ahora.hour == 23 and 58 <= ahora.minute <= 59 and bloques_ejecutados["buenas_noches"] != fecha_str:
                msg = "🌙 **¡Buenas noches, equipo!** 🌙\n\nFinalizan las actividades por hoy. El sistema analítico entra en reposo absoluto. ¡A descansar! 💤"
                await enviar_mensaje_seguro(msg)
                bloques_ejecutados["buenas_noches"] = fecha_str
            
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Error en bucle del reloj: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
