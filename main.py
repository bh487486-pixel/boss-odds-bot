import os
import re
import math
import json
import uuid
import requests
import logging

from collections import defaultdict
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==========================
# CONFIG
# ==========================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BASEBALL_API_KEY")

if not TOKEN:
    raise ValueError("Falta TELEGRAM_TOKEN en Render")

if not API_KEY:
    raise ValueError("Falta BASEBALL_API_KEY en Render")

BASE_URL = "https://v1.baseball.api-sports.io"
SEASON = 2026
BOOKMAKER_ID = 4  # Pinnacle

MAX_GAMES_TO_ANALYZE = 15
MAX_PICKS = 6

HISTORY_FILE = "picks_history.json"

# Prioridad de mercados: Run Line ya no domina
MARKET_WEIGHTS = {
    "Moneyline": 1.00,
    "Totales": 0.97,
    "F5 Totales": 0.92,
    "Run Line": 0.74,
}

# Máximo de picks por mercado en la selección final
MAX_PER_MARKET = {
    "Moneyline": 3,
    "Totales": 2,
    "F5 Totales": 1,
    "Run Line": 1,
}

# ==========================
# CACHES
# ==========================

STANDINGS_CACHE = {}
ODDS_CACHE = {}

# ==========================
# HELPERS
# ==========================

def _headers():
    return {"x-apisports-key": API_KEY}

def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(str(value).strip())
    except Exception:
        return default

def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(str(value).strip()))
    except Exception:
        return default

def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()

def _sigmoid(x):
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 1.0 if x > 0 else 0.0

def _clamp(value, low, high):
    return max(low, min(high, value))

def _load_json(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logging.error(f"Error leyendo {path}: {e}")
        return fallback

def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error guardando {path}: {e}")

def cargar_historial():
    data = _load_json(HISTORY_FILE, [])
    return data if isinstance(data, list) else []

def guardar_historial(historial):
    _save_json(HISTORY_FILE, historial)

def _as_list(response):
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return [response]
    return []

def _format_runline_label(label, juego):
    txt = str(label or "").strip().lower()
    if txt == "home -1.5":
        return f"{juego['home']} -1.5"
    if txt == "away -1.5":
        return f"{juego['away']} -1.5"
    if txt == "home +1.5":
        return f"{juego['home']} +1.5"
    if txt == "away +1.5":
        return f"{juego['away']} +1.5"
    return str(label).strip()

def _make_uid():
    return datetime.utcnow().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]

def _market_profit(stake, odd, result):
    if result == "win":
        return stake * (odd - 1.0)
    if result == "loss":
        return -stake
    return 0.0

# ==========================
# API SPORTS
# ==========================

def obtener_juegos(league_id):
    headers = _headers()

    fecha1 = datetime.utcnow().strftime("%Y-%m-%d")
    fecha2 = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

    juegos = []
    seen_pairs = set()

    for fecha in [fecha1, fecha2]:
        params = {
            "league": league_id,
            "season": SEASON,
            "date": fecha
        }

        try:
            r = requests.get(
                f"{BASE_URL}/games",
                headers=headers,
                params=params,
                timeout=30
            )
            r.raise_for_status()
            data = r.json()

            for game in data.get("response", []):
                if game.get("status", {}).get("short") != "NS":
                    continue

                teams = game.get("teams", {})
                home_obj = teams.get("home", {})
                away_obj = teams.get("away", {})

                game_id = game.get("id")
                home_team_id = home_obj.get("id")
                away_team_id = away_obj.get("id")

                home = home_obj.get("name")
                away = away_obj.get("name")

                if not game_id or not home or not away or not home_team_id or not away_team_id:
                    continue

                pair_key = (_norm(home), _norm(away))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                juegos.append({
                    "league_id": league_id,
                    "league_name": "MLB",
                    "game_id": game_id,
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "home": home,
                    "away": away,
                    "partido": f"{away} vs {home}",
                    "date": game.get("date"),
                    "time": game.get("time")
                })

        except Exception as e:
            logging.error(f"Error API games ({fecha}) league={league_id}: {e}")

    return juegos

def obtener_standings(league_id):
    if league_id in STANDINGS_CACHE:
        return STANDINGS_CACHE[league_id]

    params = {
        "league": league_id,
        "season": SEASON
    }

    try:
        r = requests.get(
            f"{BASE_URL}/standings",
            headers=_headers(),
            params=params,
            timeout=30
        )
        r.raise_for_status()

        raw = r.json().get("response", [])
        rows = raw[0] if raw and isinstance(raw[0], list) else raw

        standings = {}

        for row in rows:
            team = row.get("team", {})
            team_id = team.get("id")
            if not team_id:
                continue

            games = row.get("games", {})
            win_block = games.get("win", {}) or games.get("wins", {})
            lose_block = games.get("lose", {}) or games.get("loses", {})
            points = row.get("points", {})

            points_for = _safe_float(points.get("for"))
            points_against = _safe_float(points.get("against"))
            games_played = _safe_int(games.get("played"))

            standings[team_id] = {
                "team_id": team_id,
                "team_name": team.get("name"),
                "position": _safe_int(row.get("position"), 99),
                "win_pct": _safe_float(win_block.get("percentage")),
                "loss_pct": _safe_float(lose_block.get("percentage")),
                "games_played": games_played,
                "points_for": points_for,
                "points_against": points_against,
                "run_diff": points_for - points_against,
                "runs_for_pg": points_for / max(1, games_played),
                "runs_against_pg": points_against / max(1, games_played),
            }

        STANDINGS_CACHE[league_id] = standings
        return standings

    except Exception as e:
        logging.error(f"Error standings league={league_id}: {e}")
        return {}

def obtener_odds(game_id, league_id):
    key = (league_id, game_id)
    if key in ODDS_CACHE:
        return ODDS_CACHE[key]

    params = {
        "league": league_id,
        "season": SEASON,
        "bookmaker": BOOKMAKER_ID,
        "game": game_id
    }

    try:
        r = requests.get(
            f"{BASE_URL}/odds",
            headers=_headers(),
            params=params,
            timeout=30
        )
        r.raise_for_status()
        data = r.json().get("response", [])
        ODDS_CACHE[key] = data
        return data

    except Exception as e:
        logging.error(f"Error odds game={game_id} league={league_id}: {e}")
        return []

def _parse_total_market(values):
    lines = {}

    for v in values or []:
        label = str(v.get("value", "")).strip()
        odd = _safe_float(v.get("odd"))

        m = re.match(r"(?i)^(Over|Under)\s+([0-9]+(?:\.[0-9]+)?)$", label)
        if not m:
            continue

        side = m.group(1).title()
        line = float(m.group(2))
        lines.setdefault(line, {})[side] = odd

    complete = [
        (line, odds)
        for line, odds in lines.items()
        if "Over" in odds and "Under" in odds
    ]

    if not complete:
        return None

    line, odds = min(complete, key=lambda x: abs(x[0] - 8.5))

    return {
        "line": line,
        "over": odds["Over"],
        "under": odds["Under"]
    }

def extraer_mercados_odds(odds_response):
    if not odds_response:
        return {}

    entry = odds_response[0]
    bookmakers = entry.get("bookmakers", [])
    if not bookmakers:
        return {}

    bookmaker = next(
        (b for b in bookmakers if _safe_int(b.get("id")) == BOOKMAKER_ID),
        bookmakers[0]
    )

    markets = {}

    for bet in bookmaker.get("bets", []):
        bet_id = _safe_int(bet.get("id"))
        bet_name = str(bet.get("name", "")).strip()

        if bet_id == 1 or bet_name == "Home/Away":
            vals = bet.get("values", [])
            home_odd = None
            away_odd = None

            for v in vals:
                value = str(v.get("value", "")).strip()
                odd = _safe_float(v.get("odd"))
                if value == "Home":
                    home_odd = odd
                elif value == "Away":
                    away_odd = odd

            if home_odd and away_odd:
                markets["moneyline"] = {
                    "home": home_odd,
                    "away": away_odd
                }

        elif bet_id == 2 or bet_name == "Asian Handicap":
            handicap = {}
            for v in bet.get("values", []):
                value = str(v.get("value", "")).strip()
                odd = _safe_float(v.get("odd"))
                handicap[value] = odd
            if handicap:
                markets["runline"] = handicap

        elif bet_id == 5 or bet_name == "Over/Under":
            parsed = _parse_total_market(bet.get("values", []))
            if parsed:
                markets["total"] = parsed

        elif bet_id == 6 or bet_name == "Over/Under (1st 5 Innings)":
            parsed = _parse_total_market(bet.get("values", []))
            if parsed:
                markets["f5_total"] = parsed

    return markets

# ==========================
# MODELO
# ==========================

def calcular_fuerza_equipo(standing):
    if not standing:
        return 0.0

    win_pct = standing.get("win_pct", 0.0)
    run_diff_pg = standing.get("run_diff", 0.0) / max(1, standing.get("games_played", 1))
    position = standing.get("position", 99)

    # Más alto si gana más, tiene mejor diferencial y mejor posición
    return (win_pct * 70.0) + (run_diff_pg * 8.0) + (max(0, 30 - position) * 0.5)

def pick_moneyline(juego, standing_home, standing_away, markets):
    ml = markets.get("moneyline")
    if not ml:
        return None

    home_odd = ml.get("home")
    away_odd = ml.get("away")
    if not home_odd or not away_odd:
        return None

    home_strength = calcular_fuerza_equipo(standing_home)
    away_strength = calcular_fuerza_equipo(standing_away)

    gap = home_strength - away_strength
    prob_home = _sigmoid(gap / 8.0)
    prob_away = 1.0 - prob_home

    home_edge = prob_home - (1.0 / home_odd)
    away_edge = prob_away - (1.0 / away_odd)

    if home_edge >= away_edge:
        pick_team = juego["home"]
        odd = home_odd
        edge = home_edge
        confidence = int(
            min(
                92,
                max(
                    55,
                    55 + abs(gap) * 0.45 + edge * 35
                )
            )
        )
        reason = "Mejor win%, diferencial y localía."
    else:
        pick_team = juego["away"]
        odd = away_odd
        edge = away_edge
        confidence = int(
            min(
                92,
                max(
                    55,
                    55 + abs(gap) * 0.45 + edge * 35
                )
            )
        )
        reason = "Mejor win%, diferencial y visita."

    return {
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": "Moneyline",
        "pick": pick_team,
        "odd": odd,
        "line": None,
        "projection": None,
        "confidence": confidence,
        "ev": edge,
        "score": (confidence * MARKET_WEIGHTS["Moneyline"]) + (max(edge, 0.0) * 100.0 * 0.45),
        "reason": reason,
        "notes": []
    }

def pick_total(juego, standing_home, standing_away, market, market_name):
    if not market:
        return None

    line = market.get("line")
    over_odd = market.get("over")
    under_odd = market.get("under")

    if line is None or not over_odd or not under_odd:
        return None

    home_for = standing_home.get("runs_for_pg", 0.0) if standing_home else 0.0
    home_against = standing_home.get("runs_against_pg", 0.0) if standing_home else 0.0
    away_for = standing_away.get("runs_for_pg", 0.0) if standing_away else 0.0
    away_against = standing_away.get("runs_against_pg", 0.0) if standing_away else 0.0

    proj_home = (home_for + away_against) / 2.0
    proj_away = (away_for + home_against) / 2.0
    proj_total = proj_home + proj_away

    gap = proj_total - line

    if abs(gap) < 0.25:
        return None

    if gap > 0:
        pick_side = "Over"
        odd = over_odd
        model_prob = _sigmoid(gap * 1.9)
    else:
        pick_side = "Under"
        odd = under_odd
        model_prob = _sigmoid((-gap) * 1.9)

    implied = 1.0 / odd
    ev = model_prob - implied

    if ev < 0.012:
        return None

    confidence = int(
        min(
            88,
            max(
                55,
                55 + abs(gap) * 8 + ev * 35
            )
        )
    )

    return {
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": market_name,
        "pick": f"{pick_side} {line:.1f}",
        "odd": odd,
        "line": line,
        "projection": proj_total,
        "confidence": confidence,
        "ev": ev,
        "score": (confidence * MARKET_WEIGHTS[market_name]) + (max(ev, 0.0) * 100.0 * 0.40),
        "reason": f"Proyección de {proj_total:.2f} carreras vs línea {line:.1f}.",
        "notes": []
    }

def pick_runline(juego, standing_home, standing_away, markets):
    runline = markets.get("runline")
    if not runline:
        return None

    home_strength = calcular_fuerza_equipo(standing_home)
    away_strength = calcular_fuerza_equipo(standing_away)
    gap = home_strength - away_strength
    home_prob = _sigmoid(gap / 7.5)

    opciones = []

    for nombre, odd in runline.items():
        if not odd:
            continue

        nombre_norm = str(nombre).strip().lower()

        if nombre_norm == "home -1.5":
            est_prob = _clamp(home_prob - 0.12 + max(gap, 0.0) * 0.005, 0.05, 0.85)
        elif nombre_norm == "away -1.5":
            est_prob = _clamp((1.0 - home_prob) - 0.12 + max(-gap, 0.0) * 0.005, 0.05, 0.85)
        elif nombre_norm == "home +1.5":
            est_prob = _clamp(0.62 + home_prob * 0.25, 0.50, 0.96)
        elif nombre_norm == "away +1.5":
            est_prob = _clamp(0.62 + (1.0 - home_prob) * 0.25, 0.50, 0.96)
        else:
            continue

        implied = 1.0 / odd
        ev = est_prob - implied

        # Filtro más estricto para que Run Line no domine el ranking
        if ev < 0.03:
            continue

        score = (ev * 100.0 * 0.35) + abs(gap) * 0.5
        opciones.append((score, nombre, odd, ev))

    if not opciones:
        return None

    opciones.sort(reverse=True, key=lambda x: x[0])
    _, raw_pick, odd, ev = opciones[0]

    friendly_pick = _format_runline_label(raw_pick, juego)
    confidence = int(_clamp(58 + abs(gap) * 0.2 + ev * 22.0, 58, 82))

    return {
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": "Run Line",
        "pick": friendly_pick,
        "odd": odd,
        "line": None,
        "projection": None,
        "confidence": confidence,
        "ev": ev,
        "score": (confidence * MARKET_WEIGHTS["Run Line"]) + (max(ev, 0.0) * 100.0 * 0.25),
        "reason": "Ventaja estadística ajustada por handicap.",
        "notes": []
    }

# ==========================
# HISTORIAL / RESULTADOS
# ==========================

def guardar_picks_en_historial(picks):
    if not picks:
        return

    historial = cargar_historial()
    now = datetime.utcnow().isoformat()

    for pick in picks:
        historial.append({
            "uid": pick["uid"],
            "timestamp": now,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "league_name": pick.get("league_name"),
            "matchup": pick.get("matchup"),
            "market": pick.get("market"),
            "pick": pick.get("pick"),
            "odd": pick.get("odd"),
            "line": pick.get("line"),
            "projection": pick.get("projection"),
            "confidence": pick.get("confidence"),
            "stake": pick.get("stake"),
            "ev": pick.get("ev"),
            "score": pick.get("score"),
            "reason": pick.get("reason"),
            "status": "pending",   # pending | win | loss | push
            "result": None,
            "settled_at": None
        })

    guardar_historial(historial)

def marcar_resultado(uid, result):
    historial = cargar_historial()
    found = None

    for item in historial:
        if item.get("uid") == uid:
            item["status"] = result
            item["result"] = result
            item["settled_at"] = datetime.utcnow().isoformat()
            found = item
            break

    if found:
        guardar_historial(historial)

    return found

def resumen_historial():
    historial = cargar_historial()
    settled = [p for p in historial if p.get("status") in {"win", "loss", "push"}]

    if not settled:
        return None, {}

    overall = {
        "settled": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "staked": 0.0,
        "profit": 0.0
    }

    by_market = defaultdict(lambda: {
        "settled": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "staked": 0.0,
        "profit": 0.0
    })

    for p in settled:
        market = p.get("market", "Unknown")
        stake = _safe_float(p.get("stake"), 1.0)
        odd = _safe_float(p.get("odd"), 1.0)
        result = p.get("status")

        profit = _market_profit(stake, odd, result)

        overall["settled"] += 1
        overall["staked"] += stake
        overall["profit"] += profit

        if result == "win":
            overall["wins"] += 1
        elif result == "loss":
            overall["losses"] += 1
        else:
            overall["pushes"] += 1

        bm = by_market[market]
        bm["settled"] += 1
        bm["staked"] += stake
        bm["profit"] += profit

        if result == "win":
            bm["wins"] += 1
        elif result == "loss":
            bm["losses"] += 1
        else:
            bm["pushes"] += 1

    return overall, by_market

def formatear_resumen():
    overall, by_market = resumen_historial()

    if not overall:
        return "Aún no hay picks cerrados para calcular ROI."

    def _line(title, data):
        settled = data["settled"]
        wins = data["wins"]
        losses = data["losses"]
        pushes = data["pushes"]
        staked = data["staked"]
        profit = data["profit"]
        winrate = (wins / settled * 100.0) if settled else 0.0
        roi = (profit / staked * 100.0) if staked else 0.0
        return (
            f"{title}\n"
            f"• Cerrados: {settled}\n"
            f"• W-L-P: {wins}-{losses}-{pushes}\n"
            f"• Win rate: {winrate:.1f}%\n"
            f"• ROI: {roi:+.1f}%\n"
        )

    texto = "📊 RESUMEN DE RESULTADOS\n\n"
    texto += _line("General", overall) + "\n"

    if by_market:
        for market in ["Moneyline", "Totales", "F5 Totales", "Run Line"]:
            if market in by_market:
                texto += _line(market, by_market[market]) + "\n"

    return texto[:4000]

# ==========================
# COMANDOS
# ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bienvenido a Boss Odds MX\n\n"
        "Comandos disponibles:\n"
        "/analizar - Muestra los juegos del día\n"
        "/picks - Genera picks MLB\n"
        "/historial - Últimos picks guardados\n"
        "/resultado <uid> <win|loss|push>\n"
        "/resumen - ROI por mercado"
    )

async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = await update.message.reply_text("⏳ Analizando jornada MLB...")

    mlb = obtener_juegos(1)

    texto = "📊 JUEGOS MLB ENCONTRADOS\n\n"
    texto += f"⚾ MLB ({len(mlb)})\n\n"

    for juego in mlb:
        texto += (
            f"🆔 Juego: {juego['game_id']}\n"
            f"🏠 Home ID: {juego['home_team_id']}\n"
            f"✈️ Away ID: {juego['away_team_id']}\n"
            f"{juego['partido']}\n\n"
        )

    await mensaje.edit_text(texto[:4000])

async def picks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = await update.message.reply_text("⏳ Analizando MLB y buscando valor...")

    juegos_mlb = obtener_juegos(1)
    juegos = juegos_mlb[:MAX_GAMES_TO_ANALYZE]

    standings_mlb = obtener_standings(1)

    candidatos = []

    for juego in juegos:
        home_standing = standings_mlb.get(juego["home_team_id"])
        away_standing = standings_mlb.get(juego["away_team_id"])

        odds_response = obtener_odds(juego["game_id"], 1)
        markets = extraer_mercados_odds(odds_response)

        logging.info(f"{juego['partido']} -> markets={list(markets.keys())}")

        ml_pick = pick_moneyline(juego, home_standing, away_standing, markets)
        if ml_pick:
            candidatos.append(ml_pick)

        total_pick = pick_total(
            juego,
            home_standing,
            away_standing,
            markets.get("total"),
            "Totales"
        )
        if total_pick:
            candidatos.append(total_pick)

        f5_pick = pick_total(
            juego,
            home_standing,
            away_standing,
            markets.get("f5_total"),
            "F5 Totales"
        )
        if f5_pick:
            candidatos.append(f5_pick)

        runline_pick = pick_runline(
            juego,
            home_standing,
            away_standing,
            markets
        )
        if runline_pick:
            candidatos.append(runline_pick)

    # Un solo pick por partido: conserva el de mejor score
    mejores_por_partido = {}
    for pick in candidatos:
        partido = pick["matchup"]
        if partido not in mejores_por_partido:
            mejores_por_partido[partido] = pick
        elif pick["score"] > mejores_por_partido[partido]["score"]:
            mejores_por_partido[partido] = pick

    candidatos = list(mejores_por_partido.values())
    candidatos.sort(key=lambda x: x["score"], reverse=True)

    # Limita por mercado para que Run Line no domine
    seleccionados = []
    conteo_mercados = defaultdict(int)

    for pick in candidatos:
        mercado = pick["market"]
        limite = MAX_PER_MARKET.get(mercado, 1)

        if conteo_mercados[mercado] >= limite:
            continue

        seleccionados.append(pick)
        conteo_mercados[mercado] += 1

        if len(seleccionados) >= MAX_PICKS:
            break

    if not seleccionados:
        await mensaje.edit_text("No se encontraron picks con ventaja suficiente para MLB.")
        return

    def calcular_stake(confianza):
        if confianza >= 88:
            return 4
        if confianza >= 82:
            return 3
        if confianza >= 74:
            return 2
        return 1

    # Guardar en historial
    picks_para_guardar = []
    for pick in seleccionados:
        pick = dict(pick)
        pick["uid"] = _make_uid()
        pick["stake"] = calcular_stake(pick["confidence"])
        picks_para_guardar.append(pick)

    guardar_picks_en_historial(picks_para_guardar)

    texto = "🔥 TOP PICKS BOSS ODDS\n\n"
    texto += f"📊 MLB analizados: {len(juegos_mlb)}\n"
    texto += f"📈 Juegos usados en picks: {len(juegos)}\n"
    texto += f"📈 Candidatos detectados: {len(candidatos)}\n\n"

    medallas = {1: "🥇", 2: "🥈", 3: "🥉"}

    for idx, pick in enumerate(picks_para_guardar, start=1):
        emoji = medallas.get(idx, "⭐")
        texto += f"{emoji} PICK #{idx}\n"
        texto += f"UID: {pick['uid']}\n"
        texto += f"⚾ {pick['matchup']}\n"
        texto += f"🎯 Mercado: {pick['market']}\n"
        texto += f"Pick: {pick['pick']}\n"

        if pick.get("line") is not None:
            texto += f"Línea: {pick['line']:.1f}\n"

        if pick.get("projection") is not None:
            texto += f"Proyección: {pick['projection']:.2f}\n"

        texto += f"Cuota: {pick['odd']:.2f}\n"
        texto += f"EV: {pick.get('ev', 0.0) * 100:+.1f}%\n"
        texto += f"Confianza: {pick['confidence']}/100\n"
        texto += f"Stake: {pick['stake']}\n"
        texto += f"Razón: {pick['reason']}\n\n"

    await mensaje.edit_text(texto[:4000])

async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    historial = cargar_historial()
    if not historial:
        await update.message.reply_text("Todavía no hay picks guardados.")
        return

    ultimos = historial[-10:]
    texto = "🗂 ÚLTIMOS PICKS\n\n"

    for item in reversed(ultimos):
        texto += (
            f"UID: {item.get('uid')}\n"
            f"{item.get('market')} | {item.get('pick')}\n"
            f"{item.get('matchup')}\n"
            f"Cuota: {item.get('odd'):.2f} | Stake: {item.get('stake')} | Estado: {item.get('status')}\n\n"
        )

    await update.message.reply_text(texto[:4000])

async def resultado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /resultado <uid> <win|loss|push>")
        return

    uid = context.args[0].strip()
    result = context.args[1].strip().lower()

    if result not in {"win", "loss", "push"}:
        await update.message.reply_text("Resultado inválido. Usa: win, loss o push.")
        return

    updated = marcar_resultado(uid, result)

    if not updated:
        await update.message.reply_text(f"No encontré un pick con UID: {uid}")
        return

    await update.message.reply_text(
        f"Actualizado:\n"
        f"UID: {uid}\n"
        f"Pick: {updated.get('pick')}\n"
        f"Estado: {result}"
    )

async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = formatear_resumen()
    await update.message.reply_text(texto)

# ==========================
# MAIN
# ==========================

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analizar", analizar))
    app.add_handler(CommandHandler("picks", picks))
    app.add_handler(CommandHandler("historial", historial))
    app.add_handler(CommandHandler("resultado", resultado))
    app.add_handler(CommandHandler("resumen", resumen))

    logging.info("🤖 Boss Odds iniciado")
    app.run_polling()

if __name__ == "__main__":
    main()
