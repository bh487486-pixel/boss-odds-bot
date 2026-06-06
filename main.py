import os
import re
import json
import sys
import time
import random
import asyncio
import logging
from datetime import datetime

import requests
from telegram import Bot
import google.generativeai as genai

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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BASEBALL_API_KEY = os.getenv("BASEBALL_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")

if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY, BASEBALL_API_KEY]):
    logger.error("❌ ¡ALERTA! Faltan variables de entorno obligatorias en Render.")
    sys.exit(1)

# Inicialización de servicios
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL_NAME)
bot = Bot(token=TELEGRAM_TOKEN)

# Nombres de archivos locales
ARCHIVO_PICKS = "picks_hoy.json"
ARCHIVO_ESTADO = "estado_bot.json"

# Rango de cuotas permitidas
CUOTA_MIN = 1.00
CUOTA_MAX = 10.00

# Ligas centralizadas en API-Sports
LIGAS_PERMITIDAS = ["baseball_mlb", "baseball_lmb_real"]

# Mapeo de IDs oficiales
LIGAS_MAP = {
    "baseball_mlb": "1",
    "baseball_lmb_real": "21",
}

DEFAULT_ESTADO = {
    "fecha": None,
    "bloques_ejecutados": {
        "buenos_dias": None,
        "mlb": None,
        "lmb": None,
        "stake10": None,
        "reporte": None,
        "buenas_noches": None,
        "mundial": None
    }
}

REQUEST_TIMEOUT = (10, 30)

# ==========================================
# 4. CONTROL DE ARCHIVOS LOCALES
# ==========================================
def _cargar_json_seguro(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error al leer {path}: {e}")
        return fallback

def _guardar_json_seguro(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error al guardar {path}: {e}")

def cargar_picks():
    data = _cargar_json_seguro(ARCHIVO_PICKS, [])
    return data if isinstance(data, list) else []

def guardar_picks(picks):
    if not isinstance(picks, list):
        return
    _guardar_json_seguro(ARCHIVO_PICKS, picks)

def cargar_estado():
    data = _cargar_json_seguro(ARCHIVO_ESTADO, DEFAULT_ESTADO)
    if not isinstance(data, dict):
        return json.loads(json.dumps(DEFAULT_ESTADO))
    if "bloques_ejecutados" not in data or not isinstance(data["bloques_ejecutados"], dict):
        data["bloques_ejecutados"] = json.loads(json.dumps(DEFAULT_ESTADO["bloques_ejecutados"]))
    for k, v in DEFAULT_ESTADO["bloques_ejecutados"].items():
        data["bloques_ejecutados"].setdefault(k, v)
    data.setdefault("fecha", None)
    return data

def guardar_estado(estado):
    if not isinstance(estado, dict):
        return
    _guardar_json_seguro(ARCHIVO_ESTADO, estado)

# ==========================================
# 5. CONEXIÓN CON REINTENTOS (MÉTODO GET)
# ==========================================
def request_con_reintentos(url, headers, params, intentos=3, espera=5):
    for intento in range(1, intentos + 1):
        try:
            res = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            if res.status_code == 200:
                return res
            logger.warning(f"API respondió {res.status_code} (intento {intento}/{intentos})")
        except Exception as e:
            logger.warning(f"Intento {intento}/{intentos} falló: {e}")

        if intento < intentos:
            time.sleep(espera)
    return None

# ==========================================
# 6. HERRAMIENTAS AUXILIARES
# ==========================================
def _buscar_nombre_equipo(value, home_team, away_team):
    v = str(value or "").strip().lower()
    home_l = str(home_team).lower()
    away_l = str(away_team).lower()

    if v in {"home", "1", "local"} or home_l in v:
        return home_team
    if v in {"away", "2", "visitante", "visita"} or away_l in v:
        return away_team
    if v == str(home_team).strip().lower() or v == str(away_team).strip().lower():
        return home_team if v == str(home_team).strip().lower() else away_team
    return None

def _es_mx_equivalente(nombre_bet):
    return str(nombre_bet or "").strip().lower()

# EXTRACCIÓN BLINDADA: Busca forzosamente "game" o "fixture" en todos los niveles
def _extraer_fixture_id(item):
    if not isinstance(item, dict): return None
    if item.get("id") is not None: return item.get("id")
    if item.get("fixture_id") is not None: return item.get("fixture_id")
    
    for key in ("game", "fixture"):
        bloque = item.get(key)
        if isinstance(bloque, dict) and bloque.get("id") is not None:
            return bloque.get("id")
    return None

def mapear_icono_deporte(sport_key):
    sport_key_lower = str(sport_key).lower()
    if "baseball_mlb" in sport_key_lower:
        return "⚾ MLB"
    if "baseball_lmb" in sport_key_lower:
        return "⚾ LMB"
    return "🏅 Deporte"

# ==========================================
# 7. EXTRACCIÓN DE DATOS Y ESTADÍSTICAS EN VIVO
# ==========================================
def obtener_estadisticas_equipo(league_id, team_id):
    url = "https://v1.baseball.api-sports.io/teams/statistics"
    headers = {"x-apisports-key": BASEBALL_API_KEY}
    params = {
        "league": str(league_id),
        "season": str(datetime.now(MX_TZ).year),
        "team": str(team_id)
    }
    
    try:
        res = request_con_reintentos(url, headers, params)
        if not res: return {}
        datos = res.json().get("response", {})
        if not datos: return {}
            
        juegos_totales = datos.get("games", {}).get("played", {}).get("all", 0)
        if juegos_totales == 0: return {}
            
        carreras = datos.get("points", {})
        def _f(val):
            try: return float(str(val or 0.0).strip())
            except: return 0.0

        return {
            "juegos_disputados": juegos_totales,
            "carreras_favor_total": _f(carreras.get("for", {}).get("total", {}).get("all", 0)),
            "carreras_contra_total": _f(carreras.get("against", {}).get("total", {}).get("all", 0)),
            "promedio_favor_general": _f(carreras.get("for", {}).get("average", {}).get("all", 0)),
            "promedio_contra_general": _f(carreras.get("against", {}).get("average", {}).get("all", 0)),
            "promedio_favor_casa": _f(carreras.get("for", {}).get("average", {}).get("home", 0)),
            "promedio_contra_visita": _f(carreras.get("against", {}).get("average", {}).get("away", 0))
        }
    except Exception as e:
        logger.error(f"Error al obtener estadísticas: {e}")
        return {}

def obtener_partidos_api_sports(league_id):
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    url_games = "https://v1.baseball.api-sports.io/games"
    url_odds = "https://v1.baseball.api-sports.io/odds"
    headers = {"x-apisports-key": BASEBALL_API_KEY}

    params_games = {
        "league": str(league_id),
        "season": str(datetime.now(MX_TZ).year),
        "date": hoy,
        "timezone": "America/Mexico_City"
    }

    try:
        res_games = request_con_reintentos(url_games, headers, params_games)
        if not res_games: return []

        datos_games = res_games.json().get("response", [])
        fixtures = []
        for item in datos_games:
            fixture_id = _extraer_fixture_id(item)
            
            # Asegurar extracción desde "game" o "fixture"
            game = item.get("game") or item.get("fixture") or item
            if not isinstance(game, dict): continue
            
            status = game.get("status", {}).get("short", "")
            if status not in ["NS", "Not Started"]: continue

            teams = game.get("teams", {})
            home_id = teams.get("home", {}).get("id")
            home_team = teams.get("home", {}).get("name", "Home")
            away_id = teams.get("away", {}).get("id")
            away_team = teams.get("away", {}).get("name", "Away")
            commence_time = game.get("date", "") or item.get("date", "")

            if fixture_id is not None and home_id and away_id:
                fixtures.append({
                    "fixture_id": fixture_id,
                    "home_id": home_id,
                    "home_team": home_team,
                    "away_id": away_id,
                    "away_team": away_team,
                    "commence_time": commence_time
                })

        if not fixtures: return []

        mapeo_datos = []
        for fixture in fixtures:
            res_odds = request_con_reintentos(url_odds, headers, {"game": fixture["fixture_id"]})
            if not res_odds: continue

            datos_odds = res_odds.json().get("response", [])
            if not datos_odds: continue

            stats_home = obtener_estadisticas_equipo(league_id, fixture["home_id"])
            stats_away = obtener_estadisticas_equipo(league_id, fixture["away_id"])

            for item in datos_odds:
                game = item.get("game") or item.get("fixture") or {}
                if not isinstance(game, dict): game = {}

                teams = game.get("teams", {})
                home_team = teams.get("home", {}).get("name", fixture["home_team"])
                away_team = teams.get("away", {}).get("name", fixture["away_team"])
                commence_time = game.get("date", "") or fixture["commence_time"]
                bookmakers = item.get("bookmakers", [])

                bms_mapeados = []
                casas_permitidas = ["pinnacle", "1xbet", "betano", "bet365"]
                
                for b in bookmakers:
                    nombre_casa = str(b.get("name", "")).lower()
                    if not any(casa in nombre_casa for casa in casas_permitidas):
                        continue

                    bets = b.get("bets", [])
                    markets_mapeados = []

                    for bet in bets:
                        bet_name = _es_mx_equivalente(bet.get("name"))
                        values = bet.get("values", [])

                        if any(k in bet_name for k in ["home/away", "moneyline", "match winner", "winner", "h2h", "gana", "ganador"]):
                            outcomes = []
                            for val in values:
                                try: price = float(val.get("odd", 0))
                                except: continue
                                team_name = _buscar_nombre_equipo(val.get("value"), home_team, away_team)
                                if not team_name: team_name = home_team if len(outcomes) == 0 else away_team
                                outcomes.append({"name": team_name, "price": price})
                            if len(outcomes) >= 2:
                                markets_mapeados.append({"key": "Ganador Directo (Moneyline)", "outcomes": outcomes})

                        elif any(k in bet_name for k in ["over/under", "totals", "total"]):
                            outcomes = []
                            for val in values:
                                over_under_str = str(val.get("value", ""))
                                try: odd_val = float(val.get("odd", 0))
                                except: continue
                                try:
                                    if "over" in over_under_str.lower():
                                        punto = float(re.sub(r"[^0-9\.\-]", "", over_under_str.replace("Over", "").strip()))
                                        outcomes.append({"name": f"Over {punto}", "price": odd_val})
                                    elif "under" in over_under_str.lower():
                                        punto = float(re.sub(r"[^0-9\.\-]", "", over_under_str.replace("Under", "").strip()))
                                        outcomes.append({"name": f"Under {punto}", "price": odd_val})
                                except ValueError:
                                    continue
                            if outcomes:
                                markets_mapeados.append({"key": "Total de Carreras Generales", "outcomes": outcomes})

                        elif any(k in bet_name for k in ["handicap", "spread", "run line", "runline", "run"]):
                            outcomes = []
                            for val in values:
                                try: price = float(val.get("odd", 0))
                                except: continue
                                raw_name = val.get("value")
                                team_name = _buscar_nombre_equipo(raw_name, home_team, away_team) or home_team
                                point_raw = val.get("point") or val.get("handicap") or val.get("line")
                                try: point = float(point_raw) if point_raw is not None else 0.0
                                except: point = 0.0
                                outcomes.append({"name": f"{team_name} {point:+g}", "price": price})
                            if outcomes:
                                markets_mapeados.append({"key": "Hándicap (Runline)", "outcomes": outcomes})

                    if markets_mapeados:
                        bms_mapeados.append({"title": b.get("name", "Bookmaker"), "markets": markets_mapeados})

                if bms_mapeados:
                    mapeo_datos.append({
                        "home_team": home_team,
                        "away_team": away_team,
                        "commence_time": commence_time,
                        "bookmakers": bms_mapeados,
                        "stats_home_team": stats_home,
                        "stats_away_team": stats_away
                    })

        return mapeo_datos
    except Exception as e:
        logger.error(f"Error API-Sports Odds: {e}")
        return []

def obtener_marcadores_api_sports(league_id):
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    url = "https://v1.baseball.api-sports.io/games"
    headers = {"x-apisports-key": BASEBALL_API_KEY}
    params = {"league": str(league_id), "season": str(datetime.now(MX_TZ).year), "date": hoy, "timezone": "America/Mexico_City"}

    try:
        res = request_con_reintentos(url, headers, params)
        if not res: return []

        datos = res.json().get("response", [])
        mapeo_scores = []

        for item in datos:
            home_team = item.get("teams", {}).get("home", {}).get("name", "Home")
            away_team = item.get("teams", {}).get("away", {}).get("name", "Away")
            status = item.get("status", {}).get("short", "")

            # ARREGLO CRÍTICO: Buscar carreras en 'total' para evitar el bug de 0.0 del Profit
            scores_obj = item.get("scores", {})
            home_obj = scores_obj.get("home")
            away_obj = scores_obj.get("away")

            def parse_score(val):
                if isinstance(val, dict):
                    # En la API de Béisbol se guarda normalmente en 'total'
                    return float(val.get("total", val.get("current", 0)) or 0)
                try:
                    return float(val or 0)
                except:
                    return 0.0

            home_score = parse_score(home_obj)
            away_score = parse_score(away_obj)

            mapeo_scores.append({
                "home_team": home_team,
                "away_team": away_team,
                # Validar estatus de finalizado de béisbol
                "completed": status in ["FT", "AOT", "Finished", "F/O"],
                "scores": [{"name": home_team, "score": str(home_score)}, {"name": away_team, "score": str(away_score)}]
            })
        return mapeo_scores
    except Exception as e:
        logger.error(f"Error API-Sports Scores: {e}")
        return []

# ==========================================
# 8. CEREBRO INTELIGENCIA ARTIFICIAL (GEMINI) - MODO DEPORTIVO
# ==========================================
def _extraer_json_lista(texto):
    if not texto: return []
    txt = texto.strip().replace("`" * 3 + "json", "").replace("`" * 3, "").strip()
    inicio, fin = txt.find("["), txt.rfind("]")
    if inicio != -1 and fin != -1 and fin > inicio:
        return json.loads(txt[inicio:fin + 1].strip())
    inicio, fin = txt.find("{"), txt.rfind("}")
    if inicio != -1 and fin != -1 and fin > inicio:
        obj = json.loads(txt[inicio:fin + 1].strip())
        return obj if isinstance(obj, list) else [obj]
    return []

def _clave_unica_pick(pick):
    return f"{str(pick.get('partido','')).strip().lower()}|{str(pick.get('pick','')).strip().lower()}"

def consultar_cerebro_ia(candidatos_raw, cantidad, modo_bloque="normal"):
    if not candidatos_raw: return []
    
    # Seleccionamos una muestra aleatoria para no saturar el token de la IA
    random.shuffle(candidatos_raw)
    datos_para_ia = json.dumps(candidatos_raw[:30], ensure_ascii=False)

    base_instruccion = (
        "Eres El Bot Mexa, el tipster profesional más letal de béisbol en México.\n"
        "FILTRO ÚNICO (Probabilidad Deportiva REAL): Analiza las estadísticas provistas (promedios de carreras a favor y en contra). Si un pick NO tiene sentido en el diamante real (ej. ir a altas de carreras con equipos que no batean), DESCÁRTALO.\n"
        "Tu objetivo es seleccionar las jugadas con mayor probabilidad de acierto basadas puramente en la estadística y el contexto deportivo, eligiendo la cuota más atractiva disponible en los datos.\n"
        "REGLA DE ORO: ¡PROHIBIDO INVENTAR CUOTAS! Los valores deben ser COPIADOS EXACTAMENTE de los datos proporcionados.\n"
        "Reglas finales:\n"
        f"1. Selecciona EXACTAMENTE los {cantidad} mejores picks.\n"
        "2. Redacta el 'analisis_deportivo' explicando con argumentos reales por qué este pick VA A DARSE en el campo.\n"
        "REGLA CRÍTICA: Devuelve SOLO el siguiente formato JSON plano (sin markdown ni texto extra):\n"
    )

    prompt = (
        base_instruccion +
        "[{\"deporte\": \"⚾ Béisbol\", \"partido\": \"Equipo A vs Equipo B\", \"fecha_hora\": \"\", \"pick\": \"\", \"mercado\": \"\", \"cuota\": 0.0, \"casa_apuestas\": \"\", \"stake_num\": 2, \"analisis_deportivo\": \"\"}]"
    )

    try:
        time.sleep(2)
        response = model.generate_content(prompt + "\n\nDatos de Juegos (Estadísticas y Cuotas):\n" + datos_para_ia)
        picks_seleccionados = _extraer_json_lista(getattr(response, "text", ""))
        
        finales = []
        partidos_vistos = set()
        
        for p in picks_seleccionados:
            if not isinstance(p, dict): continue
            partido = str(p.get("partido", "")).strip().lower()
            if partido in partidos_vistos: continue
            partidos_vistos.add(partido)
            if modo_bloque == "stake_10": p["stake_num"] = 10
            finales.append(p)
            if len(finales) == cantidad: break
            
        return finales

    except Exception as e:
        logger.error(f"Error de IA: {e}")
        return []

# ==========================================
# 9. PROCESAMIENTO Y ENVÍO DE BLOQUES
# ==========================================
def procesar_bloque_especifico(lista_ligas, cantidad, modo_bloque="normal"):
    candidatos_crudos = []
    for liga in lista_ligas:
        if liga not in LIGAS_PERMITIDAS: continue
        league_id = LIGAS_MAP.get(liga)
        partidos = obtener_partidos_api_sports(league_id)
        
        for partido in partidos:
            fecha_hora_str = "Horario por confirmar"
            if partido.get("commence_time"):
                try:
                    fecha_hora_str = datetime.fromisoformat(partido.get("commence_time").replace("Z", "+00:00")).astimezone(MX_TZ).strftime("%Y-%m-%d | %I:%M %p")
                except: pass

            for bookie in partido.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    mk = market.get("key")
                    for o in market.get("outcomes", []):
                        cuota = o.get("price")
                        if isinstance(cuota, (int, float)) and CUOTA_MIN <= cuota <= CUOTA_MAX:
                            candidatos_crudos.append({
                                "deporte": mapear_icono_deporte(liga),
                                "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                                "fecha_hora": fecha_hora_str,
                                "pick": o.get('name'),
                                "mercado": mk,
                                "cuota": float(cuota),
                                "bookie": bookie.get("title"),
                                "estadisticas_local": partido.get("stats_home_team", {}),
                                "estadisticas_visitante": partido.get("stats_away_team", {})
                            })

    return consultar_cerebro_ia(candidatos_crudos, cantidad, modo_bloque)

def construir_mensaje(pick_data):
    stk = max(1, min(int(pick_data.get("stake_num", 2)), 10))
    return (
        "🔥 El Bot Mexa – Pick del Día\n\n"
        f"Deporte: {pick_data.get('deporte', '⚾ Béisbol')}\n"
        f"🗓 Fecha y Hora: {pick_data.get('fecha_hora', 'Por confirmar')}\n"
        f"Partido: {pick_data.get('partido')}\n"
        f"🎯 Pick: {pick_data.get('pick')}\n"
        f"⚖️ Mercado: {pick_data.get('mercado')}\n\n"
        f"📈 Cuota: {float(pick_data.get('cuota', 0)):.2f} (Referencia: {pick_data.get('casa_apuestas', 'Casino')})\n\n"
        f"Stake: {'⭐' * stk}\n\n"
        "🧠 Análisis Deportivo:\n"
        f"{pick_data.get('analisis_deportivo')}\n\n"
        "💡 NOTA IMPORTANTE:\n"
        "Esta cuota podría estar disponible en otras casas de apuestas. Revisen también en PlayDoit, Team México, Caliente, Codere, Winpot o Betway. ¡Aprovechen el valor y vamos con todo! 💰"
    )

async def enviar_mensaje_seguro(texto):
    try: await bot.send_message(chat_id=CHANNEL_ID, text=texto, parse_mode=None)
    except Exception as e: logger.error(f"Error Telegram: {e}")

def _filtrar_picks_nuevos(picks):
    existentes = {_clave_unica_pick(p) for p in cargar_picks()}
    return [p for p in picks if _clave_unica_pick(p) not in existentes]

async def ejecutar_bloque_remodelado(nombre_bloque, ligas, cantidad, modo="normal", intro=None):
    picks_bloque = []
    for intento in range(3):
        picks_bloque = _filtrar_picks_nuevos(procesar_bloque_especifico(ligas, cantidad, modo))
        if picks_bloque: break
        await asyncio.sleep(600)

    if not picks_bloque:
        await enviar_mensaje_seguro(f"⏳ Sistema {nombre_bloque}: Monitoreando mercado... líneas aún no abiertas o sin cuotas de valor detectadas.")
        return

    actuales = cargar_picks()
    for p in picks_bloque: actuales.append(p)
    guardar_picks(actuales)

    if intro:
        await enviar_mensaje_seguro(intro)
        await asyncio.sleep(3)

    for pick in picks_bloque:
        await enviar_mensaje_seguro(construir_mensaje(pick))
        await asyncio.sleep(5)

# ==========================================
# 10. EVALUACIÓN Y REPORTES DE PROFIT
# ==========================================
def _extraer_linea_pick(pick_str):
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*$", pick_str.strip())
    return float(match.group(1)) if match else 0.0

def evaluar_pick(pick_str, scores):
    try:
        s1, s2 = float(scores[0]["score"]), float(scores[1]["score"])
        n1, n2 = scores[0]["name"].lower(), scores[1]["name"].lower()
        p = str(pick_str or "").strip().lower()

        if "gana" in p:
            team = p.replace("gana ", "").strip()
            winner = n1 if s1 > s2 else (n2 if s2 > s1 else None)
            return "🟢 GANADO" if winner == team else ("⚪ PUSH" if winner is None else "🔴 PERDIDO")
        elif "over" in p or "under" in p or "altas" in p or "bajas" in p:
            total = s1 + s2
            linea = _extraer_linea_pick(pick_str)
            if "over" in p or "altas" in p:
                return "🟢 GANADO" if total > linea else ("🔴 PERDIDO" if total < linea else "⚪ PUSH")
            else:
                return "🟢 GANADO" if total < linea else ("🔴 PERDIDO" if total > linea else "⚪ PUSH")
        return "❔ RESULTADO MANUAL"
    except: return "❔ REVISAR"

async def mandar_reporte_profit():
    picks = cargar_picks()
    if not picks: return
    resultados = []
    for liga in list(set([p.get("sport_key") for p in picks if p.get("sport_key")])):
        resultados += obtener_marcadores_api_sports(LIGAS_MAP.get(liga))

    ganados, perdidos, total = 0, 0, 0
    msg = "📊 El Bot Mexa – Resumen de la Jornada 📊\n\nResultados oficiales:\n\n"

    for pick in picks:
        status, marcador = "❔ Pendiente", "Marcador no disponible ⏳"
        for res in resultados:
            if res.get("home_team") in pick.get("partido") and res.get("away_team") in pick.get("partido"):
                if res.get("completed"):
                    sc = res.get("scores")
                    # ARREGLO VISUAL DEL FORMATO (Evitamos el 0.0 decimal si es número entero)
                    score_home = int(float(sc[0]['score'])) if float(sc[0]['score']).is_integer() else sc[0]['score']
                    score_away = int(float(sc[1]['score'])) if float(sc[1]['score']).is_integer() else sc[1]['score']
                    marcador = f"{sc[0]['name']} {score_home} - {score_away} {sc[1]['name']} 🏁"
                    
                    status = evaluar_pick(pick.get("pick"), sc)
                    if "GANADO" in status: ganados += 1
                    elif "PERDIDO" in status: perdidos += 1
                    total += 1
                break
        msg += f"🔥 {pick.get('partido')}\nPick: {pick.get('pick')}\nResultado: {marcador}\nEstatus: {status}\n\n"

    porcentaje = (ganados / total * 100) if total > 0 else 0.0
    msg += f"📈 Efectividad: {porcentaje:.1f}%\n🟢 GANADOS: {ganados} | 🔴 PERDIDOS: {perdidos}\n\n¡Mañana regresamos por más! 💰"
    await enviar_mensaje_seguro(msg)

# ==========================================
# 11. BUCLE DE TIEMPO CENTRAL (RELOJ)
# ==========================================
async def main_loop():
    logger.info("Bot El Bot Mexa: Sistema Béisbol Unificado Iniciado.")
    estado = cargar_estado()
    
    while True:
        try:
            ahora = datetime.now(MX_TZ)
            fecha_str = ahora.strftime("%Y-%m-%d")

            if estado.get("fecha") != fecha_str:
                guardar_picks([])
                estado["fecha"] = fecha_str
                estado["bloques_ejecutados"] = json.loads(json.dumps(DEFAULT_ESTADO["bloques_ejecutados"]))
                guardar_estado(estado)
                logger.info(f"🧹 Nuevo día detectado: {fecha_str}. Estado reiniciado.")

            be = estado["bloques_ejecutados"]

            # 8:30 AM - Buenos Días
            if ahora.hour == 8 and 30 <= ahora.minute <= 35 and be["buenos_dias"] != fecha_str:
                await enviar_mensaje_seguro("¡Buenos días, Familia! ☀️ Arrancamos una nueva jornada de análisis deportivo. En breve salen las primeras jugadas del día. ¡A facturar hoy! 💸")
                be["buenos_dias"] = fecha_str
                guardar_estado(estado)

            # 10:00 AM - MLB Mañanero
            elif ahora.hour == 10 and 0 <= ahora.minute <= 5 and be["mlb"] != fecha_str:
                await ejecutar_bloque_remodelado("MLB Mañanero", ["baseball_mlb"], 3)
                be["mlb"] = fecha_str
                guardar_estado(estado)

            # 4:00 PM - LMB Tarde 
            elif ahora.hour == 16 and 0 <= ahora.minute <= 5 and be["lmb"] != fecha_str:
                await ejecutar_bloque_remodelado("LMB Tarde", ["baseball_lmb_real"], 3, intro="Familia, ya están abiertas las líneas. Aquí tienen los picks de la Liga Mexicana de Béisbol. ⚾️🔥")
                be["lmb"] = fecha_str
                guardar_estado(estado)

            # 4:30 PM - MÁXIMO VIP (STAKE 10) - Analiza todos los mercados de ambas ligas
            elif ahora.hour == 16 and 30 <= ahora.minute <= 35 and be["stake10"] != fecha_str:
                await ejecutar_bloque_remodelado("MÁXIMO VIP", LIGAS_PERMITIDAS, 1, modo="stake_10", intro="🚨 STAKE 10 DETECTADO 🚨\n\nInteligencia algorítmica aplicada. Vamos pesados aquí:")
                be["stake10"] = fecha_str
                guardar_estado(estado)

            # 11:45 PM - Reporte Profit
            elif ahora.hour == 23 and 45 <= ahora.minute <= 50 and be["reporte"] != fecha_str:
                await mandar_reporte_profit()
                be["reporte"] = fecha_str
                guardar_estado(estado)

            # 11:55 PM - Anuncio Mundial
            elif fecha_str == "2026-06-04" and ahora.hour == 23 and 55 <= ahora.minute <= 57 and be.get("mundial") != fecha_str:
                mensaje_mundial = "🚨 ¡Familia, ya se viene la semana de la Copa del Mundo! Tengan sus notificaciones activadas porque se vienen picks muy jugosos con el mejor, El Bot Mexa. ⚽🏆"
                await enviar_mensaje_seguro(mensaje_mundial)
                be["mundial"] = fecha_str
                guardar_estado(estado)

            # 11:58 PM - Buenas Noches
            elif ahora.hour == 23 and 58 <= ahora.minute <= 59 and be["buenas_noches"] != fecha_str:
                await enviar_mensaje_seguro("🌙 ¡Buenas noches, equipo! 🌙\n\nFinalizan las actividades por hoy. ¡A descansar! 💤")
                be["buenas_noches"] = fecha_str
                guardar_estado(estado)

            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Error en bucle del reloj: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
