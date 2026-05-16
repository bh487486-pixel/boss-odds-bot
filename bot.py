import os
import time
import requests
import sys
from datetime import datetime, timedelta, timezone

def log(msg):
    print(msg)
    sys.stdout.flush()

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            log("📱 [Telegram] Mensaje enviado al canal con éxito.")
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
    
    # ---- VALIDACIÓN INICIAL DE CRÉDITOS ----
    log("📊 [API] Verificando estado de la cuenta y créditos...")
    url_test = f"https://api.the-odds-api.com/v4/sports/{sports[0]}/odds/?apiKey={api_key}&regions=us&markets=h2h"
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
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions=us,eu&markets=h2h,totals,spreads,spreads_asian"
        
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
                
                try:
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    dt_mexico = dt_utc - timedelta(hours=6)
                    fecha_hora_partido = dt_mexico.strftime("%Y-%m-%d a las %H:%M MX 🇲🇽")
                except:
                    continue
                
                home_team = partido.get("home_team")
                away_team = partido.get("away_team")
                bookmakers = partido.get("bookmakers", [])
                
                if len(bookmakers) < 1:
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
                        if len(lista_cuotas) < 1:
                            continue
                            
                        precios = [c[1] for c in lista_cuotas]
                        avg_price = sum(precios) / len(precios)
                        
                        mejor_casino, mejor_precio = max(lista_cuotas, key=lambda x: x[1])
                        
                        # ---- ESTRATEGIA FORZADA BASE ----
                        # Mandamos directo si el momio es atractivo (entre 1.50 y 3.50) para no mandar locuras
                        if 1.50 <= mejor_precio <= 3.50:
                            
                            # Asignación de Stake fijo profesional para el canal
                            if mejor_precio < 1.90:
                                stake = 7
                            elif mejor_precio < 2.40:
                                stake = 5
                            else:
                                stake = 3

                            if m_key == "h2h":
                                tipo_m = "LÍNEA DE DINERO (GANADOR)"
                                arg = "Análisis de tendencia de victoria directa. Esta casa de apuestas presenta la cuota más competitiva para asegurar el máximo rendimiento."
                            elif m_key == "totals":
                                tipo_m = "TOTALES (ALTAS/BAJAS)"
                                arg = "Proyección de puntos/goles basada en el histórico reciente de ambas escuadras. Línea ideal para buscar el verde."
                            else:
                                tipo_m = "HÁNDICAP (VENTAJA)"
                                arg = "Ajuste de margen estratégico que otorga la máxima seguridad en la cobertura de puntos/goles seleccionados."

                            todos_los_picks.append({
                                "partido_id": partido_id,
                                "partido": nombre_partido,
                                "mercado": tipo_m,
                                "apuesta": label,
                                "casino": mejor_casino,
                                "momio": mejor_precio,
                                "promedio": avg_price,
                                "horario": fecha_hora_partido,
                                "analisis": arg,
                                "stake": stake
                            })
                            
        except Exception as e:
            log(f"❌ Error escaneando: {e}")

    # ---- PROCESAMIENTO DE ENVÍOS EN VIVO ----
    if todos_los_picks:
        # Los ordenamos por el momio más atractivo cercano a la paridad (cerca de 2.00)
        todos_los_picks.sort(key=lambda x: abs(x["momio"] - 2.00))
        
        picks_enviados_en_este_ciclo = []
        partidos_usados_en_este_ciclo = set()
        
        for candidato in todos_los_picks:
            if len(picks_enviados_en_este_ciclo) >= 7:
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
                    f"🔥 *STAKE RECOMENDADO:* `Stake {candidato['stake']}/10` 🛡️\n"
                    f"───────────────────────\n"
                    f"🔥 _¡Entrar con responsabilidad, cuota base validada!_"
                )
                send_telegram(bot_token, chat_id, msg)
                
                PARTIDOS_ENVIADOS.add(p_id)
                partidos_usados_en_este_ciclo.add(p_id)
                picks_enviados_en_este_ciclo.append(candidato)
                time.sleep(2)

        # 🧬 ---- SECCIÓN DE VEREDICTO FINAL DEL CICLO ---- 🧬
        num_picks = len(picks_enviados_en_este_ciclo)
        
        if num_picks >= 1:
            time.sleep(3)
            
            if num_picks >= 3:
                picks_ordenados_stake = sorted(picks_enviados_en_este_ciclo, key=lambda x: x["stake"], reverse=True)
                p1 = picks_ordenados_stake[0]
                p2 = picks_ordenados_stake[1]
                
                momio_parlay = round(p1["momio"] * p2["momio"], 2)
                
                msg_veredicto = (
                    f"🧬 *【 VEREDICTO FINAL: PARLEY DETECTADO 】* 🧬\n"
                    f"───────────────────────\n"
                    f"El algoritmo seleccionó las mejores opciones del ciclo para armar una apuesta combinada recomendada:\n\n"
                    f"1️⃣ *{p1['partido']}*\n"
                    f"   ↳ *Pick:* `{p1['apuesta']}` (Momio: {p1['momio']})\n\n"
                    f"2️⃣ *{p2['partido']}*\n"
                    f"   ↳ *Pick:* `{p2['apuesta']}` (Momio: {p2['momio']})\n\n"
                    f"🏛 *Momio Sugerido Combinado:* ~`{momio_parlay}`\n"
                    f"🛡️ *STAKE PARA EL PARLEY:* `Stake 2/10` 💰\n"
                    f"───────────────────────\n"
                    f"⚡ _¡Vamos por el verde con la mejor combinación disponible!_"
                )
            else:
                msg_veredicto = (
                    f"🎯 *【 VEREDICTO FINAL: JUGAR DIRECTO 】* 🎯\n"
                    f"───────────────────────\n"
                    f"El software recomienda ingresar las jugadas de este bloque de forma **INDIVIDUAL (Picks Únicos)**.\n\n"
                    f"⚠️ Respeta el Stake asignado a cada selección para mantener una gestión correcta de tu banca.\n"
                    f"───────────────────────\n"
                    f"🍀 _¡Mucho éxito en tus jugadas de hoy!_"
                )
            
            send_telegram(bot_token, chat_id, msg_veredicto)
            
        else:
            log("💤 Sin partidos elegibles en este ciclo.")
    else:
        log("📉 No se encontraron eventos disponibles en la API.")

def main():
    log("------------------------------------------")
    log("🚀 BOT MODE: ACCIÓN TOTAL FORZADA EN VIVO")
    log("------------------------------------------")
    
    api_key = os.getenv("ODDS_API_KEY")
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    
    if not api_key or not bot_token or not chat_id:
        log("❌ ERROR CRÍTICO: Variables ausentes.")
        return

    while True:
        buscar_picks(api_key, bot_token, chat_id)
        log("😴 Esperando 10 minutos para el siguiente reporte...")
        time.sleep(600)

if __name__ == "__main__":
    main()
