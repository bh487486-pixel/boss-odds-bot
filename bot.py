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

PICKS_ENVIADOS_REGISTRO = set()
ULTIMA_FECHA_SALUDO = "" 
CICLOS_VACIOS_CONSECUTIVOS = 0 
AVISO_ESPERA_ENVIADO = False 

def buscar_picks(api_key, bot_token, chat_id):
    global PICKS_ENVIADOS_REGISTRO, ULTIMA_FECHA_SALUDO, CICLOS_VACIOS_CONSECUTIVOS, AVISO_ESPERA_ENVIADO
    
    # 🕒 HORA ACTUAL DEL ESTADO DE MÉXICO (UTC-6)
    dt_mexico_raw = datetime.now(timezone.utc) - timedelta(hours=6)
    dt_mexico = dt_mexico_raw.replace(tzinfo=None)
    
    fecha_hoy_mx = dt_mexico.strftime("%Y-%m-%d")
    hora_hoy_mx = dt_mexico.hour
    
    dt_manana_mx = dt_mexico + timedelta(days=1)
    fecha_manana_mx = dt_manana_mx.strftime("%Y-%m-%d")
    
    # ---- 🌅 BUENOS DÍAS AUTOMÁTICO (8:00 AM) ----
    if hora_hoy_mx >= 8 and ULTIMA_FECHA_SALUDO != fecha_hoy_mx:
        msg_buenos_dias = (
            "☀️ *【 BUENOS DÍAS FAMILIA 】* ☀️\n"
            "───────────────────────\n"
            "¡Ya estamos de pie! Arrancamos con toda la actitud una nueva jornada de picks automatizados. 🚀\n\n"
            "El software ya está procesando las mejores variables y cuotas del mercado. Hoy es un excelente día para meter buena lectura y ¡pintarnos por completo de verde! 💸💚\n\n"
            "🍀 _¡Mucho éxito en tus jugadas de hoy y mantengan las alertas encendidas!_"
        )
        log("🌅 [Bot] Disparando saludo diario automático de buenos días...")
        send_telegram(bot_token, chat_id, msg_buenos_dias)
        ULTIMA_FECHA_SALUDO = fecha_hoy_mx 
        time.sleep(2)

    # TRIDENTE COMPLETO: MLB, LMB y Liga MX
    sports = [
        "baseball_mlb",
        "baseball_mexican_lmb",
        "soccer_mexico_ligamx"
    ]
    
    todos_los_picks = []
    
    # ---- VALIDACIÓN INICIAL DE CRÉDITOS ----
    log("📊 [API] Verificando estado de la cuenta y créditos...")
    url_test = f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/?apiKey={api_key}&regions=us&markets=h2h&oddsFormat=american"
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
        log(f"🔍 Escaneando mercados extendidos para: {sport}...")
        
        if "soccer" in sport:
            mercados_solicitados = "h2h,totals,spreads,btts"
        else:
            mercados_solicitados = "h2h,totals,spreads"
            
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions=us,eu&markets={mercados_solicitados}&oddsFormat=american"
        
        try:
            res = requests.get(url, timeout=15)
            if res.status_code != 200:
                continue
            
            partidos = res.json()
            
            for partido in partidos:
                partido_id = partido.get("id")
                commence_time_raw = partido.get("commence_time")
                
                try:
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    dt_mexico_partido = (dt_utc - timedelta(hours=6)).replace(tzinfo=None)
                    fecha_partido = dt_mexico_partido.strftime("%Y-%m-%d")
                    fecha_hora_partido = dt_mexico_partido.strftime("%Y-%m-%d a las %H:%M MX 🇲🇽")
                except:
                    continue
                
                if fecha_partido != fecha_hoy_mx and fecha_partido != fecha_manana_mx:
                    continue
                
                # 🎯 FILTRO RADAR DE PRIORIDAD: Ignorar en vivo y exigir mínimo 2 minutos futuros
                diferencia_tiempo = (dt_mexico_partido - dt_mexico).total_seconds()
                if diferencia_tiempo < 120:
                    log(f"⏭️ Descartando {partido.get('away_team')} vs {partido.get('home_team')} por estar en vivo o a punto de iniciar.")
                    continue
                
                home_team = partido.get("home_team")
                away_team = partido.get("away_team")
                bookmakers = partido.get("bookmakers", [])
                
                if len(bookmakers) < 1:
                    continue
                
                nombre_partido = f"{away_team} vs {home_team}"
                
                mercados_data = {
                    "h2h": {}, "totals": {}, "spreads": {}, "btts": {}
                }
                
                for bookie in bookmakers:
                    b_title = bookie.get("title")
                    for market in bookie.get("markets", []):
                        m_key = market.get("key")
                        if m_key in mercados_data:
                            for outcome in market.get("outcomes", []):
                                o_name = outcome.get("name")
                                o_price = int(outcome.get("price"))
                                o_point = outcome.get("point", None)
                                
                                label_final = o_name
                                is_baseball = "baseball" in sport
                                
                                # 1. GANADOR
                                if m_key == "h2h":
                                    if o_name.lower() == "draw":
                                        label_final = "Empate"
                                    elif o_name == home_team:
                                        label_final = f"Gana {home_team} (Local)"
                                    elif o_name == away_team:
                                        label_final = f"Gana {away_team} (Visitante)"
                                        
                                # 2. TOTALES
                                elif m_key == "totals":
                                    tipo_unidad = "Carreras" if is_baseball else "Goles"
                                    if o_name.lower() == "over":
                                        label_final = f"Altas (Over) {o_point} {tipo_unidad}"
                                    elif o_name.lower() == "under":
                                        label_final = f"Bajas (Under) {o_point} {tipo_unidad}"
                                        
                                # 3. HÁNDICAP
                                elif m_key == "spreads" and o_point is not None:
                                    tipo_unidad = "Carreras" if is_baseball else "Goles"
                                    try:
                                        num_point = float(o_point)
                                        signo = "+" if num_point > 0 else ""
                                        label_final = f"Hándicap {o_name} ({signo}{o_point} {tipo_unidad})"
                                    except:
                                        label_final = f"Hándicap {o_name} ({o_point})"
                                        
                                # 4. AMBOS ANOTAN
                                elif m_key == "btts":
                                    if o_name.lower() == "yes":
                                        label_final = "Ambos Equipos Anotan: SÍ"
                                    elif o_name.lower() == "no":
                                        label_final = "Ambos Equipos Anotan: NO"
                                
                                if label_final not in mercados_data[m_key]:
                                    mercados_data[m_key][label_final] = []
                                mercados_data[m_key][label_final].append((b_title, o_price))
                
                for m_key, opciones in mercados_data.items():
                    for label, lista_cuotas in opciones.items():
                        if len(lista_cuotas) < 1:
                            continue
                        
                        mejor_casino, mejor_precio = max(lista_cuotas, key=lambda x: x[1])
                        
                        es_valido = False
                        if mejor_precio < 0 and -250 <= mejor_precio <= -100:
                            es_valido = True
                        elif mejor_precio > 0 and 100 <= mejor_precio <= 150:
                            es_valido = True
                            
                        if es_valido:
                            llave_apuesta = f"{partido_id}_{label}"
                            
                            if llave_apuesta in PICKS_ENVIADOS_REGISTRO:
                                continue
                            
                            if mejor_precio < 0:
                                stake = 8 if mejor_precio <= -150 else 6
                            else:
                                stake = 4

                            if m_key == "h2h":
                                tipo_m = "LÍNEA DE DINERO (GANADOR)"
                                arg = "Proyección directa para el encuentro. Esta casa presenta la cuota más competitiva en el mercado de ganador directo."
                            elif m_key == "totals":
                                tipo_m = "TOTALES (ALTAS/BAJAS)"
                                arg = "Análisis matemático del mercado de anotaciones totales. Las condiciones del partido abren una ventana ideal para esta línea regularizada."
                            elif m_key == "spreads":
                                tipo_m = "HÁNDICAP (VENTAJA)"
                                arg = "Ajuste estratégico de hándicap que nos otorga una cobertura de seguridad óptima para las tendencias actuales."
                            elif m_key == "btts":
                                tipo_m = "AMBOS EQUIPOS ANOTAN"
                                arg = "Lectura ofensiva de las plantillas. El historial reciente y las necesidades de ambos clubes perfilan valor en este mercado."

                            momio_texto = f"+{mejor_precio}" if mejor_precio > 0 else str(mejor_precio)

                            if mejor_precio < 0:
                                valor_decimal_interno = round((100 / abs(mejor_precio)) + 1, 2)
                            else:
                                valor_decimal_interno = round((mejor_precio / 100) + 1, 2)

                            todos_los_picks.append({
                                "llave_apuesta": llave_apuesta,
                                "partido_id": partido_id,
                                "partido": nombre_partido,
                                "mercado": tipo_m,
                                "apuesta": label,
                                "casino": mejor_casino,
                                "momio": momio_texto,
                                "momio_dec": valor_decimal_interno,
                                "horario": fecha_hora_partido,
                                "analisis": arg,
                                "stake": stake,
                                "tiempo_restante": diferencia_tiempo
                            })
                            
        except Exception as e:
            log(f"❌ Error escaneando: {e}")

    # ---- PROCESAMIENTO DE ENVÍOS ----
    if todos_los_picks:
        CICLOS_VACIOS_CONSECUTIVOS = 0
        picks_enviados_en_este_ciclo = []
        partidos_usados_en_este_ciclo = set()
        
        # Ordenamos por proximidad de horario
        todos_los_picks = sorted(todos_los_picks, key=lambda x: x["tiempo_restante"])
        
        for candidato in todos_los_picks:
            if len(picks_enviados_en_este_ciclo) >= 7:
                break
            
            p_id = candidato["partido_id"]
            llave = candidato["llave_apuesta"]
            
            if p_id not in partidos_usados_en_este_ciclo:
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
                    f"📈 *Momio de Entrada:* `{candidato['momio']}` 🇺🇸\n"
                    f"🔥 *STAKE RECOMENDADO:* `Stake {candidato['stake']}/10` 🛡️\n"
                    f"───────────────────────\n"
                    f"🔥 _¡Entrar con responsabilidad, cuota base validada!_"
                )
                send_telegram(bot_token, chat_id, msg)
                
                PICKS_ENVIADOS_REGISTRO.add(llave)
                partidos_usados_en_este_ciclo.add(p_id)
                picks_enviados_en_este_ciclo.append(candidato)
                time.sleep(2)

        num_picks = len(picks_enviados_en_este_ciclo)
        if num_picks >= 1:
            time.sleep(3)
            
            parley_armado = False
            
            # 🧬 FILTRO INTELIGENTE PARA DECIDIR VEREDICTO DE PARLEY O DIRECTO
            if num_picks >= 2:
                # Ordenamos por nivel de Stake enviado
                picks_ordenados_confianza = sorted(picks_enviados_en_este_ciclo, key=lambda x: x["stake"], reverse=True)
                p1 = picks_ordenados_confianza[0]
                p2 = picks_ordenados_confianza[1]
                
                momio_combinado_dec = p1["momio_dec"] * p2["momio_dec"]
                
                if momio_combinado_dec >= 2.00:
                    ame_val = int((momio_combinado_dec - 1) * 100)
                    momio_parlay_texto = f"+{ame_val}"
                else:
                    ame_val = int(-100 / (momio_combinado_dec - 1))
                    momio_parlay_texto = str(ame_val)
                
                # SÓLO arma parlay si AMBOS son de alta confianza y el momio no es una locura incomprobable
                if p1["stake"] >= 6 and p2["stake"] >= 6 and (2.00 <= momio_combinado_dec <= 5.00):
                    msg_veredicto = (
                        f"🧬 *【 VEREDICTO SUGERIDO: PARLAY PRESTABLECIDO 】* 🧬\n"
                        f"───────────────────────\n"
                        f"El algoritmo detectó compatibilidad óptima para armar una combinada premium de confianza alta:\n\n"
                        f"1️⃣ *{p1['partido']}*\n"
                        f"   ↳ *Pick:* `{p1['apuesta']}` (Momio: {p1['momio']})\n\n"
                        f"2️⃣ *{p2['partido']}*\n"
                        f"   ↳ *Pick:* `{p2['apuesta']}` (Momio: {p2['momio']})\n\n"
                        f"🏛 *Momio Sugerido Combinado:* ~`{momio_parlay_texto}` 🇺🇸\n"
                        f"🛡️ *STAKE GENERAL:* `Stake 2/10` 💰\n"
                        f"───────────────────────\n"
                        f"💡 *CONSEJO DEL SOFTWARE:* Si deseas mitigar riesgos, recuerda que tienes total libertad de meter estas dos jugadas de forma *INDIVIDUAL (Picks Únicos)* respetando su stake de origen. ¡La última palabra la tienes tú!"
                    )
                    parley_armado = True
            
            # Si no califica para parlay seguro, se va obligatorio a sugerencia Individual
            if not parley_armado:
                msg_veredicto = (
                    f"🎯 *【 VEREDICTO SUGERIDO: JUGAR EN DIRECTO 】* 🎯\n"
                    f"───────────────────────\n"
                    f"El software recomienda ingresar las jugadas enviadas en este bloque de forma **INDIVIDUAL (Picks Únicos)**.\n\n"
                    f"📊 Las variaciones de las cuotas sugieren proteger el capital plano. No se detecta una combinación con la estabilidad necesaria para arriesgar un Parley.\n\n"
                    f"💡 *OPCIÓN DEL SUSCRIPTOR:* Si te agrada el riesgo y decides combinarlas en un boleto por tu cuenta, utiliza un **Stake bajo (1/10 o 2/10)** para cuidar tu banca.\n"
                    f"───────────────────────\n"
                    f"🍀 _¡Mucho éxito en la jornada de hoy!_"
                )
                
            send_telegram(bot_token, chat_id, msg_veredicto)
    else:
        log("📉 No se encontraron eventos activos en este momento.")
        CICLOS_VACIOS_CONSECUTIVOS += 1
        
        if CICLOS_VACIOS_CONSECUTIVOS >= 2 and not AVISO_ESPERA_ENVIADO:
            msg_espera = (
                "🧠 *【 ALERTAS EN VIVO: MENSAJE DE CONTROL 】* 🧠\n"
                "───────────────────────\n"
                "Gente, estamos buscando los picks ideales para ustedes. No se desesperen, que estamos analizando e investigando a fondo los movimientos de las líneas.\n\n"
                "📊 El mercado está muy cerrado en este momento, pero seguimos monitoreando **MLB, LMB y Liga MX**.\n"
                "🛡️ En cuanto se abra el valor, el software lo soltará de golpe. ¡Mantengan notificaciones activas!"
            )
            log("📱 [Telegram] El bot se está tardando en hallar picks. Lanzando aviso de tranquilidad...")
            send_telegram(bot_token, chat_id, msg_espera)
            AVISO_ESPERA_ENVIADO = True

def main():
    log("--------------------------------------------------")
    log("🚀 BOT MODE: CALIBRACIÓN DE VEREDICTOS FLEXIBLES")
    log("--------------------------------------------------")
    
    api_key = os.getenv("ODDS_API_KEY")
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    
    if not api_key or not bot_token or not chat_id:
        log("❌ ERROR CRÍTICO: Variables ausentes.")
        return

    intervalo_objetivo = 600

    while True:
        tiempo_inicio = time.time()
        buscar_picks(api_key, bot_token, chat_id)
        tiempo_transcurrido = time.time() - tiempo_inicio
        tiempo_espera_final = intervalo_objetivo - tiempo_transcurrido
        
        if tiempo_espera_final < 1:
            tiempo_espera_final = 1
            
        log(f"⏱️ Ciclo completado en {round(tiempo_transcurrido, 2)} segundos.")
        log(f"😴 Esperando {round(tiempo_espera_final, 2)} segundos exactos para clavar los 10 minutos...")
        time.sleep(tiempo_espera_final)

if __name__ == "__main__":
    main()
