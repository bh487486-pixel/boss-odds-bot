import os
import re
import math
import requests
import logging

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
MIN_CONFIDENCE = 55
MAX_PICKS = 6

# ==========================
# CACHES
# ==========================

STATS_CACHE = {}
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

def _first_dict(response):
    if isinstance(response, list):
        if not response:
            return {}
        first = response[0]
        return first if isinstance(first, dict) else {}
    return response if isinstance(response, dict) else {}

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
                    "league_name": "MLB" if league_id == 1 else "LMB",
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


def obtener_estadisticas_equipo(team_id, league_id):
    key = (league_id, team_id)
    if key in STATS_CACHE:
        return STATS_CACHE[key]

    params = {
        "league": league_id,
        "season": SEASON,
        "team": team_id
    }

    try:
        r = requests.get(
            f"{BASE_URL}/teams",
            headers=_headers(),
            params=params,
            timeout=30
        )
        r.raise_for_status()

        raw = r.json().get("response", {})
        data = _first_dict(raw)

        logging.info(
            f"TEAM {team_id} league={league_id} "
            f"type(raw)={type(raw)} "
            f"type(data)={type(data)} "
            f"keys={list(data.keys()) if isinstance(data, dict) else 'NO_DICT'}"
        )

        if not data:
            return {}

        games = data.get("games", {})
        wins = games.get("wins", {})
        loses = games.get("loses", {}) or games.get("losses", {})
        points = data.get("points", {})
        points_for = points.get("for", {})
        points_against = points.get("against", {})

        stats = {
            "team_id": team_id,
            "team_name": data.get("team", {}).get("name"),
            "games_played_all": _safe_int(games.get("played", {}).get("all")),
            "games_played_home": _safe_int(games.get("played", {}).get("home")),
            "games_played_away": _safe_int(games.get("played", {}).get("away")),

            "win_pct_all": _safe_float(wins.get("all", {}).get("percentage")),
            "win_pct_home": _safe_float(wins.get("home", {}).get("percentage")),
            "win_pct_away": _safe_float(wins.get("away", {}).get("percentage")),

            "loss_pct_all": _safe_float(loses.get("all", {}).get("percentage")),
            "loss_pct_home": _safe_float(loses.get("home", {}).get("percentage")),
            "loss_pct_away": _safe_float(loses.get("away", {}).get("percentage")),

            "runs_for_all": _safe_float(points_for.get("average", {}).get("all")),
            "runs_for_home": _safe_float(points_for.get("average", {}).get("home")),
            "runs_for_away": _safe_float(points_for.get("average", {}).get("away")),

            "runs_against_all": _safe_float(points_against.get("average", {}).get("all")),
            "runs_against_home": _safe_float(points_against.get("average", {}).get("home")),
            "runs_against_away": _safe_float(points_against.get("average", {}).get("away")),
        }

        STATS_CACHE[key] = stats
        return stats

    except Exception as e:
        logging.error(f"Error stats team={team_id} league={league_id}: {e}")
        return {}


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

            standings[team_id] = {
                "team_id": team_id,
                "team_name": team.get("name"),
                "position": _safe_int(row.get("position"), 99),
                "win_pct": _safe_float(win_block.get("percentage")),
                "loss_pct": _safe_float(lose_block.get("percentage")),
                "games_played": _safe_int(games.get("played")),
                "points_for": points_for,
                "points_against": points_against,
                "run_diff": points_for - points_against
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
# MODELO DE SCORE
# ==========================

def calcular_fuerza_equipo(stats, standing, es_local):
    if not stats:
        return 0.0

    win_pct_all = stats.get("win_pct_all", 0.0)
    loc_pct = stats.get("win_pct_home" if es_local else "win_pct_away", 0.0)
    if loc_pct <= 0:
        loc_pct = win_pct_all

    if standing:
        run_diff = standing.get("run_diff", 0.0)
    else:
        run_diff = stats.get("runs_for_all", 0.0) - stats.get("runs_against_all", 0.0)

    pos_bonus = 0.0
    if standing:
        pos = _safe_int(standing.get("position"), 99)
        pos_bonus = max(0, 30 - pos) * 0.35

    strength = (win_pct_all * 45.0) + (loc_pct * 25.0) + (run_diff * 0.20) + pos_bonus
    return strength


def crear_pick_moneyline(juego, stats_home, stats_away, standing_home, standing_away, markets):
    ml = markets.get("moneyline")
    if not ml:
        return None

    home_odd = ml.get("home")
    away_odd = ml.get("away")

    if not home_odd or not away_odd:
        return None

    home_strength = calcular_fuerza_equipo(stats_home, standing_home, True)
    away_strength = calcular_fuerza_equipo(stats_away, standing_away, False)

    gap = home_strength - away_strength
    prob_home = _sigmoid(gap / 5.5)
    prob_away = 1.0 - prob_home

    home_edge = prob_home - (1.0 / home_odd)
    away_edge = prob_away - (1.0 / away_odd)

    if home_edge <= 0.01 and away_edge <= 0.01:
        return None

    if home_edge >= away_edge:
        pick_team = juego["home"]
        odd = home_odd
        edge = home_edge
        reason = "Mejor win%, diferencial y localía."
    else:
        pick_team = juego["away"]
        odd = away_odd
        edge = away_edge
        reason = "Mejor win%, diferencial y rendimiento de visita."

    confidence = int(min(95, max(50, 55 + abs(gap) * 1.3 + edge * 120)))

    if confidence < MIN_CONFIDENCE:
        return None

    return {
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": "Moneyline",
        "pick": pick_team,
        "odd": odd,
        "line": None,
        "projection": None,
        "confidence": confidence,
        "reason": reason
    }


def crear_pick_total(juego, stats_home, stats_away, market, market_name):
    if not market:
        return None

    line = market.get("line")
    over_odd = market.get("over")
    under_odd = market.get("under")

    if line is None or not over_odd or not under_odd:
        return None

    home_for = stats_home.get("runs_for_home", 0.0) or stats_home.get("runs_for_all", 0.0)
    home_against = stats_home.get("runs_against_home", 0.0) or stats_home.get("runs_against_all", 0.0)
    away_for = stats_away.get("runs_for_away", 0.0) or stats_away.get("runs_for_all", 0.0)
    away_against = stats_away.get("runs_against_away", 0.0) or stats_away.get("runs_against_all", 0.0)

    proj_home = (home_for + away_against) / 2.0
    proj_away = (away_for + home_against) / 2.0
    proj_total = proj_home + proj_away

    gap = proj_total - line

    if abs(gap) < 0.35:
        return None

    if gap > 0:
        pick_side = "Over"
        odd = over_odd
        model_prob = _sigmoid(gap * 1.8)
    else:
        pick_side = "Under"
        odd = under_odd
        model_prob = _sigmoid((-gap) * 1.8)

    edge = model_prob - (1.0 / odd)

    if edge <= 0.01:
        return None

    confidence = int(min(95, max(50, 55 + abs(gap) * 18 + edge * 120)))

    if confidence < MIN_CONFIDENCE:
        return None

    return {
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": market_name,
        "pick": f"{pick_side} {line:.1f}",
        "odd": odd,
        "line": line,
        "projection": proj_total,
        "confidence": confidence,
        "reason": f"Proyección de {proj_total:.2f} carreras vs línea {line:.1f}."
    }

# ==========================
# COMANDOS
# ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bienvenido a Boss Odds MX\n\n"
        "Comandos disponibles:\n"
        "/analizar - Muestra los juegos del día\n"
        "/picks - Genera los picks de MLB y LMB"
    )


async def analizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = await update.message.reply_text("⏳ Analizando jornada...")

    mlb = obtener_juegos(1)
    lmb = obtener_juegos(21)

    texto = "📊 JUEGOS ENCONTRADOS\n\n"

    texto += f"⚾ MLB ({len(mlb)})\n\n"
    for juego in mlb:
        texto += (
            f"🆔 Juego: {juego['game_id']}\n"
            f"🏠 Home ID: {juego['home_team_id']}\n"
            f"✈️ Away ID: {juego['away_team_id']}\n"
            f"{juego['partido']}\n\n"
        )

    texto += f"\n⚾ LMB ({len(lmb)})\n\n"
    for juego in lmb:
        texto += (
            f"🆔 Juego: {juego['game_id']}\n"
            f"🏠 Home ID: {juego['home_team_id']}\n"
            f"✈️ Away ID: {juego['away_team_id']}\n"
            f"{juego['partido']}\n\n"
        )

    await mensaje.edit_text(texto[:4000])


async def picks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = await update.message.reply_text("⏳ Analizando MLB + LMB y buscando valor...")

    juegos_mlb = obtener_juegos(1)
    juegos_lmb = obtener_juegos(21)
    juegos = juegos_mlb + juegos_lmb

    standings_mlb = obtener_standings(1)
    standings_lmb = obtener_standings(21)

    candidatos = []

    for juego in juegos:
        league_id = juego["league_id"]
        standings = standings_mlb if league_id == 1 else standings_lmb

        home_stats = obtener_estadisticas_equipo(juego["home_team_id"], league_id)
        away_stats = obtener_estadisticas_equipo(juego["away_team_id"], league_id)

        if not home_stats or not away_stats:
            logging.info(f"Skipping stats-empty game: {juego['partido']} league={league_id}")
            continue

        home_standing = standings.get(juego["home_team_id"])
        away_standing = standings.get(juego["away_team_id"])

        odds_response = obtener_odds(juego["game_id"], league_id)
        markets = extraer_mercados_odds(odds_response)

        logging.info(f"{juego['partido']} -> markets={list(markets.keys())}")

        ml_pick = crear_pick_moneyline(
            juego,
            home_stats,
            away_stats,
            home_standing,
            away_standing,
            markets
        )
        if ml_pick:
            candidatos.append(ml_pick)

        total_pick = crear_pick_total(
            juego,
            home_stats,
            away_stats,
            markets.get("total"),
            "Totales"
        )
        if total_pick:
            candidatos.append(total_pick)

        f5_pick = crear_pick_total(
            juego,
            home_stats,
            away_stats,
            markets.get("f5_total"),
            "F5 Totales"
        )
        if f5_pick:
            candidatos.append(f5_pick)

    candidatos.sort(key=lambda x: x["confidence"], reverse=True)
    top = candidatos[:MAX_PICKS]

    if not top:
        await mensaje.edit_text(
            "No se encontraron picks con ventaja suficiente para MLB + LMB."
        )
        return

    texto = "🔥 TOP PICKS BOSS ODDS\n\n"
    texto += f"📊 MLB analizados: {len(juegos_mlb)}\n"
    texto += f"📊 LMB analizados: {len(juegos_lmb)}\n"
    texto += f"📈 Candidatos detectados: {len(candidatos)}\n\n"

    for idx, pick in enumerate(top, start=1):
        texto += f"#{idx} [{pick['league_name']}]\n"
        texto += f"⚾ {pick['matchup']}\n"
        texto += f"🎯 Mercado: {pick['market']}\n"
        texto += f"Pick: {pick['pick']}\n"

        if pick.get("line") is not None:
            texto += f"Línea: {pick['line']:.1f}\n"

        if pick.get("projection") is not None:
            texto += f"Proyección: {pick['projection']:.2f}\n"

        texto += f"Cuota: {pick['odd']:.2f}\n"
        texto += f"Confianza: {pick['confidence']}/100\n"
        texto += f"Razón: {pick['reason']}\n\n"

    await mensaje.edit_text(texto[:4000])

# ==========================
# MAIN
# ==========================

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analizar", analizar))
    app.add_handler(CommandHandler("picks", picks))

    logging.info("🤖 Boss Odds iniciado")
    app.run_polling()

if __name__ == "__main__":
    main()
