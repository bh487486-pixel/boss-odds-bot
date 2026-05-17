import os
import sys
import time
import json
import re
from datetime import datetime, timedelta, timezone
import requests

class Logger:
    @staticmethod
    def log(message: str):
        print(message)
        sys.stdout.flush()

class DatabaseManager:
    def __init__(self, db_file="historial_picks.json"):
        self.db_file = db_file
        self.data = self._load_database()

    def _load_database(self):
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                Logger.log(f"⚠️ Alerta base de datos vacía o corrupta. Reindexando: {e}")
                return {}
        return {}

    def save(self):
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            Logger.log(f"❌ Error crítico de escritura en almacenamiento Local: {e}")

    def get_picks_by_date(self, date_str: str) -> list:
        return [v for k, v in self.data.items() if not k.startswith("SYSTEM_") and v.get("fecha_registro") == date_str]

    def record_item(self, key: str, value: dict):
        self.data[key] = value
        self.save()

    def has_key(self, key: str) -> bool:
        return key in self.data

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.session = requests.Session()
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def send_message(self, text: str) -> bool:
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        try:
            res = self.session.post(self.url, json=payload, timeout=10)
            if res.status_code == 200:
                Logger.log("📱 [Telegram] Mensaje transmitido al canal con éxito.")
                return True
            Logger.log(f"❌ [Telegram] Error de respuesta de API ({res.status_code}): {res.text}")
        except Exception as e:
            Logger.log(f"❌ [Telegram] Falla de conexión HTTP: {e}")
        return False

class OddsApiClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.base_url = "https://api.the-odds-api.com/v4/sports"

    def fetch_scores(self, sport: str) -> list:
        url = f"{self.base_url}/{sport}/scores/?apiKey={self.api_key}&daysFrom=1"
        try:
            res = self.session.get(url, timeout=10)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            Logger.log(f"❌ [API Scores] Error al consultar marcadores para {sport}: {e}")
        return []

    def fetch_odds(self, sport: str, markets: str) -> list:
        url = f"{self.base_url}/{sport}/odds/?apiKey={self.api_key}&regions=us,eu&markets={markets}&oddsFormat=american"
        try:
            res = self.session.get(url, timeout=15)
            remaining = res.headers.get("x-requests-remaining")
            if remaining:
                Logger.log(f"💳 [API Cuotas] Créditos Disponibles: {remaining}")
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            Logger.log(f"❌ [API Odds] Error al extraer cuotas activas para {sport}: {e}")
        return []

class OutcomeEvaluator:
    @staticmethod
    def evaluar(mercado: str, apuesta: str, home_team: str, away_team: str, home_score: int, away_score: int) -> str:
        total_puntos = home_score + away_score
        
        if mercado == "LÍNEA DE DINERO (GANADOR)":
            if "Gana" in apuesta:
                if home_team in apuesta and home_score > away_score: return "GANADO"
                if away_team in apuesta and away_score > home_score: return "GANADO"
                return "PERDIDO"
            if "Empate" in apuesta and home_score == away_score: return "GANADO"
            return "PERDIDO"
            
        elif "TOTALES" in mercado:
            try:
                partes = apuesta.split()
                linea_float = [float(p) for p in partes if p.replace('.', '', 1).isdigit()][0]
                if "Altas" in apuesta or "Over" in apuesta:
                    return "GANADO" if total_puntos > linea_float else "PERDIDO"
                if "Bajas" in apuesta or "Under" in apuesta:
                    return "GANADO" if total_puntos < linea_float else "PERDIDO"
            except: pass

        elif "AMBOS EQUIPOS" in mercado:
            anotaron_ambos = (home_score > 0 and away_score > 0)
            if "SÍ" in apuesta and anotaron_ambos: return "GANADO"
            if "NO" in apuesta and not anotaron_ambos: return "GANADO"
            return "PERDIDO"

        elif "HÁNDICAP" in mercado:
            try:
                match = re.search(r'\(([-+]\d+\.?\d*)\)', apuesta)
                if match:
                    handicap_val = float(match.group(1))
                    if home_team in apuesta:
                        return "GANADO" if (home_score + handicap_val) > away_score else "PERDIDO"
                    if away_team in apuesta:
                        return "GANADO" if (away_score + handicap_val) > home_score else "PERDIDO"
            except: pass

        return "PENDIENTE"

class SniperTipsterBot:
    def __init__(self):
        api_key = os.getenv("ODDS_API_KEY")
        bot_token = os.getenv("BOT_TOKEN")
        chat_id = os.getenv("CHAT_ID")
        
        if not api_key or not bot_token or not chat_id:
            Logger.log("❌ ERROR CRÍTICO DE ENTORNO: Faltan variables de configuración de servidor.")
            sys.exit(1)

        self.db = DatabaseManager()
        self.telegram = TelegramNotifier(bot_token, chat_id)
        self.api = OddsApiClient(api_key)
        
        # 🎯 NUEVO RADAR CONFIGURADO: MLB, LIGA MX Y FÚTBOL EUROPEO
        self.sports = [
            "baseball_mlb", 
            "soccer_mexico_ligamx",
            "soccer_epl",            
            "soccer_spain_la_liga",  
            "soccer_germany_bundesliga"
        ]
        
        self.ciclos_vacios = 0
        self.aviso_espera_enviado = False

    def _obtener_fecha_hora_mexico(self):
        return datetime.now(timezone.utc) - timedelta(hours=6)

    def ejecutar_auditoria(self):
        Logger.log("📊 [Auditoría] Sincronizando marcadores deportivos en vivo...")
        cambio = False
        for sport in self.sports:
            partidos_finalizados = self.api.fetch_scores(sport)
            for partido in partidos_finalizados:
                if partido.get("completed") is True:
                    p_id = partido.get("id")
                    home = partido.get("home_team")
                    away = partido.get("away_team")
                    scores = partido.get("scores")
                    
                    if not scores or len(scores) < 2: continue
                    try:
                        h_score = int(next((s["score"] for s in scores if s["name"] == home), None))
                        a_score = int(next((s["score"] for s in scores if s["name"] == away), None))
                    except: continue
                    
                    for llave, v in self.db.data.items():
                        if not llave.startswith("SYSTEM_") and v.get("partido_id") == p_id and v.get("estado") == "PENDIENTE":
                            nuevo_estado = OutcomeEvaluator.evaluar(v["mercado"], v["apuesta"], home, away, h_score, a_score)
                            if nuevo_estado != "PENDIENTE":
                                self.db.data[llave]["estado"] = nuevo_estado
                                self.db.data[llave]["marcador"] = f"{a_score}-{h_score}"
                                cambio = True
        if cambio:
            self.db.save()

    def escanear_cartelera(self, fecha_hoy: str, fecha_manana: str, hora_hoy: int, total_enviados_hoy: int) -> list:
        picks_encontrados = []
        
        picks_hoy_db = self.db.get_picks_by_date(fecha_hoy)
        partidos_apostados_hoy = [p.get("partido_id") for p in picks_hoy_db]
        
        for sport in self.sports:
            # Identificar la liga para el mensaje en los logs
            tag_liga = "MLB 🇺🇸" if "mlb" in sport else "Liga MX 🇲🇽" if "ligamx" in sport else "Fútbol Europeo ⚽"
            Logger.log(f"🔍 [Escáner] Evaluando cuotas estricto en {tag_liga}")
            
            mercados = "h2h,totals,spreads,btts" if "soccer" in sport else "h2h,totals,spreads"
            
            live_status = {}
            scores_raw = self.api.fetch_scores(sport)
            for sc in scores_raw:
                marcador_str = "0-0"
                if sc.get("scores") and len(sc.get("scores")) >= 2:
                    try:
                        marcador_str = f"{sc['scores'][1].get('score', 0)}-{sc['scores'][0].get('score', 0)}"
                    except:
                        pass
                
                live_status[sc.get("id")] = {
                    "completado": sc.get("completed", False),
                    "marcador": marcador_str
                }

            partidos = self.api.fetch_odds(sport, markets=mercados)
            for partido in partidos:
                p_id = partido.get("id")
                
                # Candado Anti-Duplicados por Partido
                if p_id in partidos_apostados_hoy: continue
                if p_id in live_status and live_status[p_id]["completado"]: continue

                try:
                    dt_mex_partido = (datetime.strptime(partido.get("commence_time"), "%Y-%m-%dT%H:%M:%SZ") - timedelta(hours=6)).replace(tzinfo=None)
                    f_partido = dt_mex_partido.strftime("%Y-%m-%d")
                    h_partido_txt = dt_mex_partido.strftime("%Y-%m-%d a las %H:%M MX 🇲🇽")
                except: continue

                if f_partido != fecha_hoy and f_partido != fecha_manana: continue

                diff_segundos = (dt_mex_partido - self._obtener_fecha_hora_mexico().replace(tzinfo=None)).total_seconds()
                es_live = diff_segundos <= 0

                if es_live and diff_segundos < -14400: continue

                home = partido.get("home_team")
                away = partido.get("away_team")
                bookmakers = partido.get("bookmakers", [])
                if not bookmakers: continue

                nombre_encuentro = f"{away} vs {home}"
                mercados_organizados = {"h2h": {}, "totals": {}, "spreads": {}, "btts": {}}

                for bookie in bookmakers:
                    for market in bookie.get("markets", []):
                        m_key = market.get("key")
                        if m_key in mercados_organizados:
                            for outcome in market.get("outcomes", []):
                                o_name = outcome.get("name")
                                price = int(outcome.get("price"))
                                point = outcome.get("point", None)
                                label = o_name
                                is_base = "baseball" in sport

                                if m_key == "h2h":
                                    if o_name.lower() == "draw": label = "Empate"
                                    elif o_name == home: label = f"Gana {home} (Local)"
                                    elif o_name == away: label = f"Gana {away} (Visitante)"
                                elif m_key == "totals":
                                    unidad = "Carreras" if is_base else "Goles"
                                    label = f"Altas (Over) {point} {unidad}" if o_name.lower() == "over" else f"Bajas (Under) {point} {unidad}"
                                elif m_key == "spreads" and point is not None:
                                    unidad = "Carreras" if is_base else "Goles"
                                    signo = "+" if float(point) > 0 else ""
                                    label = f"Hándicap {o_name} ({signo}{point} {unidad})"
                                elif m_key == "btts":
                                    label = "Ambos Equipos Anotan: SÍ" if o_name.lower() == "yes" else "Ambos Equipos Anotan: NO"

                                if label not in mercados_organizados[m_key]: mercados_organizados[m_key][label] = []
                                mercados_organizados[m_key][label].append((bookie.get("title"), price))

                mejor_opcion_partido = None
                
                for m_key, opciones in mercados_organizados.items():
                    for label, lista_cuotas in opciones.items():
                        if not lista_cuotas: continue
                        casino_top, precio_top = max(lista_cuotas, key=lambda x: x[1])

                        if hora_hoy >= 16 and total_enviados_hoy < 2:
                            valido = (precio_top < 0 and -350 <= precio_top <= -100) or (precio_top > 0 and 100 <= precio_top <= 450)
                        else:
                            valido = (precio_top < 0 and -250 <= precio_top <= -100) or (precio_top > 0 and 100 <= precio_top <= 250)

                        if valido:
                            llave_apuesta = f"{p_id}_{label}_LIVE" if es_live else f"{p_id}_{label}_PRE"
                            if self.db.has_key(llave_apuesta): continue

                            stake = 8 if (precio_top < 0 and precio_top <= -150) else (6 if precio_top < 0 else 4)
                            
                            if m_key == "h2h": tipo_m = "LÍNEA DE DINERO (GANADOR)"
                            elif m_key == "totals": tipo_m = "TOTALES (ALTAS/BAJAS)"
                            elif m_key == "spreads": tipo_m = "HÁNDICAP (VENTAJA)"
                            elif m_key == "btts": tipo_m = "AMBOS EQUIPOS ANOTAN"

                            momio_str = f"+{precio_top}" if precio_top > 0 else str(precio_top)
                            dec_val = round((100 / abs(precio_top)) + 1, 2) if precio_top < 0 else round((precio_top / 100) + 1, 2)
                            marcador_actual = live_status.get(p_id, {}).get("marcador", "0-0")

                            opcion = {
                                "llave": llave_apuesta,
                                "partido_id": p_id,
                                "partido": nombre_encuentro,
                                "mercado": tipo_m,
                                "apuesta": label,
                                "casino": casino_top,
                                "momio": momio_str,
                                "momio_dec": dec_val,
                                "horario": h_partido_txt,
                                "stake": stake,
                                "es_live": es_live,
                                "marcador_live": marcador_actual,
                                "diff": diff_segundos,
                                "tag_liga": tag_liga
                            }
                            
                            if not mejor_opcion_partido or dec_val > mejor_opcion_partido["momio_dec"]:
                                mejor_opcion_partido = opcion
                
                if mejor_opcion_partido:
                    picks_encontrados.append(mejor_opcion_partido)
                    
        return picks_encontrados

    def ejecutar_ciclo(self):
        dt_mex = self._obtener_fecha_hora_mexico().replace(tzinfo=None)
        fecha_hoy = dt_mex.strftime("%Y-%m-%d")
        fecha_manana = (dt_mex + timedelta(days=1)).strftime("%Y-%m-%d")
        hora_hoy = dt_mex.hour

        Logger.log(f"\n🔄 ================= INICIO DE CICLO OOP ({dt_mex.strftime('%H:%M:%S')}) ================= 🔄")
        
        self.ejecutar_auditoria()

        llave_saludo = f"SYSTEM_SALUDO_{fecha_hoy}"
        if hora_hoy >= 8 and not self.db.has_key(llave_saludo):
            msg = (
                "☀️ *【 MODO SNIPER MULTI-LEAGUE: INICIO DE JORNADA 】* ☀️\n"
                "───────────────────────\n"
                "¡Excelente día inversionistas! Los escáneres globales están activos.\n\n"
                "🎯 *Radar Activado:* MLB 🇺🇸, Liga MX 🇲🇽 y Fútbol Europeo ⚽.\n"
                "Buscando las mejores oportunidades quirúrgicas del día. ¡Venga por esos verdes! 🚀"
            )
            if self.telegram.send_message(msg): self.db.record_item(llave_saludo, {"enviado": True})

        picks_hoy_db = self.db.get_picks_by_date(fecha_hoy)
        total_enviados = len(picks_hoy_db)
        Logger.log(f"📊 [Estado Operativo] Picks enviados hoy: {total_enviados}/4")

        if total_enviados >= 4:
            Logger.log("🛑 [Tope Alcanzado] Cuota premium completada. Bot en reposo.")
            return

        candidatos = self.escanear_cartelera(fecha_hoy, fecha_manana, hora_hoy, total_enviados)

        if candidatos and total_enviados < 4:
            self.ciclos_vacios = 0
            candidatos = sorted(candidatos, key=lambda x: (not x["es_live"], x["diff"]))
            ganador = candidatos[0]

            titulo = f"🔥 *【 SNIPER LIVE: {ganador['tag_liga']} 】* 🔥" if ganador["es_live"] else f"🧠 *【 SELECCIÓN MAESTRA: {ganador['tag_liga']} 】* 🧠"
            linea_score = f"📊 *Marcador Actual:* `{ganador['marcador_live']}`\n" if ganador["es_live"] else ""

            msg_envio = (
                f"{titulo}\n"
                f"───────────────────────\n"
                f"📅 *Horario:* {ganador['horario']}\n"
                f"⚔️ *Partido:* {ganador['partido']}\n"
                f"{linea_score}"
                f"📊 *Mercado:* `{ganador['mercado']}`\n\n"
                f"🎯 *PICK RECOMENDADO:* `{ganador['apuesta']}`\n"
                f"🏛 *Casa de Apuestas:* {ganador['casino']}\n"
                f"📈 *Momio de Entrada:* `{ganador['momio']}` 🇺🇸\n"
                f"🔥 *CONFIANZA:* `Stake {ganador['stake']}/10` 🛡️\n"
                f"───────────────────────\n"
                f"🍀 _¡Inversión analizada con software de precisión!_"
            )

            if self.telegram.send_message(msg_envio):
                v_data = {
                    "partido_id": ganador["partido_id"],
                    "partido": ganador["partido"],
                    "mercado": ganador["mercado"],
                    "apuesta": ganador["apuesta"],
                    "momio_dec": ganador["momio_dec"],
                    "momio_txt": ganador["momio"],
                    "stake": ganador["stake"],
                    "fecha_registro": fecha_hoy,
                    "estado": "PENDIENTE"
                }
                self.db.record_item(ganador["llave"], v_data)
                total_enviados += 1
                time.sleep(3)

        llave_parlay_sistema = f"SYSTEM_PARLAY_{fecha_hoy}"
        if total_enviados >= 2 and not self.db.has_key(llave_parlay_sistema):
            picks_para_combinar = self.db.get_picks_by_date(fecha_hoy)
            picks_ordenados = sorted(picks_para_combinar, key=lambda x: x["stake"], reverse=True)
            
            p1 = picks_ordenados[0]
            p2 = picks_ordenados[1]
            
            combined_dec = p1["momio_dec"] * p2["momio_dec"]
            parlay_momio_txt = f"+{int((combined_dec - 1) * 100)}" if combined_dec >= 2.00 else str(int(-100 / (combined_dec - 1)))

            msg_parlay = (
                f"🧬 *【 PARLAY MIXTO MULTI-LEAGUE 】* 🧬\n"
                f"───────────────────────\n"
                f"1️⃣ *{p1['partido']}*\n   ↳ *Pick:* `{p1['apuesta']}`\n\n"
                f"2️⃣ *{p2['partido']}*\n   ↳ *Pick:* `{p2['apuesta']}`\n\n"
                f"🏛 *Momio Combinado Estimado:* ~`{parlay_momio_txt}` 🇺🇸\n"
                f"🛡️ *STAKE GENERAL JUGADA:* `Stake 2/10` 💰\n"
                f"───────────────────────"
            )
            if self.telegram.send_message(msg_parlay):
                self.db.record_item(llave_parlay_sistema, {"enviado": True})
                Logger.log("🧬 [Parlay Gatillo] Notificación de parlay sugerido enviada exitosamente.")

        if not candidatos and total_enviados < 4:
            self.ciclos_vacios += 1

        Logger.log("😴 Ciclo finalizado de forma limpia. Durmiendo por 10 minutos...")

    def run(self):
        while True:
            try:
                self.ejecutar_ciclo()
            except Exception as e:
                Logger.log(f"💥 [Error General]: {e}")
            time.sleep(600)

if __name__ == "__main__":
    bot = SniperTipsterBot()
    bot.run()
