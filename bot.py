import os
import time
import logging
from datetime import datetime
import pytz
import requests

# --- CONFIGURACIÓN DE VARIABLES ---
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Configuración de API
# Añadimos 'us' y 'eu' porque Caliente/Playdoit suelen clonar líneas de estas regiones
API_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
REGIONS = "us,eu" 
MARKETS = "h2h,totals"

# CONFIGURACIÓN DE VALOR
UMBRAL_VALOR = 1.04  # 4% de ventaja
TZ_MEXICO = pytz.timezone("America/Mexico_City")

# --- SISTEMA DE IDENTIFICACIÓN DE CASAS ---
# Mapeo de nombres para que sea más fácil encontrarlas en México
CASAS_MX = {
    "Betway": "Betway (Momio muy similar a Caliente)",
    "888sport": "888Sport (Línea internacional)",
    "Unibet": "Unibet (Referencia para Playdoit)",
    "DraftKings": "DraftKings (Referencia)",
    "FanDuel": "FanDuel (Referencia)",
    "BetRivers": "BetRivers (Línea similar a Winpot)"
}

picks_enviados = set()

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

def buscar_picks():
    global picks_enviados
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": "decimal"
    }
    
    try:
        # Buscamos en las ligas que están activas ahorita (Soccer)
        response = requests.get(API_URL, params=params, timeout=15)
        if response.status_code != 200: return

        partidos = response.json()
        for partido in partidos:
            home = partido["home_team"]
            away = partido["away_team"]
            
            # Hora del partido
            dt_utc = datetime.strptime(partido["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            hora_mx = dt_utc.astimezone(TZ_MEXICO).strftime("%H:%M")

            bookmakers = partido.get("bookmakers", [])
            if len(bookmakers) < 2: continue

            # Analizar mercados
            for market in bookmakers[0]["markets"]:
                # Calculamos el promedio de todas las casas para este mercado
                todas_las_cuotas = []
                for b in bookmakers:
                    for m in b["markets"]:
                        if m["key"] == market["key"]:
                            for out in m["outcomes"]:
                                todas_las_cuotas.append(out["price"])
                
                if not todas_las_cuotas: continue
                promedio = sum(todas_las_cuotas) / len(todas_las_cuotas)

                # Buscar si alguna casa de las que nos interesan tiene error
                for b in bookmakers:
                    nombre_casa = b["title"]
                    # Si la casa está en nuestra lista de interés o es una oportunidad clara
                    for m in b["markets"]:
                        if m["key"] == market["key"]:
                            for out in m["outcomes"]:
                                precio = out["price"]
                                ventaja = (precio / promedio)
                                
                                # Si hay ventaja del 4%
                                if ventaja >= UMBRAL_VALOR:
                                    pick_id = f"{partido['id']}_{out['name']}_{market['key']}"
                                    if pick_id not in picks_enviados:
                                        
                                        # Personalizar nombre de la casa si es conocida en MX
                                        nombre_final = CASAS_MX.get(nombre_casa, nombre_casa)
                                        
                                        msg = (
                                            "💎 *ERROR DE LÍNEA DETECTADO* 💎\n"
                                            "─────────────────────\n"
                                            f"⚽ *Partido:* {home} vs {away}\n"
                                            f"⏰ *Inicia:* {hora_mx} (CDMX)\n"
                                            f"🏆 *Liga:* {partido['sport_title']}\n\n"
                                            f"🎯 *Pick:* {out['name']} ({market['key']})\n"
                                            f"📈 *Momio:* {precio}\n\n"
                                            f"🏛️ *Casa:* {nombre_final}\n"
                                            f"📊 *Promedio Mercado:* {round(promedio, 2)}\n"
                                            f"✅ *Ventaja:* +{round((ventaja-1)*100, 1)}%\n\n"
                                            f"➡️ *Stake Sugerido:* 5/10"
                                        )
                                        enviar_telegram(msg)
                                        picks_enviados.add(pick_id)
    except Exception as e:
        print(f"Error: {e}")

def main():
    logging.info("Bot MX Value iniciado...")
    while True:
        buscar_picks()
        time.sleep(300) # 5 minutos

if __name__ == "__main__":
    main()
