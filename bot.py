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
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
        sys.stdout.flush()

class DatabaseManager:
    def __init__(self, db_file="database_sniper.json"):
        self.db_file = db_file
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                Logger.log(f"⚠️ BD corrupta o vacía, reiniciando: {e}")
                return {}
        return {}

    def save(self):
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            Logger.log(f"❌ Error al guardar BD: {e}")

    def registrar_pick(self, pick_id: str, info: dict):
        self.data[pick_id] = info
        self.save()

    def obtener_picks_del_dia(self, fecha_hoy: str) -> list:
        return [v for k, v in self.data.items() if not k.startswith("SYS_") and v.get("fecha_registro") == fecha_hoy]

    def ya_existe_partido(self, partido_id: str, fecha_hoy: str) -> bool:
        picks_hoy = self.obtener_picks_del_dia(fecha_hoy)
        return any(p.get("partido_id") == partido_id for p in picks_hoy)

    def marcar_sistema(self, clave: str, datos: dict):
        self.data[f"SYS_{clave}"] = datos
        self.save()

    def chequeo_sistema(self, clave: str) -> bool:
        return f"SYS_{clave}" in self.data

class TelegramClient:
    def __init__(self, token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.session = requests.Session()

    def enviar(self, texto: str) -> bool:
        payload = {"chat_id": self.chat_id, "text": texto, "parse_mode": "Markdown"}
        try:
            res = self.session.post(self.url, json=payload, timeout=10)
            if res.status_code == 200:
                Logger.log("📱 Mensaje enviado a Telegram con éxito.")
                return True
            Logger.log(f"❌ Telegram API Error ({res.status_code}): {res.text}")
        except Exception as e:
            Logger.log(f"❌ Error de conexión con Telegram: {e}")
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
            if res.status_code == 200: return res.json()
        except: pass
        return []

    def fetch_odds(self, sport: str, markets: str) -> list:
        url = f"{self.base_url}/{sport}/odds/?apiKey={self.api_key}&regions=us,eu&markets={markets}&oddsFormat=american"
        try:
            res = self.session.get(url, timeout=15)
            creditos = res.headers.get("x-requests-remaining")
            if creditos:
                Logger.log(f"💳 Créditos de API restantes: {creditos}")
            if res.status_code == 200: return res.json()
        except Exception as e:
            Logger.log(f"❌ Error extrayendo cuotas para {sport}: {e}")
        return []

class TipsterEngine:
    @staticmethod
    def filtrar_y_calcular_stake(momio: int) -> int:
        if momio < -250 or momio > 350:
            return 0 
        if momio < 0:
            if momio <= -150: return 5
            return 4
        else:
            if momio <= 150: return 3
            return 2

class ProfessionalTipsterBot:
    def __init__(self):
        api_key = os.getenv("ODDS_API_KEY")
        bot_token = os.getenv("BOT_TOKEN")
        chat_id = os.getenv("CHAT_ID")

        if not api_key or not bot_token or not chat_id:
            Logger.log("❌ CRÍTICO: Faltan variables de entorno en el servidor de Render.")
            sys.exit(1)

        self.db = DatabaseManager()
        self.tg = TelegramClient(bot_token, chat_id)
        self.api = OddsApiClient(api_key)

        self.ligas = {
            "baseball_mlb": "MLB 🇺🇸",
            "soccer_mexico_ligamx": "Liga MX 🇲🇽",
            "soccer_epl": "Premier League 🏴󠁧󠁢󠁥󠁮󠁧󠁿",
            "soccer_spain_la_liga": "LaLiga 🇪🇸",
            "soccer_germany_bundesliga": "Bundesliga 🇩🇪"
        }

    def _get_hora_mexico(self):
        return datetime.now(timezone.utc) - timedelta(hours=6)

    def auditar_resultados(self):
        Logger.log("📊 Corriendo auditoría automatizada de resultados...")
        for sport in self.ligas.keys():
            partidos = self.api.fetch_scores(sport)
            for p in partidos:
                if p.get("completed"):
                    p_id = p.get("id")
                    scores = p.get("scores")
                    if not scores or len(scores) < 2: continue
                    try:
                        score_home = int(scores[0]["score"])
                        score_away = int(scores[1]["score"])
                        marcador_final = f"{score_away}-{score_home}"
                    except: continue

                    for k, v in self.db.data.items():
                        if not k.startswith("SYS_") and v.get("partido_id") == p_id and v.get("estado") == "PENDIENTE":
                            self.db.data[k]["estado"] = "FINALIZADO"
                            self.db.data[k]["marcador_final"] = marcador_final
                            Logger.log(f"✅ Partido {p_id} auditado. Resultado: {marcador_final}")
        self.db.save()

    def escanear_mercados(self, fecha_hoy: str, fecha_manana: str, total_enviados: int) -> list:
        candidatos = []

        for sport, tag in self.ligas.items():
            mercados = "h2h,totals,spreads,btts" if "soccer" in sport else "h2h,totals,spreads"
            partidos_odds = self.api.fetch_odds(sport, markets=mercados)
            
            scores_raw = self.api.fetch_scores(sport)
            live_data = {s["id"]: s for s in scores_raw}

            for p in partidos_odds:
                p_id = p.get("id")
                
                if self.db.ya_existe_partido(p_id, fecha_hoy): continue

                try:
                    dt_partido = (datetime.strptime(p.get("commence_time"), "%Y-%m-%dT%H:%M:%SZ") - timedelta(hours=6)).replace(tzinfo=None)
                    f_partido = dt_partido.strftime("%Y-%m-%d")
                    h_partido_txt = dt_partido.strftime("%d/%m %H:%M MX 🇲🇽")
                except: continue

                if f_partido != fecha_hoy and f_partido != fecha_manana: continue

                diff_segundos = (dt_partido - self._get_hora_mexico().replace(tzinfo=None)).total_seconds()
                es_live = diff_segundos <= 0

                if es_live and diff_segundos < -10800: continue 

                home = p.get("home_team")
                away = p.get("away_team")
                bookmakers = p.get("bookmakers", [])
                if not bookmakers: continue

                for bookie in bookmakers:
                    for market in bookie.get("markets", []):
                        m_key = market.get("key")
                        for outcome in market.get("outcomes", []):
                            momio = int(outcome.get("price"))
                            point = outcome.get("point", None)
                            o_name = outcome.get("name")
                            
                            stake = TipsterEngine.filtrar_y_calcular_stake(momio)
                            if stake == 0: continue 

                            es_base = "baseball" in sport
                            label_apuesta = o_name
                            
                            if m_key == "h2h":
                                tipo_m = "LÍNEA DE DINERO (GANADOR)"
                                if o_name.lower() == "draw": label_apuesta = "Empate"
                                elif o_name == home: label_apuesta = f"Gana {home} (Local)"
                                elif o_name == away: label_apuesta = f"Gana {away} (Visitante)"
                            elif m_key == "totals":
                                tipo_m = "TOTALES (ALTAS/BAJAS)"
                                unidad = "Carreras" if es_base else "Goles"
                                label_apuesta = f"Altas (Over) {point} {unidad}" if o_name.lower() == "over" else f"Bajas (Under) {point} {unidad}"
                            elif m_key == "spreads" and point is not None:
                                tipo_m = "HÁNDICAP"
                                unidad = "Carreras" if es_base else "Goles"
                                signo = "+" if float(point) > 0 else ""
                                label_apuesta = f"Hándicap {o_name} ({signo}{point} {unidad})"
                            elif m_key == "btts":
                                tipo_m = "AMBOS EQUIPOS ANOTAN"
                                label_apuesta = "Ambos Equipos Anotan: SÍ" if o_name.lower() == "yes" else "Ambos Equipos Anotan: NO"
                            else:
                                continue

                            llave_unica = f"{p_id}_{m_key}_{o_name}"
                            if self.db.chequeo_sistema(f"PICK_{llave_unica}"): continue

                            marcador_en_vivo = "0-0"
                            if es_live and p_id in live_data:
                                scs = live_data[p_id].get("scores", [])
                                if len(scs) >= 2:
                                    marcador_en_vivo = f"{scs[1].get('score',0)}-{scs[0].get('score',0)}"

                            momio_txt = f"+{momio}" if momio > 0 else str(momio)
                            
                            candidatos.append({
                                "llave": llave_unica,
                                "partido_id": p_id,
                                "partido": f"{away} vs {home}",
                                "liga": tag,
                                "mercado": tipo_m,
                                "apuesta": label_apuesta,
                                "casino": bookie.get("title"),
                                "momio": momio_txt,
                                "stake": stake,
                                "horario": h_partido_txt,
                                "es_live": es_live,
                                "marcador_live": marcador_en_vivo,
                                "prioridad": stake + (2 if es_live else 0)
                            })
        return candidatos

    def ejecutar_controlador(self):
        dt_mex = self._get_hora_mexico().replace(tzinfo=None)
        fecha_hoy = dt_mex.strftime("%Y-%m-%d")
        fecha_manana = (dt_mex + timedelta(days=1)).strftime("%Y-%m-%d")
        hora_actual = dt_mex.hour

        Logger.log(f"--- Ejecutando Escáner Profesional (Hora MX: {dt_mex.strftime('%H:%M')}) ---")
        
        self.auditar_resultados()

        if hora_actual >= 8 and not self.db.chequeo_sistema(f"SALUDO_{fecha_hoy}"):
            saludo = "🟢 SNIPER BOT: Escaner activo para hoy. Monitoreando MLB, Liga MX y Europa."
            if self.tg.enviar(saludo):
                self.db.marcar_sistema(f"SALUDO_{fecha_hoy}", {"enviado": True})

        picks_enviados_hoy = self.db.obtener_picks_del_dia(fecha_hoy)
        total_enviados = len(picks_enviados_hoy)
        Logger.log(f"Contador diario actual: {total_enviados}/4 picks emitidos.")

        if total_enviados >= 4:
            Logger.log("🔒 Meta diaria completada (4/4). El software descansa de emitir alertas por hoy.")
            return

        candidatos = self.escanear_mercados(fecha_hoy, fecha_manana, total_enviados)

        if candidatos:
            candidatos = sorted(candidatos, key=lambda x: x["prioridad"], reverse=True)
            pick_ganador = candidatos[0]

            tipo_alerta = "🔥 SNIPER LIVE PREMIUM 🔥" if pick_ganador["es_live"] else "🧠 ANALISIS PRE-PARTIDO 🧠"
            linea_live = f"Marcador Live: {pick_ganador['marcador_live']}\n" if pick_ganador["es_live"] else ""

            mensaje_pick = (
                f"{tipo_alerta}\n"
                f"Liga: {pick_ganador['liga']}\n"
                f"Partido: {pick_ganador['partido']}\n"
                f"Horario: {pick_ganador['horario']}\n"
                f"{linea_live}"
                f"Mercado: {pick_ganador['mercado']}\n\n"
                f"PICK RECOMENDADO: {pick_ganador['apuesta']}\n"
                f"Casa de Apuestas: {pick_ganador['casino']}\n"
                f"Cuota/Momio: {pick_ganador['momio']} US\n"
                f"🛡️ Stake: {pick_ganador['stake']}/10\n"
                f"Filtro de valor verificado."
            )

            if self.tg.enviar(mensaje_pick):
                info_pick = {
                    "partido_id": pick_ganador["partido_id"],
                    "partido": pick_ganador["partido"],
                    "apuesta": pick_ganador["apuesta"],
                    "momio": pick_ganador["momio"],
                    "stake": pick_ganador["stake"],
                    "fecha_registro": fecha_hoy,
                    "estado": "PENDIENTE"
                }
                self.db.registrar_pick(f"PICK_{pick_ganador['llave']}", info_pick)
                Logger.log(f"🚀 Pick emitido con éxito: {pick_ganador['apuesta']}")
        else:
            Logger.log("💤 No se encontraron errores de cuotas o valor en esta revisión.")

    def iniciar_bucle(self):
        while True:
            try:
                self.ejecutar_controlador()
            except Exception as e:
                Logger.log(f"💥 Error inesperado en el bucle principal: {e}")
            time.sleep(900)

if __name__ == "__main__":
    bot = ProfessionalTipsterBot()
    bot.iniciar_bucle()
