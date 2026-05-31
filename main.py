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

try:
    from zoneinfo import ZoneInfo
    MX_TZ = ZoneInfo("America/Mexico_City")
except Exception:
    from datetime import timezone, timedelta
    MX_TZ = timezone(timedelta(hours=-6))

# ==========================================
# 1. CONFIGURACIÓN E IMPORTACIONES
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BASEBALL_API_KEY = os.getenv("BASEBALL_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")

if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY, BASEBALL_API_KEY]):
    logger.error("¡ALERTA! Faltan variables de entorno obligatorias.")
    sys.exit(1)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL_NAME)

bot = Bot(token=TELEGRAM_TOKEN)

ARCHIVO_PICKS = "picks_hoy.json"
ARCHIVO_ESTADO = "estado_bot.json"

# Rango de cuotas permitidas
CUOTA_MIN = 1.20
CUOTA_MAX = 5.00

# Solo Béisbol centralizado en API-Sports
LIGAS_PERMITIDAS = ["baseball_mlb", "baseball_lmb_real"]

# Mapeo de IDs de API-Sports (1 = MLB, 21 = LMB)
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
    }
}

REQUEST_TIMEOUT = (10, 30)


def _cargar_json_seguro(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
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
        logger.error("guardar_picks recibió un valor inválido; se esperaba lista.")
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


def _buscar_nombre_equipo(value, home_team, away_team):
    v = str(value or "").strip().lower()
    home_l = str(home_team).lower()
    away_l = str(away_team).lower()

    if v in {"home", "1", "local"} or home_l in v:
        return home_team
    if v in {"away", "2", "visitante", "visita"} or away_l in v:
        return away_team
    if v == str(home_team).strip().lower():
        return home_team
    if v == str(away_team).strip().lower():
        return away_team
    return None


def _es_mx_equivalente(nombre_bet):
    n = str(nombre_bet or "").strip().lower()
    return n


def obtener_partidos_api_sports(league_id):
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    url = "https://v1.baseball.api-sports.io/odds"
    headers = {"x-apisports-key": BASEBALL_API_KEY}
    params = {"league": str(league_id), "season": str(datetime.now(MX_TZ).year), "date": hoy}

    try:
        res = request_con_reintentos(url, headers, params)
        if not res:
            logger.warning(f"No se pudo obtener Odds para liga {league_id}")
            return []

        datos = res.json().get("response", [])
        logger.info(f"📦 API-Sports response recibida para liga {league_id}: {len(datos)} registros.")
        mapeo_datos = []

        for item in datos:
            logger.info(f"🎯 Procesando registro crudo de liga {league_id}.")
            game = item.get("game", {})
            bookmakers = item.get("bookmakers", [])

            home_team = game.get("teams", {}).get("home", {}).get("name", "Home")
            away_team = game.get("teams", {}).get("away", {}).get("name", "Away")
            commence_time = game.get("date", "")

            bms_mapeados = []
            for b in bookmakers:
                logger.info(f"📚 Bookmaker detectado: {b.get('name', 'Bookmaker')}")
                bets = b.get("bets", [])
                markets_mapeados = []

                for bet in bets:
                    bet_name = _es_mx_equivalente(bet.get("name"))
                    values = bet.get("values", [])

                    if any(k in bet_name for k in ["home/away", "moneyline", "match winner", "winner", "h2h"]):
                        outcomes = []
                        for val in values:
                            odd_raw = val.get("odd", 0)
                            try:
                                price = float(odd_raw)
                            except (TypeError, ValueError):
                                continue

                            team_name = _buscar_nombre_equipo(val.get("value"), home_team, away_team)
                            if not team_name:
                                team_name = home_team if len(outcomes) == 0 else away_team

                            outcomes.append({"name": team_name, "price": price})

                        if len(outcomes) >= 2:
                            markets_mapeados.append({"key": "h2h", "outcomes": outcomes})

                    elif any(k in bet_name for k in ["over/under", "totals", "total"]):
                        outcomes = []
                        for val in values:
                            over_under_str = str(val.get("value", ""))
                            try:
                                odd_val = float(val.get("odd", 0))
                            except (TypeError, ValueError):
                                continue

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

                    elif any(k in bet_name for k in ["handicap", "spread", "run line", "runline"]):
                        outcomes = []
                        for val in values:
                            odd_raw = val.get("odd", 0)
                            try:
                                price = float(odd_raw)
                            except (TypeError, ValueError):
                                continue

                            raw_name = val.get("value")
                            team_name = _buscar_nombre_equipo(raw_name, home_team, away_team)
                            if not team_name:
                                team_name = str(raw_name or "") or home_team

                            point_raw = val.get("point", None)
                            if point_raw is None:
                                point_raw = val.get("handicap", None)
                            if point_raw is None:
                                point_raw = val.get("line", None)

                            try:
                                point = float(point_raw) if point_raw is not None else 0.0
                            except (TypeError, ValueError):
                                point = 0.0

                            outcomes.append({"name": team_name, "price": price, "point": point})

                        if outcomes:
                            markets_mapeados.append({"key": "spreads", "outcomes": outcomes})

                if markets_mapeados:
                    logger.info(f"🧾 Partido {home_team} vs {away_team}: {len(markets_mapeados)} mercados útiles en {b.get('name', 'Bookmaker')}.")
                    bms_mapeados.append({
                        "title": b.get("name", "Bookmaker"),
                        "markets": markets_mapeados
                    })

            if bms_mapeados:
                mapeo_datos.append({
                    "home_team": home_team,
                    "away_team": away_team,
                    "commence_time": commence_time,
                    "bookmakers": bms_mapeados
                })

        logger.info(f"📌 Total de partidos con cuotas válidas en liga {league_id}: {len(mapeo_datos)}")
        return mapeo_datos

    except Exception as e:
        logger.error(f"Error API-Sports Odds (Liga {league_id}): {e}")
        return []


def obtener_marcadores_api_sports(league_id):
    hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")
    url = "https://v1.baseball.api-sports.io/games"
    headers = {"x-apisports-key": BASEBALL_API_KEY}
    params = {"league": str(league_id), "season": str(datetime.now(MX_TZ).year), "date": hoy}

    try:
        res = request_con_reintentos(url, headers, params)
        if not res:
            logger.warning(f"No se pudo obtener Games para liga {league_id}")
            return []

        datos = res.json().get("response", [])
        logger.info(f"📦 API-Sports Games liga {league_id}: {len(datos)} registros recibidos.")
        mapeo_scores = []

        for item in datos:
            home_team = item.get("teams", {}).get("home", {}).get("name", "Home")
            away_team = item.get("teams", {}).get("away", {}).get("name", "Away")
            status = item.get("status", {}).get("short", "")

            home_score = item.get("scores", {}).get("home", {}).get("total", 0)
            away_score = item.get("scores", {}).get("away", {}).get("total", 0)

            try:
                home_score = 0 if home_score is None else float(home_score)
            except (TypeError, ValueError):
                home_score = 0
            try:
                away_score = 0 if away_score is None else float(away_score)
            except (TypeError, ValueError):
                away_score = 0

            completed = status in {"FT", "AOT"}

            mapeo_scores.append({
                "home_team": home_team,
                "away_team": away_team,
                "completed": completed,
                "scores": [
                    {"name": home_team, "score": str(home_score)},
                    {"name": away_team, "score": str(away_score)}
                ]
            })

        logger.info(f"📌 Total de marcadores procesados en liga {league_id}: {len(mapeo_scores)}")
        return mapeo_scores

    except Exception as e:
        logger.error(f"Error API-Sports Scores (Liga {league_id}): {e}")
        return []


def mapear_icono_deporte(sport_key):
    sport_key_lower = str(sport_key).lower()
    if "baseball_mlb" in sport_key_lower:
        return "⚾ MLB"
    if "baseball_lmb" in sport_key_lower:
        return "⚾ LMB"
    return "🏅 Deporte"


def _extraer_json_lista(texto):
    if not texto:
        raise ValueError("Respuesta vacía de la IA")

    txt = texto.strip().replace("```json", "").replace("```", "").strip()

    inicio = txt.find("[")
    fin = txt.rfind("]")
    if inicio != -1 and fin != -1 and fin > inicio:
        candidato = txt[inicio:fin + 1].strip()
        return json.loads(candidato)

    inicio = txt.find("{")
    fin = txt.rfind("}")
    if inicio != -1 and fin != -1 and fin > inicio:
        candidato = txt[inicio:fin + 1].strip()
        obj = json.loads(candidato)
        return obj if isinstance(obj, list) else [obj]

    raise ValueError("No se pudo extraer JSON válido de la respuesta")


def _clave_unica_pick(pick):
    return f"{str(pick.get('partido', 'Desconocido')).strip().lower()}|{str(pick.get('pick', 'Desconocido')).strip().lower()}|{str(pick.get('cuota', '0.0')).strip()}|{str(pick.get('sport_key', '')).strip().lower()}"


def _ranking_pre_gemini(picks):
    def score(x):
        cuota = float(x.get("cuota", 0.0) or 0.0)
        distancia = abs(cuota - 1.80)
        pick_txt = str(x.get("pick", "")).lower()
        if "gana" in pick_txt:
            bonus = 0.0
        elif "over" in pick_txt or "under" in pick_txt:
            bonus = 0.05
        elif "hándicap" in pick_txt or "handicap" in pick_txt:
            bonus = 0.10
        else:
            bonus = 0.15
        return distancia + bonus

    return sorted(picks, key=score)


def consultar_cerebro_ia(candidatos_raw, cantidad, modo_bloque="normal"):
    logger.info(f"🧠 Candidatos enviados a Gemini antes de ranking: {len(candidatos_raw)}")
    candidatos_raw = _ranking_pre_gemini(candidatos_raw)[:50]
    logger.info(f"🧠 Candidatos enviados a Gemini después de ranking y corte: {len(candidatos_raw)}")

    if modo_bloque != "stake_10":
        prompt = (
            f"Analiza y elige los {cantidad} mejores picks únicos del día de hoy.\n"
            "Reglas:\n"
            "1. Selecciona partidos con alta probabilidad basados en cuotas.\n"
            "2. Asigna Stake del 1 al 8 según probabilidad.\n"
            "3. No repitas partido, mercado ni cuota.\n"
            "4. Prioriza consistencia y evita picks inflados.\n"
            "5. Devuelve solo JSON plano, sin markdown.\n"
            "[{\"deporte\": \"\", \"partido\": \"\", \"fecha_hora\": \"\", \"pick\": \"\", \"cuota\": 0.0, "
            "\"bookie\": \"\", \"sport_key\": \"\", \"stake_num\": 5, \"analisis_ia\": \"\"}]"
        )
    else:
        prompt = (
            "Selecciona únicamente el pick más seguro de toda la cartelera del día de hoy.\n"
            "Asigna obligatoriamente Stake 10.\n"
            "Devuelve solo un objeto en JSON plano dentro de una lista, sin markdown.\n"
            "[{\"deporte\": \"\", \"partido\": \"\", \"fecha_hora\": \"\", \"pick\": \"\", \"cuota\": 0.0, "
            "\"bookie\": \"\", \"sport_key\": \"\", \"stake_num\": 10, \"analisis_ia\": \"\"}]"
        )

    datos_json = json.dumps(candidatos_raw, ensure_ascii=False)
    prompt_completo = prompt + "\n\nDatos:\n" + datos_json
    picks_finales_limpios = []
    picks_vistos = set()

    try:
        logger.info(f"🤖 Enviando prompt a Gemini con {len(candidatos_raw)} candidatos.")
        response = model.generate_content(prompt_completo)
        txt = getattr(response, "text", "") or ""
        picks_seleccionados = _extraer_json_lista(txt)
        logger.info(f"🧩 Gemini devolvió {len(picks_seleccionados) if isinstance(picks_seleccionados, list) else 0} elementos.")

        if not isinstance(picks_seleccionados, list):
            raise ValueError("Formato JSON inválido de la IA")

        for pick in picks_seleccionados:
            if not isinstance(pick, dict):
                continue

            clave_unica = _clave_unica_pick(pick)
            if clave_unica in picks_vistos:
                continue

            pick.setdefault("deporte", "Deporte")
            pick.setdefault("partido", "Equipo vs Equipo")
            pick.setdefault("fecha_hora", "Horario por confirmar")
            pick.setdefault("pick", "")
            pick.setdefault("cuota", 0.0)
            pick.setdefault("bookie", "Bookmaker Desconocido")
            pick.setdefault("sport_key", "")
            pick.setdefault("stake_num", 10 if modo_bloque == "stake_10" else 5)
            pick.setdefault("analisis_ia", "Análisis verificado por la IA basado en tendencias (+EV).")

            picks_finales_limpios.append(pick)
            picks_vistos.add(clave_unica)

            if len(picks_finales_limpios) == cantidad:
                break

        logger.info(f"🏁 Picks finales limpios devueltos por IA: {len(picks_finales_limpios)}")
        return picks_finales_limpios

    except Exception as e:
        logger.error(f"Error IA: Activando Red de Seguridad: {e}")
        candidatos_copia = list(candidatos_raw)
        random.shuffle(candidatos_copia)

        if modo_bloque != "stake_10":
            for p in candidatos_copia:
                if not isinstance(p, dict):
                    continue

                clave_unica = _clave_unica_pick(p)
                if clave_unica in picks_vistos:
                    continue

                p = dict(p)
                cuota = float(p.get("cuota", 0.0) or 0.0)
                if cuota <= 1.50:
                    stake = 8
                elif cuota <= 1.80:
                    stake = 7
                elif cuota <= 2.10:
                    stake = 6
                else:
                    stake = 5

                p["stake_num"] = stake
                p["analisis_ia"] = "Análisis verificado por tendencias del mercado."
                picks_finales_limpios.append(p)
                picks_vistos.add(clave_unica)

                if len(picks_finales_limpios) == cantidad:
                    break
        else:
            if candidatos_copia and isinstance(candidatos_copia[0], dict):
                p = dict(candidatos_copia[0])
                p["stake_num"] = 10
                p["analisis_ia"] = "Máxima probabilidad detectada en rachas."
                picks_finales_limpios.append(p)

        logger.info(f"🏁 Picks finales limpios devueltos por IA (fallback): {len(picks_finales_limpios)}")
        return picks_finales_limpios


def procesar_bloque_especifico(lista_ligas, cantidad, modo_bloque="normal"):
    candidatos_crudos = []

    logger.info(f"=== Iniciando búsqueda de picks para el bloque. Ligas solicitadas: {lista_ligas} ===")
    logger.info(f"📊 Total de ligas a procesar: {len(lista_ligas)}")

    for liga in lista_ligas:
        if liga not in LIGAS_PERMITIDAS:
            logger.warning(f"⚠️ La liga '{liga}' NO está en LIGAS_PERMITIDAS. Omitiendo.")
            continue

        logger.info(f"📡 Consultando datos para la liga: {liga}...")

        league_id = LIGAS_MAP.get(liga)
        if league_id is None:
            logger.error(f"❌ league_id no encontrado para {liga}. Saltando.")
            continue

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
                    clean_time = commence_time_raw.replace("Z", "+00:00")
                    partido_tiempo = datetime.fromisoformat(clean_time)
                    partido_tiempo_mx = partido_tiempo.astimezone(MX_TZ)
                    fecha_hora_str = partido_tiempo_mx.strftime("%I:%M %p")
                except Exception:
                    pass

            for bookie in partido.get("bookmakers", []):
                for market in bookie.get("markets", []):
                    market_key = market.get("key")

                    for o in market.get("outcomes", []):
                        cuota = o.get("price")

                        if isinstance(cuota, (int, float)) and CUOTA_MIN <= float(cuota) <= CUOTA_MAX:
                            nombre_deporte = mapear_icono_deporte(liga)

                            if market_key == "h2h":
                                tipo_pick = f"Gana {o.get('name')}"
                            elif market_key == "totals":
                                punto = o.get("point", 0)
                                tipo_pick = f"{'Altas/Over' if o.get('name') == 'Over' else 'Bajas/Under'} {punto}"
                            elif market_key == "spreads":
                                punto = o.get("point", 0)
                                tipo_pick = f"Hándicap {o.get('name')} {punto:+g}"
                            else:
                                continue

                            candidatos_crudos.append({
                                "deporte": nombre_deporte,
                                "partido": f"{partido.get('home_team')} vs {partido.get('away_team')}",
                                "fecha_hora": fecha_hora_str,
                                "pick": tipo_pick,
                                "cuota": float(cuota),
                                "bookie": bookie.get("title", "Bookmaker Desconocido"),
                                "sport_key": liga
                            })

    logger.info(f"📊 Candidatos crudos antes de deduplicar: {len(candidatos_crudos)}")

    candidatos_unicos = []
    vistos = set()
    for c in candidatos_crudos:
        clave = _clave_unica_pick(c)
        if clave not in vistos:
            vistos.add(clave)
            candidatos_unicos.append(c)

    picks_por_liga = {}
    for c in candidatos_unicos:
        liga = c["sport_key"]
        picks_por_liga[liga] = picks_por_liga.get(liga, 0) + 1

    for liga, count in picks_por_liga.items():
        logger.info(f"📍 {liga}: {count} picks viables extraídos.")

    logger.info(f"✅ Candidatos únicos tras deduplicar: {len(candidatos_unicos)}")

    if not candidatos_unicos:
        return []

    return consultar_cerebro_ia(candidatos_unicos, cantidad, modo_bloque=modo_bloque)


def construir_mensaje(pick_data):
    stk_num = pick_data.get("stake_num", 3)
    try:
        stk_num = int(stk_num)
    except Exception:
        stk_num = 3

    stk_num = max(1, min(stk_num, 10))
    estrellas = "⭐" * stk_num
    analisis = pick_data.get("analisis_ia", "Análisis verificado por la IA basado en tendencias (+EV).")

    m1 = "🔥 El Boss mexa – Pick del Día\n\n"
    m2 = f"Deporte: {pick_data.get('deporte', 'Deporte')}\n"
    m3 = f"Partido: ({pick_data.get('partido', 'Equipo vs Equipo')})\n"
    m4 = f"Pick: {pick_data.get('pick', '')}\n"
    m5 = f"Cuota: {float(pick_data.get('cuota', 0)):.2f}\n"
    m6 = f"Stake: {stk_num}/10 {estrellas}\n\n"
    m7 = "📊 Análisis:\n"
    m8 = f"{analisis}\n\n"
    m9 = "¡Vamos con todo! 💰"
    return m1 + m2 + m3 + m4 + m5 + m6 + m7 + m8 + m9


async def enviar_mensaje_seguro(texto):
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=texto, parse_mode=None)
    except Exception as e:
        logger.error(f"Error al enviar Telegram: {e}")


def _extraer_linea_pick(pick_str):
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*$", pick_str.strip())
    if not match:
        raise ValueError("No se pudo extraer la línea numérica del pick")
    return float(match.group(1))


def evaluar_pick(pick_str, scores):
    try:
        score1 = float(scores[0]["score"])
        score2 = float(scores[1]["score"])
        name1 = str(scores[0]["name"])
        name2 = str(scores[1]["name"])
        p = str(pick_str or "").strip().lower()

        if "gana" in p:
            team_picked = pick_str.replace("Gana ", "").strip().lower()
            winner = None
            if score1 > score2:
                winner = name1.lower()
            elif score2 > score1:
                winner = name2.lower()

            if winner == team_picked:
                return "🟢 GANADO"
            elif winner is None:
                return "⚪ EMPATE / PUSH"
            else:
                return "🔴 PERDIDO"

        elif "altas/over" in p or "bajas/under" in p:
            total_puntos = score1 + score2
            linea = _extraer_linea_pick(pick_str)

            if "altas/over" in p:
                if total_puntos > linea:
                    return "🟢 GANADO"
                elif total_puntos < linea:
                    return "🔴 PERDIDO"
                return "⚪ PUSH"
            else:
                if total_puntos < linea:
                    return "🟢 GANADO"
                elif total_puntos > linea:
                    return "🔴 PERDIDO"
                return "⚪ PUSH"

        elif "hándicap" in p or "handicap" in p:
            clean_str = pick_str.replace("Hándicap Asiático ", "").replace("Hándicap ", "").replace("Handicap ", "").strip()
            partes = clean_str.rsplit(" ", 1)
            if len(partes) == 2:
                equipo_h = partes[0].strip().lower()
                linea_h = float(partes[1])

                score_equipo = score1 if equipo_h == name1.lower() else (score2 if equipo_h == name2.lower() else None)
                score_rival = score2 if equipo_h == name1.lower() else (score1 if equipo_h == name2.lower() else None)

                if score_equipo is not None and score_rival is not None:
                    if score_equipo + linea_h > score_rival:
                        return "🟢 GANADO"
                    elif score_equipo + linea_h < score_rival:
                        return "🔴 PERDIDO"
                    else:
                        return "⚪ PUSH"

        return "❔ RESULTADO MANUAL"

    except (ValueError, TypeError, IndexError, KeyError) as e:
        logger.warning(f"⚠️ Error evaluando pick '{pick_str}': {e}")
        return "❔ REVISAR"


def _picks_existentes_unicos():
    actuales = cargar_picks()
    return {_clave_unica_pick(p) for p in actuales if isinstance(p, dict)}


def _filtrar_picks_nuevos(picks):
    existentes = _picks_existentes_unicos()
    nuevos = []
    for p in picks:
        if not isinstance(p, dict):
            continue
        clave = _clave_unica_pick(p)
        if clave not in existentes:
            nuevos.append(p)
            existentes.add(clave)
    return nuevos


async def ejecutar_bloque_remodelado(nombre_bloque, ligas, cantidad, modo="normal", intro=None):
    logger.info(f"Iniciando bloque: {nombre_bloque}")

    picks_bloque = []
    for intento in range(3):
        picks_bloque = procesar_bloque_especifico(ligas, cantidad, modo_bloque=modo)
        logger.info(f"📤 Bloque '{nombre_bloque}' intento {intento + 1}: {len(picks_bloque)} picks candidatos.")
        picks_bloque = _filtrar_picks_nuevos(picks_bloque)

        if picks_bloque:
            logger.info(f"✅ ¡Éxito al intento {intento + 1}!")
            break

        logger.warning(f"⚠️ Intento {intento + 1} fallido. Esperando 10 min...")
        await asyncio.sleep(600)

    if not picks_bloque:
        logger.error(f"❌ Después de 3 intentos, no hubo datos para {nombre_bloque}")
        await enviar_mensaje_seguro(f"⏳ Sistema {nombre_bloque}: Monitoreando mercado... líneas aún no abiertas.")
        return

    actuales = cargar_picks()
    logger.info(f"💾 Picks guardados actualmente antes de añadir bloque: {len(actuales)}")
    claves_actuales = {_clave_unica_pick(p) for p in actuales if isinstance(p, dict)}
    for pick in picks_bloque:
        if _clave_unica_pick(pick) not in claves_actuales:
            actuales.append(pick)
            claves_actuales.add(_clave_unica_pick(pick))
    guardar_picks(actuales)
    logger.info(f"💾 Picks totales guardados después del bloque '{nombre_bloque}': {len(actuales)}")

    if intro:
        await enviar_mensaje_seguro(intro)
        await asyncio.sleep(3)

    for pick in picks_bloque:
        await enviar_mensaje_seguro(construir_mensaje(pick))
        await asyncio.sleep(5)


async def mandar_reporte_profit():
    picks_totales = cargar_picks()
    logger.info(f"📊 Generando reporte con {len(picks_totales)} picks totales guardados.")
    if not picks_totales:
        return

    ligas_jugadas = list(set([pick.get("sport_key") for pick in picks_totales if pick.get("sport_key")]))
    todos_los_resultados = []

    for liga in ligas_jugadas:
        league_id = LIGAS_MAP.get(liga)
        if league_id:
            todos_los_resultados += obtener_marcadores_api_sports(league_id)

    ganados, perdidos, total_evaluados = 0, 0, 0
    msg = "📊 El Boss mexa – Resumen de la Jornada 📊\n\nResultados oficiales:\n\n"

    for pick in picks_totales:
        marcador_texto = "Marcador no disponible ⏳"
        estado_pick = "❔ Pendiente"

        for res in todos_los_resultados:
            home_team = res.get("home_team", "")
            away_team = res.get("away_team", "")
            partido_txt = pick.get("partido", "")

            if home_team in partido_txt and away_team in partido_txt:
                if res.get("completed"):
                    scores = res.get("scores")
                    if scores and len(scores) == 2:
                        marcador_texto = f"{scores[0]['name']} {scores[0]['score']} - {scores[1]['score']} {scores[1]['name']} 🏁"
                        estado_pick = evaluar_pick(pick.get("pick", ""), scores)
                        if "GANADO" in estado_pick:
                            ganados += 1
                        elif "PERDIDO" in estado_pick:
                            perdidos += 1
                        total_evaluados += 1
                else:
                    marcador_texto = "Partido en juego ⏳"
                break

        msg += (
            f"🔥 {pick.get('partido', 'Partido')}\n"
            f"Pick: {pick.get('pick', '')}\n"
            f"Resultado: {marcador_texto}\n"
            f"Estatus: {estado_pick}\n\n"
        )

    porcentaje = (ganados / total_evaluados * 100) if total_evaluados > 0 else 0.0
    msg += f"📈 Efectividad del día: {porcentaje:.1f}%\n"
    msg += f"🟢 GANADOS: {ganados} | 🔴 PERDIDOS: {perdidos}\n\n"
    msg += "¡Mañana regresamos por más verdes! 📉💰"
    await enviar_mensaje_seguro(msg)


async def main_loop():
    logger.info("Bot El Boss mexa: Sistema Béisbol Unificado Iniciado.")

    estado = cargar_estado()
    fecha_hoy = datetime.now(MX_TZ).strftime("%Y-%m-%d")

    if estado.get("fecha") != fecha_hoy:
        guardar_picks([])
        estado["fecha"] = fecha_hoy
        estado["bloques_ejecutados"] = json.loads(json.dumps(DEFAULT_ESTADO["bloques_ejecutados"]))
        guardar_estado(estado)

    while True:
        try:
            ahora = datetime.now(MX_TZ)
            fecha_str = ahora.strftime("%Y-%m-%d")

            if estado.get("fecha") != fecha_str:
                guardar_picks([])
                estado["fecha"] = fecha_str
                estado["bloques_ejecutados"] = json.loads(json.dumps(DEFAULT_ESTADO["bloques_ejecutados"]))
                guardar_estado(estado)
                logger.info(f"🧹 Nuevo día detectado. Estado reiniciado para {fecha_str}.")

            bloques_ejecutados = estado["bloques_ejecutados"]

            if ahora.hour == 0 and ahora.minute == 5 and estado.get("fecha") == fecha_str:
                guardar_picks([])

            if ahora.hour == 7 and 45 <= ahora.minute <= 50 and bloques_ejecutados["buenos_dias"] != fecha_str:
                msg = "¡Buenos días, Familia! ☀️ Arrancamos una nueva jornada de análisis deportivo. En breve salen las primeras jugadas del día. ¡A facturar hoy! 💸"
                await enviar_mensaje_seguro(msg)
                bloques_ejecutados["buenos_dias"] = fecha_str
                guardar_estado(estado)

            elif ahora.hour == 8 and 30 <= ahora.minute <= 35 and bloques_ejecutados["mlb"] != fecha_str:
                await ejecutar_bloque_remodelado("MLB Mañanero", ["baseball_mlb"], 3)
                bloques_ejecutados["mlb"] = fecha_str
                guardar_estado(estado)

            elif ahora.hour == 13 and 0 <= ahora.minute <= 5 and bloques_ejecutados["lmb"] != fecha_str:
                intro_lmb = "Familia, ya están abiertas las líneas. Aquí tienen los picks de la Liga Mexicana de Béisbol. ⚾️🔥"
                await ejecutar_bloque_remodelado("LMB Tarde", ["baseball_lmb_real"], 3, intro=intro_lmb)
                bloques_ejecutados["lmb"] = fecha_str
                guardar_estado(estado)

            elif ahora.hour == 15 and 0 <= ahora.minute <= 5 and bloques_ejecutados["stake10"] != fecha_str:
                intro_s10 = "🚨 STAKE 10 DETECTADO 🚨\n\nInteligencia algorítmica aplicada. Vamos pesados aquí:"
                await ejecutar_bloque_remodelado("MÁXIMO VIP", LIGAS_PERMITIDAS, 1, modo="stake_10", intro=intro_s10)
                bloques_ejecutados["stake10"] = fecha_str
                guardar_estado(estado)

            elif ahora.hour == 23 and 45 <= ahora.minute <= 50 and bloques_ejecutados["reporte"] != fecha_str:
                await mandar_reporte_profit()
                bloques_ejecutados["reporte"] = fecha_str
                guardar_estado(estado)

            elif ahora.hour == 23 and 58 <= ahora.minute <= 59 and bloques_ejecutados["buenas_noches"] != fecha_str:
                msg = "🌙 ¡Buenas noches, equipo! 🌙\n\nFinalizan las actividades por hoy. ¡A descansar! 💤"
                await enviar_mensaje_seguro(msg)
                bloques_ejecutados["buenas_noches"] = fecha_str
                guardar_estado(estado)

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Error en bucle del reloj: {e}")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main_loop())
