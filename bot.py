import os
import time
import requests
import sys
from datetime import datetime, timedelta, timezone

def log(msg):
    print(msg)
    sys.stdout.flush()

def send_telegram(token, chat_id, text):
    url = f"https://telegram.org{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            log("📱 [Telegram] Mensaje enviado al canal con éxito.")
        else:
            log(f"❌ [Telegram] Error al enviar: {res.status_code}")
    except Exception as e:
        log(f"❌ [Telegram] Error de conexión: {e}")

# Cambiamos el set simple por un diccionario para controlar el tiempo de expiración
PARTIDOS_ENVIADOS = {}

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
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # ---- LIMPIEZA AUTOMÁTICA DE MEMORIA ----
    # Eliminamos partidos guardados cuya hora de inicio ya pasó hace más de 3 horas
    PARTIDOS_ENVIADOS = {pid: exp_time for pid, exp_time in PARTIDOS_ENVIADOS.items() if exp_time > ahora_utc - timedelta(hours=3)}
    
    # ---- VALIDACIÓN INICIAL DE CRÉDITOS ----
    log("📊 [API] Verificando estado de la cuenta y créditos...")
    url_test = f"https://the-odds-api.com{sports[0]}/odds/?apiKey={api_key}&regions=us&markets=h2h"
    try:
        res_test = requests.get(url_test, timeout=10)
        if res_test.status_code == 200:
            restantes = res_test.headers.get("x-requests-remaining")
            usados = res_test.headers.get("x-requests-used")
            if restantes is not None and usados is not None:
                log(f"📊 [CRÉDITOS API] Usados este mes: {usados} | Restantes disponibles: {restantes}")
        else:
            log(f"⚠️ No se pudieron leer las credenciales. Código API: {res_test.status_code}")
    except Exception as e:
        log(f"⚠️ Error de conexión al checar créditos: {e}")

    for sport in sports:
        log(f"🔍 Escaneando mercados múltiples para: {sport}...")
        url = f"https://the-odds-api.com{sport}/odds/?apiKey={api_key}&regions=us,eu&markets=h2h,totals,spreads,spreads_asian"
        
        try:
            res = requests.get(url, timeout=15)
            if res.status_code != 200:
                continue
            
            partidos = res.json()
            
            for partido in partidos:
                partido_id = partido.get("id")
                
                # Si el partido ya fue procesado y enviado, lo saltamos
                if partido_id in PARTIDOS_ENVIADOS:
                    continue
                    
                commence_time_raw = partido.get("commence_time")
                
                try:
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    
                    # ---- FILTRO DE TIEMPO OPTIMIZADO ----
                    # Saltamos si falta menos de 2 minutos para empezar (filtro cohete)
                    if dt_utc <= ahora_utc + timedelta(minutes=2):
                        continue
                    # NUEVO: Saltamos partidos lejanos (más de 36 horas en el futuro) para no bloquearlos antes de tiempo
                    if dt_utc > ahora_utc + timedelta(hours=36):
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
                mercados_data = {"h2h": {}, "totals": {}, "spreads": {}, "spreads_asian": {}}
                
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
                                        
                                elif (m_key == "spreads" or m_key == "spreads_asian") and o_point is not None:
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
                        if len(lista_cuotas) < 3:
                            continue
                            
                        precios = [c[1] for c in lista_cuotas]
                        avg_price = sum(precios) / len(precios)
                        
                        mejor_casino, mejor_precio = max(lista_cuotas, key=lambda x: x[1])
                        ventaja = (mejor_precio / avg_price) - 1
                        
                        if ventaja >= 0.02:
                            if m_key == "h2h" and mejor_precio > 4.00:
                                continue

                            # ---- ASIGNACIÓN DE STAKE CONSERVA_2% ----
                            if ventaja >= 0.07:
                                stake = 8 if mejor_precio < 2.50 else 7
                            elif ventaja >= 0.04:
                                stake = 6 if mejor_precio < 2.20 else 5
                            else:
                                stake = 3 if mejor_precio < 2.00 else 2

                            if m_key == "h2h":
                                tipo_m = "LÍNEA DE DINERO (GANADOR)"
                                arg = "Desajuste directo en las probabilidades de victoria. Este casino se quedó atrás y ofrece una cuota inflada con excelente valor."
                            elif m_key == "totals":
                                tipo_m = "TOTALES (ALTAS/BAJAS)"
                                arg = "La línea de puntos o goles propuesta por este casino está mal balanceada frente al promedio del mercado global."
                            else:
                                tipo_m = "HÁNDICAP (VENTAJA)"
                                arg = "La ventaja otorgada en este hándicap nos da un colchón de seguridad tremendo frente a la línea corregida."

                            # COMPLETADO: Guardamos la estructura del pick y añadimos la fecha UTC para control de expiración
                            todos_los_picks.append({
                                "partido_id": partido_id,
                                "partido": nombre_partido,
                                "mercado": tipo_m,
                                "apuesta": label,
                                "casino": mejor_casino,
                                "cuota": mejor_precio,
                                "ventaja": ventaja,
                                "stake": stake,
                                "fecha": fecha_hora_partido,
                                "dt_utc": dt_utc,
                                "argumento": arg
                            })
        except Exception as e:
            log(f"⚠️ Error al procesar deportes en {sport}: {e}")
            continue

    # ---- PROCESAMIENTO Y ENVÍO DE ALERTAS FINALES ----
    if not todos_los_picks:
        log("📋 Todo en orden en las líneas de los casinos. No hay desajustes de valor.")
    else:
        log(f"🔥 ¡Se encontraron {len(todos_los_picks)} picks con valor!")
        for pick in todos_los_picks:
            # Construcción del mensaje en Markdown para Telegram
            mensaje = (
                f"🚨 *¡ALERTA DE VALOR DETECTADA!* 🚨\n\n"
                f"⚽ *Partido:* {pick['partido']}\n"
                f"📅 *Horario:* {pick['fecha']}\n"
                f"🎯 *Mercado:* {pick['mercado']}\n"
                f"✅ *Selección:* {pick['apuesta']}\n"
                f"💰 *Casino:* {pick['casino']} | *Cuota:* {pick['cuota']}\n"
                f"📊 *Ventaja detectada:* {pick['ventaja']*100:.2f}%\n"
                f"💪 *Stake Recomendado:* {pick['stake']}/10\n\n"
                f"📝 *Análisis:* {pick['argumento']}"
            )
            
            # Envío a Telegram
            send_telegram(bot_token, chat_id, mensaje)
            
            # Añadimos el partido al registro histórico junto con su hora de inicio UTC
            PARTIDOS_ENVIADOS[pick['partido_id']] = pick['dt_utc']
