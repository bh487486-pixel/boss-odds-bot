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

API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"
UMBRAL_VALOR = 1.05 
TZ_MEXICO = pytz.timezone("America/Mexico_City")

# Días en español para el formato
DIAS_SEMANA = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo"
}

partidos_enviados_hoy = set()

def enviar_telegram_con_botones(mensaje, id_evento):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Ganada", "callback_data": f"win_{id_evento}"},
                {"text": "❌ Perdida", "callback_data": f"loss_{id_evento}"}
            ],
            [{"text": "📊 Marcador en Vivo", "url": "https://www.google.com/search?q=resultados+deportivos+hoy"}]
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
    except: pass

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

                dt_utc = datetime.strptime(evento["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                ahora_utc = datetime.now(pytz.UTC)
                
                # Filtro: Solo hoy y mañana (próximas 36 horas)
                if dt_utc < (ahora_utc + timedelta(minutes=10)) or dt_utc > (ahora_utc + timedelta(hours=36)):
                    continue
                
                # Conversión a zona horaria de México
                dt_mx = dt_utc.astimezone(TZ_MEXICO)
                dia_nombre = DIAS_SEMANA.get(dt_mx.strftime("%A"), dt_mx.strftime("%A"))
                fecha_formateada = dt_mx.strftime("%d de %B") # Ejemplo: 15 de Mayo
                hora_inicio = dt_mx.strftime("%H:%M")

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
                                        "💎 *PICK DE VALOR DETECTADO* 💎\n"
                                        "─────────────────────\n"
                                        f"🏟️ *Evento:* {evento['home_team']} vs {evento['away_team']}\n"
                                        f"📅 *Día:* {dia_nombre}, {dt_mx.strftime('%d/%m/%Y')}\n"
                                        f"⏰ *Inicia:* {hora_inicio} (CDMX)\n"
                                        f"🏆 *Liga:* {evento['sport_title']}\n\n"
                                        f"🎯 *Apuesta:* {out['name']} ({m['key']})\n"
                                        f"📈 *Momio:* {out['price']}\n"
                                        f"🏛️ *Casa:* {casa}\n"
                                        f"📊 *Ventaja:* +{round((ventaja-1)*100, 1)}%\n"
                                        "─────────────────────\n"
                                        f"🕒 *Detección:* {datetime.now(TZ_MEXICO).strftime('%H:%M:%S')}"
                                    )
                                })
        except: continue

    if oportunidades:
        mejor = max(oportunidades, key=lambda x: x["ventaja"])
        enviar_telegram_con_botones(mejor["msg"], mejor["id"])
        partidos_enviados_hoy.add(mejor["id"])

def main():
    logging.info("Bot Master v5: Formato de Fecha y Día añadido.")
    while True:
        buscar_mejor_pick()
        time.sleep(600)

if __name__ == "__main__":
    main()
