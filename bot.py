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

    # 🔥 FILTRO CORREGIDO: Filtra los partidos por el día en que se JUEGAN, no cuando se mandan
    def obtener_picks_jugados_el_dia(self, fecha_busqueda: str) -> list:
        return [v for k, v in self.data.items() if not k.startswith("SYS_") and v.get("fecha_juego") == fecha_busqueda]

    def ya_existe_partido(self, partido_id: str) -> bool:
        return f"PICK_{partido_id}" in self.data

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
        if momio < -250 or momio > 300:
            return 0 
        if momio < 0:
            return 5 if momio <= -150 else 4
        else:
            return 3 if momio <= 140 else 2

    def calcular_probabilidad_dinamica(self, momio: int) -> int:
        try:
            if momio < 0:
                prob_implicita = (abs(momio) / (abs(momio) + 100)) * 100
            else:
                prob_implicita = (100 / (momio + 100)) * 100
            
            prob_final = int(prob_implicita + 14)
            if prob_final > 88: prob_final = 88
            if prob_final < 55: prob_final = 55
            return prob_final
        except:
            return 75

    def analizar_probabilidad_y_valor(self, momio: int, mercado_key: str) -> bool:
        if momio < -250 or momio > 250:
            return False
        if momio <= -110 and momio >= -180:
            return True
        if mercado_key in ["spreads", "totals"] and momio >= 100 and momio <= 130:
            return True
        return False

    def enviar_reporte_profit_y_despedida(self, fecha_hoy: str):
        if self.db.chequeo_sistema(f"CIERRE_CANAL_{fecha_hoy}"):
            return

        # 🔥 OBTENEMOS EXCLUSIVAMENTE LOS JUEGOS DISPUTADOS HOY
        picks_disputados_hoy = self.db.obtener_picks_jugados_el_dia(fecha_hoy)

        Logger.log(f"📊 Generando balance para juegos del día {fecha_hoy}. Encontrados: {len(picks_disputados_hoy)}")
        verdes = 0
        rojos = 0
        unidades_netas = 0.0

        for p in picks_disputados_hoy:
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
            f"📅 *Picks Disputados Hoy:* `{fecha_hoy}`\n"
            f"🎯 *Total Evaluados:* `{len(picks_disputados_hoy)}`\n\n"
            f"🟢 *Ganados:* `{verdes}`\n"
            f"🔴 *Perdidos:* `{rojos}`\n"
            f"📊 *Balance Neto:* `{signo}{unidades_netas:.2f} Unidades` {emoji_balance}\n"
            f"────────────────────────\n"
            f"🤖 _Resultados calculados basados en los juegos concluidos de hoy._"
        )
        
        mensaje_noches = (
            "🌙 *【 CIERRE DE CANAL 】* 🌙\n"
            "────────────────────────\n"
            "Familia, finalizamos las actividades por el día de hoy. "
            "El bot entra en modo de descanso y se reactivará por la mañana. "
            "¡Que tengan una excelente noche y nos vemos mañana para seguir sumando! 😴"
        )

        if self.tg.enviar(mensaje_profit):
            time.sleep(2)
            if self.tg.enviar(mensaje_noches):
                self.db.marcar_sistema(f"CIERRE_CANAL_{fecha_hoy}", {"enviado": True, "profit": unidades_netas})

    def escanear_mercados(self, fecha_hoy: str):
        dt_actual_mx = self._get_hora_mexico()

        # Evitar buscar si ya mandamos 6 picks jugados hoy (Tope diario)
        picks_hoy = self.db.obtener_picks_jugados_el_dia(fecha_hoy)
        if len(picks_hoy) >= 6:
            return

        for sport, tag in self.ligas.items():
            mercados_solicitados = "h2h,totals,spreads"
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={self.api_key}&regions=us&markets={mercados_solicitados}&oddsFormat=american"

            try:
                res = self.session.get(url, timeout=15)
                if res.status_code != 200: continue
                partidos = res.json()
            except:
                continue

            for p in partidos:
                p_id = p.get("id")
                if self.db.ya_existe_partido(p_id): continue

                home = p.get("home_team")
                away = p.get("away_team")
                bookmakers = p.get("bookmakers", [])
                if not bookmakers: continue

                try:
                    commence_time_raw = p.get("commence_time")
                    dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ")
                    dt_mx = dt_utc - timedelta(hours=6)
                    
                    # Identificar la fecha real en la que se disputará el juego
                    fecha_real_juego = dt_mx.strftime("%Y-%m-%d")
                    
                    tiempo_restante = dt_mx - dt_actual_mx.replace(tzinfo=None)
                    if tiempo_restante < timedelta(minutes=10):
                        continue
                    
                    # 🔥 CANDADO DE ANTICIPACIÓN: En el día no analiza juegos a más de 15 horas
                    # para evitar encasquetar partidos de mañana lunes en el flujo pesado de hoy
                    if tiempo_restante > timedelta(hours=15):
                        continue

                    dia_semana_en = dt_mx.strftime("%A")
                    dia_semana_es = self.dias_es.get(dia_semana_en, dia_semana_en)
                    mes_en = dt_mx.strftime("%b")
                    mes_es = self.meses_es.get(mes_en, mes_en)
                    
                    hora_ampm = dt_mx.strftime("%I:%M %p")
                    horario_juego_texto = f"{dia_semana_es}, {dt_mx.strftime('%d')} de {mes_es} - {hora_ampm} MX"
                except Exception as e:
                    Logger.log(f"⚠️ Error procesando horario: {e}")
                    continue

                opcion_elegida = None
                mercado_origen = None
                
                for bk in bookmakers:
                    markets = bk.get("markets", [])
                    for m_key in ["totals", "spreads", "h2h"]:
                        target_market = next((m for m in markets if m.get("key") == m_key), None)
                        if not target_market: continue
                        
                        outcomes = target_market.get("outcomes", [])
                        for out in outcomes:
                            momio = int(out.get("price", 100))
                            if self.analizar_probabilidad_y_valor(momio, m_key):
                                stake = self.calcular_stake(momio)
                                if stake > 0:
                                    opcion_elegida = out
                                    mercado_origen = m_key
                                    break
                        if opcion_elegida: break
                    if opcion_elegida: break

                if not opcion_elegida or not mercado_origen: continue

                momio = int(opcion_elegida.get("price"))
                momio_txt = f"+{momio}" if momio > 0 else str(momio)
                stake = self.calcular_stake(momio)
                porcentaje_real = self.calcular_probabilidad_dinamica(momio)

                label_pick_final = opcion_elegida.get("name")
                point = opcion_elegida.get("point")
                
                if mercado_origen == "totals":
                    tipo = "Más de" if opcion_elegida.get("name").lower() in ["over", "más"] else "Menos de"
                    unidad = "Carreras" if "baseball" in sport else "Goles"
                    label_pick_final = f"{tipo} {point} {unidad}"
                elif mercado_origen == "spreads":
                    signo = "+" if float(point) > 0 else ""
                    label_pick_final = f"Hándicap {opcion_elegida.get('name')} {signo}{point}"
                elif mercado_origen == "h2h":
                    if label_pick_final == home: label_pick_final = f"Gana {home} (Local)"
                    elif label_pick_final == away: label_pick_final = f"Gana {away} (Visitante)"

                mensaje = (
                    f"🧠 *【 ANÁLISIS DE VALOR OPTIMIZADO 】* 🧠\n"
                    f"🏆 *Liga:* {tag}\n"
                    f"📅 *Calendario:* `{horario_juego_texto}`\n"
                    f"────────────────────────\n"
                    f"⚔️ *Partido:* {away} vs {home}\n"
                    f"🎯 *PICK:* `{label_pick_final}`\n"
                    f"🏛️ *Casa:* {bookmakers[0].get('title')}\n"
                    f"📈 *Cuota/Momio:* `{momio_txt}`\n"
                    f"🛡️ *Seguridad:* `Stake {stake}/10 (Porcentaje: {porcentaje_real}%)`\n"
                    f"────────────────────────\n"
                    f"🤖 _Filtro de valor calculado dinámicamente._"
                )

                if self.tg.enviar(mensaje):
                    info_pick = {
                        "partido_id": p_id,
                        "partido": f"{away} vs {home}",
                        "apuesta": label_pick_final,
                        "momio_num": momio,
                        "stake": stake,
                        "fecha_registro": fecha_hoy,
                        "fecha_juego": fecha_real_juego,  # 🔥 SE GUARDA LA FECHA DE DISPUTA REAL
                        "estado": "PENDIENTE"
                    }
                    self.db.registrar_pick(f"PICK_{p_id}", info_pick)
                    Logger.log(f"🚀 Pick enviado para jugarse el {fecha_real_juego}: {label_pick_final}.")
                    return 

    def ejecutar(self):
        while True:
            tiempo_espera_segundos = 1800
            try:
                dt_mex = self._get_hora_mexico()
                fecha_hoy = dt_mex.strftime("%Y-%m-%d")
                hora_actual = dt_mex.hour

                Logger.log(f"--- Ciclo de Monitoreo de Fecha Real (Hora MX: {dt_mex.strftime('%H:%M')}) ---")

                if hora_actual >= 23 or hora_actual < 5:
                    if hora_actual >= 23:
                        # 🔥 Envía solo los resultados correspondientes al día de hoy
                        self.enviar_reporte_profit_y_despedida(fecha_hoy)
                    
                    Logger.log("😴 Modo Nocturno. Servidor pausado por 6 horas...")
                    tiempo_espera_segundos = 21600
                
                else:
                    tiempo_espera_segundos = 1800
                    
                    if hora_actual == 8:
                        if not self.db.chequeo_sistema(f"DIAS_{fecha_hoy}"):
                            msg_dias = (
                                "☀️ *【 BUENOS DÍAS 】* ☀️\n"
                                "────────────────────────\n"
                                "¡Ya estamos activos, equipo! 🚀 El escáner se encuentra buscando las líneas más seguras para los partidos de hoy. ¡A ganar! 📈💰"
                            )
                            if self.tg.enviar(msg_dias):
                                self.db.marcar_sistema(f"DIAS_{fecha_hoy}", {"enviado": True})

                    self.escanear_mercados(fecha_hoy)
                    
            except Exception as e:
                Logger.log(f"💥 Error en el controlador principal: {e}")
            
            time.sleep(tiempo_espera_segundos)

if __name__ == "__main__":
    bot = ProfessionalBot()
    bot.ejecutar()
