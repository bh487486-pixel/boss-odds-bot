import os
import re
import json
import sys
import time
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

# Inicialización de servicios
bot = Bot(token=TELEGRAM_TOKEN)

# Nombres de archivos locales
ARCHIVO_PICKS = "picks_hoy.json"
ARCHIVO_ESTADO = "estado_bot.json"

# Rango de cuotas permitidas
CUOTA_MIN = 1.15
CUOTA_MAX = 4.00

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
# 6. HERRAMIENTAS AUXILIARES DE PROCESAMIENTO
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

def _extraer_fixture_id(item):
    if not isinstance(item, dict):
        return None
    # Forzando búsqueda en "game" primero, luego "fixture"
    for key in ("game", "fixture"):
        bloque = item.get(key)
        if isinstance(bloque, dict) and bloque.get("id") is not None:
            return bloque.get("id")
    if item.get("id") is not None:
        return item.get("id")
    if item.get("fixture_id") is not None:
        return item.get("fixture_id")
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
            "promedio_favor_general": _f(carreras.get("for", {}).get("average", {}).get("all", 0)),
            "promedio_contra_general": _f(carreras.get("against", {}).get("average", {}).get("all", 0)),
            "promedio_favor_casa": _f(carreras.get("for", {}).get("average", {}).get("home", 0)),
            "promedio_contra_casa": _f(carreras.get("against", {}).get("average", {}).get("home", 0)),
            "promedio_favor_visita": _f(carreras.get("for", {}).get("average", {}).get("away", 0)),
            "promedio_contra_visita": _f(carreras.get("against", {}).get("average", {}).get("away", 0))
        }
    except Exception as e:
        logger.error(f"Error al obtener estadísticas del equipo {team_id}: {e}")
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
                for b in bookmakers:
                    nombre_casa = str(b.get("name", "")).lower()
                    if nombre_casa not in ["bet365", "bwin", "betano", "pinnacle", "1xbet"]:
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
                                markets_mapeados.append({"key": "h2h", "outcomes": outcomes})

                        elif any(k in bet_name for k in ["over/under", "totals", "total"]):
                            outcomes = []
                            for val in values:
                                over_under_str = str(val.get("value", ""))
                                try: odd_val = float(val.get("odd", 0))
                                except: continue
                                try:
                                    if "over" in over_under_str.lower():
                                        punto = float(re.sub(r"[^0-9\.\-]", "", over_under_str.replace("Over", "").strip()))
                                        outcomes.append({"name": "Over", "price": odd_val, "point": punto})
                                    elif "under" in over_under_str.lower():
                                        punto = float(re.sub(r"[^0-9\.\-]", "", over_under_str.replace("Under", "").strip()))
                                        outcomes.append({"name": "Under", "price": odd_val, "point": punto})
                                except ValueError:
                                    continue
                            if outcomes:
                                markets_mapeados.append({"key": "totals", "outcomes": outcomes})

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
                                outcomes.append({"name": team_name, "price": price, "point": point})
                            if outcomes:
                                markets_mapeados.append({"key": "spreads", "outcomes": outcomes})

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

            home_score = item.get("scores", {}).get("home", {}).get("current", 0)
            away_score = item.get("scores", {}).get("away", {}).get("current", 0)

            try: home_score = 0 if home_score is None else float(home_score)
            except: home_score = 0
            try: away_score = 0 if away_score is None else float(away_score)
            except: away_score = 0

            mapeo_scores.append({
                "home_team": home_team,
                "away_team": away_team,
                "completed": status in ["FT", "AOT"],
                "scores": [{"name": home_team, "score": str(home_score)}, {"name": away_team, "score": str(away_score)}]
            })
        return mapeo_scores
    except Exception as e:
        logger.error(f"Error API-Sports Scores: {e}")
        return []

# ==========================================
# 8. CEREBRO MATEMÁTICO PURO (SIN IA)
# ==========================================
def _clave_unica_pick(pick):
    return f"{str(pick.get('partido','')).strip().lower()}|{str(pick.get('pick','')).strip().lower()}"

def calcular_valor_estadistico(pick_data):
    stats_h = pick_data.get("estadisticas_local", {})
    stats_a = pick_data.get("estadisticas_visitante", {})

    # Extracción de promedios (prioridad a localía/visita real)
    hf = stats_h.get("promedio_favor_casa", stats_h.get("promedio_favor_general", 0))
    hc = stats_h.get("promedio_contra_casa", stats_h.get("promedio_contra_general", 0))
    af = stats_a.get("promedio_favor_visita", stats_a.get("promedio_favor_general", 0))
    ac = stats_a.get("promedio_contra_visita", stats_a.get("promedio_contra_general", 0))

    # Expectativa de carreras por equipo cruzando ataque vs defensa
    exp_home = (hf + ac) / 2
    exp_away = (af + hc) / 2
    exp_total = exp_home + exp_away
    diff = exp_home - exp_away # Positivo = Favor Local

    pick_str = pick_data["pick"].lower()
    mercado = pick_data["mercado_raw"]

    ventaja = 0.0
    esperado_str = ""

    if mercado == "totals":
        match = re.search(r"[\d\.]+", pick_str)
        linea = float(match.group()) if match else 8.5
        if "over" in pick_str or "altas" in pick_str:
            ventaja = exp_total - linea
            esperado_str = f"{exp_total:.2f} carreras en total"
        elif "under" in pick_str or "bajas" in pick_str:
            ventaja = linea - exp_total
            esperado_str = f"{exp_total:.2f} carreras en total"

    elif mercado == "h2h":
        team_name = pick_str.replace("gana ", "").strip().lower()
        home_name = str(pick_data["partido"].split(" vs ")[0]).lower()
        if team_name in home_name or home_name in team_name:
            ventaja = diff # Apuesta al local
            esperado_str = f"victoria local por un margen de {diff:.2f} carreras"
        else:
            ventaja = -diff # Apuesta al visitante
            esperado_str = f"victoria visitante por un margen de {-diff:.2f} carreras"

    elif mercado == "spreads":
        match = re.search(r"([-+]\d+\.?\d*)", pick_str)
        handicap = float(match.group(1)) if match else 0.0
        home_name = str(pick_data["partido"].split(" vs ")[0]).lower()
        if home_name in pick_str.lower():
            ventaja = diff + handicap
            esperado_str = f"desempeño local real de {diff:.2f} carreras"
        else:
            ventaja = (-diff) + handicap
            esperado_str = f"desempeño visitante real de {-diff:.2f} carreras"

    return round(ventaja, 2), esperado_str

def procesar_logica_matematica(candidatos_raw, cantidad, modo_bloque="normal"):
    picks_validos = []
    
    for c in candidatos_raw:
        ventaja, esperado_str = calcular_valor_estadistico(c)
        if ventaja > 0: # Solo picks con Value Positivo
            c["ventaja"] = ventaja
            c["esperado_str"] = esperado_str
            picks_validos.append(c)

    # Ordenar por el que tiene mayor ventaja estadística
    picks_validos.sort(key=lambda x: x["ventaja"], reverse=True)

    finales = []
    vistos = set()

    for p in picks_validos:
        partido = p["partido"]
        
        # FILTRO DE HIERRO PARA STAKE 10
        if modo_bloque == "stake_10":
            if p["ventaja"] < 1.5: 
                continue # Rechazar si no hay ventaja enorme
            p["stake_num"] = 10
        else:
            if p["ventaja"] < 0.5:
                continue # Evita mandar basura en bloques normales
            if p["ventaja"] >= 1.5: p["stake_num"] = 4
            elif p["ventaja"] >= 1.0: p["stake_num"] = 3
            else: p["stake_num"] = 2

        if partido not in vistos:
            vistos.add(partido)
            p["analisis_math"] = (
                f"Análisis Matemático: El algoritmo proyecta {p['esperado_str']} cruzando el pitcheo y bateo local/visitante. "
                f"Contra la línea ofrecida en los casinos, detectamos un borde estadístico de {p['ventaja']} unidades a favor. "
                "Jugada basada 100% en promedios reales y probabilidad."
            )
            finales.append(p)
            
        if len(finales) == cantidad:
            break

    return finales

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
                    fecha_hora_str = datetime.fromisoformat(partido.get("commence_time").replace("Z", "+00:00")).astimezone(MX_TZ).strftime("%I:%M %p")
                except: pass

            for bookie in partido.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    mk = market.get("key")
                    for o in market.get("outcomes", []):
                        cuota = o.get("price")
                        if isinstance(cuota, (int, float)) and CUOTA_MIN <= cuota <= CUOTA_MAX:
                            if mk == "h2h": tp = f"Gana {o.get('name')}"
                            elif mk == "totals": tp = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {o.get('point', 0)}"
                            elif mk == "spreads": tp = f"Hándicap {o.get('name')} {o.get('point', 0):+g}"
                            else: continue

                            candidatos_crudos.append({
                                "deporte": mapear_icono_deporte(liga),
                                "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                                "fecha_hora": fecha_hora_str,
                                "pick": tp,
                                "cuota": float(cuota),
                                "bookie": bookie.get("title"),
                                "sport_key": liga,
                                "mercado_raw": mk,
                                "estadisticas_local": partido.get("stats_home_team", {}),
                                "estadisticas_visitante": partido.get("stats_away_team", {})
                            })

    return procesar_logica_matematica(candidatos_crudos, cantidad, modo_bloque)

def construir_mensaje(pick_data):
    stk = pick_data.get("stake_num", 2)
    return (
        "🔥 El Bot Mexa – Pick del Día\n\n"
        f"Deporte: {pick_data.get('deporte')}\n"
        f"Partido: {pick_data.get('partido')}\n"
        f"Pick: {pick_data.get('pick')}\n"
        f"Cuota: {float(pick_data.get('cuota', 0)):.2f}\n"
        f"Stake: {'⭐' * stk}\n\n"
        "📊 Análisis:\n"
        f"{pick_data.get('analisis_math')}\n\n"
        "¡Vamos con todo! 💰"
    )

async def enviar_mensaje_seguro(texto):
    try: await bot.send_message(chat_id=CHANNEL_ID, text=texto, parse_mode=None)
    except Exception as e: logger.error(f"Error Telegram: {e}")

def _filtrar_picks_nuevos(picks):
    existentes = {_clave_unica_pick(p) for p in cargar_picks()}
    return [p for p in picks if _clave_unica_pick(p) not in existentes]

async def ejecutar_bloque_remodelado(nombre_bloque, ligas, cantidad, modo="normal", intro=None):
    picks_bloque = _filtrar_picks_nuevos(procesar_bloque_especifico(ligas, cantidad, modo))

    if not picks_bloque:
        await enviar_mensaje_seguro(f"⏳ Sistema {nombre_bloque}: Monitoreando mercado... líneas no alcanzan la ventaja matemática requerida.")
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
                    marcador = f"{sc[0]['name']} {sc[0]['score']} - {sc[1]['score']} {sc[1]['name']} 🏁"
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
    logger.info("Bot El Bot Mexa: Sistema Béisbol Matemático Iniciado.")
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

            # 4:30 PM - MÁXIMO VIP (STAKE 10)
            elif ahora.hour == 16 and 30 <= ahora.minute <= 35 and be["stake10"] != fecha_str:
                await ejecutar_bloque_remodelado("MÁXIMO VIP", LIGAS_PERMITIDAS, 1, modo="stake_10", intro="🚨 STAKE 10 DETECTADO 🚨\n\nMotor matemático al límite. Vamos pesados aquí:")
                be["stake10"] = fecha_str
                guardar_estado(estado)

            # 11:45 PM - Reporte Profit
            elif ahora.hour == 23 and 45 <= ahora.minute <= 50 and be["reporte"] != fecha_str:
                await mandar_reporte_profit()
                be["reporte"] = fecha_str
                guardar_estado(estado)

            # 11:55 PM - Anuncio Mundial
            elif fecha_str == "2026-06-04" and ahora.hour == 23 and 55 <= ahora.minute <= 57 and be.get("mundial") != fecha_str:
                mensaje_mundial = "🚨 ¡Familia, ya se viene la semana de la Copa del Mundo! Tengan sus notificaciones activadas porque se vienen picks muy jugosos con el mejor, El Boss Mexa. ⚽🏆"
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
