import os
import time
import logging
from datetime import datetime, timedelta
import pytz
import requests

# --- CONFIGURACIÓN ---
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

LIGAS_TOP = [
    "soccer_mexico_ligamx", "soccer_epl", "soccer_uefa_champions_league",
    "basketball_nba", "baseball_mlb", "soccer_spain_la_liga", 
    "soccer_italy_serie_a", "soccer_germany_bundesliga"
]

MARKETS = "h2h,totals,spreads,btts"
API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"

# --- AJUSTE A 3% ---
UMBRAL_VALOR = 1.03 

TZ_MEXICO = pytz.timezone("America/Mexico_City")

DIAS_SEMANA = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo"
}

historial_enviados = []

def enviar_telegram_con_botones(mensaje, id_unico):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ Ganada", "callback_data": f"w_{id_unico}"}, {"text": "❌ Perdida", "callback_data": f"l_{id_unico}"}],
            [{"text": "📊 Marcador", "url": "https://www.google.com/search?q=resultados+deportivos"}]
        ]
    }
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "reply_markup": keyboard}
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

def buscar_mejor_pick():
    global historial_enviados
    oportunidades = []

    for liga in LIGAS_TOP:
        url = API_URL.format(sport=liga)
        params = {"apiKey": ODDS_API_KEY, "regions": "us,eu", "markets": MARKETS, "oddsFormat": "decimal"}
        
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code != 200: continue
            
            for evento in res.json():
                dt_utc = datetime.strptime(evento["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                # Sigue el filtro de HOY y MAÑANA (36 horas)
                if dt_utc < (datetime.now(pytz.UTC) + timedelta(minutes=5)) or dt_utc > (datetime.now(pytz.UTC) + timedelta(hours=36)):
                    continue
                
                dt_mx = dt_utc.astimezone(TZ_MEXICO)
                dia_full = f"{DIAS_SEMANA.get(dt_mx.strftime('%A'), dt_mx.strftime('%A'))}, {dt_mx.strftime('%d/%m/%Y')}"
                
                bookmakers = evento.get("bookmakers", [])
                for b in bookmakers:
                    casa = b["title"]
                    for m in b["markets"]:
                        for out in m["outcomes"]:
                            nombre_pick = out["name"]
                            if "point" in out:
                                signo = "+" if out["point"] > 0 and m["key"] == "spreads" else ""
                                nombre_pick = f"{out['name']} {signo}{out['point']}"
                            
                            id_unico = f"{evento['id']}_{m['key']}_{nombre_pick}"
                            if id_unico in historial_enviados: continue

                            precios = [o["price"] for bk in bookmakers for mk in bk["markets"] 
                                      if mk["key"] == m["key"] for o in mk["outcomes"] if o["name"] == out["name"]]
                            
                            if len(precios) < 3: continue
                            promedio = sum(precios) / len(precios)
                            ventaja = out["price"] / promedio

                            # AHORA BUSCA VENTAJAS DESDE EL 3%
                            if ventaja >= UMBRAL_VALOR:
                                oportunidades.append({
                                    "ventaja": ventaja,
                                    "id_unico": id_unico,
                                    "msg": (
                                        "🎯 *NUEVA OPORTUNIDAD (3%+)* 🎯\n"
                                        "─────────────────────\n"
                                        f"🏟️ *Evento:* {evento['home_team']} vs {evento['away_team']}\n"
                                        f"📅 *Día:* {dia_full}\n"
                                        f"⏰ *Inicia:* {dt_mx.strftime('%H:%M')} (CDMX)\n"
                                        f"🏆 *Liga:* {evento['sport_title']}\n\n"
                                        f"🎯 *Pick:* {nombre_pick}\n"
                                        f"📊 *Mercado:* {m['key'].replace('h2h','Ganador').replace('totals','Goles/Puntos').replace('spreads','Hándicap').replace('btts','Ambos Anotan')}\n\n"
                                        f"📈 *Momio:* {out['price']}\n"
                                        f"🏛️ *Casa:* {casa}\n"
                                        f"✅ *Ventaja:* +{round((ventaja-1)*100, 1)}%\n"
                                        "─────────────────────\n"
                                        f"🕒 *Detección:* {datetime.now(TZ_MEXICO).strftime('%H:%M:%S')}"
                                    )
                                })
        except: continue

    if oportunidades:
        # Mandar el mejor pick del ciclo
        mejor = max(oportunidades, key=lambda x: x["ventaja"])
        enviar_telegram_con_botones(mejor["msg"], mejor["id_unico"])
        historial_enviados.append(mejor["id_unico"])
        if len(historial_enviados) > 200: historial_enviados.pop(0)

def main():
    logging.info("Bot Master v7: Umbral 3% + Hoy/Mañana + Anti-Repetición.")
    while True:
        buscar_mejor_pick()
        time.sleep(420) # 7 minutos entre escaneos

if __name__ == "__main__":
    main()
