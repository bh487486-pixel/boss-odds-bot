import os
import sys
import time
import json
import re
from datetime import datetime, timedelta, timezone

import requests

# -------------------------------------------------------------------------
# LOGGER CLASS (Render Optimized)
# -------------------------------------------------------------------------
class Logger:
    """Clase encargada de manejar los logs en tiempo real para la consola de Render."""
    
    @staticmethod
    def _get_mexico_time() -> datetime:
        # Hora de México (UTC-6) fija para consistencia en logs y lógica
        tz_mx = timezone(timedelta(hours=-6))
        return datetime.now(tz_mx)

    @classmethod
    def info(cls, message: str):
        current_time = cls._get_mexico_time().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] INFO: {message}")
        sys.stdout.flush()

    @classmethod
    def warning(cls, message: str):
        current_time = cls._get_mexico_time().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] WARNING: {message}")
        sys.stdout.flush()

    @classmethod
    def error(cls, message: str):
        current_time = cls._get_mexico_time().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] ERROR: {message}")
        sys.stdout.flush()


# -------------------------------------------------------------------------
# DATABASE MANAGER CLASS
# -------------------------------------------------------------------------
class DatabaseManager:
    """Clase para la persistencia local de picks y control de límites diarios."""
    
    def __init__(self, filename: str = "database_sniper.json"):
        self.filename = filename
        self._init_db()

    def _init_db(self):
        if not os.path.exists(self.filename):
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump({"picks": [], "daily_greetings": []}, f, indent=4)
            Logger.info(f"Base de datos local creada: {self.filename}")

    def _load(self) -> dict:
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            Logger.error("Error leyendo la base de datos JSON. Restaurando estructura.")
            return {"picks": [], "daily_greetings": []}

    def _save(self, data: dict):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def get_picks_by_date(self, date_str: str) -> list:
        """Retorna los picks enviados en una fecha específica (YYYY-MM-DD)."""
        data = self._load()
        return [p for p in data.get("picks", []) if p.get("sent_date") == date_str]

    def is_game_blocked(self, game_id: str) -> bool:
        """Candado de No-Contradicción: Verifica si el partido ya tiene un pick."""
        data = self._load()
        for pick in data.get("picks", []):
            if pick.get("game_id") == game_id:
                return True
        return False

    def save_pick(self, game_id: str, sport: str, home_team: str, away_team: str, market: str, pick_name: str, odds: int, stake: int, sent_date: str):
        data = self._load()
        new_pick = {
            "game_id": game_id,
            "sport": sport,
            "home_team": home_team,
            "away_team": away_team,
            "market": market,
            "pick_name": pick_name,
            "odds": odds,
            "stake": stake,
            "sent_date": sent_date,
            "status": "PENDING",
            "final_score": None
        }
        data["picks"].append(new_pick)
        self._save(data)
        Logger.info(f"Pick guardado en DB para el juego {game_id} ({home_team} vs {away_team})")

    def get_pending_picks(self) -> list:
        data = self._load()
        return [p for p in data.get("picks", []) if p.get("status") == "PENDING"]

    def update_pick_status(self, game_id: str, status: str, final_score: str):
        data = self._load()
        for pick in data.get("picks", []):
            if pick["game_id"] == game_id:
                pick["status"] = status
                pick["final_score"] = final_score
                break
        self._save(data)
        Logger.info(f"Auditoría: Estado del juego {game_id} actualizado a {status} ({final_score})")

    def has_greeted_today(self, date_str: str) -> bool:
        data = self._load()
        return date_str in data.get("daily_greetings", [])

    def record_greeting(self, date_str: str):
        data = self._load()
        if date_str not in data["daily_greetings"]:
            data["daily_greetings"].append(date_str)
            self._save(data)


# -------------------------------------------------------------------------
# THE ODDS API & TELEGRAM INTEGRATION SERVICE
# -------------------------------------------------------------------------
class SportsBettingBot:
    """Núcleo del bot que gestiona las llamadas a APIs, lógica de filtrado y notificaciones."""
    
    def __init__(self):
        self.odds_api_key = os.getenv("ODDS_API_KEY")
        self.bot_token = os.getenv("BOT_TOKEN")
        self.chat_id = os.getenv("CHAT_ID")
        
        self.db = DatabaseManager()
        
        # Ligas autorizadas por la estrategia de inversión
        self.target_sports = [
            "baseball_mlb",
            "soccer_mexico_ligamx",
            "soccer_epl",
            "soccer_spain_la_liga",
            "soccer_germany_bundesliga"
        ]
        
        self.validate_environment()

    def validate_environment(self):
        if not all([self.odds_api_key, self.bot_token, self.chat_id]):
            Logger.error("Faltan variables de entorno obligatorias (ODDS_API_KEY, BOT_TOKEN, CHAT_ID).")
            sys.exit(1)
        Logger.info("Variables de entorno validadas correctamente.")

    def _get_mexico_now(self) -> datetime:
        tz_mx = timezone(timedelta(hours=-6))
        return datetime.now(tz_mx)

    def send_telegram_message(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return True
            Logger.error(f"Error enviando a Telegram: {response.text}")
            return False
        except Exception as e:
            Logger.error(f"Excepción al conectar con Telegram: {e}")
            return False

    def check_and_send_daily_greeting(self):
        """Envía el saludo matutino a partir de las 8:00 AM si no se ha enviado hoy."""
        now = self._get_mexico_now()
        current_date_str = now.strftime("%Y-%m-%d")
        
        if now.hour >= 8:
            if not self.db.has_greeted_today(current_date_str):
                greeting_text = (
                    "☀️ *¡Buenos días, Familia de Inversores!* ☀️\n\n"
                    "El *SniperTipsterBot* ya está activo rastreando valor en los mercados del día.\n\n"
                    "⚠️ *Recordatorio de Gestión de Capital (Bankroll Management):*\n"
                    "• Respeta estrictamente el sistema de Stakes asignado.\n"
                    "• No sobre-arriesgues dinero que necesitas.\n"
                    "• La disciplina a largo plazo es lo que separa a un apostador común de un inversor de élite.\n\n"
                    "¡Vamos por una jornada ganadora! 🎯"
                )
                if self.send_telegram_message(greeting_text):
                    self.db.record_greeting(current_date_str)
                    Logger.info("Saludo matutino diario enviado con éxito.")

    def run_automated_audit(self):
        """Audita picks pendientes consultando marcadores finales recientes."""
        Logger.info("Iniciando auditoría automatizada de resultados...")
        pending_picks = self.db.get_pending_picks()
        if not pending_picks:
            Logger.info("No hay picks pendientes por auditar.")
            return

        # Para optimizar, agrupamos los juegos pendientes por liga
        sports_to_check = list(set([p["sport"] for p in pending_picks]))
        
        for sport in sports_to_check:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/scores/"
            params = {
                "apiKey": self.odds_api_key,
                "daysFrom": 3
            }
            try:
                response = requests.get(url, params=params, timeout=15)
                if response.status_code != 200:
                    Logger.warning(f"No se pudieron obtener scores para {sport}: {response.status_code}")
                    continue
                
                scores_data = response.json()
                for match in scores_data:
                    if match.get("completed") is True:
                        game_id = match.get("id")
                        # Buscamos si tenemos este juego como pendiente
                        for pick in pending_picks:
                            if pick["game_id"] == game_id:
                                # Formatear marcador final
                                scores = match.get("scores", [])
                                score_str = " - ".join([f"{s['name']}: {s['score']}" for s in scores]) if scores else "Completed"
                                self.db.update_pick_status(game_id, "FINALIZADO", score_str)
                                
            except Exception as e:
                Logger.error(f"Error durante la auditoría de {sport}: {e}")

    def calculate_stake(self, odds: int) -> int:
        """Determina el Stake profesional basado en el rango de cuota americana."""
        if -250 <= odds <= -150:
            return 5
        elif -149 <= odds <= -101:
            return 4
        elif 100 <= odds <= 150:
            return 3
        elif 151 <= odds <= 350:
            return 2
        return 0

    def format_league_name(self, sport_key: str) -> str:
        mapping = {
            "baseball_mlb": "⚾ MLB",
            "soccer_mexico_ligamx": "🇲🇽 LIGA MX",
            "soccer_epl": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 PREMIER LEAGUE",
            "soccer_spain_la_liga": "🇪🇸 LA LIGA",
            "soccer_germany_bundesliga": "🇩🇪 BUNDESLIGA"
        }
        return mapping.get(sport_key, sport_key.upper())

    def process_market_odds(self) -> list:
        """Escanea todas las ligas autorizadas buscando picks válidos candidatos."""
        candidate_picks = []
        
        for sport in self.target_sports:
            Logger.info(f"Escaneando mercado para la liga: {sport}")
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
            params = {
                "apiKey": self.odds_api_key,
                "regions": "us,eu", # Revisar múltiples regiones para capturar el mejor mercado
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american"
            }
            
            try:
                response = requests.get(url, params=params, timeout=15)
                if response.status_code != 200:
                    Logger.error(f"Error de API al consultar odds de {sport}: {response.status_code}")
                    continue
                
                games = response.json()
                for game in games:
                    game_id = game.get("id")
                    
                    # Candado de No-Contradicción inmediato
                    if self.db.is_game_blocked(game_id):
                        continue
                        
                    home_team = game.get("home_team")
                    away_team = game.get("away_team")
                    commence_time_str = game.get("commence_time")
                    
                    # Determinar si el partido está en vivo de forma básica basándonos en la hora de inicio
                    # O bien, si la API ya no devuelve mercados pre-match estándar.
                    # Convertir hora de inicio a objeto datetime UTC
                    commence_time = datetime.strptime(commence_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    now_utc = datetime.now(timezone.utc)
                    
                    is_live = now_utc >= commence_time
                    
                    # Procesar cuotas del primer bookmaker disponible que tenga mercados válidos
                    bookmakers = game.get("bookmakers", [])
                    if not bookmakers:
                        continue
                    
                    # Usamos el primero de la lista (suele ser el de mayor liquidez o el configurado por defecto)
                    bookmaker = bookmakers[0]
                    bookmaker_name = bookmaker.get("title")
                    
                    for market in bookmaker.get("markets", []):
                        market_key = market.get("key") # h2h, spreads, totals
                        outcomes = market.get("outcomes", [])
                        
                        for outcome in outcomes:
                            odds = outcome.get("price")
                            if odds is None:
                                continue
                                
                            # Convertir a entero para evaluar rangos de forma segura
                            try:
                                odds_int = int(odds)
                            except ValueError:
                                continue
                            
                            # Filtro estricto de momios profesionales (-250 a +350)
                            if -250 <= odds_int <= 350:
                                stake = self.calculate_stake(odds_int)
                                if stake == 0:
                                    continue
                                
                                # Estructurar nombre del Pick de forma clara
                                pick_name = outcome.get("name")
                                if "point" in outcome:
                                    pick_name = f"{pick_name} ({outcome.get('point')})"
                                
                                candidate_picks.append({
                                    "game_id": game_id,
                                    "sport": sport,
                                    "home_team": home_team,
                                    "away_team": away_team,
                                    "commence_time": commence_time,
                                    "market_key": market_key,
                                    "pick_name": pick_name,
                                    "odds": odds_int,
                                    "stake": stake,
                                    "bookmaker": bookmaker_name,
                                    "is_live": is_live
                                })
                                
            except Exception as e:
                Logger.error(f"Error procesando {sport}: {e}")
                
        return candidate_picks

    def fetch_live_score(self, sport: str, game_id: str) -> str:
        """Busca el marcador actual en vivo de un partido en curso."""
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/scores/"
        params = {"apiKey": self.odds_api_key, "daysFrom": 1}
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                for match in res.json():
                    if match.get("id") == game_id:
                        scores = match.get("scores", [])
                        if scores:
                            return " | ".join([f"{s['name']}: {s['score']}" for s in scores])
        except Exception as e:
            Logger.error(f"Error consultando live score: {e}")
        return "Marcador No Disponible"

    def execute_cycle(self):
        """Ejecuta un ciclo completo de análisis, filtrado y envío de alertas."""
        now_mx = self._get_mexico_now()
        current_date_str = now_mx.strftime("%Y-%m-%d")
        
        # 1. Ejecutar Saludo Diario si corresponde
        self.check_and_send_daily_greeting()
        
        # 2. Auditoría Automatizada de Partidos Anteriores
        self.run_automated_audit()
        
        # 3. Validar Tope Diario de 4 Picks Máximo en el transcurso del día
        sent_today = self.db.get_picks_by_date(current_date_str)
        if len(sent_today) >= 4:
            Logger.warning(f"Tope diario alcanzado ({len(sent_today)}/4 picks enviados). Escaneo suspendido hasta mañana.")
            return

        Logger.info(f"Iniciando escaneo de mercados. Picks enviados hoy: {len(sent_today)}/4")
        
        # 4. Obtener todos los candidatos de valor
        candidates = self.process_market_odds()
        if not candidates:
            Logger.info("No se encontraron oportunidades con valor estadístico en este ciclo.")
            return

        # 5. Priorización Avanzada: Ordenar por mayor Stake (mayor probabilidad/valor)
        candidates.sort(key=lambda x: x["stake"], reverse=True)
        best_pick = candidates[0]
        
        # Doble verificación por seguridad contra colisiones en hilos o bases de datos aceleradas
        if self.db.is_game_blocked(best_pick["game_id"]):
            return

        # Ajustar marcador si es LIVE
        live_score_text = ""
        if best_pick["is_live"]:
            live_score_text = self.fetch_live_score(best_pick["sport"], best_pick["game_id"])

        # Convertir horario UTC del partido a horario de México para la plantilla del mensaje
        tz_mx = timezone(timedelta(hours=-6))
        match_time_mx = best_pick["commence_time"].withtzinfo(timezone.utc).astimezone(tz_mx)
        time_formatted = match_time_mx.strftime("%I:%M %p")

        # Mapear el nombre del mercado técnico a términos legibles en español
        market_mapping = {
            "h2h": "Línea de Dinero (Ganador)",
            "totals": "Totales (Altas/Bajas)",
            "spreads": "Hándicap"
        }
        market_es = market_mapping.get(best_pick["market_key"], best_pick["market_key"].upper())

        # 6. Construir Plantilla Premium de Telegram en Markdown
        alert_type_header = "🚨 *SNIPER LIVE ALERT* 🚨" if best_pick["is_live"] else "🎯 *SNIPER PRE-MATCH ALERT* 🎯"
        
        message_body = (
            f"{alert_type_header}\n\n"
            f"🏆 *Liga:* {self.format_league_name(best_pick['sport'])}\n"
            f"⚔️ *Partido:* {best_pick['away_team']} vs {best_pick['home_team']}\n"
            f"⏰ *Horario (MX):* {time_formatted}\n"
        )
        
        if best_pick["is_live"]:
            message_body += f"📊 *Marcador en Vivo:* `{live_score_text}`\n"
            
        message_body += (
            f"📈 *Mercado:* {market_es}\n\n"
            f"🔥 *Pick Recomendado:* `{best_pick['pick_name']}`\n"
            f"💰 *Momio/Cuota:* `{best_pick['odds']}`\n"
            f"🏛️ *Casa de Apuestas:* {best_pick['bookmaker']}\n\n"
            f"💎 *STAKE SUGERIDO:* `Stake {best_pick['stake']}/10`\n\n"
            f"⚠️ _Invierta con responsabilidad. Controle su banca._"
        )

        # 7. Envío y registro definitivo del Pick
        if self.send_telegram_message(message_body):
            self.db.save_pick(
                game_id=best_pick["game_id"],
                sport=best_pick["sport"],
                home_team=best_pick["home_team"],
                away_team=best_pick["away_team"],
                market=market_es,
                pick_name=best_pick["pick_name"],
                odds=best_pick["odds"],
                stake=best_pick["stake"],
                sent_date=current_date_str
            )
            Logger.info(f"Alerta enviada exitosamente a Telegram para el partido: {best_pick['away_team']} vs {best_pick['home_team']}")


# -------------------------------------------------------------------------
# MAIN EXECUTION LOOP
# -------------------------------------------------------------------------
def main():
    Logger.info("Iniciando SniperTipsterBot - Motor de Inversión de Élite.")
    bot = SportsBettingBot()
    
    # Bucle infinito controlado cada 15 minutos (900 segundos) para Render
    while True:
        try:
            bot.execute_cycle()
        except Exception as e:
            Logger.error(f"Error crítico no controlado en el bucle principal: {e}")
            
        Logger.info("Ciclo finalizado. Esperando 15 minutos para el siguiente escaneo...")
        time.sleep(900)

if __name__ == "__main__":
    main()
