import os
import re
import json
import sys
import time
import math
import asyncio
import logging
from datetime import datetime

import requests
from telegram import Bot

# ==========================================
# 1. CONTROL DE ZONA HORARIA (MÉXICO)
# ==========================================
try:
    from zoneinfo import ZoneInfo
    MX_TZ = ZoneInfo("America/Mexico_City")
except Exception:
    from datetime import timezone, timedelta
    MX_TZ = timezone(timedelta(hours=-6))

# ==========================================
# 2. CONFIGURACIÓN DE LOGS (MONITOREO)
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# 3. CARGA DE VARIABLES DE ENTORNO
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
BASEBALL_API_KEY = os.getenv("BASEBALL_API_KEY")

if not all([TELEGRAM_TOKEN, CHANNEL_ID, BASEBALL_API_KEY]):
    logger.error("❌ ¡ALERTA! Faltan variables de entorno obligatorias en Render.")
    sys.exit(1)

bot = Bot(token=TELEGRAM_TOKEN)

ARCHIVO_PICKS = "picks_hoy.json"
ARCHIVO_ESTADO = "estado_bot.json"

# Rango de cuotas optimizado para buscar valor real profesional (+EV)
CUOTA_MIN = 1.65
CUOTA_MAX = 3.50
EDGE_MINIMO = 0.05  # 5% de ventaja matemática mínima exigida

LIGAS_PERMITIDAS = ["baseball_mlb", "baseball_lmb_real"]
LIGAS_MAP = {"baseball_mlb": "1", "baseball_lmb_real": "21"}

# PROMEDIO HISTÓRICO DE CARRERAS DE LA LEAGUE (Base de Regresión)
PROMEDIO_CARRERAS_LIGA = 5.1

# ==========================================
# DICCIONARIOS SABERMÉTRICOS INTERNOS (FACTOR DE PARQUE Y POWER RANKING WRC+)
# ==========================================
PARK_FACTORS = {
    "diablos rojos del mexico": 1.30, "pericos de puebla": 1.25, "bravos de leon": 1.25,
    "rieleros de aguascalientes": 1.20, "saraperos de saltillo": 1.20, "acereros de monclova": 1.15,
    "sultanes de monterrey": 1.10, "toros de tijuana": 1.05, "tecolotes de los dos laredos": 1.00,
    "caliente de durango": 1.10, "dorados de chihuahua": 1.15, "charros de jalisco": 1.20,
    "algodoneros de union laguna": 1.05, "leones de yucatan": 0.85, "piratas de campeche": 0.85, 
    "olmecas de tabasco": 0.80, "el aguila de veracruz": 0.90, "tigres de quintana roo": 0.85, 
    "conspiradores de queretaro": 1.15, "colorado rockies": 1.35, "boston red sox": 1.12, 
    "cincinnati reds": 1.10, "texas rangers": 1.08, "san diego padres": 0.92, 
    "seattle mariners": 0.90, "san francisco giants": 0.91, "new york mets": 0.93, 
    "st. louis cardinals": 0.95
}

WRC_PLUS_RANKING = {
    "diablos rojos del mexico": 125, "sultanes de monterrey": 115, "pericos de puebla": 112,
    "acereros de monclova": 110, "charros de jalisco": 108, "conspiradores de queretaro": 105,
    "toros de tijuana": 102, "tecolotes de los dos laredos": 100, "saraperos de saltillo": 102,
    "bravos de leon": 98, "algodoneros de union laguna": 97, "el aguila de veracruz": 95,
    "guerreros de oaxaca": 104, "leones de yucatan": 94, "piratas de campeche": 90,
    "olmecas de tabasco": 88, "tigres de quintana roo": 85, "caliente de durango": 93,
    "dorados de chihuahua": 91, "rieleros de aguascalientes": 96, "los angeles dodgers": 120, 
    "atlanta braves": 115, "new york yankees": 118, "houston astros": 110, 
    "oakland athletics": 85, "colorado rockies": 90
}

DEFAULT_ESTADO = {
    "fecha": None,
    "bloques_ejecutados": {"buenos_dias": None, "mlb": None, "lmb": None, "stake10": None, "reporte": None, "buenas_noches": None}
}

REQUEST_TIMEOUT = (10, 30)

# ==========================================
# 4. CONTROL DE ARCHIVOS LOCALES
# ==========================================
def _cargar_json_seguro(path, fallback):
    if not os.path.exists(path): return fallback
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception as e:
        logger.error(f"Error al leer {path}: {e}")
        return fallback

def _guardar_json_seguro(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error al guardar {path}: {e}")

def cargar_picks(): return _cargar_json_seguro(ARCHIVO_PICKS, [])
def guardar_picks(picks): _guardar_json_seguro(ARCHIVO_PICKS, picks)
def cargar_estado():
    data = _cargar_json_seguro(ARCHIVO_ESTADO, DEFAULT_ESTADO)
    if not isinstance(data, dict): return json.loads(json.dumps(DEFAULT_ESTADO))
    data.setdefault("bloques_ejecutados", {})
    return data
def guardar_estado(estado): _guardar_json_seguro(ARCHIVO_ESTADO, estado)

# ==========================================
# 5. CONEXIÓN CON REINTENTOS
# ==========================================
def request_con_reintentos(url, headers, params, intentos=3, espera=5):
    for intento in range(1, intentos + 1):
        try:
            res = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            if res.status_code == 200: return res
            logger.warning(f"API respondió {res.status_code} (intento {intento}/{intentos})")
        except Exception as e:
            logger.warning(f"Intento {intento}/{intentos} falló: {e}")
        if intento < intentos: time.sleep(espera)
    return None

# ==========================================
# 6. HERRAMIENTAS AUXILIARES
# ==========================================
def _buscar_nombre_equipo(value, home_team, away_team):
    v = str(value or "").strip().lower()
    if v in {"home", "1", "local"} or str(home_team).lower() in v: return home_team
    if v in {"away", "2", "visitante", "visita"} or str(away_team).lower() in v: return away_team
    return home_team

def _es_mx_equivalente(nombre_bet): return str(nombre_bet or "").strip().lower()

def _extraer_fixture_id(item):
    if not isinstance(item, dict): return None
    for key in ("game", "fixture"):
        bloque = item.get(key)
        if isinstance(bloque, dict) and Custom_id := bloque.get("id"): return Custom_id
    return item.get("id") or item.get("fixture_id")

def mapear_icono_deporte(sport_key):
    return "⚾ MLB" if "mlb" in str(sport_key).lower() else "⚾ LMB"

# ==========================================
# 7. EXTRACCIÓN DE DATOS EN VIVO
# ==========================================
def obtener_estadisticas_equipo(league_id, team_id):
    url = "https://v1.baseball.api-sports.io/teams/statistics"
    headers = {"x-apisports-key": BASEBALL_API_KEY}
    params = {"league": str(league_id), "season": str(datetime.now(MX_TZ).year), "team": str(team_id)}
    try:
        res = request_con_reintentos(url, headers, params)
        if not res: return {}
        datos = res.json().get("response", {})
        if not datos: return {}
        carreras = datos.get("points", {})
        def _f(val):
            try: return float(str(val or 0.0).strip())
            except: return 0.0
        return {
            "promedio_favor_casa": _f(carreras.get("for", {}).get("average", {}).get("home", 0)),
            "contra_casa": _f(carreras.get("against", {}).get("average", {}).get("home", 0)),
            "promedio_favor_visita": _f(carreras.get("for", {}).get("average", {}).get("away", 0)),
            "contra_visita": _f(carreras.get("against", {}).get("average", {}).get("away", 0))
        }
    except: return {}

def obtener_partidos_api_sports(league_id):
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    url_games = "https://v1.baseball.api-sports.io/games"
    url_odds = "https://v1.baseball.api-sports.io/odds"
    headers = {"x-apisports-key": BASEBALL_API_KEY}
    params_games = {"league": str(league_id), "season": str(datetime.now(MX_TZ).year), "date": hoy, "timezone": "America/Mexico_City"}

    try:
        res_games = request_con_reintentos(url_games, headers, params_games)
        if not res_games: return []
        datos_games = res_games.json().get("response", [])
        fixtures = []
        for item in datos_games:
            fixture_id = _extraer_fixture_id(item)
            game = item.get("game") or item.get("fixture") or item
            if not isinstance(game, dict) or game.get("status", {}).get("short", "") not in ["NS", "Not Started"]: continue
            teams = game.get("teams", {})
            fixtures.append({
                "fixture_id": fixture_id, "home_id": teams.get("home", {}).get("id"), "home_team": teams.get("home", {}).get("name"),
                "away_id": teams.get("away", {}).get("id"), "away_team": teams.get("away", {}).get("name"), "commence_time": game.get("date", "")
            })

        if not fixtures: return []
        mapeo_datos = []
        for fx in fixtures:
            res_odds = request_con_reintentos(url_odds, headers, {"game": fx["fixture_id"]})
            if not res_odds: continue
            datos_odds = res_odds.json().get("response", [])
            if not datos_odds: continue
            stats_h = obtener_estadisticas_equipo(league_id, fx["home_id"])
            stats_a = obtener_estadisticas_equipo(league_id, fx["away_id"])

            for item in datos_odds:
                bookmakers = item.get("bookmakers", [])
                bms_mapeados = []
                for b in bookmakers:
                    if str(b.get("name", "")).lower() not in ["bet365", "betano", "pinnacle", "1xbet"]: continue
                    markets_mapeados = []
                    for bet in b.get("bets", []):
                        bn = _es_mx_equivalente(bet.get("name"))
                        vals = bet.get("values", [])
                        if any(k in bn for k in ["home/away", "moneyline", "winner", "gana"]):
                            outcomes = [{"name": _buscar_nombre_equipo(v.get("value"), fx["home_team"], fx["away_team"]), "price": float(v.get("odd", 0))} for v in vals]
                            markets_mapeados.append({"key": "h2h", "outcomes": outcomes})
                        elif any(k in bn for k in ["over/under", "totals"]):
                            outcomes = []
                            for v in vals:
                                ov_un = str(v.get("value", "")).lower()
                                p_str = re.sub(r"[^0-9\.]", "", ov_un)
                                outcomes.append({"name": "Over" if "over" in ov_un else "Under", "price": float(v.get("odd", 0)), "point": float(p_str or 8.5)})
                            markets_mapeados.append({"key": "totals", "outcomes": outcomes})
                    if markets_mapeados: bms_mapeados.append({"title": b.get("name"), "markets": markets_mapeados})
                
                if bms_mapeados:
                    mapeo_datos.append({
                        "home_team": fx["home_team"], "away_team": fx["away_team"], "commence_time": fx["commence_time"],
                        "bookmakers": bms_mapeados, "stats_home_team": stats_h, "stats_away_team": stats_a
                    })
        return mapeo_datos
    except: return []

# ==========================================
# 8. MOTOR DE DISTRIBUCIÓN DE POISSON Y REGRESIÓN DE LÍNEA
# ==========================================
def calcular_probabilidad_poisson(lambda_carreras, carreras_exactas):
    if lambda_carreras <= 0: return 0.0
    return (math.exp(-lambda_carreras) * (lambda_carreras ** carreras_exactas)) / math.factorial(carreras_exactas)

def evaluar_over_under_poisson(lambda_casa, lambda_visita, linea_casino):
    prob_under, prob_over, prob_push = 0.0, 0.0, 0.0
    for c_casa in range(16):
        for c_visita in range(16):
            p_combinada = calcular_probabilidad_poisson(lambda_casa, c_casa) * calcular_probabilidad_poisson(lambda_visita, c_visita)
            total_carreras = c_casa + c_visita
            if total_carreras < linea_casino: prob_under += p_combinada
            elif total_carreras > linea_casino: prob_over += p_combinada
            else: prob_push += p_combinada
    return {"Over": prob_over, "Under": prob_under, "Push": prob_push}

def calcular_sabermetria_y_borde(pick_data, modo_bloque):
    home_clean = str(pick_data["home_team"]).lower().strip()
    away_clean = str(pick_data["away_team"]).lower().strip()
    stats_h = pick_data.get("stats_home_team", {})
    stats_a = pick_data.get("stats_away_team", {})

    hf = stats_h.get("promedio_favor_casa", 4.8)
    hc = stats_h.get("contra_casa", 4.8)
    af = stats_a.get("promedio_favor_visita", 4.8)
    ac = stats_a.get("contra_visita", 4.8)

    wrc_h = WRC_PLUS_RANKING.get(home_clean, 100) / 100.0
    wrc_a = WRC_PLUS_RANKING.get(away_clean, 100) / 100.0
    pf = PARK_FACTORS.get(home_clean, 1.00)

    # NUEVA FÓRMULA DE REGRESIÓN NO LINEAL (Ajustada con la raíz cuadrada del Park Factor)
    proj_casa = ((hf * wrc_h / PROMEDIO_CARRERAS_LIGA) * (ac / PROMEDIO_CARRERAS_LIGA) * PROMEDIO_CARRERAS_LIGA) * math.sqrt(pf)
    proj_visita = ((af * wrc_a / PROMEDIO_CARRERAS_LIGA) * (hc / PROMEDIO_CARRERAS_LIGA) * PROMEDIO_CARRERAS_LIGA) * math.sqrt(pf)

    pick_str = pick_data["pick"].lower()
    mercado = pick_data["mercado_raw"]
    prob_calculada = 0.0
    detalles = ""

    if mercado == "totals":
        match = re.search(r"[\d\.]+", pick_str)
        linea_casino = float(match.group()) if match else 8.5
        if linea_casino <= 4.5: return 0.0, "" # Bloqueo absoluto de líneas basura

        # AISLAMIENTO F5 (55% del juego completo) PARA EL STAKE 10
        if modo_bloque == "stake_10":
            linea_f5 = round(linea_casino * 0.55, 1)
            matrices = evaluar_over_under_poisson(proj_casa * 0.55, proj_visita * 0.55, linea_f5)
            if "over" in pick_str or "altas" in pick_str:
                prob_calculada = matrices["Over"]
                pick_data["pick"] = f"F5 (Primeras 5 Entradas) Altas/Over {linea_f5}"
            else:
                prob_calculada = matrices["Under"]
                pick_data["pick"] = f"F5 (Primeras 5 Entradas) Bajas/Under {linea_f5}"
            detalles = f"Análisis F5 aislado: Matriz de Poisson proyecta un {(prob_calculada*100):.1f}% de éxito sobre la línea ajustada de {linea_f5}."
        else:
            matrices = evaluar_over_under_poisson(proj_casa, proj_visita, linea_casino)
            prob_calculada = matrices["Over"] if ("over" in pick_str or "altas" in pick_str) else matrices["Under"]
            detalles = f"Distribución de Poisson proyecta {(proj_casa+proj_visita):.2f} carreras totales en el parque. Probabilidad matemática: {(prob_calculada*100):.1f}%."

    elif mercado == "h2h":
        # Simulación simplificada de Moneyline por Poisson
        prob_home_gana = proj_casa / (proj_casa + proj_visita) if (proj_casa + proj_visita) > 0 else 0.5
        is_home = str(pick_data["home_team"]).lower() in pick_str
        prob_calculada = prob_home_gana if is_home else (1.0 - prob_home_gana)
        detalles = f"Regresión cruzada otorga una probabilidad de victoria del {(prob_calculada*100):.1f}% basada en ventaja relativa ofensiva/defensiva."

    # CÁLCULO CIENTÍFICO DEL EDGE ANTE LA CUOTA ACTUAL
    edge_real = (prob_calculada * pick_data["cuota"]) - 1
    return edge_real, detalles

def procesar_logica_matematica(candidatos_raw, cantidad, modo_bloque="normal"):
    picks_validos = []
    for c in candidatos_raw:
        edge, analisis = calcular_sabermetria_y_borde(c, modo_bloque)
        # VALIDACIÓN DEL FILTRO UMBRAL MÍNIMO (Mata líneas basura o evaporadas)
        if edge >= EDGE_MINIMO:
            c["ventaja"] = edge
            c["analisis_math"] = analisis
            picks_validos.append(c)

    picks_validos.sort(key=lambda x: x["ventaja"], reverse=True)
    finales, vistos = [], set()

    for p in picks_validos:
        partido = p["partido"]
        if modo_bloque == "stake_10":
            if p["ventaja"] < 0.08: continue # Exigencia del 8% de Edge para el Stake 10
            p["stake_num"] = 10
        else:
            if p["ventaja"] >= 0.12: p["stake_num"] = 4
            elif p["ventaja"] >= 0.08: p["stake_num"] = 3
            else: p["stake_num"] = 2

        if partido not in vistos:
            vistos.add(partido)
            p["analisis_math"] += f" Modelo detecta una ventaja (+EV) de +{(p['ventaja']*100):.1f}% sobre la línea del casino."
            finales.append(p)
        if len(finales) == cantidad: break
    return finales

# ==========================================
# 9. PROCESAMIENTO Y ENVÍO DE BLOQUES
# ==========================================
def procesar_bloque_especifico(lista_ligas, cantidad, modo_bloque="normal"):
    candidatos_crudos = []
    for liga in lista_ligas:
        partidos = obtener_partidos_api_sports(LIGAS_MAP.get(liga))
        for part in partidos:
            try: fh = datetime.fromisoformat(part.get("commence_time").replace("Z", "+00:00")).astimezone(MX_TZ).strftime("%I:%M %p")
            except: fh = "Por confirmar"
            for bookie in part.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    for o in market.get("outcomes", []):
                        if CUOTA_MIN <= o.get("price", 0) <= CUOTA_MAX:
                            candidatos_crudos.append({
                                "deporte": mapear_icono_deporte(liga), "partido": f"{part['home_team']} vs {part['away_team']}",
                                "home_team": part['home_team'], "away_team": part['away_team'], "fecha_hora": fh,
                                "pick": f"Gana {o['name']}" if market['key'] == "h2h" else f"{o['name']} {o['point']}",
                                "cuota": o['price'], "bookie": bookie['title'], "sport_key": liga, "mercado_raw": market['key'],
                                "stats_home_team": part['stats_home_team'], "stats_away_team": part['stats_away_team']
                            })
    return os_res := procesar_logica_matematica(candidatos_crudos, cantidad, modo_bloque)

def construir_mensaje(p):
    return (
        "🔥 El Bot Mexa – Pick del Día\n\n"
        f"Deporte: {p['deporte']}\n"
        f"Partido: {p['partido']}\n"
        f"Pick: {p['pick']}\n"
        f"Cuota: {float(p['cuota']):.2f} (Ref: {p['bookie']})\n"
        f"Stake: {'⭐' * p['stake_num']}\n\n"
        "📊 Análisis:\n"
        f"{p['analisis_math']}\n\n"
        "¡Vamos con todo! 💰"
    )

async def enviar_mensaje_seguro(texto):
    try: await bot.send_message(chat_id=CHANNEL_ID, text=texto, parse_mode=None)
    except Exception as e: logger.error(f"Error Telegram: {e}")

def _filtrar_picks_nuevos(picks):
    existentes = {f"{str(p.get('partido','')).strip().lower()}|{str(p.get('pick','')).strip().lower()}" for p in cargar_picks()}
    return [p for p in picks if f"{str(p.get('partido','')).strip().lower()}|{str(p.get('pick','')).strip().lower()}" not in existentes]

async def ejecutar_bloque_remodelado(nombre_bloque, ligas, cantidad, modo="normal", intro=None):
    picks_bloque = _filtrar_picks_nuevos(procesar_bloque_especifico(ligas, cantidad, modo))
    if not picks_bloque:
        logger.info(f"⏳ {nombre_bloque}: No se enviaron picks. Las cuotas en vivo no pasaron el filtro de Edge mínimo (+EV).")
        return
    actuales = cargar_picks()
    for p in picks_bloque: actuales.append(p)
    guardar_picks(actuales)
    if intro: await enviar_mensaje_seguro(intro); await asyncio.sleep(3)
    for p in picks_bloque: await enviar_mensaje_seguro(construir_mensaje(p)); await asyncio.sleep(5)

# ==========================================
# 10. BUCLE RELOJ CENTRAL
# ==========================================
async def main_loop():
    logger.info("Bot El Bot Mexa: Sistema Béisbol Sabermétrico Poisson V3.0 Iniciado.")
    estado = cargar_estado()
    while True:
        try:
            ahora = datetime.now(MX_TZ)
            fecha_str = ahora.strftime("%Y-%m-%d")
            if estado.get("fecha") != fecha_str:
                guardar_picks([]); estado["fecha"] = fecha_str
                estado["bloques_ejecutados"] = json.loads(json.dumps(DEFAULT_ESTADO["bloques_ejecutados"]))
                guardar_estado(estado)
            
            be = estado["bloques_ejecutados"]
            if ahora.hour == 8 and 30 <= ahora.minute <= 35 and be.get("buenos_dias") != fecha_str:
                await enviar_mensaje_seguro("¡Buenos días, Familia! ☀️ Arrancamos la jornada. Filtros de regresión de ventaja y matrices de Poisson listos. 💸")
                be["buenos_dias"] = fecha_str; guardar_estado(estado)
            elif ahora.hour == 10 and 0 <= ahora.minute <= 5 and be.get("mlb") != fecha_str:
                await ejecutar_bloque_remodelado("MLB Mañanero", ["baseball_mlb"], 3)
                be["mlb"] = fecha_str; guardar_estado(estado)
            elif ahora.hour == 16 and 0 <= ahora.minute <= 5 and be.get("lmb") != fecha_str:
                await ejecutar_bloque_remodelado("LMB Tarde", ["baseball_lmb_real"], 3, intro="Familia, líneas validadas bajo análisis de probabilidad discreta. Aquí los picks de la LMB: ⚾️🔥")
                be["lmb"] = fecha_str; guardar_estado(estado)
            elif ahora.hour == 16 and 30 <= ahora.minute <= 35 and be.get("stake10") != fecha_str:
                await ejecutar_bloque_remodelado("MÁXIMO VIP", LIGAS_PERMITIDAS, 1, modo="stake_10", intro="🚨 STAKE 10 DETECTADO 🚨\n\nAislamiento F5 de alta probabilidad activo. Ventaja matemática estricta:")
                be["stake10"] = fecha_str; guardar_estado(estado)
            elif ahora.hour == 23 and 58 <= ahora.minute <= 59 and be.get("buenas_noches") != fecha_str:
                await enviar_mensaje_seguro("🌙 ¡Buenas noches, equipo! Finalizan las actividades por hoy. ¡A descansar! 💤")
                be["buenas_noches"] = fecha_str; guardar_estado(estado)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Error reloj: {e}"); await asyncio.sleep(30)

if __name__ == "__main__": asyncio.run(main_loop())
