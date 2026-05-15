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
    "basketball_nba", "baseball_mlb", "soccer_spain_la_liga"
]

MARKETS = "h2h,totals,spreads,btts"
API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"
UMBRAL_VALOR = 1.03 
TZ_MEXICO = pytz.timezone("America/Mexico_City")

DIAS_SEMANA = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo"
}

historial_enviados = []

def buscar_mejor_pick():
    global historial_enviados
    oportunidades = []
    
    # Intentamos rastrear los créditos en los headers de la respuesta
    creditos_restantes = "Desconocido"

    for liga in LIGAS_TOP:
        url = API_URL.format(sport=liga)
        params = {"apiKey": ODDS_API_KEY, "regions": "us,eu", "markets": MARKETS, "oddsFormat": "decimal"}
        
        try:
            res = requests.get(url, params=params, timeout=12)
            
            # --- MONITOR DE CRÉDITOS ---
            if "x-requests-remaining" in res.headers:
                creditos_restantes = res.headers["x-requests-remaining"]

            if res.status_code != 200: continue
            
            for evento in res.json():
                dt_utc = datetime.strptime(evento["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                if dt_utc < (datetime.now(pytz.UTC) + timedelta(minutes=5)) or dt_utc > (datetime.now(pytz.UTC) + timedelta(hours=36)):
                    continue
                
                dt_mx = dt_utc.astimezone(TZ_MEXICO)
                bookmakers = evento.get("bookmakers", [])
                for b in bookmakers:
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

                            if ventaja >= UMBRAL_VALOR:
                                oportunidades.append({
                                    "ventaja": ventaja,
                                    "id_unico": id_unico,
                                    "msg": (
                                        "🎯 *PICK DETECTADO (3%+)* 🎯\n"
                                        "─────────────────────\n"
                                        f"🏟️ *Evento:* {evento['home_team']} vs {evento['away_team']}\n"
                                        f"📅 *Día:* {DIAS_SEMANA.get(dt_mx.strftime('%A'), dt_mx.strftime('%A'))}, {dt_mx.strftime('%d/%m/%Y')}\n"
                                        f"⏰ *Inicia:* {dt_mx.strftime('%H:%M')} (CDMX)\n\n"
                                        f"🎯 *Pick:* {nombre_pick}\n"
                                        f"📈 *Momio:* {out['price']} ({b['title']})\n"
                                        f"✅ *Ventaja:* +{round((ventaja-1)*100, 1)}%"
                                    )
                                })
        except: continue

    # Reporte en la consola de Render
    print(f"--- Escaneo Terminado --- Créditos restantes: {creditos_restantes}")

    if oportunidades:
        mejor = max(oportunidades, key=lambda x: x["ventaja"])
        # (Aquí va tu función enviar_telegram_con_botones habitual)
        historial_enviados.append(mejor["id_unico"])

def main():
    while True:
        buscar_mejor_pick()
        time.sleep(600)

if __name__ == "__main__":
    main()
