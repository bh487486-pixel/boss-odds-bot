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

# Ligas: Fútbol, NBA y MLB (Béisbol)
LIGAS_TOP = [
    "soccer_mexico_ligamx", "soccer_epl", "soccer_uefa_champions_league",
    "basketball_nba", "baseball_mlb", "soccer_spain_la_liga"
]

API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"
UMBRAL_VALOR = 1.05  # 5% de ventaja
TZ_MEXICO = pytz.timezone("America/Mexico_City")

# Memoria para no repetir
partidos_enviados_hoy = set()

def enviar_telegram_con_botones(mensaje, id_evento):
    """Envía mensaje con botones para seguimiento."""
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # Creamos botones interactivos
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Ganada", "callback_data": f"win_{id_evento}"},
                {"text": "❌ Perdida", "callback_data": f"loss_{id_evento}"}
            ],
            [{"text": "📊 Ver Estadísticas", "url": "https://www.google.com/search?q=resultados+de+deportes"}]
        ]
    }
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    }
    
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Error enviando botones: {e}")

def buscar_mejor_pick():
    global partidos_enviados_hoy
    oportunidades = []

    for liga in LIGAS_TOP:
        url = API_URL.format(sport=liga)
        params = {"apiKey": ODDS_API_KEY, "regions": "us,eu", "markets": "h2h,totals", "oddsFormat": "decimal"}
        
        try:
            res = requests.get(url, params=params, timeout=12)
            if res.status_code != 200: continue
            
            for evento in res.json():
                id_evento = evento["id"]
                if id_evento in partidos_enviados_hoy: continue

                # Filtro de tiempo: ignorar si falta menos de 10 min o ya empezó
                dt_utc = datetime.strptime(evento["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                if dt_utc < (datetime.now(pytz.UTC) + timedelta(minutes=10)): continue
                
                hora_mx = dt_utc.astimezone(TZ_MEXICO).strftime("%H:%M")
                bookmakers = evento.get("bookmakers", [])
                if len(bookmakers) < 3: continue

                for b in bookmakers:
                    casa = b["title"]
                    for m in b["markets"]:
                        for out in m["outcomes"]:
                            precios = [o["price"] for bk in bookmakers for mk in bk["markets"] 
                                      if mk["key"] == m["key"] for o in mk["outcomes"] if o["name"] == out["name"]]
                            
                            promedio = sum(precios) / len(precios)
                            ventaja = out["price"] / promedio

                            if ventaja >= UMBRAL_VALOR:
                                oportunidades.append({
                                    "ventaja": ventaja,
                                    "id": id_evento,
                                    "msg": (
                                        "💎 *PICK EXCLUSIVO DETECTADO* 💎\n"
                                        "─────────────────────\n"
                                        f"🏟️ *Evento:* {evento['home_team']} vs {evento['away_team']}\n"
                                        f"⏰ *Inicia:* {hora_mx} (CDMX)\n"
                                        f"🏆 *Liga:* {evento['sport_title']}\n\n"
                                        f"🎯 *Pick:* {out['name']} ({m['key']})\n"
                                        f"📈 *Momio:* {out['price']}\n"
                                        f"🏛️ *Casa:* {casa}\n"
                                        f"📊 *Ventaja:* +{round((ventaja-1)*100, 1)}%\n"
                                        "─────────────────────\n"
                                        "⚠️ *Instrucción:* Selecciona el resultado abajo para tu registro personal."
                                    )
                                })
        except: continue

    if oportunidades:
        mejor = max(oportunidades, key=lambda x: x["ventaja"])
        enviar_telegram_con_botones(mejor["msg"], mejor["id"])
        partidos_enviados_hoy.add(mejor["id"])

def main():
    logging.info("Bot Ultra con Botones y Multiliga iniciado.")
    while True:
        buscar_mejor_pick()
        time.sleep(600) # Cada 10 minutos para ser premium y no spam

if __name__ == "__main__":
    main()
