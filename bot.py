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
            log("📱 [Telegram] ¡Análisis Multi-Mercado enviado!")
        else:
            log(f"❌ [Telegram] Error al enviar: {res.status_code}")
    except Exception as e:
        log(f"❌ [Telegram] Error de conexión: {e}")

PARTIDOS_ENVIADOS = set()

def buscar_picks(api_key, bot_token, chat_id):
    global PARTIDOS_ENVIADOS
    sports = ["baseball_mlb", "soccer_mexico_ligamx"]
    
    todos_los_picks = []
    ahora_utc = datetime.utcnow()
    
    for sport in sports:
        log(f"🔍 Escaneando mercados múltiples para: {sport}...")
        # Agregamos los mercados h2h (ganador), totals (over/under) y spreads (hándicap) en la URL
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
                
                # Filtro de tiempo (mínimo 15 minutos en el futuro)
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
                
                # Diccionarios para agrupar cuotas por mercado
                mercados_data = {"h2h": {}, "totals": {}, "spreads": {}}
                
                # Extraer y organizar las cuotas de todos los casinos disponibles
                for bookie in bookmakers:
                    b_title = bookie.get("title")
                    for market in bookie.get("markets", []):
                        m_key = market.get("key")
                        if m_key in mercados_data:
                            for outcome in market.get("outcomes", []):
                                # Creamos una llave única para promediar correctamente
                                o_name = outcome.get("name")
                                o_price = outcome.get("price")
                                o_point = outcome.get("point", "") # Para el .point de Over/Under o Hándicap
                                
                                # Guardamos bajo la etiqueta exacta (ej: "Over 2.5" o "Gana Pachuca")
                                full_label = f"{o_name} {o_point}".strip()
                                if full_label not in mercados_data[m_key]:
                                    mercados_data[m_key][full_label] = []
                                mercados_data[m_key][full_label].append((b_title, o_price))
                
                # Analizar cada mercado organizado
                for m_key, opciones in mercados_data.items():
                    for label, lista_cuotas in opciones.items():
                        # Necesitamos que al menos 4 casinos tengan este mercado específico para promediar
                        if len(lista_cuotas) < 4:
                            continue
                            
                        precios = [c[1] for c in lista_cuotas]
                        avg_price = sum(precios) / len(precios)
                        
                        mejor_casino, mejor_precio = max(lista_cuotas, key=lambda x: x[1])
                        ventaja = (mejor_precio / avg_price) - 1
                        
                        # Si encontramos ventaja del 4% o más, se genera el pick
                        if ventaja >= 0.04:
                            # Ajuste de argumentos automáticos estilo Tipster VIP
                            if m_key == "h2h":
                                tipo_m = "LÍNEA DE DINERO (GANADOR)"
                                arg = f"Desajuste directo en la victoria. Este casino está pagando una cuota desproporcionada comparada con el promedio global."
                            elif m_key == "totals":
                                tipo_m = "TOTALES (OVER/UNDER)"
                                arg = f"La línea de puntos/goles en este casino está mal calculada. Las probabilidades matemáticas apuntan a que esta cuota de {label} está regalada."
                            else:
                                tipo_m = "HÁNDICAP / SPREAD"
                                arg = f"La ventaja de puntos o carreras otorgada ({label}) tiene un colchón matemático óptimo. Cobertura perfecta para asegurar."

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

    # ---- ENTRADA DEL TIPSTER AL CANAL (MAX 6 PARTIDOS DIFERENTES) ----
    if todos_los_picks:
        todos_los_picks.sort(key=lambda x: x["ventaja"], reverse=True)
        
        picks_enviados_ciclo = 0
        partidos_usados_en_este_ciclo = set()
        
        for candidato in todos_los_picks:
            if picks_enviados_ciclo >= 6:
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
    log("🚀 BOT MODE: SUPER TIPSTER MULTI-MERCADO ACTIVADO")
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
