import os
import time
import requests
import sys
import json
import re
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

DB_FILE = "historial_picks.json"

def cargar_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def guardar_db(data):
    try:
        with open(DB_FILE, "w") as f: json.dump(data, f, indent=4)
    except Exception as e: log(f"❌ Error DB: {e}")

# ---- 🛡️ MEMORIA ANTI-DUPLICADOS RESISTENTE A REINICIOS ----
PICKS_ENVIADOS_REGISTRO = set()
ULTIMA_FECHA_SALUDO = "" 
ULTIMA_FECHA_REPORTE = ""
CICLOS_VACIOS_CONSECUTIVOS = 0 
AVISO_ESPERA_ENVIADO = False 

def inicializar_registro_desde_db():
    global PICKS_ENVIADOS_REGISTRO
    db = cargar_db()
    for llave in db.keys():
        PICKS_ENVIADOS_REGISTRO.add(llave)
    log(f"📦 [Memoria] Historial sincronizado. {len(PICKS_ENVIADOS_REGISTRO)} picks cargados para evitar spam por reinicio.")

# ---- 🧠 CEREBRO EVALUADOR AUTOMÁTICO DE MARCADORES ----
def evaluar_resultado(mercado, apuesta, home_team, away_team, home_score, away_score):
    try:
        hs = int(home_score)
        as_val = int(away_score)
    except:
        return "PENDIENTE"
        
    total_puntos = hs + as_val
    
    if mercado == "LÍNEA DE DINERO (GANADOR)":
        if "Gana" in apuesta:
            if home_team in apuesta and hs > as_val: return "GANADO"
            if away_team in apuesta and as_val > hs: return "GANADO"
            return "PERDIDO"
        if "Empate" in apuesta and hs == as_val: return "GANADO"
        return "PERDIDO"
        
    elif "TOTALES" in mercado:
        try:
            partes = apuesta.split()
            nodo_numero = [float(p) for p in partes if p.replace('.','',1).isdigit()][0]
            if "Altas" in apuesta or "Over" in apuesta:
                return "GANADO" if total_puntos > nodo_numero else "PERDIDO"
            if "Bajas" in apuesta or "Under" in apuesta:
                return "GANADO" if total_puntos < nodo_numero else "PERDIDO"
        except: pass

    elif "AMBOS EQUIPOS" in mercado:
        anotan_ambos = (hs > 0 and as_val > 0)
        if "SÍ" in apuesta and anotan_ambos: return "GANADO"
        if "NO" in apuesta and not anotan_ambos: return "GANADO"
        return "PERDIDO"
        
    elif "HÁNDICAP" in mercado:
        try:
            match = re.search(r'\(([-+]\d+\.?\d*)\)', apuesta)
            if match:
                handicap_val = float(match.group(1))
                if home_team in apuesta:
                    return "GANADO" if (hs + handicap_val) > as_val else "PERDIDO"
                if away_team in apuesta:
                    return "GANADO" if (as_val + handicap_val) > hs else "PERDIDO"
        except: pass

    return "PENDIENTE"

# ---- 🔄 REVISOR AUTOMÁTICO DE MARCADORES (API SCORES) ----
def verificar_marcadores_api(api_key):
    db = cargar_db()
    sports = ["baseball_mlb", "baseball_mexican_lmb", "soccer_mexico_ligamx", "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga"]
    cambio = False
    
    for sport in sports:
        url_scores = f"https://api.the-odds-api.com/v4/sports/{sport}/scores/?apiKey={api_key}&daysFrom=1"
        try:
            res = requests.get(url_scores, timeout=10)
            if res.status_code != 200: continue
            partidos_terminados = res.json()
            
            for partido in partidos_terminados:
                if partido.get("completed") is True:
                    p_id = partido.get("id")
                    home_team = partido.get("home_team")
                    away_team = partido.get("away_team")
                    scores = partido.get("scores")
                    if not scores or len(scores) < 2: continue
                    
                    h_score = next((s["score"] for s in scores if s["name"] == home_team), None)
                    a_score = next((s["score"] for s in scores if s["name"] == away_team), None)
                    if h_score is None or a_score is None: continue
                    
                    for llave, v in db.items():
                        if v.get("partido_id") == p_id and v.get("estado") == "PENDIENTE":
                            nuevo_estado = evaluar_resultado(v["mercado"], v["apuesta"], home_team, away_team, h_score, a_score)
                            if nuevo_estado != "PENDIENTE":
                                db[llave]["estado"] = nuevo_estado
                                db[llave]["marcador"] = f"{a_score}-{h_score}"
                                cambio = True
        except: pass
            
    if cambio:
        guardar_db(db)

def buscar_picks(api_key, bot_token, chat_id):
    global PICKS_ENVIADOS_REGISTRO, ULTIMA_FECHA_SALUDO, ULTIMA_FECHA_REPORTE, CICLOS_VACIOS_CONSECUTIVOS, AVISO_ESPERA_ENVIADO
    
    dt_mexico_raw = datetime.now(timezone.utc) - timedelta(hours=6)
    dt_mexico = dt_mexico_raw.replace(tzinfo=None)
    fecha_hoy_mx = dt_mexico.strftime("%Y-%m-%d")
    hora_hoy_mx = dt_mexico.hour
    fecha_manana_mx = (dt_mexico + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # ---- 🌅 BUENOS DÍAS AUTOMÁTICO (8:00 AM) ----
    if hora_hoy_mx >= 8 and ULTIMA_FECHA_SALUDO != fecha_hoy_mx:
        msg_buenos_dias = (
            "☀️ *【 BUENOS DÍAS FAMILIA 】* ☀️\n"
            "───────────────────────\n"
            "¡Ya estamos de pie! Arrancamos con toda la actitud una nueva jornada de picks automatizados. 🚀\n\n"
            "El software ya está procesando pre-partidos y monitoreando las alertas en vivo. 💸💚"
        )
        send_telegram(bot_token, chat_id, msg_buenos_dias)
        ULTIMA_FECHA_SALUDO = fecha_hoy_mx 
        time.sleep(2)

    # ---- 📊 ENVÍO AUTOMÁTICO DE RECAP DIARIO (11:00 PM) ----
    if hora_hoy_mx >= 23 and ULTIMA_FECHA_REPORTE != fecha_hoy_mx:
        db = cargar_db()
        if db:
            ganados, perdidos, unidades_netas, total_hoy = 0, 0, 0.0, 0
            texto_reporte = f"📊 *【 RECAP Y PROFIT DIARIO ({fecha_hoy_mx}) 】* 📊\n───────────────────────\n"
            for k, v in db.items():
                if v.get("fecha_registro") == fecha_hoy_mx:
                    total_hoy += 1
                    est = v.get("estado", "PENDIENTE")
                    icon = "⏳"
                    if est == "GANADO":
                        icon = "🟢"; ganados += 1
                        unidades_netas += v["stake"] * (v["momio_dec"] - 1)
                    elif est == "PERDIDO":
                        icon = "🔴"; perdidos += 1
                        unidades_netas -= v["stake"]
                    marcador_txt = f" [{v['marcador']}]" if "marcador" in v else ""
                    texto_reporte += f"{icon} *{v['partido']}*{marcador_txt}\n   ↳ `{v['apuesta']}` | Cuota: {v['momio_txt']} | (Stake {v['stake']})\n\n"
            
            if total_hoy > 0:
                signo = "+" if unidades_netas >= 0 else ""
                texto_reporte += f"───────────────────────\n📈 *Picks Auditados:* `{total_hoy}`\n🟢 *G:* `{ganados}` | 🔴 *P:* `{perdidos}`\n💰 *PROFIT NETO:* `{signo}{round(unidades_netas, 2)} Unidades` 🔥"
                send_telegram(bot_token, chat_id, texto_reporte)
                ULTIMA_FECHA_REPORTE = fecha_hoy_mx
                time.sleep(2)

    # 📋 CARTELERA PROFESIONAL EXCLUSIVA
    sports = [
        "baseball_mlb", 
        "baseball_mexican_lmb", 
        "soccer_mexico_ligamx",
        "soccer_epl",            
        "soccer_spain_la_liga",  
        "soccer_germany_bundesliga"
    ]
    todos_los_picks = []
    
    for sport in sports:
        # 📝 LOGS DE MONITOREO SOLICITADOS EN RENDER:
        if "mlb" in sport: log("🔍 [Radar] Analizando partidos de las Grandes Ligas (MLB)...")
        elif "mexican_lmb" in sport: log("🔍 [Radar] Analizando cartelera de la Liga Mexicana de Béisbol (LMB)...")
        elif "ligamx" in sport: log("🔍 [Radar] Analizando jornada activa de la Liga MX...")
        elif "soccer_" in sport: log(f"🔍 [Radar] Analizando cuotas en vivo de Fútbol Europeo ({sport})...")

        mercados_solicitados = "h2h,totals,spreads,btts" if "soccer" in sport else "h2h,totals,spreads"
        
        # 1. Monitorear estados reales
        diccionario_periodos = {}
        url_scores = f"https://api.the-odds-api.com/v4/sports/{sport}/scores/?apiKey={api_key}&daysFrom=1"
        try:
            res_sc = requests.get(url_scores, timeout=10)
            if res_sc.status_code == 200:
                for p_sc in res_sc.json():
                    p_id = p_sc.get("id")
                    scores_lista = p_sc.get("scores", [])
                    completado = p_sc.get("completed", False)
                    ignorar_por_terminar = False
                    txt_marcador = "0-0"
                    
                    if scores_lista and len(scores_lista) >= 2:
                        txt_marcador = f"{scores_lista[1].get('score')}-{scores_lista[0].get('score')}"
                        if completado: ignorar_por_terminar = True
                            
                    diccionario_periodos[p_id] = {"ignorar": ignorar_por_terminar, "marcador": txt_marcador}
        except: pass

        # 2. Escaneo y Filtrado de Momios Profesional
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions=us,eu&markets={mercados_solicitados}&oddsFormat=american"
        try:
            res = requests.get(url, timeout=15)
            
            # 💳 IMPRESIÓN DE CRÉDITOS EN RENDER
            remanente = res.headers.get("x-requests-remaining")
            usados = res.headers.get("x-requests-used")
            if remanente:
                log(f"💳 [Créditos API] Restantes: {remanente} | Mensuales Usados: {usados}")
                
            if res.status_code != 200: continue
            partidos = res.json()
            
            for partido in partidos:
                partido_id = partido.get("id")
                if partido_id in diccionario_periodos and diccionario_periodos[partido_id]["ignorar"]: continue
                    
                commence_time_raw = partido.get("commence_time")
                try:
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    dt_mexico_partido = (dt_utc - timedelta(hours=6)).replace(tzinfo=None)
                    fecha_partido = dt_mexico_partido.strftime("%Y-%m-%d")
                    fecha_hora_partido = dt_mexico_partido.strftime("%Y-%m-%d a las %H:%M MX 🇲🇽")
                except: continue
                
                if fecha_partido != fecha_hoy_mx and fecha_partido != fecha_manana_mx: continue
                
                diferencia_tiempo = (dt_mexico_partido - dt_mexico).total_seconds()
                es_en_vivo = diferencia_tiempo <= 0
                
                # 🛑 CANDADO DE SEGURIDAD MÁXIMA: Más de 4 horas de haber iniciado se descarta por completo.
                if es_en_vivo and diferencia_tiempo < -14400: continue
                
                home_team = partido.get("home_team")
                away_team = partido.get("away_team")
                bookmakers = partido.get("bookmakers", [])
                if len(bookmakers) < 1: continue
                
                nombre_partido = f"{away_team} vs {home_team}"
                mercados_data = {"h2h": {}, "totals": {}, "spreads": {}, "btts": {}}
                
                for bookie in bookmakers:
                    for market in bookie.get("markets", []):
                        m_key = market.get("key")
                        if m_key in mercados_data:
                            for outcome in market.get("outcomes", []):
                                o_name = outcome.get("name")
                                o_price = int(outcome.get("price"))
                                o_point = outcome.get("point", None)
                                label_final = o_name
                                is_baseball = "baseball" in sport
                                
                                if m_key == "h2h":
                                    if o_name.lower() == "draw": label_final = "Empate"
                                    elif o_name == home_team: label_final = f"Gana {home_team} (Local)"
                                    elif o_name == away_team: label_final = f"Gana {away_team} (Visitante)"
                                elif m_key == "totals":
                                    tipo_unidad = "Carreras" if is_baseball else "Goles"
                                    if o_name.lower() == "over": label_final = f"Altas (Over) {o_point} {tipo_unidad}"
                                    elif o_name.lower() == "under": label_final = f"Bajas (Under) {o_point} {tipo_unidad}"
                                elif m_key == "spreads" and o_point is not None:
                                    tipo_unidad = "Carreras" if is_baseball else "Goles"
                                    try:
                                        num_point = float(o_point)
                                        signo = "+" if num_point > 0 else ""
                                        label_final = f"Hándicap {o_name} ({signo}{o_point} {tipo_unidad})"
                                    except: label_final = f"Hándicap {o_name} ({o_point})"
                                elif m_key == "btts":
                                    if o_name.lower() == "yes": label_final = "Ambos Equipos Anotan: SÍ"
                                    elif o_name.lower() == "no": label_final = "Ambos Equipos Anotan: NO"
                                
                                if label_final not in mercados_data[m_key]: mercados_data[m_key][label_final] = []
                                mercados_data[m_key][label_final].append((bookie.get("title"), o_price))
                
                for m_key, opciones in mercados_data.items():
                    for label, lista_cuotas in opciones.items():
                        if len(lista_cuotas) < 1: continue
                        mejor_casino, mejor_precio = max(lista_cuotas, key=lambda x: x[1])
                        
                        if es_en_vivo:
                            es_valido = (mejor_precio < 0 and -300 <= mejor_precio <= -100) or (mejor_precio > 0 and 100 <= mejor_precio <= 500)
                        else:
                            es_valido = (mejor_precio < 0 and -250 <= mejor_precio <= -100) or (mejor_precio > 0 and 100 <= mejor_precio <= 250)
                            
                        if es_valido:
                            llave_apuesta = f"{partido_id}_{label}_LIVE" if es_en_vivo else f"{partido_id}_{label}_PRE"
                            if llave_apuesta in PICKS_ENVIADOS_REGISTRO: continue
                            
                            # 🛡️ GESTIÓN DE STAKE INTELIGENTE (1-10)
                            stake = 8 if (mejor_precio < 0 and mejor_precio <= -150) else (6 if mejor_precio < 0 else 4)
                            
                            if m_key == "h2h": tipo_m = "LÍNEA DE DINERO (GANADOR)"
                            elif m_key == "totals": tipo_m = "TOTALES (ALTAS/BAJAS)"
                            elif m_key == "spreads": tipo_m = "HÁNDICAP (VENTAJA)"
                            elif m_key == "btts": tipo_m = "AMBOS EQUIPOS ANOTAN"

                            momio_texto = f"+{mejor_precio}" if mejor_precio > 0 else str(mejor_precio)
                            valor_decimal_interno = round((100 / abs(mejor_precio)) + 1, 2) if mejor_precio < 0 else round((mejor_precio / 100) + 1, 2)
                            marcador_actual_str = diccionario_periodos.get(partido_id, {}).get("marcador", "0-0")

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
                                "stake": stake,
                                "es_en_vivo": es_en_vivo,
                                "marcador_live": marcador_actual_str,
                                "tiempo_restante": diferencia_tiempo
                            })
        except: continue

    if todos_los_picks:
        CICLOS_VACIOS_CONSECUTIVOS = 0
        picks_enviados_en_este_ciclo = []
        partidos_usados_en_este_ciclo = set()
        db = cargar_db()
        
        todos_los_picks = sorted(todos_los_picks, key=lambda x: (not x["es_en_vivo"], x["tiempo_restante"]))
        
        # Filtro estricto contra-apuestas
        picks_filtrados_unicos = []
        partidos_ya_agregados_pre_envio = set()
        for p in todos_los_picks:
            if p["partido_id"] not in partidos_ya_agregados_pre_envio:
                picks_filtrados_unicos.append(p)
                partidos_ya_agregados_pre_envio.add(p["partido_id"])
        
        # 🎯 CONTROL DE FLUJO ESTRICTO: MAX 4 PICKS POR VUELTA
        for candidato in picks_filtrados_unicos:
            if len(picks_enviados_en_este_ciclo) >= 4: break 
            
            p_id = candidato["partido_id"]
            llave = candidato["llave_apuesta"]
            
            if llave not in PICKS_ENVIADOS_REGISTRO and p_id not in partidos_usados_en_este_ciclo:
                titulo_bloque = "🔥 *【 EN VIVO: JOYAS DEL RADAR 】* 🔥" if candidato["es_en_vivo"] else "🧠 *【 ANÁLISIS PROFESIONAL VIP 】* 🧠"
                linea_marcador = f"📊 *Marcador Actual:* `{candidato['marcador_live']}`\n" if candidato["es_en_vivo"] else ""
                
                msg = (
                    f"{titulo_bloque}\n"
                    f"───────────────────────\n"
                    f"📅 *Evento:* {candidato['horario']}\n"
                    f"⚔️ *Encuentro:* {candidato['partido']}\n"
                    f"{linea_marcador}"
                    f"📊 *Mercado:* `{candidato['mercado']}`\n\n"
                    f"🎯 *PICK RECOMENDADO:* `{candidato['apuesta']}`\n"
                    f"🏛 *Casa de Apuestas:* {candidato['casino']}\n"
                    f"📈 *Momio de Entrada:* `{candidato['momio']}` 🇺🇸\n"
                    f"🔥 *STAKE RECOMENDADO:* `Stake {candidato['stake']}/10` 🛡️\n"
                    f"───────────────────────\n"
                    f"🔥 _¡Entrar con responsabilidad, cuota validada en tiempo real!_"
                )
                send_telegram(bot_token, chat_id, msg)
                
                db[llave] = {
                    "partido_id": p_id,
                    "partido": candidato['partido'],
                    "mercado": candidato['mercado'],
                    "apuesta": candidato['apuesta'],
                    "momio_dec": candidato['momio_dec'],
                    "momio_txt": candidato['momio'],
                    "stake": candidato['stake'],
                    "fecha_registro": fecha_hoy_mx,
                    "estado": "PENDIENTE"
                }
                
                PICKS_ENVIADOS_REGISTRO.add(llave)
                partidos_usados_en_este_ciclo.add(p_id)
                picks_enviados_en_este_ciclo.append(candidato)
                time.sleep(2)

        guardar_db(db)

        num_picks = len(picks_enviados_en_este_ciclo)
        if num_picks >= 1:
            time.sleep(3)
            parley_armado = False
            
            if num_picks >= 2:
                picks_ordenados_confianza = sorted(picks_enviados_en_este_ciclo, key=lambda x: x["stake"], reverse=True)
                p1 = picks_ordenados_confianza[0]
                p2 = picks_ordenados_confianza[1]
                momio_combinado_dec = p1["momio_dec"] * p2["momio_dec"]
                momio_parlay_texto = f"+{int((momio_combinado_dec - 1) * 100)}" if momio_combinado_dec >= 2.00 else str(int(-100 / (momio_combinado_dec - 1)))
                
                if p1["stake"] >= 6 and p2["stake"] >= 6 and (2.00 <= momio_combinado_dec <= 5.00):
                    msg_veredicto = (
                        f"🧬 *【 VEREDICTO SUGERIDO: PARLEY MIXTO 】* 🧬\n"
                        f"───────────────────────\n"
                        f"El algoritmo armó compatibilidad cruzando oportunidades de alto valor:\n\n"
                        f"1️⃣ *{p1['partido']}*\n   ↳ *Pick:* `{p1['apuesta']}`\n\n"
                        f"2️⃣ *{p2['partido']}*\n   ↳ *Pick:* `{p2['apuesta']}`\n\n"
                        f"🏛 *Momio Combinado:* ~`{momio_parlay_texto}` 🇺🇸\n"
                        f"🛡️ *STAKE GENERAL:* `Stake 2/10` 💰"
                    )
                    send_telegram(bot_token, chat_id, msg_veredicto)
                    parley_armado = True
            
            if not parley_armado:
                msg_veredicto = (
                    f"🎯 *【 VEREDICTO SUGERIDO: JUGAR EN DIRECTO 】* 🎯\n"
                    f"───────────────────────\n"
                    f"El software recomienda ingresar las jugadas enviadas de forma **INDIVIDUAL (Picks Únicos)**.\n"
                    f"───────────────────────\n"
                    f"🍀 _¡Mucho éxito en la jornada!_"
                )
                send_telegram(bot_token, chat_id, msg_veredicto)
    else:
        CICLOS_VACIOS_CONSECUTIVOS += 1
        if CICLOS_VACIOS_CONSECUTIVOS >= 2 and not AVISO_ESPERA_ENVIADO:
            msg_espera = (
                "🧠 *【 ALERTAS EN VIVO: MENSAJE DE CONTROL 】* 🧠\n"
                "───────────────────────\n"
                "Monitoreando la cartelera activa y partidos en vivo...\n"
                "📊 Filtros aplicados para descartar cierres de juego."
            )
            send_telegram(bot_token, chat_id, msg_espera)
            AVISO_ESPERA_ENVIADO = True

def main():
    log("--------------------------------------------------")
    log("🚀 BOT MODE: PRODUCCIÓN PROFESIONAL VIP ACTIVO")
    log("--------------------------------------------------")
    
    api_key = os.getenv("ODDS_API_KEY")
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    
    if not api_key or not bot_token or not chat_id:
        log("❌ ERROR CRÍTICO: Falta configurar variables de entorno.")
        return

    # Sincronizar memoria con base de datos JSON
    inicializar_registro_desde_db()

    while True:
        log("\n🔄 ================= INICIO DE CICLO ================= 🔄")
        verificar_marcadores_api(api_key)
        buscar_picks(api_key, bot_token, chat_id)
        log("😴 Escaneo finalizado con éxito. Durmiendo por 10 minutos...")
        log("🔄 ================== FIN DE CICLO ================== 🔄\n")
        time.sleep(600)

if __name__ == "__main__":
    main()
