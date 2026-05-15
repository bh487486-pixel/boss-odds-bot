import os
import time
import requests
import sys
from datetime import datetime, timedelta

def log(msg):
    print(msg)
    sys.stdout.flush()

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            log("📱 [Telegram] ¡Alerta enviada con éxito!")
        else:
            log(f"❌ [Telegram] Error al enviar: {res.status_code}")
    except Exception as e:
        log(f"❌ [Telegram] Error de conexión: {e}")

# Historial para no repetir picks ya enviados
ENVIADOS = {}

def buscar_picks(api_key, bot_token, chat_id):
    global ENVIADOS
    sports = ["baseball_mlb", "soccer_mexico_ligamx"]
    
    todos_los_picks = []
    
    for sport in sports:
        log(f"🔍 Analizando mercado: {sport}...")
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions=us,eu&markets=h2h"
        
        try:
            res = requests.get(url, timeout=15)
            if res.status_code != 200:
                continue
            
            partidos = res.json()
            
            for partido in partidos:
                partido_id = partido.get("id")
                home_team = partido.get("home_team")
                away_team = partido.get("away_team")
                commence_time_raw = partido.get("commence_time")
                bookmakers = partido.get("bookmakers", [])
                
                if len(bookmakers) < 5:
                    continue
                
                # ---- CONVERSIÓN DE UTC A HORA DE MÉXICO (Ajuste de -6 horas) ----
                try:
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    dt_mexico = dt_utc - timedelta(hours=6) # Ajusta al huso horario de CDMX
                    fecha_hora_partido = dt_mexico.strftime("%Y-%m-%d a las %H:%M Horario MX 🇲🇽")
                except Exception as e:
                    fecha_hora_partido = commence_time_raw
                
                odds_home = []
                odds_away = []
                
                for bookie in bookmakers:
                    for market in bookie.get("markets", []):
                        if market.get("key") == "h2h":
                            for outcome in market.get("outcomes", []):
                                if outcome.get("name") == home_team:
                                    odds_home.append((bookie.get("title"), outcome.get("price")))
                                elif outcome.get("name") == away_team:
                                    odds_away.append((bookie.get("title"), outcome.get("price")))
                
                if not odds_home or not odds_away:
                    continue
                
                avg_home = sum([o[1] for o in odds_home]) / len(odds_home)
                avg_away = sum([o[1] for o in odds_away]) / len(odds_away)
                
                nombre_partido = f"{away_team} vs {home_team}"
                
                # Evaluar Local
                mejor_casino_home, mejor_precio_home = max(odds_home, key=lambda x: x[1])
                ventaja_home = (mejor_precio_home / avg_home) - 1
                
                if ventaja_home >= 0.04:
                    todos_los_picks.append({
                        "id_unico": f"{partido_id}_home_{mejor_precio_home}",
                        "partido": nombre_partido,
                        "apuesta": f"Gana {home_team} (Local)",
                        "casino": mejor_casino_home,
                        "momio": mejor_precio_home,
                        "promedio": avg_home,
                        "ventaja": ventaja_home,
                        "horario": fecha_hora_partido
                    })
                
                # Evaluar Visitante
                mejor_casino_away, mejor_precio_away = max(odds_away, key=lambda x: x[1])
                ventaja_away = (mejor_precio_away / avg_away) - 1
                
                if ventaja_away >= 0.04:
                    todos_los_picks.append({
                        "id_unico": f"{partido_id}_away_{mejor_precio_away}",
                        "partido": nombre_partido,
                        "apuesta": f"Gana {away_team} (Visitante)",
                        "casino": mejor_casino_away,
                        "momio": mejor_precio_away,
                        "promedio": avg_away,
                        "ventaja": ventaja_away,
                        "horario": fecha_hora_partido
                    })
                        
        except Exception as e:
            log(f"❌ Error escaneando: {e}")

    # ---- FILTRO: HASTA 6 PICKS DE PARTIDOS DIFERENTES ----
    if todos_los_picks:
        todos_los_picks.sort(key=lambda x: x["ventaja"], reverse=True)
        
        picks_enviados_hoy = 0
        partidos_ya_usados = set()
        
        for candidato in todos_los_picks:
            if picks_enviados_hoy >= 6:
                break
                
            if candidato["id_unico"] not in ENVIADOS and candidato["partido"] not in partidos_ya_usados:
                msg = (
                    f"🔥 *¡ALERTA DE VALOR!* 🔥\n\n"
                    f"📅 *Horario:* {candidato['horario']}\n"
                    f"⚔️ *Partido:* {candidato['partido']}\n"
                    f"🎯 *Apuesta Recomendada:* {candidato['apuesta']}\n"
                    f"🏛 *Casino:* {candidato['casino']}\n\n"
                    f"📈 *Momio Encontrado:* {candidato['momio']}\n"
                    f"📊 *Promedio General:* {candidato['promedio']:.2f}\n"
                    f"💰 *Ventaja sobre Mercado:* {candidato['ventaja']*100:.1f}%"
                )
                send_telegram(bot_token, chat_id, msg)
                
                ENVIADOS[candidato["id_unico"]] = True
                partidos_ya_usados.add(candidato["partido"])
                picks_enviados_hoy += 1
                
        if picks_enviados_hoy == 0:
            log("💤 Las mejores oportunidades ya fueron notificadas. Esperando nuevos movimientos.")
        else:
            log(f"✅ Se enviaron {picks_enviados_hoy} picks corregidos con hora local.")
    else:
        log("📉 No hay oportunidades que superen el filtro en este momento.")

def main():
    log("------------------------------------------")
    log("🚀 BOT MULTI-PICK CORREGIDO (HORA MX) ACTIVADO")
    log("------------------------------------------")
    
    api_key = os.getenv("ODDS_API_KEY")
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    
    if not api_key or not bot_token or not chat_id:
        log("❌ ERROR CRÍTICO: Variables de entorno ausentes.")
        return

    while True:
        buscar_picks(api_key, bot_token, chat_id)
        log("😴 Esperando 5 minutos para el siguiente escaneo...")
        time.sleep(300)

if __name__ == "__main__":
    main()
