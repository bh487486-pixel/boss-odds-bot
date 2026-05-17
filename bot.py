import os
import sys
import time
import json
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

class ProfessionalBot:
    def __init__(self):
        api_key = os.getenv("ODDS_API_KEY")
        bot_token = os.getenv("BOT_TOKEN")
        chat_id = os.getenv("CHAT_ID")

        if not api_key or not bot_token or not chat_id:
            Logger.log("❌ CRÍTICO: Faltan variables de entorno en Render.")
            sys.exit(1)

        self.db = DatabaseManager()
        self.tg = TelegramClient(bot_token, chat_id)
        self.api_key = api_key
        self.session = requests.Session()

        self.ligas = {
            "baseball_mlb": "MLB USA",
            "soccer_mexico_ligamx": "Liga MX",
            "soccer_epl": "Premier League",
            "soccer_spain_la_liga": "LaLiga",
            "soccer_germany_bundesliga": "Bundesliga"
        }

        self.dias_es = {
            "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
            "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo"
        }
        self.meses_es = {
            "Jan": "Enero", "Feb": "Febrero", "Mar": "Marzo", "Apr": "Abril",
            "May": "Mayo", "Jun": "Junio", "Jul": "Julio", "Aug": "Agosto",
            "Sep": "Septiembre", "Oct": "Octubre", "Nov": "Noviembre", "Dec": "Diciembre"
        }

    def _get_hora_mexico(self):
        return datetime.now(timezone.utc) - timedelta(hours=6)

    def calcular_stake(self, momio: int) -> int:
        if momio < -250 or momio > 350:
            return 0 
        if momio < 0:
            return 5 if momio <= -150 else 4
        else:
            return 3 if momio <= 150 else 2

    def enviar_reporte_profit(self, fecha_hoy: str, picks_hoy: list):
        if self.db.chequeo_sistema(f"PROFIT_{fecha_hoy}"):
            return

        Logger.log("📊 Son las 11:00 PM. Generando balance de cierre diario...")
        verdes = 0
        rojos = 0
        unidades_netas = 0.0

        for p in picks_hoy:
            stake = int(p.get("stake", 1))
            momio = int(p.get("momio_num", 100))
            estado = p.get("estado", "PENDIENTE")

            if estado == "GANADO":
                verdes += 1
                if momio > 0:
                    unidades_netas += stake * (momio / 100)
                else:
                    unidades_netas += stake * (100 / abs(momio))
            elif estado == "PERDIDO":
                rojos += 1
                unidades_netas -= stake

        signo = "+" if unidades_netas >= 0 else ""
        emoji_balance = "💰💰" if unidades_netas >= 0 else "📉⚠️"

        mensaje_profit = (
            f"🏁 *【 CIERRE DE JORNADA INTERNO 】* 🏁\n"
            f"────────────────────────\n"
            f"📅 *Fecha:* `{fecha_hoy}`\n"
            f"🎯 *Picks Enviados Hoy:* `{len(picks_hoy)}/5`\n\n"
            f"🟢 *Ganados:* `{verdes}`\n"
            f"🔴 *Perdidos:* `{rojos}`\n"
            f"📊 *Balance Neto:* `{signo}{unidades_netas:.2f} Unidades` {emoji_balance}\n"
            f"────────────────────────\n"
            f"🤖 _Reporte programado enviado automáticamente a las 11:00 PM._"
        )
        
        if self.tg.enviar(mensaje_profit):
            self.db.marcar_sistema(f"PROFIT_{fecha_hoy}", {"enviado": True, "profit": unidades_netas})

    def escanear_mercados(self, fecha_hoy: str):
        for sport, tag in self.ligas.items():
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={self.api_key}&regions=us&markets=h2h,totals&oddsFormat=american"
            try:
                res = self.session.get(url, timeout=15)
                if res.status_code != 200: continue
                partidos = res.json()
            except:
                continue

            for p in partidos:
                p_id = p.get("id")
                
                if self.db.ya_existe_partido(p_id, fecha_hoy): continue

                home = p.get("home_team")
                away = p.get("away_team")
                bookmakers = p.get("bookmakers", [])
                if not bookmakers: continue

                try:
                    commence_time_raw = p.get("commence_time")
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    dt_mx = dt_utc - timedelta(hours=6)
                    
                    dia_semana_en = dt_mx.strftime("%A")
                    dia_semana_es = self.dias_es.get(dia_semana_en, dia_semana_en)
                    
                    mes_en = dt_mx.strftime("%b")
                    mes_es = self.meses_es.get(mes_en, mes_en)
                    
                    # CORRECCIÓN AQUÍ: Se cambió %H:%M por %I:%M %p para forzar el formato AM/PM (Ej: 10:30 PM)
                    hora_ampm = dt_mx.strftime("%I:%M %p")
                    horario_juego_texto = f"{dia_semana_es}, {dt_mx.strftime('%d')} de {mes_es} - {hora_ampm} MX"
                except:
                    horario_juego_texto = "Por confirmar"

                market = bookmakers[0].get("markets", [])[0]
                
                for outcome in market.get("outcomes", []):
                    momio = int(outcome.get("price"))
                    stake = self.calcular_stake(momio)
                    if stake == 0: continue

                    # CORRECCIÓN AQUÍ: Ajustado el tope máximo estricto a 5 picks por día
                    picks_hoy = self.db.obtener_picks_del_dia(fecha_hoy)
                    if len(picks_hoy) >= 5:
                        Logger.log("🔒 Límite de 5 picks alcanzado por hoy. Deteniendo envíos.")
                        return

                    momio_txt = f"+{momio}" if momio > 0 else str(momio)
                    label_apuesta = outcome.get("name")
                    if label_apuesta == home: label_apuesta = f"Gana {home} (Local)"
                    elif label_apuesta == away: label_apuesta = f"Gana {away} (Visitante)"

                    mensaje = (
                        f"🧠 *【 ANÁLISIS DE VALOR OPTIMIZADO 】* 🧠\n"
                        f"🏆 *Liga:* {tag}\n"
                        f"📅 *Calendario:* `{horario_juego_texto}`\n"
                        f"────────────────────────\n"
                        f"⚔️ *Partido:* {away} vs {home}\n"
                        f"🎯 *PICK:* `{label_apuesta}`\n"
                        f"🏛️ *Casa:* {bookmakers[0].get('title')}\n"
                        f"📈 *Cuota/Momio:* `{momio_txt}`\n"
                        f"🛡️ *Riesgo:* `Stake {stake}/10`\n"
                        f"────────────────────────\n"
                        f"🤖 _Filtro de valor verificado e ingresado a base de datos._"
                    )

                    if self.tg.enviar(mensaje):
                        info_pick = {
                            "partido_id": p_id,
                            "partido": f"{away} vs {home}",
                            "apuesta": label_apuesta,
                            "momio_num": momio,
                            "stake": stake,
                            "fecha_registro": fecha_hoy,
                            "estado": "PENDIENTE"
                        }
                        self.db.registrar_pick(f"PICK_{p_id}", info_pick)
                        Logger.log(f"🚀 Pick enviado con éxito: {label_apuesta}")
                        return 

    def ejecutar(self):
        while True:
            try:
                dt_mex = self._get_hora_mexico()
                fecha_hoy = dt_mex.strftime("%Y-%m-%d")
                hora_actual = dt_mex.hour
                minuto_actual = dt_mex.minute

                Logger.log(f"--- Ciclo de Monitoreo (Hora MX: {dt_mex.strftime('%H:%M')}) ---")
                
                picks_hoy = self.db.obtener_picks_del_dia(fecha_hoy)

                if hora_actual >= 23:
                    self.enviar_reporte_profit(fecha_hoy, picks_hoy)

                if hora_actual == 23 and minuto_actual >= 30:
                    if not self.db.chequeo_sistema(f"NOCHES_{fecha_hoy}"):
                        msg_noches = (
                            "🌙 *【 CIERRE DE CANAL 】* 🌙\n"
                            "────────────────────────\n"
                            "Familia, finalizamos las actividades por el día de hoy. "
                            "El bot se queda monitoreando los mercados de madrugada para arrancar con todo mañana. "
                            "¡Que tengan una excelente noche y descansen! 😴💤"
                        )
                        if self.tg.enviar(msg_noches):
                            self.db.marcar_sistema(f"NOCHES_{fecha_hoy}", {"enviado": True})

                if hora_actual == 8 and minuto_actual >= 30:
                    if not self.db.chequeo_sistema(f"DIAS_{fecha_hoy}"):
                        msg_dias = (
                            "☀️ *【 BUENOS DÍAS 】* ☀️\n"
                            "────────────────────────\n"
                            "¡Ya estamos activos, equipo! 🚀 El escáner ya se encuentra analizando "
                            "los primeros momios y líneas de valor del día. Mantengan las notificaciones "
                            "activas que hoy vamos por esos verdes. ¡Mucho éxito en la jornada! 📈💰"
                        )
                        if self.tg.enviar(msg_dias):
                            self.db.marcar_sistema(f"DIAS_{fecha_hoy}", {"enviado": True})

                # CORRECCIÓN AQUÍ: Ajustado a 5 en la verificación visual del ciclo
                if len(picks_hoy) >= 5:
                    Logger.log("🔒 Meta diaria completada (5/5). No se buscarán más picks por hoy.")
                else:
                    self.escanear_mercados(fecha_hoy)
                    
            except Exception as e:
                Logger.log(f"💥 Error en el controlador principal: {e}")
            
            Logger.log("💤 Esperando 30 minutos para la siguiente revisión...")
            time.sleep(1800)

if __name__ == "__main__":
    bot = ProfessionalBot()
    bot.ejecutar()
