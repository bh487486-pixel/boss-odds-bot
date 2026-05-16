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
            log("📱 [Telegram] ¡Análisis VIP Multi-Liga enviado!")
        else:
            log(f"❌ [Telegram] Error al enviar: {res.status_code}")
    except Exception as e:
        log(f"❌ [Telegram] Error de conexión: {e}")

PARTIDOS_ENVIADOS = set()

def buscar_picks(api_key, bot_token, chat_id):
    global PARTIDOS_ENVIADOS
    
    # MLB, Liga MX, Premier League, LaLiga y Bundesliga
    sports = [
        "baseball_mlb", 
        "soccer_mexico_ligamx",
        "soccer_epl", 
        "soccer_spain_la_liga", 
        "soccer_germany_bundesliga"
    ]
    
    todos_los_picks = []
    ahora_utc = datetime.utcnow()
    
    for sport in sports:
        log(f"🔍 Escaneando mercados múltiples para: {sport}...")
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions=us,eu&markets=h2h,totals,spreads"
        
        try:
            res = requests.get(url, timeout=15)
            if res.status_code != 200:
                continue
            
            partidos = res.json()
            
            for partido in partidos:
                partido_id = partido.get("id")
                
                if partido_id in PARTIDOS_ENVIADOS:
                    continue
                    
                commence_time_raw = partido.get("commence_time")
                
                # Filtro de tiempo mínimo (15 minutos en el futuro)
                try:
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    if dt_utc <= ahora_utc + timedelta(minutes=15):
                        continue
                    dt_mexico = dt_utc - timedelta(hours=6)
                    fecha_hora_partido = dt_mexico.strftime("%Y-%m-%d a las %H:%M MX 🇲🇽")
                except:
                    continue
                
                home_team = partido.get("home_team")
                away_team = partido.get("away_team")
                bookmakers = partido.get("bookmakers", [])
                
                if len(bookmakers) < 5:
                    continue
                
                nombre_partido = f"{away_team} vs {home_team}"
                mercados_data = {"h2h": {}, "totals": {}, "spreads": {}}
                
                for bookie in bookmakers:
                    b_title = bookie.get("title")
                    for market in bookie.get("markets", []):
                        m_key = market.get("key")
                        if m_key in mercados_data:
                            for outcome in market.get("outcomes", []):
                                o_name = outcome.get("name")
                                o_price = outcome.get("price")
                                o_point = outcome.get("point", None)
                                
                                # Traducción y formateo al español
                                label_final = o_name
                                if m_key == "h2h":
                                    if o_name.lower() == "draw":
                                        label_final = "Empate"
                                    elif o_name == home_team:
                                        label_final = f"Gana {home_team} (Local)"
                                    elif o_name == away_team:
                                        label_final = f"Gana {away_team} (Visitante)"
                                        
                                elif m_key == "totals":
                                    if o_name.lower() == "over":
                                        label_final = f"Altas (Over) {o_point}"
                                    elif o_name.lower() == "under":
                                        label_final = f"Bajas (Under) {o_point}"
                                        
                                elif m_key == "spreads" and o_point is not None:
                                    try:
                                        num_point = float(o_point)
                                        signo = "+" if num_point > 0 else ""
                                        label_final = f"Hándicap {o_name} ({signo}{o_point})"
                                    except:
                                        label_final = f"Hándicap {o_name} ({o_point})"
                                
                                if label_final not in mercados_data[m_key]:
                                    mercados_data[m_key][label_final] = []
                                mercados_data[m_key][label_final].append((b_title, o_price))
                
                for m_key, opciones in mercados_data.items():
                    for label, lista_cuotas in opciones.items():
                        if len(lista_cuotas) < 4:
                            continue
                            
                        precios = [c[1] for c in lista_cuotas]
                        avg_price = sum(precios) / len(precios)
                        
                        mejor_casino, mejor_precio = max(lista_cuotas, key=lambda x: x[1])
                        ventaja = (mejor_precio / avg_price) - 1
                        
                        if ventaja >= 0.04:
                            if m_key == "h2h":
                                tipo_m = "LÍNEA DE DINERO (GANADOR)"
                                arg = "Desajuste directo en las probabilidades de victoria. Este casino se quedó atrás y nos ofrece una cuota inflada con excelente valor."
                            elif m_key == "totals":
                                tipo_m = "TOTALES (ALTAS/BAJAS)"
                                arg = "La línea de puntos o goles propuesta por este casino está mal balanceada frente al promedio. Margen matemático óptimo para apostar."
                            else:
                                tipo_m = "HÁNDICAP (VENTAJA)"
                                arg = "La ventaja otorgada en este hándicap nos da un colchón de seguridad tremendo. Las cuotas del mercado general protegen esta línea."

                            todos_los_picks.append({
                                "partido_id": partido_id,
                                "partido": nombre_partido,
                                "mercado": tipo_m,
                                "apuesta": label,
                                "casino": mejor_casino,
                                "momio": mejor_precio,
                                "promedio": avg_price,
                                "ventaja": ventaja,
                                "horario": fecha_hora_partido,
                                "analisis": arg
                            })
                            
        except Exception as e:
            log(f"❌ Error escaneando: {e}")

    # ---- ENTRADA AL CANAL (MÁXIMO 7 PARTIDOS DIFERENTES) ----
    if todos_los_picks:
        todos_los_picks.sort(key=lambda x: x["ventaja"], reverse=True)
        
        picks_enviados_ciclo = 0
        partidos_usados_en_este_ciclo = set()
        
        for candidato in todos_los_picks:
            # Límite actualizado a 7 picks por ciclo
            if picks_enviados_ciclo >= 7:
                break
                
            p_id = candidato["partido_id"]
            
            if p_id not in PARTIDOS_ENVIADOS and p_id not in partidos_usados_en_este_ciclo:
                msg = (
                    f"🧠 *【 ANÁLISIS PROFESIONAL VIP 】* 🧠\n"
                    f"───────────────────────\n"
                    f"📅 *Evento:* {candidato['horario']}\n"
                    f"⚔️ *Encuentro:* {candidato['partido']}\n"
                    f"📊 *Mercado:* `{candidato['mercado']}`\n\n"
                    f"📝 *LECTURA DEL ENCUENTRO:*\n"
                    f"_{candidato['analisis']}_\n\n"
                    f"🎯 *PICK RECOMENDADO:* `{candidato['apuesta']}`\n"
                    f"🏛 *Casa de Apuestas:* {candidato['casino']}\n"
                    f"📈 *Momio de Entrada:* {candidato['momio']}\n"
                    f"📊 *Cuota Promedio:* {candidato['promedio']:.2f}\n"
                    f"💰 *Ventaja Matemática:* {candidato['ventaja']*100:.1f}%\n"
                    f"───────────────────────\n"
                    f"🔥 _¡Entrar con responsabilidad, valor detectado!_"
                )
                send_telegram(bot_token, chat_id, msg)
                
                PARTIDOS_ENVIADOS.add(p_id)
                partidos_usados_en_este_ciclo.add(p_id)
                picks_enviados_ciclo += 1
                
        if picks_enviados_ciclo == 0:
            log("💤 Sin novedades de valor en este ciclo.")
    else:
        log("📉 Todo en orden en las líneas de los casinos.")

def main():
    log("------------------------------------------")
    log("🚀 BOT MODE: SUPER TIPSTER 7 PICKS ACTIVADO")
    log("------------------------------------------")
    
    api_key = os.getenv("ODDS_API_KEY")
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    
    if not api_key or not bot_token or not chat_id:
        log("❌ ERROR CRÍTICO: Variables ausentes.")
        return

    while True:
        buscar_picks(api_key, bot_token, chat_id)
        # 10 minutos de espera activos (600 segundos)
        log("😴 Esperando 10 minutos para el siguiente reporte de valor...")
        time.sleep(600)

if __name__ == "__main__":
    main()
