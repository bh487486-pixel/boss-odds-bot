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

# LIGAS ELEGIDAS (Balance entre ahorro y acción)
LIGAS_TOP = [
    "soccer_mexico_ligamx", 
    "baseball_mlb",
    "basketball_nba",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_uefa_champions_league"
]

MARKETS = "h2h,totals,spreads,btts"
API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"
UMBRAL_VALOR = 1.03  # 3% de ventaja para que caigan picks pronto
TZ_MEXICO = pytz.timezone("America/Mexico_City")

DIAS_SEMANA = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo"
}

historial_enviados = []

def enviar_telegram(mensaje, id_unico):
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
    except: 
        print("❌ Error enviando a Telegram")

def buscar_mejor_pick():
    global historial_enviados
    ahora_mx = datetime.now(TZ_MEXICO)
    
    # MODO AHORRO (Opcional: puedes comentar esto si quieres picks 24/7)
    if ahora_mx.hour < 7:
        print("🌙 Horario nocturno: Modo ahorro activo.")
        return

    print(f"🔍 Iniciando escaneo de {len(LIGAS_TOP)} ligas...")
    oportunidades = []
    creditos_restantes = "Desconocido"

    for liga in LIGAS_TOP:
        url = API_URL.format(sport=liga)
        params = {"apiKey": ODDS_API_KEY, "regions": "us,eu", "markets": MARKETS, "oddsFormat": "decimal"}
        
        try:
            res = requests.get(url, params=params, timeout=12)
            if "x-requests-remaining" in res.headers:
                creditos_restantes = res.headers["x-requests-remaining"]

            if res.status_code == 401:
                print("❌ ERROR: API Key inválida o vencida.")
                return
            
            if res.status_code != 200: continue
            
            for evento in res.json():
                dt_utc = datetime.strptime(evento["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
                # Solo hoy y mañana (36 horas)
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
                                        "🎯 *OPORTUNIDAD DETECTADA* 🎯\n"
                                        "─────────────────────\n"
                                        f"🏟️ *Evento:* {evento['home_team']} vs {evento['away_team']}\n"
                                        f"📅 *Día:* {DIAS_SEMANA.get(dt_mx.strftime('%A'), dt_mx.strftime('%A'))}, {dt_mx.strftime('%d/%m/%Y')}\n"
                                        f"⏰ *Inicia:* {dt_mx.strftime('%H:%M')} (CDMX)\n\n"
                                        f"🏆 *Liga:* {evento['sport_title']}\n"
                                        f"🎯 *Pick:* {nombre_pick}\n"
                                        f"📈 *Momio:* {out['price']} ({b['title']})\n"
                                        f"✅ *Ventaja:* +{round((ventaja-1)*100, 1)}%\n"
                                        "─────────────────────"
                                    )
                                })
        except Exception as e:
            print(f"⚠️ Error en liga {liga}: {e}")
            continue

    print(f"✅ Escaneo terminado. Créditos restantes: {creditos_restantes}")

    if oportunidades:
        mejor = max(oportunidades, key=lambda x: x["ventaja"])
        enviar_telegram(mejor["msg"], mejor["id_unico"])
        historial_enviados.append(mejor["id_unico"])
        print(f"🚀 Pick enviado a Telegram: {mejor['id_unico']}")
        if len(historial_enviados) > 200: historial_enviados.pop(0)
    else:
        print("ℹ️ No se encontraron picks con ventaja suficiente en este ciclo.")

def main():
    print("------------------------------------------")
    print("🚀 BOT INICIADO - ESPERANDO PRIMER ESCANEO")
    print("------------------------------------------")
    
    while True:
        buscar_mejor_pick()
        print("😴 Esperando 15 minutos para el siguiente escaneo...")
        time.sleep(900)

if __name__ == "__main__":
    main()
