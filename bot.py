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
            log("📱 [Telegram] ¡Análisis de Tipster enviado con éxito!")
        else:
            log(f"❌ [Telegram] Error al enviar: {res.status_code}")
    except Exception as e:
        log(f"❌ [Telegram] Error de conexión: {e}")

PARTIDOS_ENVIADOS = set()

def buscar_picks(api_key, bot_token, chat_id):
    global PARTIDOS_ENVIADOS
    sports = ["baseball_mlb", "soccer_mexico_ligamx"]
    
    todos_los_picks = []
    
    for sport in sports:
        log(f"🔍 Escaneando mercados para análisis premium: {sport}...")
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions=us,eu&markets=h2h"
        
        try:
            res = requests.get(url, timeout=15)
            if res.status_code != 200:
                continue
            
            partidos = res.json()
            
            for partido in partidos:
                partido_id = partido.get("id")
                
                if partido_id in PARTIDOS_ENVIADOS:
                    continue
                    
                home_team = partido.get("home_team")
                away_team = partido.get("away_team")
                commence_time_raw = partido.get("commence_time")
                bookmakers = partido.get("bookmakers", [])
                
                if len(bookmakers) < 5:
                    continue
                
                try:
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    dt_mexico = dt_utc - timedelta(hours=6)
                    fecha_hora_partido = dt_mexico.strftime("%Y-%m-%d a las %H:%M MX 🇲🇽")
                except:
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
                
                # ---- INTELIGENCIA ARTIFICIAL DE ARGUMENTACIÓN POR DEPORTE ----
                # Si es fútbol (Liga MX)
                if "soccer" in sport:
                    argumento_local = f"El conjunto local llega con la obligación táctica de proponer. El mercado global está castigando el momio, pero este casino nos da una ventaja clara para cubrir el hándicap o la victoria directa protegiendo el capital."
                    argumento_visita = f"Escenario de alta presión para el visitante o escenario de contraataque perfecto si traen ventaja en el global. La línea presenta un desajuste crítico; este momio tiene un valor matemático tremendo para aprovechar la urgencia del rival."
                # Si es béisbol (MLB / LMB)
                else:
                    argumento_local = f"Tendencia favorable para el pitcheo abridor o rotación estimada. Este casino se quedó dormido con la línea de apertura y nos regala una cuota muy por encima del promedio de Las Vegas."
                    argumento_visita = f"Racha ofensiva o ventaja en el bullpen que el algoritmo del casino local no está detectando correctamente. Valor puro en la cuota para pegarle al favorito en la carretera."

                # Evaluar Local
                mejor_casino_home, mejor_precio_home = max(odds_home, key=lambda x: x[1])
                ventaja_home = (mejor_precio_home / avg_home) - 1
                
                if ventaja_home >= 0.04:
                    todos_los_picks.append({
                        "partido_id": partido_id,
                        "partido": nombre_partido,
                        "apuesta": f"{home_team} (Ganador Local)",
                        "casino": mejor_casino_home,
                        "momio": mejor_precio_home,
                        "promedio": avg_home,
                        "ventaja": ventaja_home,
                        "horario": fecha_hora_partido,
                        "analisis": argumento_local
                    })
                
                # Evaluar Visitante
                mejor_casino_away, mejor_precio_away = max(odds_away, key=lambda x: x[1])
                ventaja_away = (mejor_precio_away / avg_away) - 1
                
                if ventaja_away >= 0.04:
                    todos_los_picks.append({
                        "partido_id": partido_id,
                        "partido": nombre_partido,
                        "apuesta": f"{away_team} (Ganador Visitante)",
                        "casino": mejor_casino_away,
                        "momio": mejor_precio_away,
                        "promedio": avg_away,
                        "ventaja": ventaja_away,
                        "horario": fecha_hora_partido,
                        "analisis": argumento_visita
                    })
                        
        except Exception as e:
            log(f"❌ Error escaneando: {e}")

    # ---- ENTRADA DEL TIPSTER AL CANAL (MAX 6) ----
    if todos_los_picks:
        todos_los_picks.sort(key=lambda x: x["ventaja"], reverse=True)
        
        picks_enviados_ciclo = 0
        partidos_usados_en_este_ciclo = set()
        
        for candidato in todos_los_picks:
            if picks_enviados_ciclo >= 6:
                break
                
            p_id = candidato["partido_id"]
            
            if p_id not in PARTIDOS_ENVIADOS and p_id not in partidos_usados_en_este_ciclo:
                # Mensaje formateado estilo canal VIP Premium
                msg = (
                    f"🧠 *【 ANÁLISIS PROFESIONAL VIP 】* 🧠\n"
                    f"───────────────────────\n"
                    f"📅 *Evento:* {candidato['horario']}\n"
                    f"⚔️ *Encuentro:* {candidato['partido']}\n\n"
                    f"📝 *LECTURA DEL ENCUENTRO:*\n"
                    f"_{candidato['analisis']}_\n\n"
                    f"🎯 *PICK RECOMENDADO:* `{candidato['apuesta']}`\n"
                    f"🏛 *Casa de Apuestas:* {candidato['casino']}\n"
                    f"📈 *Momio de Entrada:* {candidato['momio']}\n"
                    f"📊 *Cuota Promedio de Mercado:* {candidato['promedio']:.2f}\n"
                    f"💰 *Ventaja Matemática:* {candidato['ventaja']*100:.1f}%\n"
                    f"───────────────────────\n"
                    f"🔥 _¡Entrar con responsabilidad, valor detectado!_"
                )
                send_telegram(bot_token, chat_id, msg)
                
                PARTIDOS_ENVIADOS.add(p_id)
                partidos_usados_en_este_ciclo.add(p_id)
                picks_enviados_ciclo += 1
                
        if picks_enviados_ciclo == 0:
            log("💤 Sin novedades en este ciclo.")
    else:
        log("📉 Todo normal en las cuotas.")

def main():
    log("------------------------------------------")
    log("🚀 BOT MODE: TIPSTER VIP CHAT ACTIVADO")
    log("------------------------------------------")
    
    api_key = os.getenv("ODDS_API_KEY")
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    
    if not api_key or not bot_token or not chat_id:
        log("❌ ERROR CRÍTICO: Variables ausentes.")
        return

    while True:
        buscar_picks(api_key, bot_token, chat_id)
        log("😴 Esperando 5 minutos para el siguiente reporte de valor...")
        time.sleep(300)

if __name__ == "__main__":
    main()
