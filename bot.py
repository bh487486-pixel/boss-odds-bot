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

        # Lista de ligas en orden estándar de revisión rápida
        self.ligas = {
            "soccer_epl": "Premier League",
            "soccer_spain_la_liga": "LaLiga",
            "soccer_germany_bundesliga": "Bundesliga",
            "baseball_mlb": "MLB USA",
            "soccer_mexico_ligamx": "Liga MX"
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

    def analizar_probabilidad_y_valor(self, momio: int) -> bool:
        if momio < -250 or momio > 350:
            return False
        if momio <= -110 and momio >= -180:
            return True
        if momio >= 100 and momio <= 350:
            return True
        return False

    def _calcular_momio_combinado(self, momio1: int, momio2: int) -> tuple:
        dec1 = (100 / abs(momio1)) + 1 if momio1 < 0 else (momio1 / 100) + 1
        dec2 = (100 / abs(momio2)) + 1 if momio2 < 0 else (momio2 / 100) + 1
        dec_final = dec1 * dec2
        if dec_final >= 2.0:
            am_final = int((dec_final - 1) * 100)
            txt_final = f"+{am_final}"
        else:
            am_final = int(-100 / (dec_final - 1))
            txt_final = str(am_final)
        return am_final, txt_final

    def enviar_reporte_profit_y_despedida(self, fecha_hoy: str, picks_hoy: list):
        """
        Envía de forma unificada a las 11:00 PM el reporte de profit y las buenas noches.
        """
        if self.db.chequeo_sistema(f"CIERRE_CANAL_{fecha_hoy}"):
            return

        Logger.log("📊 Son las 11:00 PM. Generando balance de cierre y despedida...")
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

        # 1. Mensaje del Profit Diario
        mensaje_profit = (
            f"🏁 *【 CIERRE DE JORNADA INTERNO 】* 🏁\n"
            f"────────────────────────\n"
            f"📅 *Fecha:* `{fecha_hoy}`\n"
            f"🎯 *Picks Enviados Hoy:* `{len(picks_hoy)}/6`\n\n"
            f"🟢 *Ganados:* `{verdes}`\n"
            f"🔴 *Perdidos:* `{rojos}`\n"
            f"📊 *Balance Neto:* `{signo}{unidades_netas:.2f} Unidades` {emoji_balance}\n"
            f"────────────────────────\n"
            f"🤖 _Reporte programado enviado automáticamente._"
        )
        
        # 2. Mensaje de Buenas Noches integrado
        mensaje_noches = (
            "🌙 *【 CIERRE DE CANAL 】* 🌙\n"
            "────────────────────────\n"
            "Familia, finalizamos las actividades por el día de hoy. "
            "El bot entra en modo de descanso y se reactivará por la mañana. "
            "¡Que tengan una excelente noche y nos vemos mañana para seguir sumando! 😴"
        )

        # Enviamos ambos bloques
        if self.tg.enviar(mensaje_profit):
            time.sleep(2)  # Pequeña pausa para no saturar Telegram
            if self.tg.enviar(mensaje_noches):
                self.db.marcar_sistema(f"CIERRE_CANAL_{fecha_hoy}", {"enviado": True, "profit": unidades_netas})

    def escanear_mercados(self, fecha_hoy: str):
        dt_actual_mx = self._get_hora_mexico()

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
                    
                    tiempo_restante = dt_mx - dt_actual_mx.replace(tzinfo=None)
                    
                    # Filtro mínimo: Que el juego no haya empezado (mínimo 10 min de colchón)
                    if tiempo_restante < timedelta(minutes=10):
                        continue
                    
                    # Candado superior para no mandar partidos de la próxima semana
                    if tiempo_restante > timedelta(hours=24):
                        continue

                    dia_semana_en = dt_mx.strftime("%A")
                    dia_semana_es = self.dias_es.get(dia_semana_en, dia_semana_en)
                    mes_en = dt_mx.strftime("%b")
                    mes_es = self.meses_es.get(mes_en, mes_en)
                    
                    hora_ampm = dt_mx.strftime("%I:%M %p")
                    horario_juego_texto = f"{dia_semana_es}, {dt_mx.strftime('%d')} de {mes_es} - {hora_ampm} MX"
                except Exception as e:
                    Logger.log(f"⚠️ Error procesando horario de juego: {e}")
                    horario_juego_texto = "Por confirmar"

                mercado_h2h = None
                mercado_totals = None
                
                for bk in bookmakers:
                    for m in bk.get("markets", []):
                        if m.get("key") == "h2h" and not mercado_h2h:
                            mercado_h2h = m
                        if m.get("key") == "totals" and not mercado_totals:
                            mercado_totals = m
                    if mercado_h2h and mercado_totals:
                        break

                if not mercado_h2h: continue

                outcomes_validos = []
                for outcome in mercado_h2h.get("outcomes", []):
                    momio = int(outcome.get("price"))
                    
                    if not self.analizar_probabilidad_y_valor(momio):
                        continue

                    stake = self.calcular_stake(momio)
                    if stake > 0:
                        outcomes_validos.append((outcome, momio, stake))

                if not outcomes_validos: continue

                outcomes_validos.sort(key=lambda x: x[1], reverse=True)
                outcome_elegido, momio, stake = outcomes_validos[0]

                # Límite global diario
                picks_hoy = self.db.obtener_picks_del_dia(fecha_hoy)
                if len(picks_hoy) >= 6:
                    return

                momio_txt = f"+{momio}" if momio > 0 else str(momio)
                label_apuesta = outcome_elegido.get("name")
                if label_apuesta == home: label_apuesta = f"Gana {home} (Local)"
                elif label_apuesta == away: label_apuesta = f"Gana {away} (Visitante)"

                es_combinada_conveniente = (momio <= -150)
                momio_para_guardar = momio

                if es_combinada_conveniente and (mercado_totals and mercado_totals.get("outcomes")):
                    out_total = mercado_totals.get("outcomes")[0]
                    puntos = out_total.get("point")
                    momio_total = int(out_total.get("price", -110))
                    
                    if "baseball" in sport:
                        label_pick_final = f"{label_apuesta} + Más de {puntos} Carreras"
                    else:
                        label_pick_final = f"{label_apuesta} + Más de {puntos} Goles"
                    
                    titulo_analisis = "🧠 *【 COMBINADA DE VALOR OPTIMIZADO 】* 🧠"
                    momio_para_guardar, momio_final_txt = self._calcular_momio_combinado(momio, momio_total)
                else:
                    label_pick_final = label_apuesta
                    titulo_analisis = "🧠 *【 ANÁLISIS DE VALOR OPTIMIZADO 】* 🧠"
                    momio_final_txt = momio_txt

                mensaje = (
                    f"{titulo_analisis}\n"
                    f"🏆 *Liga:* {tag}\n"
                    f"📅 *Calendario:* `{horario_juego_texto}`\n"
                    f"────────────────────────\n"
                    f"⚔️ *Partido:* {away} vs {home}\n"
                    f"🎯 *PICK:* `{label_pick_final}`\n"
                    f"🏛️ *Casa:* {bookmakers[0].get('title')}\n"
                    f"📈 *Cuota/Momio:* `{momio_final_txt}`\n"
                    f"🛡️ *Riesgo:* `Stake {stake}/10`\n"
                    f"────────────────────────\n"
                    f"🤖 _Filtro de valor verificado de forma inteligente._"
                )

                if self.tg.enviar(mensaje):
                    info_pick = {
                        "partido_id": p_id,
                        "partido": f"{away} vs {home}",
                        "apuesta": label_pick_final,
                        "momio_num": momio_para_guardar,
                        "stake": stake,
                        "fecha_registro": fecha_hoy,
                        "estado": "PENDIENTE"
                    }
                    self.db.registrar_pick(f"PICK_{p_id}", info_pick)
                    Logger.log(f"🚀 Pick enviado: {label_pick_final}. Cerrando ciclo actual para esperar los 30 minutos.")
                    
                    # 🔥 RETORNO LIBRE: Mandó un solo pick, frena y sale para respetar los 30 minutos de espacio.
                    # En la siguiente vuelta revisará todo parejo otra vez libremente.
                    return 

    def ejecutar(self):
        while True:
            tiempo_espera_segundos = 1800  # 30 minutos por defecto
            try:
                dt_mex = self._get_hora_mexico()
                fecha_hoy = dt_mex.strftime("%Y-%m-%d")
                hora_actual = dt_mex.hour

                Logger.log(f"--- Ciclo de Monitoreo (Hora MX: {dt_mex.strftime('%H:%M')}) ---")
                
                picks_hoy = self.db.obtener_picks_del_dia(fecha_hoy)

                # 🏁 CONTROL DE CIERRE DIRECTO A LAS 11:00 PM (Hora >= 23)
                if hora_actual >= 23 or hora_actual < 5:
                    if hora_actual >= 23:
                        # Envía el Profit y el Cierre al mismo tiempo
                        self.enviar_reporte_profit_y_despedida(fecha_hoy, picks_hoy)
                    
                    Logger.log("😴 Apagado Nocturno Completo Activo. Durmiendo bloque largo de 6 horas...")
                    tiempo_espera_segundos = 21600  # 6 horas exactas de sueño profundo
                
                else:
                    # HORARIO DIURNO (5:00 AM a 10:59 PM)
                    tiempo_espera_segundos = 1800  # Forzamos los 30 minutos obligatorios entre escaneos
                    
                    # Mensaje de Buenos Días a las 8 AM
                    if hora_actual == 8:
                        if not self.db.chequeo_sistema(f"DIAS_{fecha_hoy}"):
                            msg_dias = (
                                "☀️ *【 BUENOS DÍAS 】* ☀️\n"
                                "────────────────────────\n"
                                "¡Ya estamos activos, equipo! 🚀 El escáner se encuentra distribuyendo "
                                "los picks del día. ¡Mantengan notificaciones activas! 📈💰"
                            )
                            if self.tg.enviar(msg_dias):
                                self.db.marcar_sistema(f"DIAS_{fecha_hoy}", {"enviado": True})

                    if len(picks_hoy) >= 6:
                        Logger.log("🔒 Meta diaria completada (6/6). No se buscarán más picks por hoy.")
                    else:
                        # Busca de manera libre y suelta en todas las ligas, pero manda máximo 1 por ciclo
                        self.escanear_mercados(fecha_hoy)
                    
            except Exception as e:
                Logger.log(f"💥 Error en el controlador principal: {e}")
            
            minutos_log = int(tiempo_espera_segundos / 60)
            Logger.log(f"💤 Esperando {minutos_log} minutos para la siguiente revisión...")
            time.sleep(tiempo_espera_segundos)

if __name__ == "__main__":
    bot = ProfessionalBot()
    bot.ejecutar()
