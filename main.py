import os
import re
import math
import json
import uuid
import time
import requests
import logging

from collections import defaultdict
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

# ==========================
# CONFIG
# ==========================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BASEBALL_API_KEY")
CHANNEL_ID_RAW = os.getenv("TELEGRAM_CHANNEL_ID") or os.getenv("CHANNEL_ID")

if not TOKEN:
    raise ValueError("Falta TELEGRAM_TOKEN en Render")

if not API_KEY:
    raise ValueError("Falta BASEBALL_API_KEY en Render")

BASE_URL = "https://v1.baseball.api-sports.io"
SEASON = 2026
BOOKMAKER_ID = 4

MLB_LEAGUE_ID = 1
LMB_LEAGUE_ID = 21

LEAGUES = {
    MLB_LEAGUE_ID: "MLB",
    LMB_LEAGUE_ID: "LMB",
}

MAX_GAMES_TO_ANALYZE = 15
DEFAULT_MAX_PICKS = 6
MAX_PICKS_PER_MATCHUP = 2

FORM_LOOKBACK_DAYS = 30
USE_RECENT_FORM_DEFAULT = True

CACHE_TTL_SECONDS = 900  # 15 minutos

PICK_DAY_MIN_CONFIDENCE = 85
PICK_DAY_MIN_EV = 0.03

PICK_DAY_FILE = "pick_day_cache.json"
HISTORY_FILE = "picks_history.json"
LAST_GENERATED_FILE = "last_generated.json"

MARKET_FILTER_LABELS = {
    "ALL": "Todos",
    "ML": "Moneyline",
    "TOTALS": "Totales",
    "RUNLINE": "Run Line",
}

DEFAULT_MAX_PER_MARKET = {
    "Moneyline": 3,
    "Totales": 2,
    "F5 Totales": 1,
    "Run Line": 1,
}

LEAGUE_MODEL = {
    MLB_LEAGUE_ID: {  # MLB
        "base_win": 68.0,
        "base_diff": 7.0,
        "base_pos": 0.45,
        "recent_win": 15.0,
        "last5_win": 6.0,
        "recent_diff": 2.5,
        "moneyline_gap_div": 7.0,
        "totals_gap_mult": 1.7,
        "runline_gap_div": 7.5,
        "runline_ev_min": 0.03,
        "totals_ev_min": 0.012,
        "market_weights": {
            "Moneyline": 1.00,
            "Totales": 0.97,
            "F5 Totales": 0.92,
            "Run Line": 0.40,
        }
    },
    LMB_LEAGUE_ID: {  # LMB
        "base_win": 55.0,
        "base_diff": 4.5,
        "base_pos": 0.25,
        "recent_win": 22.0,
        "last5_win": 10.0,
        "recent_diff": 4.0,
        "moneyline_gap_div": 6.2,
        "totals_gap_mult": 1.9,
        "runline_gap_div": 6.8,
        "runline_ev_min": 0.035,
        "totals_ev_min": 0.015,
        "market_weights": {
            "Moneyline": 0.95,
            "Totales": 1.05,
            "F5 Totales": 0.95,
            "Run Line": 0.30,
        }
    }
}

# ==========================
# CACHES / STATE
# ==========================

GAMES_CACHE = {}
STANDINGS_CACHE = {}
ODDS_CACHE = {}
FORM_CACHE = {}

USER_SETTINGS = defaultdict(lambda: {
    "use_recent_form": USE_RECENT_FORM_DEFAULT,
    "enable_runline": True,
    "market_filter": "ALL",
    "max_picks": DEFAULT_MAX_PICKS,
    "league_id": MLB_LEAGUE_ID,
})

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

def _blend(a, b, weight=0.7):
    a = _safe_float(a)
    b = _safe_float(b)
    return (a * weight) + (b * (1 - weight))

def _clamp(value, low, high):
    return max(low, min(high, value))

def _load_json(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error leyendo {path}: {e}")
        return fallback

def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error guardando {path}: {e}")

def _cache_get(cache, key):
    entry = cache.get(key)
    if not entry:
        return None
    ts = entry.get("ts", 0)
    if time.time() - ts > CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return entry.get("data")

def _cache_set(cache, key, data):
    cache[key] = {"ts": time.time(), "data": data}

def cargar_historial():
    data = _load_json(HISTORY_FILE, [])
    return data if isinstance(data, list) else []

def guardar_historial(historial):
    _save_json(HISTORY_FILE, historial)

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
            "league_id": pick.get("league_id"),
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
            "status": "pending",
            "result": None,
            "settled_at": None
        })

    guardar_historial(historial)

def _load_last_generated_db():
    data = _load_json(LAST_GENERATED_FILE, {})
    return data if isinstance(data, dict) else {}

def _save_last_generated_db(data):
    _save_json(LAST_GENERATED_FILE, data)

def _store_last_generated(chat_id, payload):
    db = _load_last_generated_db()
    db[str(chat_id)] = payload
    _save_last_generated_db(db)

def _get_last_generated(chat_id):
    db = _load_last_generated_db()
    return db.get(str(chat_id))

def _load_pick_day_state():
    data = _load_json(PICK_DAY_FILE, {})
    return data if isinstance(data, dict) else {}

def _save_pick_day_state(state):
    _save_json(PICK_DAY_FILE, state)

def _get_pick_day_payload(league_id):
    state = _load_pick_day_state()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"{league_id}:{today}"
    return state.get(key)

def _set_pick_day_payload(league_id, payload):
    state = _load_pick_day_state()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"{league_id}:{today}"
    state[key] = payload
    _save_pick_day_state(state)

def _get_channel_chat_id():
    if not CHANNEL_ID_RAW:
        return None
    raw = str(CHANNEL_ID_RAW).strip()
    if raw.startswith("@"):
        return raw
    try:
        return int(raw)
    except Exception:
        return raw

def _as_list(response):
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return [response]
    return []

def _make_uid():
    return datetime.utcnow().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]

def _market_profit(stake, odd, result):
    if result == "win":
        return stake * (odd - 1.0)
    if result == "loss":
        return -stake
    return 0.0

def _result_label(result):
    return {
        "win": "Ganado",
        "loss": "Perdido",
        "push": "Push",
        "pending": "Pendiente",
    }.get(str(result).lower(), str(result))

def _confidence_label(confidence):
    if confidence >= 88:
        return "Elite"
    if confidence >= 82:
        return "Premium"
    if confidence >= 74:
        return "Fuerte"
    return "Moderado"

def _league_name(league_id):
    return LEAGUES.get(league_id, f"Liga {league_id}")

def _league_short(league_id):
    return "MLB" if league_id == MLB_LEAGUE_ID else "LMB" if league_id == LMB_LEAGUE_ID else f"L{league_id}"

def _filter_label(filter_key):
    return MARKET_FILTER_LABELS.get(
        str(filter_key).upper(),
        str(filter_key)
    )

def _is_reasonable_total_odd(odd):
    try:
        odd = float(odd)
        return 1.20 <= odd <= 3.20
    except Exception:
        return False

def _is_reasonable_runline_odd(odd):
    try:
        odd = float(odd)
        return 1.20 <= odd <= 2.30
    except Exception:
        return False

def _current_date():
    return datetime.utcnow().strftime("%Y-%m-%d")

def _league_settings(league_id):
    return LEAGUE_MODEL.get(league_id, LEAGUE_MODEL[MLB_LEAGUE_ID])

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

def _market_allowed(market_filter, market_name, enable_runline=True):
    if market_name == "Run Line" and not enable_runline:
        return False
    if market_filter == "ALL":
        return True
    if market_filter == "ML":
        return market_name == "Moneyline"
    if market_filter == "TOTALS":
        return market_name in {"Totales", "F5 Totales"}
    if market_filter == "RUNLINE":
        return market_name == "Run Line"
    return True

def _market_caps_for_filter(market_filter, max_picks):
    if market_filter == "ALL":
        return dict(DEFAULT_MAX_PER_MARKET)
    if market_filter == "ML":
        return {"Moneyline": max_picks}
    if market_filter == "TOTALS":
        return {"Totales": max_picks, "F5 Totales": max_picks}
    if market_filter == "RUNLINE":
        return {"Run Line": max_picks}
    return dict(DEFAULT_MAX_PER_MARKET)

def _correlation_key(pick):
    matchup = str(pick.get("matchup", ""))
    market = str(pick.get("market", ""))
    pick_text = str(pick.get("pick", "")).strip()
    pick_norm = _norm(pick_text)

    if market == "Moneyline":
        return f"{matchup}|team|{pick_norm}"

    if market == "Run Line":
        team = re.sub(r"\s*[+-]1\.5\s*$", "", pick_text).strip()
        return f"{matchup}|team|{_norm(team)}"

    if market in {"Totales", "F5 Totales"}:
        side = "over" if pick_text.lower().startswith("over") else "under"
        return f"{matchup}|{market}|{side}"

    return f"{matchup}|{market}|{pick_norm}"

def _rank_candidates(candidates, rank_by="score"):
    if rank_by == "odd":
        return sorted(candidates, key=lambda x: (x["odd"], x["score"]), reverse=True)
    if rank_by == "premium":
        return sorted(candidates, key=lambda x: (x["confidence"], x["ev"], x["score"]), reverse=True)
    return sorted(candidates, key=lambda x: x["score"], reverse=True)

def _select_candidates(candidates, max_picks, strict_day=False, rank_by="score"):
    candidates = _rank_candidates(candidates, rank_by=rank_by)

    if strict_day:
        for pick in candidates:
            if pick.get("confidence", 0) < PICK_DAY_MIN_CONFIDENCE:
                continue
            if pick.get("ev", 0.0) < PICK_DAY_MIN_EV:
                continue
            return [pick]
        return []

    selected = []
    selected_by_matchup = defaultdict(int)
    used_corr = set()

    for pick in candidates:
        matchup = pick["matchup"]
        if selected_by_matchup[matchup] >= MAX_PICKS_PER_MATCHUP:
            continue

        corr = _correlation_key(pick)
        if corr in used_corr:
            continue

        selected.append(pick)
        selected_by_matchup[matchup] += 1
        used_corr.add(corr)

        if len(selected) >= max_picks:
            break

    return selected

# ==========================
# DATA FETCH
# ==========================

def obtener_juegos(league_id):
    cache_key = ("games", league_id, SEASON, _current_date())
    cached = _cache_get(GAMES_CACHE, cache_key)
    if cached is not None:
        return cached

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
                    "league_name": _league_name(league_id),
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

    _cache_set(GAMES_CACHE, cache_key, juegos)
    return juegos

def obtener_standings(league_id):
    cache_key = ("standings", league_id, SEASON)
    cached = _cache_get(STANDINGS_CACHE, cache_key)
    if cached is not None:
        return cached

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

        _cache_set(STANDINGS_CACHE, cache_key, standings)
        return standings

    except Exception as e:
        logging.error(f"Error standings league={league_id}: {e}")
        return {}

def obtener_forma_equipo(team_id, league_id, use_recent_form=True):
    cache_key = ("form", league_id, team_id, use_recent_form, SEASON)
    cached = _cache_get(FORM_CACHE, cache_key)
    if cached is not None:
        return cached

    if not use_recent_form:
        _cache_set(FORM_CACHE, cache_key, {})
        return {}

    date_to = datetime.utcnow().strftime("%Y-%m-%d")
    date_from = (datetime.utcnow() - timedelta(days=FORM_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    params = {
        "league": league_id,
        "season": SEASON,
        "team": team_id,
        "date_from": date_from,
        "date_to": date_to
    }

    try:
        r = requests.get(
            f"{BASE_URL}/games",
            headers=_headers(),
            params=params,
            timeout=30
        )
        r.raise_for_status()

        raw = r.json().get("response", [])
        games = _as_list(raw)

        valid_games = []

        for game in games:
            status = game.get("status", {})
            short = status.get("short", "")
            long_status = status.get("long", "")

            if short != "FT" and long_status != "Finished":
                continue

            teams = game.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})

            home_id = home.get("id")
            away_id = away.get("id")

            if team_id not in {home_id, away_id}:
                continue

            scores = game.get("scores", {})
            home_score = _safe_int(scores.get("home", {}).get("total"))
            away_score = _safe_int(scores.get("away", {}).get("total"))

            team_is_home = team_id == home_id
            runs_for = home_score if team_is_home else away_score
            runs_against = away_score if team_is_home else home_score

            timestamp = _safe_int(game.get("timestamp"), 0)
            valid_games.append({
                "timestamp": timestamp,
                "runs_for": runs_for,
                "runs_against": runs_against,
                "won": runs_for > runs_against,
            })

        if not valid_games:
            _cache_set(FORM_CACHE, cache_key, {})
            return {}

        valid_games.sort(key=lambda x: x["timestamp"], reverse=True)
        last10 = valid_games[:10]
        last5 = valid_games[:5]

        def resumen(lst):
            games = len(lst)
            if not games:
                return {
                    "games": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_pct": None,
                    "runs_for_pg": None,
                    "runs_against_pg": None,
                    "run_diff_pg": None,
                    "record": "N/A",
                }

            wins = sum(1 for j in lst if j["won"])
            losses = games - wins
            runs_for = sum(j["runs_for"] for j in lst)
            runs_against = sum(j["runs_against"] for j in lst)

            return {
                "games": games,
                "wins": wins,
                "losses": losses,
                "win_pct": wins / max(1, games),
                "runs_for_pg": runs_for / max(1, games),
                "runs_against_pg": runs_against / max(1, games),
                "run_diff_pg": (runs_for - runs_against) / max(1, games),
                "record": f"{wins}-{losses}",
            }

        r10 = resumen(last10)
        r5 = resumen(last5)

        forma = {
            "recent_games": r10["games"],
            "recent_record": r10["record"],
            "last5_record": r5["record"],
            "recent_win_pct": r10["win_pct"],
            "last5_win_pct": r5["win_pct"],
            "recent_runs_for_pg": r10["runs_for_pg"],
            "recent_runs_against_pg": r10["runs_against_pg"],
            "recent_run_diff_pg": r10["run_diff_pg"],
            "last5_runs_for_pg": r5["runs_for_pg"],
            "last5_runs_against_pg": r5["runs_against_pg"],
            "last5_run_diff_pg": r5["run_diff_pg"],
        }

        _cache_set(FORM_CACHE, cache_key, forma)
        return forma

    except Exception as e:
        logging.error(f"Error forma team={team_id} league={league_id}: {e}")
        _cache_set(FORM_CACHE, cache_key, {})
        return {}

def obtener_odds(game_id, league_id):
    cache_key = ("odds", league_id, game_id, SEASON, BOOKMAKER_ID)
    cached = _cache_get(ODDS_CACHE, cache_key)
    if cached is not None:
        return cached

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
        _cache_set(ODDS_CACHE, cache_key, data)
        return data

    except Exception as e:
        logging.error(f"Error odds game={game_id} league={league_id}: {e}")
        return []

def _parse_total_market(values):
    candidates = []

    for v in values or []:
        label = str(v.get("value", "")).strip()
        odd = _safe_float(v.get("odd"))

        m = re.match(r"(?i)^(Over|Under)\s+([0-9]+(?:\.[0-9]+)?)$", label)
        if not m:
            continue

        side = m.group(1).title()
        line = float(m.group(2))
        candidates.append({
            "line": line,
            "side": side,
            "odd": odd
        })

    if not candidates:
        return None

    grouped = {}
    for c in candidates:
        grouped.setdefault(c["line"], {})[c["side"]] = c["odd"]

    complete = []
    for line, odds in grouped.items():
        if "Over" in odds and "Under" in odds:
            complete.append((line, odds["Over"], odds["Under"]))

    if not complete:
        return None

    sane = [
        item for item in complete
        if _is_reasonable_total_odd(item[1]) and _is_reasonable_total_odd(item[2])
    ]

    pool = sane if sane else complete
    line, over_odd, under_odd = min(pool, key=lambda x: abs(x[0] - 8.5))

    logging.info(f"[TOTALS DEBUG] chosen line={line} over={over_odd} under={under_odd} candidates={complete}")

    return {
        "line": line,
        "over": over_odd,
        "under": under_odd
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
                markets["moneyline"] = {"home": home_odd, "away": away_odd}

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

def calcular_fuerza_equipo(standing, forma=None, league_id=MLB_LEAGUE_ID):
    if not standing:
        return 0.0

    cfg = _league_settings(league_id)

    win_pct = standing.get("win_pct", 0.0)
    run_diff_pg = standing.get("run_diff", 0.0) / max(1, standing.get("games_played", 1))
    position = standing.get("position", 99)

    score = (win_pct * cfg["base_win"]) + (run_diff_pg * cfg["base_diff"]) + (max(0, 30 - position) * cfg["base_pos"])

    if forma:
        recent_win_pct = forma.get("recent_win_pct")
        last5_win_pct = forma.get("last5_win_pct")
        recent_run_diff_pg = forma.get("recent_run_diff_pg")

        if recent_win_pct is not None:
            score += recent_win_pct * cfg["recent_win"]
        if last5_win_pct is not None:
            score += last5_win_pct * cfg["last5_win"]
        if recent_run_diff_pg is not None:
            score += recent_run_diff_pg * cfg["recent_diff"]

    return score

def _summary_form(forma):
    if not forma:
        return "N/A"
    return f"{forma.get('recent_record', 'N/A')} últimos 10 | {forma.get('last5_record', 'N/A')} últimos 5"

def pick_moneyline(juego, standing_home, standing_away, form_home, form_away, markets):
    league_id = juego["league_id"]
    cfg = _league_settings(league_id)

    ml = markets.get("moneyline")
    if not ml:
        return None

    home_odd = ml.get("home")
    away_odd = ml.get("away")
    if not home_odd or not away_odd:
        return None

    home_strength = calcular_fuerza_equipo(standing_home, form_home, league_id)
    away_strength = calcular_fuerza_equipo(standing_away, form_away, league_id)

    gap = home_strength - away_strength
    prob_home = _sigmoid(gap / cfg["moneyline_gap_div"])

    implied_home = 1.0 / home_odd
    implied_away = 1.0 / away_odd

    home_edge = prob_home - implied_home
    away_edge = (1.0 - prob_home) - implied_away

    if max(home_edge, away_edge) < 0.015:
        return None

    if home_edge >= away_edge:
        pick_team = juego["home"]
        odd = home_odd
        ev = home_edge
        side_note = "localía"
    else:
        pick_team = juego["away"]
        odd = away_odd
        ev = away_edge
        side_note = "visita"

    form_note = ""
    if form_home and form_away:
        form_note = f" Forma: {juego['home']} {_summary_form(form_home)} | {juego['away']} {_summary_form(form_away)}."

    confidence = int(_clamp(58 + abs(gap) * 0.35 + ev * 30.0, 58, 90))
    score = (confidence * cfg["market_weights"]["Moneyline"]) + (max(ev, 0.0) * 100.0 * 0.45)

    return {
        "league_id": league_id,
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": "Moneyline",
        "pick": pick_team,
        "odd": odd,
        "line": None,
        "projection": None,
        "confidence": confidence,
        "ev": ev,
        "score": score,
        "reason": f"Mejor win%, diferencial y {side_note}.{form_note}",
        "notes": [],
    }

def pick_total(juego, standing_home, standing_away, form_home, form_away, market, market_name):
    league_id = juego["league_id"]
    cfg = _league_settings(league_id)

    if not market:
        return None

    line = market.get("line")
    over_odd = market.get("over")
    under_odd = market.get("under")

    if line is None or not over_odd or not under_odd:
        return None

    if not _is_reasonable_total_odd(over_odd) or not _is_reasonable_total_odd(under_odd):
        logging.info(f"[TOTALS DEBUG] descartado {juego['partido']} {market_name} line={line} over={over_odd} under={under_odd}")
        return None

    home_for = _blend(
        standing_home.get("runs_for_pg", 0.0) if standing_home else 0.0,
        form_home.get("recent_runs_for_pg") if form_home else None,
        0.35
    )
    home_against = _blend(
        standing_home.get("runs_against_pg", 0.0) if standing_home else 0.0,
        form_home.get("recent_runs_against_pg") if form_home else None,
        0.35
    )
    away_for = _blend(
        standing_away.get("runs_for_pg", 0.0) if standing_away else 0.0,
        form_away.get("recent_runs_for_pg") if form_away else None,
        0.35
    )
    away_against = _blend(
        standing_away.get("runs_against_pg", 0.0) if standing_away else 0.0,
        form_away.get("recent_runs_against_pg") if form_away else None,
        0.35
    )

    proj_home = (home_for + away_against) / 2.0
    proj_away = (away_for + home_against) / 2.0
    proj_total = proj_home + proj_away

    gap = proj_total - line

    if abs(gap) < 0.20:
        return None

    if gap > 0:
        pick_side = "Over"
        odd = over_odd
        model_prob = _sigmoid(gap * cfg["totals_gap_mult"])
    else:
        pick_side = "Under"
        odd = under_odd
        model_prob = _sigmoid((-gap) * cfg["totals_gap_mult"])

    implied = 1.0 / odd
    ev = model_prob - implied

    if ev < cfg["totals_ev_min"]:
        return None

    confidence = int(_clamp(58 + abs(gap) * 7.5 + ev * 25.0, 58, 88))
    score = (confidence * cfg["market_weights"][market_name]) + (max(ev, 0.0) * 100.0 * 0.40)

    form_note = ""
    if form_home and form_away:
        form_note = f" Forma: {_summary_form(form_home)} | {_summary_form(form_away)}."

    return {
        "league_id": league_id,
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": market_name,
        "pick": f"{pick_side} {line:.1f}",
        "odd": odd,
        "line": line,
        "projection": proj_total,
        "confidence": confidence,
        "ev": ev,
        "score": score,
        "reason": f"Proyección de {proj_total:.2f} carreras vs línea {line:.1f}.{form_note}",
        "notes": [],
    }

def pick_runline(juego, standing_home, standing_away, form_home, form_away, markets):
    league_id = juego["league_id"]
    cfg = _league_settings(league_id)

    runline = markets.get("runline")
    if not runline:
        return None

    home_strength = calcular_fuerza_equipo(standing_home, form_home, league_id)
    away_strength = calcular_fuerza_equipo(standing_away, form_away, league_id)
    gap = home_strength - away_strength
    home_prob = _sigmoid(gap / cfg["runline_gap_div"])

    opciones = []

    for nombre, odd in runline.items():
        if not odd:
            continue
        if not _is_reasonable_runline_odd(odd):
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

        if ev < cfg["runline_ev_min"]:
            continue

        score = (ev * 100.0 * 0.35) + abs(gap) * 0.5
        opciones.append((score, nombre, odd, ev))

    if not opciones:
        return None

    opciones.sort(reverse=True, key=lambda x: x[0])
    _, raw_pick, odd, ev = opciones[0]

    friendly_pick = _format_runline_label(raw_pick, juego)
    confidence = int(_clamp(58 + abs(gap) * 0.2 + ev * 22.0, 58, 84))
    score = (confidence * cfg["market_weights"]["Run Line"]) + (max(ev, 0.0) * 100.0 * 0.25)

    form_note = ""
    if form_home and form_away:
        form_note = f" Forma: {_summary_form(form_home)} | {_summary_form(form_away)}."

    return {
        "league_id": league_id,
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": "Run Line",
        "pick": friendly_pick,
        "odd": odd,
        "line": None,
        "projection": None,
        "confidence": confidence,
        "ev": ev,
        "score": score,
        "reason": f"Ventaja estadística ajustada por handicap.{form_note}",
        "notes": [],
    }

# ==========================
# HISTORIAL / RESULTADOS
# ==========================

def calcular_stake(confianza):
    if confianza >= 88:
        return 4
    if confianza >= 82:
        return 3
    if confianza >= 74:
        return 2
    return 1

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
        "profit": 0.0,
    }

    by_market = defaultdict(lambda: {
        "settled": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "staked": 0.0,
        "profit": 0.0,
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

# ==========================
# GENERATION CORE
# ==========================

def _build_candidates_for_league(league_id, market_filter, use_recent_form, enable_runline):
    juegos_all = obtener_juegos(league_id)
    juegos = juegos_all[:MAX_GAMES_TO_ANALYZE]
    standings = obtener_standings(league_id)

    candidatos = []

    for juego in juegos:
        home_standing = standings.get(juego["home_team_id"])
        away_standing = standings.get(juego["away_team_id"])

        home_form = obtener_forma_equipo(juego["home_team_id"], league_id, use_recent_form) if use_recent_form else {}
        away_form = obtener_forma_equipo(juego["away_team_id"], league_id, use_recent_form) if use_recent_form else {}

        odds_response = obtener_odds(juego["game_id"], league_id)
        markets = extraer_mercados_odds(odds_response)

        logging.info(f"{juego['partido']} ({_league_short(league_id)}) -> markets={list(markets.keys())}")

        if not markets:
            continue

        if _market_allowed(market_filter, "Moneyline", enable_runline):
            ml_pick = pick_moneyline(juego, home_standing, away_standing, home_form, away_form, markets)
            if ml_pick:
                candidatos.append(ml_pick)

        if _market_allowed(market_filter, "Totales", enable_runline):
            total_pick = pick_total(
                juego, home_standing, away_standing, home_form, away_form, markets.get("total"), "Totales"
            )
            if total_pick:
                candidatos.append(total_pick)

            f5_pick = pick_total(
                juego, home_standing, away_standing, home_form, away_form, markets.get("f5_total"), "F5 Totales"
            )
            if f5_pick:
                candidatos.append(f5_pick)

        if _market_allowed(market_filter, "Run Line", enable_runline):
            runline_pick = pick_runline(juego, home_standing, away_standing, home_form, away_form, markets)
            if runline_pick:
                candidatos.append(runline_pick)

    return juegos_all, juegos, candidatos

def _select_final_picks(candidatos, market_filter, max_picks, strict_day=False, premium_mode=False, best_odds_mode=False):
    if premium_mode:
        candidatos = [c for c in candidatos if c.get("confidence", 0) >= 82 and c.get("ev", 0.0) >= 0.04]
    if best_odds_mode:
        candidatos = [c for c in candidatos if c.get("confidence", 0) >= 75 and c.get("ev", 0.0) >= 0.02]

    rank_by = "score"
    if premium_mode:
        rank_by = "premium"
    elif best_odds_mode:
        rank_by = "odd"

    if strict_day:
        return _select_candidates(candidatos, 1, strict_day=True, rank_by="score")

    market_caps = _market_caps_for_filter(market_filter, max_picks)
    preliminares = _select_candidates(candidatos, max_picks * 2, strict_day=False, rank_by=rank_by)

    seleccionados = []
    conteo_mercados = defaultdict(int)

    for pick in preliminares:
        mercado = pick["market"]
        limite = market_caps.get(mercado, max_picks)

        if conteo_mercados[mercado] >= limite:
            continue

        seleccionados.append(pick)
        conteo_mercados[mercado] += 1

        if len(seleccionados) >= max_picks:
            break

    return seleccionados

def generar_picks(
    chat_id,
    league_id,
    market_filter="DEFAULT",
    max_picks=0,
    use_recent_form=None,
    enable_runline=None,
    strict_day=False,
    premium_mode=False,
    best_odds_mode=False
):
    settings = USER_SETTINGS[chat_id]

    if market_filter == "DEFAULT":
        market_filter = settings["market_filter"]

    if max_picks <= 0:
        max_picks = settings["max_picks"]

    if use_recent_form is None:
        use_recent_form = settings["use_recent_form"]

    if enable_runline is None:
        enable_runline = settings["enable_runline"]

    if strict_day:
        market_filter = "ALL"
        max_picks = 1

    juegos_all, juegos, candidatos = _build_candidates_for_league(
        league_id=league_id,
        market_filter=market_filter,
        use_recent_form=use_recent_form,
        enable_runline=enable_runline
    )

    seleccionados = _select_final_picks(
        candidatos,
        market_filter=market_filter,
        max_picks=max_picks,
        strict_day=strict_day,
        premium_mode=premium_mode,
        best_odds_mode=best_odds_mode
    )

    meta = {
        "analizados": len(juegos_all),
        "usados": len(juegos),
        "candidatos": len(candidatos),
    }

    return seleccionados, meta, settings

def _build_payload_from_selection(selected, meta, settings, league_id, market_filter, max_picks, mode_label, strict_day=False):
    picks_guardados = []
    for pick in selected:
        pick = dict(pick)
        pick["uid"] = _make_uid()
        pick["stake"] = calcular_stake(pick["confidence"])
        picks_guardados.append(pick)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "league_id": league_id,
        "league_name": _league_name(league_id),
        "market_filter": market_filter,
        "max_picks": max_picks,
        "meta": meta,
        "settings": settings,
        "picks": picks_guardados,
        "mode_label": mode_label,
        "strict_day": strict_day,
    }

def _build_summary_text(payload):
    meta = payload["meta"]
    picks = payload["picks"]
    settings = payload["settings"]
    league_name = payload.get("league_name", "Liga")
    mode_label = payload.get("mode_label", "Top Picks")

    counts = defaultdict(int)
    for pick in picks:
        counts[pick["market"]] += 1

    texto = f"🔥 TOP PICKS BOSS ODDS | {league_name}\n\n"
    texto += f"🎛 Modo: {mode_label}\n"
    texto += f"🎛 Filtro: {_league_short(payload.get('league_id', MLB_LEAGUE_ID))} / {_filter_label(payload['market_filter'])}\n"
    texto += f"📊 Juegos analizados: {meta['analizados']}\n"
    texto += f"📈 Juegos usados: {meta['usados']}\n"
    texto += f"📈 Candidatos: {meta['candidatos']}\n"
    texto += f"🎯 Seleccionados: {len(picks)}\n"
    texto += f"🔢 Top solicitado: {payload['max_picks']}\n\n"

    for market in ["Moneyline", "Totales", "F5 Totales", "Run Line"]:
        if counts.get(market):
            texto += f"• {market}: {counts[market]}\n"

    texto += "\n"
    texto += f"Forma reciente: {'ON' if settings['use_recent_form'] else 'OFF'}\n"
    texto += f"Run Line: {'ON' if settings['enable_runline'] else 'OFF'}\n"
    texto += "\nCada pick llega en un mensaje separado.\n"

    return texto[:4000]

def _build_pick_card(pick, idx):
    level = _confidence_label(pick["confidence"])
    texto = (
        f"{'🔥' if idx == 1 else '🥈' if idx == 2 else '🥉' if idx == 3 else '⭐'} PICK #{idx}\n"
        f"⚾ {pick['matchup']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"✅ Selección: {pick['pick']}\n"
        f"🎯 Mercado: {pick['market']}\n"
        f"💰 Cuota: {pick['odd']:.2f}\n"
    )

    if pick.get("line") is not None:
        texto += f"📏 Línea: {pick['line']:.1f}\n"

    if pick.get("projection") is not None:
        texto += f"📈 Proyección: {pick['projection']:.2f}\n"

    texto += (
        f"🎲 Stake: {pick['stake']}/5\n"
        f"📊 Confianza: {pick['confidence']}%\n"
        f"⭐ Nivel: {level}\n"
        f"📉 EV: {pick.get('ev', 0.0) * 100:+.1f}%\n"
        f"━━━━━━━━━━━━━━\n"
        f"Boss Odds MX\n"
    )

    return texto[:4000]

def _build_analysis_text(payload):
    if not payload or not payload.get("picks"):
        return "Todavía no hay una selección reciente para mostrar análisis."

    meta = payload["meta"]
    picks = payload["picks"]

    texto = "📋 ANÁLISIS DETALLADO\n\n"
    texto += f"Liga: {payload.get('league_name', 'N/A')}\n"
    texto += f"Modo: {payload.get('mode_label', 'Top Picks')}\n"
    texto += f"Filtro: {_filter_label(payload.get('market_filter', 'ALL'))}\n"
    texto += f"Generado: {payload.get('generated_at', 'N/A')}\n"
    texto += f"Analizados: {meta.get('analizados', 0)} | Candidatos: {meta.get('candidatos', 0)}\n\n"

    for idx, pick in enumerate(picks, start=1):
        texto += f"{idx}. {pick['matchup']}\n"
        texto += f"   {pick['market']} -> {pick['pick']}\n"
        texto += f"   Cuota: {pick['odd']:.2f} | Confianza: {pick['confidence']}% | EV: {pick.get('ev', 0.0) * 100:+.1f}%\n"
        if pick.get("line") is not None:
            texto += f"   Línea: {pick['line']:.1f}\n"
        if pick.get("projection") is not None:
            texto += f"   Proyección: {pick['projection']:.2f}\n"
        texto += f"   Razón: {pick.get('reason', '')}\n\n"

    return texto[:4000]

def _build_channel_summary_text(payload):
    meta = payload["meta"]
    settings = payload["settings"]

    texto = f"🔥 BOSS ODDS MX | {_league_name(payload.get('league_id', MLB_LEAGUE_ID))}\n\n"
    texto += f"🎛 Modo: {payload.get('mode_label', 'Top Picks')}\n"
    texto += f"🎛 Filtro: {_filter_label(payload.get('market_filter', 'ALL'))}\n"
    texto += f"📊 Juegos analizados: {meta['analizados']}\n"
    texto += f"📈 Candidatos: {meta['candidatos']}\n"
    texto += f"🎯 Publicados: {len(payload.get('picks', []))}\n"
    texto += f"🔢 Top: {payload.get('max_picks', len(payload.get('picks', [])))}\n"
    texto += f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
    texto += f"Forma reciente: {'ON' if settings['use_recent_form'] else 'OFF'} | Run Line: {'ON' if settings['enable_runline'] else 'OFF'}\n"
    return texto[:4000]

def _build_channel_pick_text(pick, idx):
    level = _confidence_label(pick["confidence"])
    texto = (
        f"{'🔥' if idx == 1 else '🥈' if idx == 2 else '🥉' if idx == 3 else '⭐'} PICK #{idx}\n"
        f"⚾ {pick['matchup']}\n"
        f"✅ {pick['pick']}\n"
        f"🎯 Mercado: {pick['market']}\n"
        f"💰 Cuota: {pick['odd']:.2f}\n"
    )
    if pick.get("line") is not None:
        texto += f"📏 Línea: {pick['line']:.1f}\n"
    texto += (
        f"🎲 Stake: {pick['stake']}/5\n"
        f"📊 Confianza: {pick['confidence']}% ({level})\n"
        f"📉 EV: {pick.get('ev', 0.0) * 100:+.1f}%\n"
        f"━━━━━━━━━━━━━━\n"
        f"Boss Odds MX VIP\n"
    )
    return texto[:4000]

def _replace_status(text, new_status_label):
    if not text:
        return f"Estado: {new_status_label}"
    if "Estado:" in text:
        return re.sub(r"Estado:\s*.*", f"Estado: {new_status_label}", text, count=1)
    return text + f"\n\nEstado: {new_status_label}"

def _build_vip_text():
    return (
        "👑 BOSS ODDS VIP\n\n"
        "Planes de membresía:\n\n"
        "1 mes: $500 MXN\n"
        "3 meses: $900 MXN\n"
        "12 meses: $2,000 MXN\n\n"
        "Acceso a picks premium, análisis más profundo y selección diaria."
    )

def _build_history_text():
    historial = cargar_historial()
    if not historial:
        return "Todavía no hay picks guardados."

    ultimos = historial[-10:]
    texto = "🗂 ÚLTIMOS PICKS\n\n"

    for item in reversed(ultimos):
        odd = _safe_float(item.get("odd"), 0.0)
        texto += (
            f"UID: {item.get('uid')}\n"
            f"{item.get('market')} | {item.get('pick')}\n"
            f"{item.get('matchup')}\n"
            f"Cuota: {odd:.2f} | Stake: {item.get('stake')} | Estado: {_result_label(item.get('status'))}\n\n"
        )

    return texto[:4000]

def _build_performance_text():
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

    texto = "📊 RENDIMIENTO\n\n"
    texto += _line("General", overall) + "\n"

    for market in ["Moneyline", "Totales", "F5 Totales", "Run Line"]:
        if market in by_market:
            texto += _line(market, by_market[market]) + "\n"

    return texto[:4000]

def _build_rankings_text(league_id):
    standings = obtener_standings(league_id)
    if not standings:
        return f"No hay standings disponibles para {_league_name(league_id)}."

    rows = []
    for team_id, data in standings.items():
        win_pct = _safe_float(data.get("win_pct"), 0.0)
        games_played = _safe_int(data.get("games_played"), 1)
        run_diff = _safe_float(data.get("run_diff"), 0.0)
        pos = _safe_int(data.get("position"), 99)
        score = (win_pct * 68.0) + ((run_diff / max(1, games_played)) * 7.0) + (max(0, 30 - pos) * 0.45)
        rows.append((score, data))

    rows.sort(key=lambda x: x[0], reverse=True)
    top = rows[:10]

    texto = f"📈 POWER RANKINGS {_league_name(league_id)}\n\n"
    for i, (score, data) in enumerate(top, start=1):
        texto += (
            f"{i}. {data.get('team_name')}\n"
            f"   Win%: {(_safe_float(data.get('win_pct')) * 100):.1f}% | "
            f"RD: {_safe_float(data.get('run_diff')):+.0f} | "
            f"Score: {score:.1f}\n\n"
        )

    return texto[:4000]

def _build_games_text(league_id):
    mlb = obtener_juegos(league_id)
    texto = f"📅 CARTELERA {_league_name(league_id)}\n\n"
    texto += f"⚾ Juegos encontrados: {len(mlb)}\n\n"

    for juego in mlb:
        texto += f"• {juego['away']} vs {juego['home']}  (ID {juego['game_id']})\n"

    return texto[:4000]

def _build_test_text(league_id):
    juegos = obtener_juegos(league_id)
    standings = obtener_standings(league_id)

    total_odds = 0
    ml = 0
    totals = 0
    f5 = 0
    runline = 0

    for j in juegos:
        odds_response = obtener_odds(j["game_id"], league_id)
        if odds_response:
            total_odds += 1
            markets = extraer_mercados_odds(odds_response)
            if markets.get("moneyline"):
                ml += 1
            if markets.get("total"):
                totals += 1
            if markets.get("f5_total"):
                f5 += 1
            if markets.get("runline"):
                runline += 1

    texto = f"🧪 TEST {_league_name(league_id)}\n\n"
    texto += f"Juegos próximos: {len(juegos)}\n"
    texto += f"Juegos con odds: {total_odds}\n"
    texto += f"Moneyline disponible: {ml}\n"
    texto += f"Totales disponibles: {totals}\n"
    texto += f"F5 Totales disponibles: {f5}\n"
    texto += f"Run Line disponible: {runline}\n"
    texto += f"Standings cargados: {'Sí' if standings else 'No'}\n"
    return texto[:4000]

def _main_menu_text(chat_id):
    s = USER_SETTINGS[chat_id]
    return (
        "🔥 BOSS ODDS MX\n\n"
        "Selecciona una liga.\n\n"
        f"Liga por defecto: {_league_name(s['league_id'])}\n"
        f"Top por defecto: {s['max_picks']}\n"
        f"Forma reciente: {'ON' if s['use_recent_form'] else 'OFF'}\n"
        f"Run Line: {'ON' if s['enable_runline'] else 'OFF'}"
    )

def _config_menu_text(chat_id):
    s = USER_SETTINGS[chat_id]
    return (
        "⚙️ CONFIGURACIÓN\n\n"
        f"Liga por defecto: {_league_name(s['league_id'])}\n"
        f"Forma reciente: {'ON' if s['use_recent_form'] else 'OFF'}\n"
        f"Run Line: {'ON' if s['enable_runline'] else 'OFF'}\n"
        f"Modo por defecto: {_filter_label(s['market_filter'])}\n"
        f"Top por defecto: {s['max_picks']}"
    )

# ==========================
# KEYBOARDS
# ==========================

def main_menu_markup():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 MLB", callback_data=f"league:{MLB_LEAGUE_ID}"),
            InlineKeyboardButton("🇲🇽 LMB", callback_data=f"league:{LMB_LEAGUE_ID}"),
        ],
        [
            InlineKeyboardButton("📊 Rendimiento", callback_data="menu:rendimiento"),
            InlineKeyboardButton("📈 Rankings MLB", callback_data=f"rankings:{MLB_LEAGUE_ID}"),
        ],
        [
            InlineKeyboardButton("📈 Rankings LMB", callback_data=f"rankings:{LMB_LEAGUE_ID}"),
            InlineKeyboardButton("🗂 Historial", callback_data="menu:historial"),
        ],
        [
            InlineKeyboardButton("👑 VIP", callback_data="menu:vip"),
            InlineKeyboardButton("⚙️ Configuración", callback_data="menu:config"),
        ]
    ])

def league_menu_markup(league_id):
    rows = [
        [InlineKeyboardButton("🔥 Pick del Día", callback_data=f"gen:{league_id}:DAY:1")],
        [
            InlineKeyboardButton("🥇 Top 3", callback_data=f"gen:{league_id}:DEFAULT:3"),
            InlineKeyboardButton("⭐ Top 6", callback_data=f"gen:{league_id}:DEFAULT:6"),
        ],
        [
            InlineKeyboardButton("💎 Top Premium", callback_data=f"gen:{league_id}:PREMIUM:3"),
            InlineKeyboardButton("💰 Mejor Cuota del Día", callback_data=f"gen:{league_id}:ODDS:1"),
        ],
        [
            InlineKeyboardButton("💰 Moneyline", callback_data=f"gen:{league_id}:ML:0"),
            InlineKeyboardButton("📈 Totales", callback_data=f"gen:{league_id}:TOTALS:0"),
        ],
        [
            InlineKeyboardButton("🏃 Run Line", callback_data=f"gen:{league_id}:RUNLINE:0"),
            InlineKeyboardButton("📢 Publicar al Canal", callback_data="publish:last"),
        ],
        [
            InlineKeyboardButton("📋 Ver análisis", callback_data="analysis:last"),
        ]
    ]

    if league_id == LMB_LEAGUE_ID:
        rows.insert(4, [InlineKeyboardButton("🧪 Test LMB", callback_data=f"test:{LMB_LEAGUE_ID}")])

    rows.append([InlineKeyboardButton("🔙 Menú", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

def publish_summary_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver análisis", callback_data="analysis:last")],
        [InlineKeyboardButton("📢 Publicar al Canal", callback_data="publish:last")],
        [InlineKeyboardButton("🔙 Menú", callback_data="menu:main")],
    ])

def pick_result_markup(uid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Win", callback_data=f"res:{uid}:win"),
            InlineKeyboardButton("❌ Loss", callback_data=f"res:{uid}:loss"),
            InlineKeyboardButton("➖ Push", callback_data=f"res:{uid}:push"),
        ],
        [
            InlineKeyboardButton("🗂 Historial", callback_data="menu:historial"),
            InlineKeyboardButton("📊 Rendimiento", callback_data="menu:rendimiento"),
        ]
    ])

def config_menu_markup(chat_id):
    s = USER_SETTINGS[chat_id]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"Liga: {_league_name(s['league_id'])}",
                callback_data=f"league:{s['league_id']}"
            ),
        ],
        [
            InlineKeyboardButton(
                f"Forma reciente: {'ON' if s['use_recent_form'] else 'OFF'}",
                callback_data="config:toggle_form"
            ),
            InlineKeyboardButton(
                f"Run Line: {'ON' if s['enable_runline'] else 'OFF'}",
                callback_data="config:toggle_runline"
            ),
        ],
        [
            InlineKeyboardButton("Modo: Todos", callback_data="config:set_filter:ALL"),
            InlineKeyboardButton("Modo: Moneyline", callback_data="config:set_filter:ML"),
        ],
        [
            InlineKeyboardButton("Modo: Totales", callback_data="config:set_filter:TOTALS"),
            InlineKeyboardButton("Modo: Run Line", callback_data="config:set_filter:RUNLINE"),
        ],
        [
            InlineKeyboardButton("Top 3", callback_data="config:set_top:3"),
            InlineKeyboardButton("Top 6", callback_data="config:set_top:6"),
        ],
        [
            InlineKeyboardButton("🔙 Menú", callback_data="menu:main"),
        ]
    ])

# ==========================
# ACTIONS
# ==========================

async def _send_payload(chat_id, context, payload, query=None):
    if not payload.get("picks"):
        msg = "No se encontraron picks con ventaja suficiente."
        if payload.get("strict_day"):
            msg = "No se encontró un Pick del Día con el umbral actual."
        if query is not None:
            await query.edit_message_text(msg, reply_markup=main_menu_markup())
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=main_menu_markup())
        return

    summary_text = _build_summary_text(payload)
    if query is not None:
        await query.edit_message_text(summary_text, reply_markup=publish_summary_markup())
    else:
        await context.bot.send_message(chat_id=chat_id, text=summary_text, reply_markup=publish_summary_markup())

    for idx, pick in enumerate(payload["picks"], start=1):
        await context.bot.send_message(
            chat_id=chat_id,
            text=_build_pick_card(pick, idx),
            reply_markup=pick_result_markup(pick["uid"])
        )

async def ejecutar_generacion(
    chat_id,
    context,
    league_id,
    market_filter="DEFAULT",
    max_picks=0,
    strict_day=False,
    premium_mode=False,
    best_odds_mode=False,
    query=None
):
    settings = USER_SETTINGS[chat_id]

    try:
        if query is not None:
            await query.edit_message_text("⏳ Analizando y buscando valor...")
        else:
            await context.bot.send_message(chat_id=chat_id, text="⏳ Analizando y buscando valor...")

        selected, meta, settings = generar_picks(
            chat_id=chat_id,
            league_id=league_id,
            market_filter=market_filter,
            max_picks=max_picks,
            use_recent_form=settings["use_recent_form"],
            enable_runline=settings["enable_runline"],
            strict_day=strict_day,
            premium_mode=premium_mode,
            best_odds_mode=best_odds_mode
        )

        if strict_day:
            mode_label = "Pick del Día"
        elif premium_mode:
            mode_label = "Top Premium"
        elif best_odds_mode:
            mode_label = "Mejor Cuota del Día"
        else:
            mode_label = "Top Picks"

        payload = _build_payload_from_selection(
            selected=selected,
            meta=meta,
            settings=settings,
            league_id=league_id,
            market_filter=market_filter if market_filter != "DEFAULT" else settings["market_filter"],
            max_picks=max_picks if max_picks > 0 else settings["max_picks"],
            mode_label=mode_label,
            strict_day=strict_day
        )

        guardar_picks_en_historial(payload["picks"])
        _store_last_generated(chat_id, payload)

        await _send_payload(chat_id, context, payload, query=query)

    except Exception as e:
        logging.exception(f"Error en ejecutar_generacion league={league_id}: {e}")
        try:
            if query is not None:
                await query.edit_message_text(
                    f"⚠️ Ocurrió un error al generar picks.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Ocurrió un error al generar picks.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
        except Exception:
            pass

async def ejecutar_pick_del_dia(chat_id, context, league_id, query=None):
    try:
        cached = _get_pick_day_payload(league_id)
        if cached:
            _store_last_generated(chat_id, cached)
            await _send_payload(chat_id, context, cached, query=query)
            return

        settings = USER_SETTINGS[chat_id]
        selected, meta, _ = generar_picks(
            chat_id=chat_id,
            league_id=league_id,
            market_filter="ALL",
            max_picks=1,
            use_recent_form=settings["use_recent_form"],
            enable_runline=settings["enable_runline"],
            strict_day=True
        )

        payload = _build_payload_from_selection(
            selected=selected,
            meta=meta,
            settings=settings,
            league_id=league_id,
            market_filter="ALL",
            max_picks=1,
            mode_label="Pick del Día",
            strict_day=True
        )

        _set_pick_day_payload(league_id, payload)
        guardar_picks_en_historial(payload["picks"])
        _store_last_generated(chat_id, payload)

        await _send_payload(chat_id, context, payload, query=query)

    except Exception as e:
        logging.exception(f"Error en ejecutar_pick_del_dia league={league_id}: {e}")
        try:
            if query is not None:
                await query.edit_message_text(
                    f"⚠️ Ocurrió un error al generar el Pick del Día.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Ocurrió un error al generar el Pick del Día.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
        except Exception:
            pass

async def publish_last_to_channel(chat_id, context):
    payload = _get_last_generated(chat_id)
    if not payload or not payload.get("picks"):
        return False, "No hay picks recientes para publicar. Genera primero un Top 3, Top 6 o Pick del Día."

    channel_id = _get_channel_chat_id()
    if channel_id is None:
        return False, "Falta configurar TELEGRAM_CHANNEL_ID en Render."

    try:
        summary = _build_channel_summary_text(payload)
        await context.bot.send_message(chat_id=channel_id, text=summary)

        for idx, pick in enumerate(payload["picks"], start=1):
            await context.bot.send_message(chat_id=channel_id, text=_build_channel_pick_text(pick, idx))

        payload["published_at"] = datetime.utcnow().isoformat()
        _store_last_generated(chat_id, payload)

        return True, f"Publicado en el canal: {len(payload['picks'])} picks."
    except Exception as e:
        logging.error(f"Error publicando al canal: {e}")
        return False, f"No se pudo publicar en el canal: {e}"

# ==========================
# MENÚS / CALLBACKS
# ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    USER_SETTINGS[chat_id]
    await update.message.reply_text(
        _main_menu_text(chat_id),
        reply_markup=main_menu_markup()
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        data = query.data
        chat_id = query.message.chat.id
        settings = USER_SETTINGS[chat_id]

        if data == "menu:main":
            await query.answer()
            await query.edit_message_text(
                _main_menu_text(chat_id),
                reply_markup=main_menu_markup()
            )
            return

        if data == "menu:rendimiento":
            await query.answer()
            await query.edit_message_text(_build_performance_text(), reply_markup=main_menu_markup())
            return

        if data == "menu:historial":
            await query.answer()
            await query.edit_message_text(_build_history_text(), reply_markup=main_menu_markup())
            return

        if data == "menu:vip":
            await query.answer()
            await query.edit_message_text(_build_vip_text(), reply_markup=main_menu_markup())
            return

        if data == "menu:config":
            await query.answer()
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data.startswith("league:"):
            _, lid = data.split(":", 1)
            league_id = _safe_int(lid, MLB_LEAGUE_ID)
            settings["league_id"] = league_id
            await query.answer()
            await query.edit_message_text(
                f"🎯 {_league_name(league_id)}\n\nElige una opción.",
                reply_markup=league_menu_markup(league_id)
            )
            return

        if data.startswith("rankings:"):
            _, lid = data.split(":", 1)
            league_id = _safe_int(lid, MLB_LEAGUE_ID)
            await query.answer()
            await query.edit_message_text(_build_rankings_text(league_id), reply_markup=main_menu_markup())
            return

        if data == "analysis:last":
            await query.answer()
            payload = _get_last_generated(chat_id) or _get_pick_day_payload(settings["league_id"])
            await query.edit_message_text(_build_analysis_text(payload), reply_markup=main_menu_markup())
            return

        if data == "config:toggle_form":
            settings["use_recent_form"] = not settings["use_recent_form"]
            await query.answer("Forma reciente actualizada")
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data == "config:toggle_runline":
            settings["enable_runline"] = not settings["enable_runline"]
            await query.answer("Run Line actualizado")
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data.startswith("config:set_filter:"):
            _, _, filter_key = data.split(":", 2)
            settings["market_filter"] = filter_key
            await query.answer("Modo por defecto actualizado")
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data.startswith("config:set_top:"):
            _, _, top_s = data.split(":", 2)
            settings["max_picks"] = _safe_int(top_s, DEFAULT_MAX_PICKS)
            await query.answer("Top por defecto actualizado")
            await query.edit_message_text(_config_menu_text(chat_id), reply_markup=config_menu_markup(chat_id))
            return

        if data.startswith("test:"):
            _, lid = data.split(":", 1)
            league_id = _safe_int(lid, LMB_LEAGUE_ID)
            await query.answer()
            await query.edit_message_text(_build_test_text(league_id), reply_markup=league_menu_markup(league_id))
            return

        if data.startswith("gen:"):
            _, lid, mode, limit_s = data.split(":", 3)
            league_id = _safe_int(lid, settings["league_id"])

            strict_day = False
            premium_mode = False
            best_odds_mode = False
            filter_key = settings["market_filter"]

            if mode == "DAY":
                await query.answer("Generando Pick del Día...", show_alert=False)
                await ejecutar_pick_del_dia(chat_id=chat_id, context=context, league_id=league_id, query=query)
                return

            if mode == "PREMIUM":
                premium_mode = True
                filter_key = "ALL"
                limit = _safe_int(limit_s, 3)
            elif mode == "ODDS":
                best_odds_mode = True
                filter_key = "ALL"
                limit = 1
            elif mode == "DEFAULT":
                limit = _safe_int(limit_s, settings["max_picks"])
                filter_key = settings["market_filter"]
            else:
                limit = _safe_int(limit_s, settings["max_picks"])
                filter_key = mode

            if limit <= 0:
                limit = settings["max_picks"]

            await query.answer("Generando picks...", show_alert=False)
            await ejecutar_generacion(
                chat_id=chat_id,
                context=context,
                league_id=league_id,
                market_filter=filter_key,
                max_picks=limit,
                strict_day=strict_day,
                premium_mode=premium_mode,
                best_odds_mode=best_odds_mode,
                query=query
            )
            return

        if data == "publish:last":
            await query.answer("Publicando al canal...", show_alert=False)
            ok, msg = await publish_last_to_channel(chat_id, context)
            await context.bot.send_message(
                chat_id=chat_id,
                text=("✅ " + msg) if ok else ("⚠️ " + msg),
                reply_markup=main_menu_markup()
            )
            return

        if data.startswith("res:"):
            _, uid, result = data.split(":", 2)
            updated = marcar_resultado(uid, result)

            if not updated:
                await query.answer("No encontré ese pick")
                return

            current_text = query.message.text or ""
            new_text = _replace_status(current_text, _result_label(result))

            await query.edit_message_text(
                text=new_text,
                reply_markup=pick_result_markup(uid)
            )
            await query.answer(f"Marcado como {_result_label(result)}")
            return

        await query.answer()

    except Exception as e:
        logging.exception(f"Error en handle_callback: {e}")
        try:
            if update.callback_query:
                await update.callback_query.answer("Ocurrió un error")
                await update.callback_query.edit_message_text(
                    f"⚠️ Ocurrió un error.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
        except Exception:
            pass

# ==========================
# ERROR HANDLER
# ==========================

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Error no manejado", exc_info=context.error)

# ==========================
# MAIN
# ==========================

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(on_error)

    logging.info("🤖 Boss Odds iniciado")
    app.run_polling()

if __name__ == "__main__":
    main()
