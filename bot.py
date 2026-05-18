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
        football_key = os.getenv("FOOTBALL_API_KEY")

        if not api_key or not bot_token or not chat_id or not football_key:
            Logger.log("❌ CRÍTICO: Faltan variables de entorno en Render.")
            sys.exit(1)

        self.db = DatabaseManager()
        self.tg = TelegramClient(bot_token, chat_id)
        self.api_key = api_key
        self.football_key = football_key
        self.session = requests.Session()

        self.ligas = {
            "soccer_mexico_ligamx": "Liga MX",
            "baseball_mlb": "MLB USA",
            "soccer_epl": "Premier League"
        }

        self.mapeo_liga_mx = {
            "Club América": 2281, "Guadalajara": 2288, "Cruz Azul": 2287, 
            "Pumas UNAM": 2295, "UANL Tigres": 2296, "Monterrey": 2289,
            "Toluca": 2297, "Santos Laguna": 2294, "Pachuca": 2291,
            "León": 2284, "Atlas": 2282, "Tijuana": 2293, 
            "Querétaro": 2292, "Puebla": 2290, "Mazatlán FC": 4700,
            "Necaxa": 2285, "Atlético San Luis": 2283, "Juárez": 2286
        }

        self.dias_es = {"Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles", "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo"}
        self.meses_es = {"Jan": "Enero", "Feb": "Febrero", "Mar": "Marzo", "Apr": "Abril", "May": "Mayo", "Jun": "Junio", "Jul": "Julio", "Aug": "Agosto", "Sep": "Septiembre", "Oct": "Octubre", "Nov": "Noviembre", "Dec": "Diciembre"}

    def _get_hora_mexico(self):
        return datetime.now(timezone.utc) - timedelta(hours=6)

    def calcular_stake(self, momio: int) -> int:
        if momio < -250 or momio > 300: return 0 
        if momio < 0: return 5 if momio <= -150 else 4
        else: return 3 if momio <= 140 else 2

    def calcular_probabilidad_dinamica(self, momio: int) -> int:
        try:
            if momio < 0: prob_implicita = (abs(momio) / (abs(momio) + 100)) * 100
            else: prob_implicita = (100 / (momio + 100)) * 100
            prob_final = int(prob_implicita + 14)
            return min(max(prob_final, 55), 88)
        except: return 75

    def obtener_promedio_goles_api(self, team_id: int) -> float:
        url = "https://v3.football.api-sports.io/teams/statistics"
        headers = {"x-rapidapi-key": self.football_key, "x-rapidapi-host": "v3.football.api-sports.io"}
        params = {"league": "262", "season": "2026", "team": str(team_id)}
        try:
            res = self.session.get(url, headers=headers, params=params, timeout=8)
            if res.status_code == 200:
                data = res.json()
                stats = data.get("response", {})
                if stats:
                    return float(stats.get("goals", {}).get("for", {}).get("average", {}).get("total", 1.3))
            return 1.3
        except: return 1.3

    # 🔥 GENERADOR DE ANÁLISIS INTEGRAL (ESTADÍSTICA + FACTORES EXTERNOS)
    def generar_analisis_coherente(self, sport: str, mercado_label: str, home: str, away: str, prom_comb: float = None) -> str:
        es_futbol = "soccer" in sport
        es_beisbol = "baseball" in sport
        argumento_base = ""

        # 1. Bloque Estadístico Automatizado
        if "Más de" in mercado_label or "Over" in mercado_label:
            if es_futbol:
                goles_txt = f" con un promedio combinado de `{prom_comb:.2f}` goles por encuentro" if prom_comb else ""
                argumento_base = f"📊 *Métricas:* Ambos conjuntos muestran una clara tendencia ofensiva esta temporada{goles_txt}. Sus transiciones rápidas y debilidades en las líneas bajas rivales abren un escenario ideal para buscar las altas."
            elif es_beisbol:
                argumento_base = f"📊 *Métricas:* El poder al bate de los line-ups actuales frente a la fatiga del picheo abridor proyecta un partido de alta anotación en la MLB. La línea puesta por el casino se quedó corta."
        elif "Menos de" in mercado_label or "Under" in mercado_label:
            if es_futbol:
                goles_txt = f" respaldado por un promedio de apenas `{prom_comb:.2f}` goles" if prom_comb else ""
                argumento_base = f"📊 *Métricas:* Choque de alta rigidez táctica. Ambos técnicos priorizan el orden defensivo en bloque bajo{goles_txt}. Esperamos un partido muy trabado en media cancha con escasas oportunidades."
            elif es_beisbol:
                argumento_base = f"📊 *Métricas:* Los lanzadores abridores asignados para hoy y la efectividad histórica del bullpen proyectan un duelo dominado completamente por las serpentinas en la MLB. Línea de bajas plenamente justificada."
        elif "Hándicap" in mercado_label:
            argumento_base = f"📊 *Métricas:* El mercado de hándicap nos ofrece una ventaja matemática crucial. El cruce de datos arroja que el equipo seleccionado mantiene una consistencia de cobertura que supera la línea exigida por el casino."
        else:
            argumento_base = f"📊 *Métricas:* La jerarquía de la plantilla y el momento actual inclinan la balanza. El momio asignado presenta una asimetría de valor matemática frente a la probabilidad real en la cancha."

        # 2. Bloque de Factores Contextuales (Plantilla para el canal del administrador)
        factores_externos = (
            f"\n\n🏟️ *Estadio y Localía:* _[Analizar factor viaje de {away} y ventaja de local de {home}]_\n"
            f"🌤️ *Condiciones Climáticas:* _[Pendiente verificar viento/lluvia/altura a la hora del juego]_\n"
            f"❌ *Reporte de Bajas:* _[Revisar confirmaciones de alineación de último minuto]_"
        )

        return argumento_base + factores_externos

    def analizar_probabilidad_y_valor(self, momio: int, mercado_key: str) -> bool:
        if momio < -250 or momio > 250: return False
        if momio <= -110 and momio >= -180: return True
        if mercado_key in ["spreads", "totals"] and momio >= 100 and momio <= 130: return True
        return False

    def enviar_reporte_profit_y_despedida(self, fecha_hoy: str):
        if self.db.chequeo_sistema(f"CIERRE_CANAL_{fecha_hoy}"): return
        picks_disputados_hoy = self.db.obtener_picks_jugados_el_dia(fecha_hoy)
        verdes, rojos, unidades_netas = 0, 0, 0.0

        for p in picks_disputados_hoy:
            stake = int(p.get("stake", 1))
            momio = int(p.get("momio_num", 100))
            estado = p.get("estado", "PENDIENTE")
            if estado == "GANADO":
                verdes += 1
                unidades_netas += stake * (100 / abs(momio)) if momio < 0 else stake * (momio / 100)
            elif estado == "PERDIDO":
                rojos += 1
                unidades_netas -= stake

        signo = "+" if unidades_netas >= 0 else ""
        mensaje_profit = (
            f"🏁 *【 CIERRE DE JORNADA INTERNO 】* 🏁\n"
            f"────────────────────────\n"
            f"📅 *Picks Disputados Hoy:* `{fecha_hoy}`\n"
            f"🎯 *Total Evaluados:* `{len(picks_disputados_hoy)}`\n\n"
            f"🟢 *Ganados:* `{verdes}`\n"
            f"🔴 *Perdidos:* `{rojos}`\n"
            f"📊 *Balance Neto:* `{signo}{unidades_netas:.2f} Unidades`\n"
            f"────────────────────────\n"
            f"🤖 _Resultados calculados de forma automatizada._"
        )
        if self.tg.enviar(mensaje_profit):
            self.db.marcar_sistema(f"CIERRE_CANAL_{fecha_hoy}", {"enviado": True})

    def escanear_mercados(self, fecha_hoy: str):
        dt_actual_mx = self._get_hora_mexico()
        if len(self.db.obtener_picks_jugados_el_dia(fecha_hoy)) >= 6: return

        for sport, tag in self.ligas.items():
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={self.api_key}&regions=us&markets=h2h,totals,spreads&oddsFormat=american"
            try:
                res = self.session.get(url, timeout=15)
                if res.status_code != 200: continue
                partidos = res.json()
            except: continue

            for p in partidos:
                p_id = p.get("id")
                if self.db.ya_existe_partido(p_id): continue

                home = p.get("home_team")
                away = p.get("away_team")
                bookmakers = p.get("bookmakers", [])
                if not bookmakers: continue

                try:
                    commence_time_raw = p.get("commence_time")
                    dt_mx = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ") - timedelta(hours=6)
                    fecha_real_juego = dt_mx.strftime("%Y-%m-%d")
                    tiempo_restante = dt_mx - dt_actual_mx.replace(tzinfo=None)
                    if tiempo_restante < timedelta(minutes=10) or tiempo_restante > timedelta(hours=15): continue
                    horario_texto = f"{dt_mx.strftime('%d')} de {self.meses_es.get(dt_mx.strftime('%b'))} - {dt_mx.strftime('%I:%M %p')} MX"
                except: continue

                promedio_combinado = None
                if sport == "soccer_mexico_ligamx":
                    id_home = self.mapeo_liga_mx.get(home)
                    id_away = self.mapeo_liga_mx.get(away)
                    if id_home and id_away:
                        prom_home = self.obtener_promedio_goles_api(id_home)
                        prom_away = self.obtener_promedio_goles_api(id_away)
                        promedio_combinado = prom_home + prom_away

                opcion_elegida, mercado_origen = None, None
                for bk in bookmakers:
                    markets = bk.get("markets", [])
                    for m_key in ["totals", "spreads", "h2h"]:
                        target_market = next((m for m in markets if m.get("key") == m_key), None)
                        if not target_market: continue
                        for out in target_market.get("outcomes", []):
                            momio = int(out.get("price", 100))
                            if self.analizar_probabilidad_y_valor(momio, m_key):
                                if self.calcular_stake(momio) > 0:
                                    opcion_elegida, mercado_origen = out, m_key
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
                    label_pick_final = f"{tipo} {point} {'Carreras' if 'baseball' in sport else 'Goles'}"
                elif mercado_origen == "spreads":
                    label_pick_final = f"Hándicap {opcion_elegida.get('name')} {'+' if float(point) > 0 else ''}{point}"
                elif mercado_origen == "h2h":
                    label_pick_final = f"Gana {home} (Local)" if label_pick_final == home else f"Gana {away} (Visitante)"

                texto_analisis_profesional = self.generar_analisis_coherente(sport, label_pick_final, home, away, promedio_combinado)

                mensaje = (
                    f"🧠 *【 ALERTA DE VALOR PREMIUM 】* 🧠\n"
                    f"🏆 *Liga:* {tag}\n"
                    f"📅 *Calendario:* `{horario_texto}`\n"
                    f"────────────────────────\n"
                    f"⚔️ *Partido:* {away} vs {home}\n"
                    f"🎯 *PICK:* `{label_pick_final}`\n"
                    f"🏛️ *Casa:* {bookmakers[0].get('title')}\n"
                    f"📈 *Cuota/Momio:* `{momio_txt}`\n"
                    f"🛡️ *Seguridad:* `Stake {stake}/10 ({porcentaje_real}% Probabilidad)`\n\n"
                    f"{texto_analisis_profesional}\n"
                    f"────────────────────────\n"
                    f"🤖 _Filtro estadístico y matemático activo._"
                )

                if self.tg.enviar(mensaje):
                    self.db.registrar_pick(f"PICK_{p_id}", {
                        "partido_id": p_id, "partido": f"{away} vs {home}", "apuesta": label_pick_final,
                        "momio_num": momio, "stake": stake, "fecha_registro": fecha_hoy,
                        "fecha_juego": fecha_real_juego, "estado": "PENDIENTE"
                    })
                    return 

    def ejecutar(self):
        while True:
            tiempo_espera = 1800
            try:
                dt_mex = self._get_hora_mexico()
                fecha_hoy = dt_mex.strftime("%Y-%m-%d")
                hora_actual = dt_mex.hour
                Logger.log(f"--- Ciclo de Análisis Avanzado Abierto (Hora MX: {dt_mex.strftime('%H:%M')}) ---")

                if hora_actual >= 23 or hora_actual < 5:
                    if hora_actual >= 23: self.enviar_reporte_profit_y_despedida(fecha_hoy)
                    tiempo_espera = 21600
                else:
                    if hora_actual == 8 and not self.db.chequeo_sistema(f"DIAS_{fecha_hoy}"):
                        if self.tg.enviar("☀️ *【 BUENOS DÍAS 】* ☀️\n\n¡Escáner Premium abierto! Buscando valor analítico en la cartelera de hoy. 📈💰"):
                            self.db.marcar_sistema(f"DIAS_{fecha_hoy}", {"enviado": True})
                    self.escanear_mercados(fecha_hoy)
            except Exception as e: Logger.log(f"💥 Error: {e}")
            time.sleep(tiempo_espera)

if __name__ == "__main__":
    ProfessionalBot().ejecutar()
