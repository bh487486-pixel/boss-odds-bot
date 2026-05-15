import os
import time
import logging
from datetime import datetime
import pytz
import requests

# --- CONFIGURACIÓN ---
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

API_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
REGIONS = "us,eu" 
MARKETS = "h2h,totals"

# Ajustamos a 5% para que lo que llegue sea realmente bueno
UMBRAL_VALOR = 1.05  
TZ_MEXICO = pytz.timezone("America/Mexico_City")

# Para no repetir el mismo pick del mismo partido
picks_enviados = set()

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

def buscar_mejor_pick():
    global picks_enviados
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": "decimal"
    }
    
    try:
        response = requests.get(API_URL, params=params, timeout=15)
        if response.status_code != 200: return

        partidos = response.json()
        posibles_oportunidades = []

        for partido in partidos:
            home = partido["home_team"]
            away = partido["away_team"]
            dt_utc = datetime.strptime(partido["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            hora_mx = dt_utc.astimezone(TZ_MEXICO).strftime("%H:%M")

            bookmakers = partido.get("bookmakers", [])
            if len(bookmakers) < 3: continue

            for b in bookmakers:
                casa_nombre = b["title"]
                for market in b["markets"]:
                    # Solo Over/Under 2.5 o Ganador para no saturar
                    for out in market["outcomes"]:
                        # Calculamos el promedio rápido para este outcome específico
                        precios_otros = []
                        for b2 in bookmakers:
                            for m2 in b2["markets"]:
                                if m2["key"] == market["key"]:
                                    for out2 in m2["outcomes"]:
                                        if out2["name"] == out["name"]:
                                            precios_otros.append(out2["price"])
                        
                        if not precios_otros: continue
                        promedio = sum(precios_otros) / len(precios_otros)
                        ventaja = out["price"] / promedio

                        if ventaja >= UMBRAL_VALOR:
                            pick_id = f"{partido['id']}_{out['name']}_{market['key']}"
                            if pick_id not in picks_enviados:
                                posibles_oportunidades.append({
                                    "id": pick_id,
                                    "msg": (
                                        "🎯 *PICK DE ALTO VALOR* 🎯\n"
                                        "─────────────────────\n"
                                        f"⚽ *Evento:* {home} vs {away}\n"
                                        f"⏰ *Inicia:* {hora_mx} (CDMX)\n\n"
                                        f"➡️ *Apuesta:* {out['name']}\n"
                                        f"📈 *Momio:* {out['price']} en {casa_nombre}\n"
                                        f"📊 *Promedio:* {round(promedio, 2)}\n"
                                        f"✅ *Ventaja:* +{round((ventaja-1)*100, 1)}%\n\n"
                                        f"➡️ *Stake:* 5/10"
                                    ),
                                    "ventaja_num": ventaja
                                })

        # --- AQUÍ ESTÁ EL TRUCO ANTI-SPAM ---
        # Si hay muchas opciones, solo mandamos la que tenga la ventaja más grande
        if posibles_oportunidades:
            mejor_opcion = max(posibles_oportunidades, key=lambda x: x["ventaja_num"])
            enviar_telegram(mejor_opcion["msg"])
            picks_enviados.add(mejor_opcion["id"])
            
    except Exception as e:
        print(f"Error: {e}")

def main():
    # Limpiar caché de enviados cada 12 horas para no saturar memoria
    while True:
        buscar_mejor_pick()
        # Espera 10 minutos entre mensajes para que no te vuelva loco
        time.sleep(600) 

if __name__ == "__main__":
    main()
