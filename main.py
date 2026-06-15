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
from itertools import combinations
from zoneinfo import ZoneInfo

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

# Usar todas las casas disponibles
BOOKMAKER_ID = None

MLB_LEAGUE_ID = 1
LMB_LEAGUE_ID = 21

LEAGUES = {
    MLB_LEAGUE_ID: "MLB",
    LMB_LEAGUE_ID: "LMB",
}

MEXICO_TZ = ZoneInfo("America/Mexico_City")

MAX_GAMES_TO_ANALYZE = 15
DEFAULT_MAX_PICKS = 6
MAX_PICKS_PER_MATCHUP = 2

FORM_LOOKBACK_DAYS = 30
USE_RECENT_FORM_DEFAULT = True

CACHE_TTL_SECONDS = 900

PICK_DAY_MIN_CONFIDENCE = 80
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

BASE_TOTALS = {
    MLB_LEAGUE_ID: 8.7,
    LMB_LEAGUE_ID: 10.0,
}

LEAGUE_MODEL = {
    MLB_LEAGUE_ID: {
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
    LMB_LEAGUE_ID: {
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

def _dbg(msg: str):
    logging.info(msg)
    print(msg, flush=True)

def _mx_now():
    return datetime.now(MEXICO_TZ)

def _mx_date():
    return _mx_now().strftime("%Y-%m-%d")

def _mx_stamp():
    return _mx_now().strftime("%d/%m/%Y %I:%M %p")

def _month_key(dt=None):
    dt = dt or _mx_now()
    return dt.strftime("%Y-%m")

def _month_label(dt=None):
    dt = dt or _mx_now()
    months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    ]
    return f"{months[dt.month - 1].capitalize()} {dt.year}"

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

def _as_list(response):
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return [response]
    return []

def _make_uid():
    return _mx_now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]

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

def _replace_status(text, new_status):
    try:
        if not text:
            return f"Estado: {new_status}"

        if "Estado:" in text:
            return re.sub(r"Estado:\s*.*", f"Estado: {new_status}", text, count=1)

        return text + f"\n\nEstado: {new_status}"
    except Exception:
        return text

def _probability_label(probability):
    if probability >= 88:
        return "Muy alta"
    if probability >= 82:
        return "Alta"
    if probability >= 74:
        return "Media"
    return "Baja"

def _league_name(league_id):
    return LEAGUES.get(league_id, f"Liga {league_id}")

def _league_short(league_id):
    if league_id == MLB_LEAGUE_ID:
        return "MLB"
    if league_id == LMB_LEAGUE_ID:
        return "LMB"
    return f"L{league_id}"

def _filter_label(filter_key):
    return MARKET_FILTER_LABELS.get(str(filter_key).upper(), str(filter_key))

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

def _league_settings(league_id):
    return LEAGUE_MODEL.get(league_id, LEAGUE_MODEL[MLB_LEAGUE_ID])

def _league_baseline_total(league_id):
    return BASE_TOTALS.get(league_id, BASE_TOTALS[MLB_LEAGUE_ID])

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
        return sorted(candidates, key=lambda x: (
            x["odd"],
            x.get("probability", x.get("confidence", 0)),
            x["score"]
        ), reverse=True)
    if rank_by == "premium":
        return sorted(candidates, key=lambda x: (
            x.get("probability", x.get("confidence", 0)),
            x["score"],
            x["ev"],
            -x.get("odd", 0.0)
        ), reverse=True)
    if rank_by == "probability":
        return sorted(candidates, key=lambda x: (
            x.get("probability", x.get("confidence", 0)),
            x["score"],
            x["ev"],
            -x.get("odd", 0.0)
        ), reverse=True)
    return sorted(candidates, key=lambda x: (
        x.get("probability", x.get("confidence", 0)),
        x["score"],
        x["ev"],
        -x.get("odd", 0.0)
    ), reverse=True)

def _select_candidates(candidates, max_picks, strict_day=False, rank_by="score"):
    candidates = _rank_candidates(candidates, rank_by=rank_by)

    if strict_day:
        for pick in candidates:
            if pick.get("probability", pick.get("confidence", 0)) < PICK_DAY_MIN_CONFIDENCE:
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

def _smart_probability(total_gap, ev, league_id, market_name):
    gap_abs = abs(total_gap)
    base = 50.0

    if market_name == "Moneyline":
        base += gap_abs * 2.65
        base += max(0.0, ev) * 125.0
    elif market_name in {"Totales", "F5 Totales"}:
        base += gap_abs * 2.95
        base += max(0.0, ev) * 118.0
    elif market_name == "Run Line":
        base += gap_abs * 2.45
        base += max(0.0, ev) * 110.0

    if league_id == LMB_LEAGUE_ID:
        base += 1.0

    return int(_clamp(base, 50, 90))

def _stake_from_probability(probability):
    if probability >= 88:
        return 4
    if probability >= 82:
        return 3
    if probability >= 74:
        return 2
    return 1

def _odd_pressure(odd):
    """Penalty for higher odds so the model favors hit-rate over payout size."""
    odd = _safe_float(odd, 0.0)
    if odd <= 1.55:
        return 0.0
    if odd <= 1.90:
        return (odd - 1.55) * 0.8
    if odd <= 2.20:
        return 0.28 + (odd - 1.90) * 2.0
    if odd <= 2.60:
        return 0.88 + (odd - 2.20) * 3.0
    return 2.08 + (odd - 2.60) * 4.0

def _odds_gate(probability, odd, market_name):
    odd = _safe_float(odd, 0.0)
    probability = _safe_int(probability, 0)
    if market_name == "Moneyline":
        if odd >= 1.80 and probability < 72:
            return False
        if odd >= 2.05 and probability < 78:
            return False
        if odd >= 2.30 and probability < 84:
            return False
        if odd >= 2.60 and probability < 88:
            return False
    elif market_name in {"Totales", "F5 Totales"}:
        if odd >= 1.90 and probability < 70:
            return False
        if odd >= 2.15 and probability < 76:
            return False
        if odd >= 2.40 and probability < 82:
            return False
        if odd >= 2.65 and probability < 86:
            return False
    elif market_name == "Run Line":
        if odd >= 1.85 and probability < 70:
            return False
        if odd >= 2.10 and probability < 75:
            return False
        if odd >= 2.35 and probability < 80:
            return False
        if odd >= 2.60 and probability < 85:
            return False
    return True

def _best_odd_update(store, key, odd):
    odd = _safe_float(odd, 0.0)
    if odd <= 0:
        return
    current = store.get(key)
    if current is None or odd > current:
        store[key] = odd

def _flatten_side_line_values(grouped):
    values = []
    for line, sides in grouped.items():
        for side, odd in sides.items():
            values.append({"value": f"{side} {line}", "odd": odd})
    return values

def _history_settled_items():
    historial = cargar_historial()
    return [p for p in historial if p.get("status") in {"win", "loss", "push"}]

def _history_settled_items_current_month():
    mk = _month_key()
    return [
        p for p in _history_settled_items()
        if str(p.get("timestamp", ""))[:7] == mk
    ]


def _published_uids(payload):
    return set(payload.get("published_pick_uids", []))

def _history_items_for_today():
    today = _mx_date()
    historial = cargar_historial()
    return [
        p for p in historial
        if str(p.get("published_at", ""))[:10] == today or p.get("date") == today
    ]

def _daily_result_items():
    return _history_items_for_today()



def _combo_market_group(market):
    market = str(market or "").strip()
    if market in {"Totales", "F5 Totales"}:
        return "TOTALS"
    if market == "Moneyline":
        return "ML"
    if market == "Run Line":
        return "RUNLINE"
    return market.upper()

def _combo_kind_label(kind):
    return {
        "parlay": "Parlay",
        "combinada": "Combinada",
    }.get(str(kind).lower(), str(kind).title())

def _combo_option_label(option):
    kind = str(option.get("kind", "")).lower()
    probability = _safe_int(option.get("probability", option.get("confidence", 0)))
    odd = _safe_float(option.get("odd", 0.0), 0.0)

    if kind == "parlay":
        prefix = "🧩"
    elif kind == "combinada":
        prefix = "🧠"
    else:
        prefix = "⭐"

    pick = str(option.get("pick", "")).strip()
    matchup = str(option.get("matchup", "")).strip()

    if matchup and matchup != pick:
        label = f"{prefix} {pick} | {matchup} | {probability}% | {odd:.2f}"
    else:
        label = f"{prefix} {pick} | {probability}% | {odd:.2f}"

    return label[:120]

def _build_combo_option(kind, league_id, legs):
    odd = 1.0
    prob_decimal = 1.0
    score = 0.0
    matchups = []

    for leg in legs:
        odd *= _safe_float(leg.get("odd"), 1.0)
        prob_decimal *= _safe_float(leg.get("probability", leg.get("confidence", 0)), 0.0) / 100.0
        score += _safe_float(leg.get("score"), 0.0)
        matchups.append(str(leg.get("matchup", "")).strip())

    probability = int(_clamp(prob_decimal * 100.0, 1, 99))
    implied = 1.0 / odd if odd > 0 else 0.0
    ev = prob_decimal - implied

    if kind == "parlay":
        leg_label = " + ".join(str(leg.get("pick", "")).strip() for leg in legs)
        matchup_label = " / ".join(dict.fromkeys(matchups))
        market_label = "Parlay"
        reason = "Parlay construido con valor combinado."
    else:
        leg_label = " + ".join(str(leg.get("pick", "")).strip() for leg in legs)
        matchup_label = matchups[0] if matchups else "Combinada"
        market_label = "Combinada"
        reason = "Combinada del mismo juego con mercados compatibles."

    return {
        "uid": _make_uid(),
        "league_id": league_id,
        "league_name": _league_name(league_id),
        "matchup": matchup_label,
        "market": market_label,
        "pick": leg_label,
        "odd": odd,
        "line": None,
        "projection": None,
        "confidence": probability,
        "probability": probability,
        "ev": ev,
        "stake": _stake_from_probability(probability),
        "score": score + (probability * 0.5),
        "reason": reason,
        "notes": [],
        "kind": kind,
        "legs": legs,
    }

def _build_parlay_options(candidates, league_id, limit=6):
    top = _rank_candidates(
        [c for c in candidates if _safe_int(c.get("probability", c.get("confidence", 0)), 0) >= 65],
        rank_by="premium"
    )[:10]

    options = []
    for leg1, leg2 in combinations(top, 2):
        if leg1.get("matchup") == leg2.get("matchup"):
            continue
        option = _build_combo_option("parlay", league_id, [leg1, leg2])
        if option["probability"] < 15:
            continue
        options.append(option)

    options.sort(key=lambda x: (x["score"], x["probability"], x["odd"]), reverse=True)
    return options[:limit]

def _build_combinada_options(candidates, league_id, limit=6):
    grouped = defaultdict(list)
    for c in candidates:
        grouped[str(c.get("matchup", ""))].append(c)

    options = []
    for matchup, group in grouped.items():
        ranked = _rank_candidates(group, rank_by="premium")[:5]

        for size in (2, 3):
            for legs in combinations(ranked, size):
                groups = [_combo_market_group(leg.get("market")) for leg in legs]
                if len(groups) != len(set(groups)):
                    continue
                option = _build_combo_option("combinada", league_id, list(legs))
                if option["probability"] < 20:
                    continue
                options.append(option)

    options.sort(key=lambda x: (x["score"], x["probability"], x["odd"]), reverse=True)
    return options[:limit]

def _build_combo_payload(chat_id, league_id, combo_kind="parlay", limit=6):
    settings = USER_SETTINGS[chat_id]
    use_recent_form = settings["use_recent_form"]
    enable_runline = settings["enable_runline"]

    juegos_all, juegos, candidatos = _build_candidates_for_league(
        league_id=league_id,
        market_filter="ALL",
        use_recent_form=use_recent_form,
        enable_runline=enable_runline
    )

    if combo_kind == "parlay":
        selected = _build_parlay_options(candidatos, league_id, limit=limit)
        mode_label = "Parlay"
    else:
        selected = _build_combinada_options(candidatos, league_id, limit=limit)
        mode_label = "Combinada"

    meta = {
        "analizados": len(juegos_all),
        "usados": len(juegos),
        "candidatos": len(candidatos),
    }

    payload = _make_payload(
        selected=selected,
        meta=meta,
        settings=settings,
        league_id=league_id,
        market_filter="ALL",
        max_picks=len(selected),
        mode_label=mode_label,
        strict_day=False,
        mode_kind=combo_kind,
    )
    return payload

# ==========================
# STORAGE
# ==========================

def cargar_historial():
    data = _load_json(HISTORY_FILE, [])
    return data if isinstance(data, list) else []

def guardar_historial(historial):
    _save_json(HISTORY_FILE, historial)

def guardar_picks_en_historial(picks, published_at=None, publish_scope="ALL"):
    if not picks:
        return

    historial = cargar_historial()
    now = published_at or _mx_now().isoformat()

    for pick in picks:
        historial.append({
            "uid": pick["uid"],
            "timestamp": now,
            "date": _mx_date(),
            "league_id": pick.get("league_id"),
            "league_name": pick.get("league_name"),
            "matchup": pick.get("matchup"),
            "market": pick.get("market"),
            "pick": pick.get("pick"),
            "odd": pick.get("odd"),
            "line": pick.get("line"),
            "projection": pick.get("projection"),
            "probability": pick.get("probability", pick.get("confidence")),
            "confidence": pick.get("probability", pick.get("confidence")),
            "stake": pick.get("stake"),
            "ev": pick.get("ev"),
            "score": pick.get("score"),
            "reason": pick.get("reason"),
            "status": "pending",
            "result": None,
            "settled_at": None,
            "published_at": now,
            "publish_scope": publish_scope,
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
    key = f"{league_id}:{_mx_date()}"
    return state.get(key)

def _set_pick_day_payload(league_id, payload):
    state = _load_pick_day_state()
    key = f"{league_id}:{_mx_date()}"
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

def _make_payload(selected, meta, settings, league_id, market_filter, max_picks, mode_label, strict_day=False, mode_kind="picks"):
    picks_guardados = []
    for pick in selected:
        p = dict(pick)
        p["uid"] = _make_uid()
        p["stake"] = _stake_from_probability(p["probability"])
        picks_guardados.append(p)

    return {
        "generated_at": _mx_now().isoformat(),
        "league_id": league_id,
        "league_name": _league_name(league_id),
        "market_filter": market_filter,
        "max_picks": max_picks,
        "meta": meta,
        "settings": settings,
        "picks": picks_guardados,
        "mode_label": mode_label,
        "strict_day": strict_day,
        "mode_kind": mode_kind,
    }

# ==========================
# API SPORTS
# ==========================

def obtener_juegos(league_id):
    cache_key = ("games", league_id, SEASON, _mx_date())
    cached = _cache_get(GAMES_CACHE, cache_key)
    if cached is not None:
        return cached

    headers = _headers()
    fecha1 = _mx_date()
    fecha2 = (_mx_now() + timedelta(days=1)).strftime("%Y-%m-%d")

    juegos = []
    seen_pairs = set()

    for fecha in [fecha1, fecha2]:
        params = {
            "league": league_id,
            "season": SEASON,
            "date": fecha
        }

        try:
            r = requests.get(f"{BASE_URL}/games", headers=headers, params=params, timeout=30)
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

    params = {"league": league_id, "season": SEASON}

    try:
        r = requests.get(f"{BASE_URL}/standings", headers=_headers(), params=params, timeout=30)
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

            _dbg(
                f"[STANDINGS] {league_id} | {team.get('name')} | "
                f"PF={points_for:.1f} PA={points_against:.1f} GP={games_played} | "
                f"RF/G={standings[team_id]['runs_for_pg']:.2f} RA/G={standings[team_id]['runs_against_pg']:.2f}"
            )

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

    date_to = _mx_date()
    date_from = (_mx_now() - timedelta(days=FORM_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    params = {
        "league": league_id,
        "season": SEASON,
        "team": team_id,
        "date_from": date_from,
        "date_to": date_to
    }

    try:
        r = requests.get(f"{BASE_URL}/games", headers=_headers(), params=params, timeout=30)
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
    cache_key = ("odds", league_id, game_id, SEASON, "ALL")
    cached = _cache_get(ODDS_CACHE, cache_key)
    if cached is not None:
        return cached

    params = {
        "league": league_id,
        "season": SEASON,
        "game": game_id
    }

    try:
        r = requests.get(f"{BASE_URL}/odds", headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        data = r.json().get("response", [])
        _cache_set(ODDS_CACHE, cache_key, data)
        return data

    except Exception as e:
        logging.error(f"Error odds game={game_id} league={league_id}: {e}")
        return []

def _parse_total_market(values, league_id=None):
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
    baseline = _league_baseline_total(league_id) if league_id in LEAGUES else 8.5
    line, over_odd, under_odd = min(pool, key=lambda x: abs(x[0] - baseline))

    logging.info(f"[TOTALS DEBUG] chosen line={line} over={over_odd} under={under_odd} candidates={complete}")
    print(f"[TOTALS DEBUG] chosen line={line} over={over_odd} under={under_odd} candidates={complete}", flush=True)

    return {
        "line": line,
        "over": over_odd,
        "under": under_odd
    }

def extraer_mercados_odds(odds_response, league_id=None):
    if not odds_response:
        return {}

    entry = odds_response[0]
    bookmakers = entry.get("bookmakers", [])
    if not bookmakers:
        return {}

    moneyline_best = {"home": None, "away": None}
    runline_best = {}
    total_grouped = defaultdict(dict)
    f5_grouped = defaultdict(dict)

    for bookmaker in bookmakers:
        bets = bookmaker.get("bets", []) or []

        for bet in bets:
            bet_id = _safe_int(bet.get("id"))
            bet_name = str(bet.get("name", "")).strip()

            # Moneyline / Match Winner
            if bet_id in {1, 14} or bet_name in {"Home/Away", "Match Winner", "1x2"}:
                vals = bet.get("values", [])
                for v in vals:
                    value = str(v.get("value", "")).strip()
                    odd = _safe_float(v.get("odd"))
                    if value == "Home":
                        _best_odd_update(moneyline_best, "home", odd)
                    elif value == "Away":
                        _best_odd_update(moneyline_best, "away", odd)

            # Run line / Handicap
            elif bet_id in {2, 3, 12} or bet_name in {"Asian Handicap", "Asian Handicap (1st 5 Innings)", "Asian Handicap (1st Inning)"}:
                for v in bet.get("values", []):
                    value = str(v.get("value", "")).strip()
                    odd = _safe_float(v.get("odd"))
                    _best_odd_update(runline_best, value, odd)

            # Totales
            elif bet_id == 5 or bet_name == "Over/Under":
                for v in bet.get("values", []):
                    label = str(v.get("value", "")).strip()
                    odd = _safe_float(v.get("odd"))

                    m = re.match(r"(?i)^(Over|Under)\s+([0-9]+(?:\.[0-9]+)?)$", label)
                    if not m:
                        continue

                    side = m.group(1).title()
                    line = float(m.group(2))
                    _best_odd_update(total_grouped[line], side, odd)

            elif bet_id == 6 or bet_name == "Over/Under (1st 5 Innings)":
                for v in bet.get("values", []):
                    label = str(v.get("value", "")).strip()
                    odd = _safe_float(v.get("odd"))

                    m = re.match(r"(?i)^(Over|Under)\s+([0-9]+(?:\.[0-9]+)?)$", label)
                    if not m:
                        continue

                    side = m.group(1).title()
                    line = float(m.group(2))
                    _best_odd_update(f5_grouped[line], side, odd)

    markets = {}

    if moneyline_best.get("home") and moneyline_best.get("away"):
        markets["moneyline"] = {
            "home": moneyline_best["home"],
            "away": moneyline_best["away"]
        }

    if runline_best:
        markets["runline"] = runline_best

    total_values = _flatten_side_line_values(total_grouped)
    f5_values = _flatten_side_line_values(f5_grouped)

    parsed_total = _parse_total_market(total_values, league_id)
    parsed_f5 = _parse_total_market(f5_values, league_id)

    if parsed_total:
        markets["total"] = parsed_total

    if parsed_f5:
        markets["f5_total"] = parsed_f5

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

    probability = _smart_probability(gap, ev, league_id, "Moneyline")
    if probability < 72:
        return None
    if not _odds_gate(probability, odd, "Moneyline"):
        return None
    score = (probability * 1.25) + (max(ev, 0.0) * 100.0 * 0.10) - _odd_pressure(odd)

    return {
        "league_id": league_id,
        "league_name": juego["league_name"],
        "matchup": juego["partido"],
        "market": "Moneyline",
        "pick": pick_team,
        "odd": odd,
        "line": None,
        "projection": None,
        "confidence": probability,
        "probability": probability,
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
        print(f"[TOTALS DEBUG] descartado {juego['partido']} {market_name} line={line} over={over_odd} under={under_odd}", flush=True)
        return None

    base_total = _league_baseline_total(league_id)

    home_off = _blend(
        form_home.get("recent_runs_for_pg") if form_home else None,
        standing_home.get("runs_for_pg", 0.0) if standing_home else 0.0,
        0.90
    )
    home_def = _blend(
        form_home.get("recent_runs_against_pg") if form_home else None,
        standing_home.get("runs_against_pg", 0.0) if standing_home else 0.0,
        0.90
    )
    away_off = _blend(
        form_away.get("recent_runs_for_pg") if form_away else None,
        standing_away.get("runs_for_pg", 0.0) if standing_away else 0.0,
        0.90
    )
    away_def = _blend(
        form_away.get("recent_runs_against_pg") if form_away else None,
        standing_away.get("runs_against_pg", 0.0) if standing_away else 0.0,
        0.90
    )

    _dbg(
        f"[TOTALS INPUT] {juego['partido']} | "
        f"home_off={home_off:.2f} home_def={home_def:.2f} "
        f"away_off={away_off:.2f} away_def={away_def:.2f} line={line}"
    )

    home_est = (0.58 * home_off) + (0.42 * away_def)
    away_est = (0.58 * away_off) + (0.42 * home_def)
    raw_total = home_est + away_est

    proj_total = (base_total * 0.78) + (raw_total * 0.22)
    proj_total = _clamp(proj_total, base_total - 2.0, base_total + 3.5)

    _dbg(
        f"[TOTALS PROJECTION] {juego['partido']} | "
        f"home_est={home_est:.2f} away_est={away_est:.2f} raw_total={raw_total:.2f} "
        f"proj_total={proj_total:.2f} line={line}"
    )

    gap = proj_total - line
    abs_gap = abs(gap)

    if abs_gap < 0.35:
        return None

    if gap > 0:
        pick_side = "Over"
        odd = over_odd
    else:
        pick_side = "Under"
        odd = under_odd

    implied = 1.0 / odd

    sensitivity = 1.15 if league_id == MLB_LEAGUE_ID else 1.05
    model_prob = 0.50 + min(0.24, (abs_gap / sensitivity) * 0.10)
    ev = model_prob - implied

    if ev < cfg["totals_ev_min"] and abs_gap < 0.90:
        return None

    probability = _smart_probability(gap, ev, league_id, market_name)
    if probability < 68:
        return None
    if not _odds_gate(probability, odd, market_name):
        return None
    score = (probability * 1.10) + (max(ev, 0.0) * 100.0 * 0.08) - _odd_pressure(odd)

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
        "confidence": probability,
        "probability": probability,
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

        score = (ev * 100.0 * 0.15) + abs(gap) * 0.25 - _odd_pressure(odd)
        opciones.append((score, nombre, odd, ev))

    if not opciones:
        return None

    opciones.sort(reverse=True, key=lambda x: x[0])
    _, raw_pick, odd, ev = opciones[0]

    friendly_pick = _format_runline_label(raw_pick, juego)
    probability = _smart_probability(gap, ev, league_id, "Run Line")
    if probability < 70:
        return None
    if not _odds_gate(probability, odd, "Run Line"):
        return None
    score = (probability * 1.00) + (max(ev, 0.0) * 100.0 * 0.06) - _odd_pressure(odd)

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
        "confidence": probability,
        "probability": probability,
        "ev": ev,
        "score": score,
        "reason": f"Ventaja estadística ajustada por handicap.{form_note}",
        "notes": [],
    }

# ==========================
# HISTORIAL / RESULTADOS
# ==========================

def marcar_resultado(uid, result):
    historial = cargar_historial()
    found = None

    for item in historial:
        if item.get("uid") == uid:
            item["status"] = result
            item["result"] = result
            item["settled_at"] = _mx_now().isoformat()
            found = item
            break

    if found:
        guardar_historial(historial)

    return found

def resumen_historial_mensual():
    historial = _history_settled_items_current_month()

    if not historial:
        return None, {}

    overall = {
        "settled": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "staked": 0.0,
        "profit": 0.0,
    }

    by_league = defaultdict(lambda: {
        "settled": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "staked": 0.0,
        "profit": 0.0,
    })

    for p in historial:
        league_name = p.get("league_name", "Liga")
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

        lg = by_league[league_name]
        lg["settled"] += 1
        lg["staked"] += stake
        lg["profit"] += profit

        if result == "win":
            lg["wins"] += 1
        elif result == "loss":
            lg["losses"] += 1
        else:
            lg["pushes"] += 1

    return overall, by_league

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
        markets = extraer_mercados_odds(odds_response, league_id)

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
        candidatos = [
            c for c in candidatos
            if c.get("probability", c.get("confidence", 0)) >= 80 and c.get("ev", 0.0) >= 0.035
        ]
    if best_odds_mode:
        candidatos = [
            c for c in candidatos
            if c.get("probability", c.get("confidence", 0)) >= 74 and c.get("ev", 0.0) >= 0.02
        ]

    rank_by = "probability"
    if premium_mode:
        rank_by = "premium"
    elif best_odds_mode:
        rank_by = "odd"

    if strict_day:
        return _select_candidates(candidatos, 1, strict_day=True, rank_by="probability")

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
    texto += f"🔢 Top solicitado: {payload['max_picks']}\n"
    texto += f"🕒 {_mx_stamp()}\n\n"

    for market in ["Moneyline", "Totales", "F5 Totales", "Run Line"]:
        if counts.get(market):
            texto += f"• {market}: {counts[market]}\n"

    texto += "\n"
    texto += f"Probabilidad inteligente: {'ON' if settings['use_recent_form'] else 'OFF'}\n"
    texto += f"Run Line: {'ON' if settings['enable_runline'] else 'OFF'}\n"
    texto += "\nLas opciones quedan disponibles para publicar.\n"

    return texto[:4000]



def _build_pick_card(pick, idx):
    level = _probability_label(pick.get("probability", pick.get("confidence", 0)))
    probability = _safe_int(pick.get("probability", pick.get("confidence", 0)))
    league_short = _league_short(pick.get("league_id", MLB_LEAGUE_ID))

    if pick.get("kind"):
        title = f"{'🔥' if idx == 1 else '🥈' if idx == 2 else '🥉' if idx == 3 else '⭐'} {_combo_kind_label(pick.get('kind'))} #{idx}"
    else:
        title = f"{'🔥' if idx == 1 else '🥈' if idx == 2 else '🥉' if idx == 3 else '⭐'} PICK {league_short} #{idx}"

    texto = (
        f"{title}\n"
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
        f"🎲 Apuesta: {pick['stake']}/5\n"
        f"📊 Probabilidad: {probability}%\n"
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
        probability = _safe_int(pick.get("probability", pick.get("confidence", 0)))
        texto += f"{idx}. {pick['matchup']}\n"
        texto += f"   {pick['market']} -> {pick['pick']}\n"
        texto += f"   Cuota: {pick['odd']:.2f} | Probabilidad: {probability}% | EV: {pick.get('ev', 0.0) * 100:+.1f}%\n"
        if pick.get("line") is not None:
            texto += f"   Línea: {pick['line']:.1f}\n"
        if pick.get("projection") is not None:
            texto += f"   Proyección: {pick['projection']:.2f}\n"
        texto += f"   Razón: {pick.get('reason', '')}\n\n"

    return texto[:4000]



def _build_channel_summary_text(payload, picks=None):
    meta = payload["meta"]
    settings = payload["settings"]
    picks = picks if picks is not None else payload.get("picks", [])
    total_generated = len(payload.get("picks", []))
    selected_count = len(picks)

    texto = f"🔥 BOSS ODDS MX | {_league_name(payload.get('league_id', MLB_LEAGUE_ID))}\n\n"
    texto += f"🎛 Modo: {payload.get('mode_label', 'Top Picks')}\n"
    texto += f"🎛 Filtro: {_filter_label(payload.get('market_filter', 'ALL'))}\n"
    texto += f"📊 Juegos analizados: {meta['analizados']}\n"
    texto += f"📈 Candidatos: {meta['candidatos']}\n"
    texto += f"🎯 Publicados: {selected_count}\n"
    texto += f"🧾 Generados: {total_generated}\n"
    texto += f"🕒 {_mx_stamp()}\n\n"
    texto += f"Probabilidad inteligente: {'ON' if settings['use_recent_form'] else 'OFF'} | Run Line: {'ON' if settings['enable_runline'] else 'OFF'}\n"
    return texto[:4000]

def _build_channel_pick_text(pick, idx):
    level = _probability_label(pick.get("probability", pick.get("confidence", 0)))
    probability = _safe_int(pick.get("probability", pick.get("confidence", 0)))
    league_short = _league_short(pick.get("league_id", MLB_LEAGUE_ID))

    if pick.get("kind"):
        title = f"{'🔥' if idx == 1 else '🥈' if idx == 2 else '🥉' if idx == 3 else '⭐'} {_combo_kind_label(pick.get('kind'))} #{idx}"
    else:
        title = f"{'🔥' if idx == 1 else '🥈' if idx == 2 else '🥉' if idx == 3 else '⭐'} PICK {league_short} #{idx}"

    texto = (
        f"{title}\n"
        f"⚾ {pick['matchup']}\n"
        f"✅ {pick['pick']}\n"
        f"🎯 Mercado: {pick['market']}\n"
        f"💰 Cuota: {pick['odd']:.2f}\n"
    )
    if pick.get("line") is not None:
        texto += f"📏 Línea: {pick['line']:.1f}\n"
    texto += (
        f"🎲 Stake: {pick.get('stake', 1)}/5\n"
        f"📊 Probabilidad: {probability}% ({level})\n"
        f"📉 EV: {pick.get('ev', 0.0) * 100:+.1f}%\n"
        f"━━━━━━━━━━━━━━\n"
        f"Boss Odds MX VIP\n"
    )
    return texto[:4000]

def _build_publish_prompt_text(payload):
    picks = payload.get("picks", [])
    mode_kind = payload.get("mode_kind", "picks")
    kind_label = _combo_kind_label(mode_kind) if mode_kind != "picks" else "PUBLICAR AL CANAL"
    published = _published_uids(payload)

    if mode_kind == "picks":
        texto = "📢 PUBLICAR AL CANAL\n\n"
        texto += "Selecciona qué apuesta quieres publicar.\n"
        texto += "Las publicadas quedarán marcadas con ✅ y la lista seguirá visible.\n\n"
    else:
        texto = f"📢 {kind_label.upper()} DISPONIBLES\n\n"
        texto += "Selecciona la combinación que quieres publicar.\n"
        texto += "Las publicadas quedarán marcadas con ✅ y la lista seguirá visible.\n\n"

    for idx, pick in enumerate(picks, start=1):
        probability = _safe_int(pick.get("probability", pick.get("confidence", 0)))
        mark = "✅ " if pick.get("uid") in published else ""
        if mode_kind == "picks":
            texto += f"{mark}{idx}. {pick['matchup']} | {pick['market']} | {pick['pick']} | Probabilidad {probability}%\n"
        else:
            texto += f"{mark}{idx}. {pick['matchup']} | {pick['pick']} | Probabilidad {probability}% | Cuota {pick['odd']:.2f}\n"

    return texto[:4000]

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
        return "Todavía no hay picks publicados."

    texto = "🗂 HISTORIAL DE PICKS PUBLICADOS\n\n"
    texto += f"Total guardados: {len(historial)}\n\n"

    for item in reversed(historial):
        odd = _safe_float(item.get("odd"), 0.0)
        probability = _safe_int(item.get("probability", item.get("confidence", 0)))
        texto += (
            f"UID: {item.get('uid')}\n"
            f"{item.get('market')} | {item.get('pick')}\n"
            f"{item.get('matchup')}\n"
            f"Cuota: {odd:.2f} | Apuesta: {item.get('stake')} | Probabilidad: {probability}% | Estado: {_result_label(item.get('status'))}\n\n"
        )
        if len(texto) > 3800:
            break

    return texto[:4000]

def _build_performance_text():
    overall, by_league = resumen_historial_mensual()

    if not overall:
        return f"📊 RESUMEN MENSUAL\n\nAún no hay picks cerrados en {_month_label()}."

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
            f"• G-P-P: {wins}-{losses}-{pushes}\n"
            f"• Efectividad: {winrate:.1f}%\n"
            f"• Rendimiento: {roi:+.1f}%\n"
        )

    texto = f"📊 RESUMEN MENSUAL\n\n"
    texto += f"Mes: {_month_label()}\n"
    texto += f"📌 Cerrados: {overall['settled']}\n"
    texto += f"✅ Ganados: {overall['wins']}\n"
    texto += f"❌ Perdidos: {overall['losses']}\n"
    texto += f"➖ Push: {overall['pushes']}\n"
    texto += f"🎯 Efectividad: {(overall['wins'] / max(1, overall['settled']) * 100):.1f}%\n"
    texto += f"💵 Apuesta total: {overall['staked']:.2f}\n"
    texto += f"📈 Beneficio: {overall['profit']:+.2f}\n\n"

    for league_name in ["MLB", "LMB"]:
        if league_name in by_league:
            texto += _line(league_name, by_league[league_name]) + "\n"

    return texto[:4000]


def _daily_summary_data():
    items = _daily_result_items()
    published = len(items)
    settled = [p for p in items if p.get("status") in {"win", "loss", "push"}]
    wins = sum(1 for p in settled if p.get("status") == "win")
    losses = sum(1 for p in settled if p.get("status") == "loss")
    pushes = sum(1 for p in settled if p.get("status") == "push")
    pending = published - len(settled)
    staked = sum(_safe_float(p.get("stake"), 0.0) for p in settled)
    profit = sum(_market_profit(_safe_float(p.get("stake"), 0.0), _safe_float(p.get("odd"), 0.0), p.get("status")) for p in settled)
    effectiveness = (wins / max(1, len(settled)) * 100.0) if settled else 0.0
    return {
        "date": _mx_date(),
        "published": published,
        "settled": len(settled),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": pending,
        "staked": staked,
        "profit": profit,
        "effectiveness": effectiveness,
        "items": items,
    }

def _build_daily_results_text():
    data = _daily_summary_data()

    texto = "📋 RESULTADO DEL DÍA\n\n"
    texto += f"Fecha: {data['date']}\n"
    texto += f"📌 Publicados: {data['published']}\n"
    texto += f"✅ Ganados: {data['wins']}\n"
    texto += f"❌ Perdidos: {data['losses']}\n"
    texto += f"➖ Push: {data['pushes']}\n"
    texto += f"⏳ Pendientes: {data['pending']}\n"
    texto += f"🎯 Efectividad: {data['effectiveness']:.1f}%\n"
    texto += f"💵 Apuesta total: {data['staked']:.2f}\n"
    texto += f"📈 Beneficio: {data['profit']:+.2f}\n\n"

    if data["items"]:
        texto += "Últimos resultados:\n"
        for item in reversed(data["items"][-8:]):
            odd = _safe_float(item.get("odd"), 0.0)
            texto += (
                f"• {item.get('market')} | {item.get('pick')} | "
                f"{odd:.2f} | {_result_label(item.get('status'))}\n"
            )
    else:
        texto += "Aún no hay picks del día para mostrar.\n"

    return texto[:4000]

def _build_channel_daily_results_text():
    data = _daily_summary_data()
    texto = "📅 RESULTADO DEL DÍA\n\n"
    texto += f"Fecha: {data['date']}\n"
    texto += f"✅ Ganados: {data['wins']}\n"
    texto += f"❌ Perdidos: {data['losses']}\n"
    texto += f"➖ Push: {data['pushes']}\n"
    texto += f"🎯 Efectividad: {data['effectiveness']:.1f}%\n"
    texto += f"📈 Beneficio: {data['profit']:+.2f}\n"
    return texto[:4000]

def daily_results_markup():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Publicar al Canal", callback_data="resultado:publish")
        ],
        [
            InlineKeyboardButton("🔙 Menú", callback_data="menu:main")
        ]
    ])


async def publish_daily_results_to_channel(chat_id, context):
    channel_id = _get_channel_chat_id()
    if channel_id is None:
        return False, "Falta configurar TELEGRAM_CHANNEL_ID en Render."

    try:
        await context.bot.send_message(chat_id=channel_id, text=_build_channel_daily_results_text())
        return True, "Resultado del día publicado."
    except Exception as e:
        logging.error(f"Error publicando resultado del día: {e}")
        return False, f"No se pudo publicar el resultado del día: {e}"

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
    juegos = obtener_juegos(league_id)
    texto = f"📅 CARTELERA {_league_name(league_id)}\n\n"
    texto += f"⚾ Juegos encontrados: {len(juegos)}\n\n"

    for juego in juegos:
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
            markets = extraer_mercados_odds(odds_response, league_id)
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
        f"Probabilidad inteligente: {'ON' if s['use_recent_form'] else 'OFF'}\n"
        f"Run Line: {'ON' if s['enable_runline'] else 'OFF'}"
    )

def _config_menu_text(chat_id):
    s = USER_SETTINGS[chat_id]
    return (
        "⚙️ CONFIGURACIÓN\n\n"
        f"Liga por defecto: {_league_name(s['league_id'])}\n"
        f"Probabilidad inteligente: {'ON' if s['use_recent_form'] else 'OFF'}\n"
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
            InlineKeyboardButton("📈 Rankings", callback_data="menu:rankings"),
            InlineKeyboardButton("📋 Análisis", callback_data="analysis:last"),
        ],
        [
            InlineKeyboardButton("📋 Resultado del Día", callback_data="menu:resultado"),
            InlineKeyboardButton("📊 Rendimiento", callback_data="menu:rendimiento"),
        ],
        [
            InlineKeyboardButton("🗂 Historial", callback_data="menu:historial"),
            InlineKeyboardButton("👑 VIP", callback_data="menu:vip"),
        ],
        [
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
            InlineKeyboardButton("🧩 Parlay", callback_data=f"gen:{league_id}:PARLAY:6"),
        ],
        [
            InlineKeyboardButton("🧠 Combinada", callback_data=f"gen:{league_id}:COMBINADA:6"),
            InlineKeyboardButton("📢 Publicar al Canal", callback_data="publish:last"),
        ],
        [
            InlineKeyboardButton("📅 Juegos", callback_data=f"games:{league_id}"),
            InlineKeyboardButton("📋 Ver análisis", callback_data="analysis:last"),
        ]
    ]

    if league_id == LMB_LEAGUE_ID:
        rows.insert(4, [InlineKeyboardButton("🧪 Test LMB", callback_data=f"test:{LMB_LEAGUE_ID}")])

    rows.append([InlineKeyboardButton("🔙 Menú", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

def rankings_menu_markup():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 Rankings MLB", callback_data=f"rankings:{MLB_LEAGUE_ID}"),
            InlineKeyboardButton("📈 Rankings LMB", callback_data=f"rankings:{LMB_LEAGUE_ID}"),
        ],
        [
            InlineKeyboardButton("🔙 Menú", callback_data="menu:main"),
        ]
    ])

def publish_selector_markup(payload):
    picks = payload.get("picks", [])
    mode_kind = payload.get("mode_kind", "picks")
    published = _published_uids(payload)

    rows = [[InlineKeyboardButton("📢 Publicar todos", callback_data="publish:all")]]

    for idx, pick in enumerate(picks):
        probability = _safe_int(pick.get("probability", pick.get("confidence", 0)))
        is_published = pick.get("uid") in published

        if mode_kind == "picks":
            label = f"{'✅ ' if is_published else ''}{idx + 1}. {pick.get('market', '')} | {pick.get('pick', '')} | {probability}%"
            callback = f"publish:pick:{idx}"
        else:
            label = f"{'✅ ' if is_published else ''}{idx + 1}. {pick.get('pick', '')} | {probability}%"
            callback = f"publish:pick:{idx}"

        rows.append([InlineKeyboardButton(label[:60], callback_data=callback)])

    rows.append([InlineKeyboardButton("🔙 Menú", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

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
                f"Probabilidad inteligente: {'ON' if s['use_recent_form'] else 'OFF'}",
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
# PUBLISH HELPERS
# ==========================

def _subset_payload_picks(payload, indexes):
    picks = payload.get("picks", [])
    selected = []
    for idx in indexes:
        if 0 <= idx < len(picks):
            selected.append(picks[idx])
    return selected


async def _publish_picks_to_channel(chat_id, context, payload, selected_picks):
    channel_id = _get_channel_chat_id()
    if channel_id is None:
        return False, "Falta configurar TELEGRAM_CHANNEL_ID en Render."

    if not selected_picks:
        return False, "No hay apuestas seleccionadas para publicar."

    published = _published_uids(payload)
    to_publish = [p for p in selected_picks if p.get("uid") not in published]
    if not to_publish:
        return False, "Esa apuesta ya estaba publicada."

    try:
        for idx, pick in enumerate(to_publish, start=1):
            await context.bot.send_message(chat_id=channel_id, text=_build_channel_pick_text(pick, idx))

        guardar_picks_en_historial(to_publish, published_at=_mx_now().isoformat(), publish_scope="SELECTED")
        payload["published_at"] = _mx_now().isoformat()
        payload["published_pick_uids"] = sorted(published.union({p.get("uid") for p in to_publish}))
        _store_last_generated(chat_id, payload)

        return True, f"Publicado en el canal: {len(to_publish)} apuesta(s)."
    except Exception as e:
        logging.error(f"Error publicando al canal: {e}")
        return False, f"No se pudo publicar en el canal: {e}"


# ==========================
# ACTIONS
# ==========================

async def _send_payload(chat_id, context, payload, query=None):
    if not payload.get("picks"):
        msg = "No se encontraron apuestas con ventaja suficiente."
        if payload.get("strict_day"):
            msg = "No se encontró un Pick del Día con el umbral actual."
        if query is not None:
            await query.edit_message_text(msg, reply_markup=main_menu_markup())
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=main_menu_markup())
        return

    mode_kind = payload.get("mode_kind", "picks")

    if mode_kind == "picks":
        summary_text = _build_summary_text(payload)
        selector_markup = publish_selector_markup(payload)
        if query is not None:
            await query.edit_message_text(summary_text, reply_markup=selector_markup)
        else:
            await context.bot.send_message(chat_id=chat_id, text=summary_text, reply_markup=selector_markup)

        for idx, pick in enumerate(payload["picks"], start=1):
            await context.bot.send_message(
                chat_id=chat_id,
                text=_build_pick_card(pick, idx),
                reply_markup=pick_result_markup(pick["uid"])
            )
        return

    prompt_text = _build_publish_prompt_text(payload)
    selector_markup = publish_selector_markup(payload)
    if query is not None:
        await query.edit_message_text(prompt_text, reply_markup=selector_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=prompt_text, reply_markup=selector_markup)

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

        payload = _make_payload(
            selected=selected,
            meta=meta,
            settings=settings,
            league_id=league_id,
            market_filter=market_filter if market_filter != "DEFAULT" else settings["market_filter"],
            max_picks=max_picks if max_picks > 0 else settings["max_picks"],
            mode_label=mode_label,
            strict_day=strict_day,
            mode_kind="picks"
        )

        _store_last_generated(chat_id, payload)

        await _send_payload(chat_id, context, payload, query=query)

    except Exception as e:
        logging.exception(f"Error en ejecutar_generacion league={league_id}: {e}")
        try:
            if query is not None:
                await query.edit_message_text(
                    f"⚠️ Ocurrió un error al generar apuestas.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Ocurrió un error al generar apuestas.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
        except Exception:
            pass

async def ejecutar_generacion_combo(
    chat_id,
    context,
    league_id,
    combo_kind="parlay",
    limit=6,
    query=None
):
    try:
        if query is not None:
            await query.edit_message_text("⏳ Armando combinaciones con valor...")
        else:
            await context.bot.send_message(chat_id=chat_id, text="⏳ Armando combinaciones con valor...")

        payload = _build_combo_payload(chat_id, league_id, combo_kind=combo_kind, limit=limit)

        _store_last_generated(chat_id, payload)

        await _send_payload(chat_id, context, payload, query=query)

    except Exception as e:
        logging.exception(f"Error en ejecutar_generacion_combo league={league_id} kind={combo_kind}: {e}")
        try:
            if query is not None:
                await query.edit_message_text(
                    f"⚠️ Ocurrió un error al generar combinaciones.\n\n{e}",
                    reply_markup=main_menu_markup()
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Ocurrió un error al generar combinaciones.\n\n{e}",
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

        payload = _make_payload(
            selected=selected,
            meta=meta,
            settings=settings,
            league_id=league_id,
            market_filter="ALL",
            max_picks=1,
            mode_label="Pick del Día",
            strict_day=True,
            mode_kind="picks"
        )

        _set_pick_day_payload(league_id, payload)
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

async def publish_last_to_channel(chat_id, context, indexes=None):
    payload = _get_last_generated(chat_id)
    if not payload or not payload.get("picks"):
        return False, "No hay apuestas recientes para publicar. Genera primero un Top 3, Top 6, Parlay o Combinada."

    if indexes is None:
        selected_picks = payload.get("picks", [])
    else:
        selected_picks = _subset_payload_picks(payload, indexes)

    return await _publish_picks_to_channel(chat_id, context, payload, selected_picks)

# ==========================
# MENÚS / CALLBACKS
# ==========================

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
            await query.edit_message_text(_main_menu_text(chat_id), reply_markup=main_menu_markup())
            return

        if data == "menu:rankings":
            await query.answer()
            await query.edit_message_text("📈 Rankings\n\nSelecciona una liga.", reply_markup=rankings_menu_markup())
            return

        if data == "menu:resultado":
            await query.answer()
            await query.edit_message_text(_build_daily_results_text(), reply_markup=daily_results_markup())
            return

        if data == "menu:games":
            await query.answer()
            await query.edit_message_text(_build_games_text(settings["league_id"]), reply_markup=league_menu_markup(settings["league_id"]))
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

        if data.startswith("games:"):
            _, lid = data.split(":", 1)
            league_id = _safe_int(lid, settings["league_id"])
            await query.answer()
            await query.edit_message_text(
                _build_games_text(league_id),
                reply_markup=league_menu_markup(league_id)
            )
            return

        if data == "analysis:last":
            await query.answer()
            payload = _get_last_generated(chat_id) or _get_pick_day_payload(settings["league_id"])
            await query.edit_message_text(_build_analysis_text(payload), reply_markup=main_menu_markup())
            return

        if data == "config:toggle_form":
            settings["use_recent_form"] = not settings["use_recent_form"]
            await query.answer("Probabilidad inteligente actualizada")
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

            if mode == "DAY":
                await query.answer("Generando Pick del Día...", show_alert=False)
                await ejecutar_pick_del_dia(chat_id=chat_id, context=context, league_id=league_id, query=query)
                return

            if mode == "PREMIUM":
                limit = _safe_int(limit_s, 3)
                await query.answer("Generando apuestas...", show_alert=False)
                await ejecutar_generacion(
                    chat_id=chat_id,
                    context=context,
                    league_id=league_id,
                    market_filter="ALL",
                    max_picks=limit,
                    premium_mode=True,
                    query=query
                )
                return

            if mode == "ODDS":
                await query.answer("Generando apuestas...", show_alert=False)
                await ejecutar_generacion(
                    chat_id=chat_id,
                    context=context,
                    league_id=league_id,
                    market_filter="ALL",
                    max_picks=1,
                    best_odds_mode=True,
                    query=query
                )
                return

            if mode == "PARLAY":
                limit = _safe_int(limit_s, 6)
                await query.answer("Generando parlay...", show_alert=False)
                await ejecutar_generacion_combo(
                    chat_id=chat_id,
                    context=context,
                    league_id=league_id,
                    combo_kind="parlay",
                    limit=limit,
                    query=query
                )
                return

            if mode == "COMBINADA":
                limit = _safe_int(limit_s, 6)
                await query.answer("Generando combinadas...", show_alert=False)
                await ejecutar_generacion_combo(
                    chat_id=chat_id,
                    context=context,
                    league_id=league_id,
                    combo_kind="combinada",
                    limit=limit,
                    query=query
                )
                return

            if mode == "DEFAULT":
                limit = _safe_int(limit_s, settings["max_picks"])
                filter_key = settings["market_filter"]
            else:
                limit = _safe_int(limit_s, settings["max_picks"])
                filter_key = mode

            if limit <= 0:
                limit = settings["max_picks"]

            await query.answer("Generando apuestas...", show_alert=False)
            await ejecutar_generacion(
                chat_id=chat_id,
                context=context,
                league_id=league_id,
                market_filter=filter_key,
                max_picks=limit,
                query=query
            )
            return

        if data == "publish:last":
            await query.answer()
            payload = _get_last_generated(chat_id)
            if not payload or not payload.get("picks"):
                await query.edit_message_text(
                    "No hay apuestas recientes para publicar.",
                    reply_markup=main_menu_markup()
                )
                return

            await query.edit_message_text(
                _build_publish_prompt_text(payload),
                reply_markup=publish_selector_markup(payload)
            )
            return

        if data == "publish:all":
            await query.answer("Publicando todas...")
            ok, msg = await publish_last_to_channel(chat_id, context, indexes=None)
            payload = _get_last_generated(chat_id)
            if payload and payload.get("picks"):
                await query.edit_message_text(
                    _build_publish_prompt_text(payload),
                    reply_markup=publish_selector_markup(payload)
                )
            else:
                await query.edit_message_text(
                    ("✅ " + msg) if ok else ("⚠️ " + msg),
                    reply_markup=main_menu_markup()
                )
            return

        if data.startswith("publish:pick:"):
            _, _, idx_s = data.split(":", 2)
            idx = _safe_int(idx_s, -1)
            await query.answer("Publicando apuesta seleccionada...")
            ok, msg = await publish_last_to_channel(chat_id, context, indexes=[idx])
            payload = _get_last_generated(chat_id)
            if payload and payload.get("picks"):
                await query.edit_message_text(
                    _build_publish_prompt_text(payload),
                    reply_markup=publish_selector_markup(payload)
                )
            else:
                await query.edit_message_text(
                    ("✅ " + msg) if ok else ("⚠️ " + msg),
                    reply_markup=main_menu_markup()
                )
            return

        if data.startswith("resultado:"):
            if data == "resultado:publish":
                await query.answer("Publicando resultado del día...", show_alert=False)
                ok, msg = await publish_daily_results_to_channel(chat_id, context)
                payload = _build_daily_results_text()
                await query.edit_message_text(
                    payload,
                    reply_markup=daily_results_markup()
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

# ==========================
# ERROR HANDLER
# ==========================

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
