import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta, timezone

class Logger:
    @staticmethod
    def log(message):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
        sys.stdout.flush()

class SniperBot:
    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")
        self.bot_token = os.getenv("BOT_TOKEN")
        self.chat_id = os.getenv("CHAT_ID")
        
        if not self.api_key or not self.bot_token or not self.chat_id:
            Logger.log("❌ Error: Faltan variables de entorno.")
            sys.exit(1)
            
        self.db_file = "database.json"
        self.enviados = self.cargar_db()
        
        # Ligas clásicas configuradas
        self.ligas = [
            "baseball_mlb",
            "soccer_mexico_ligamx",
            "soccer_epl",
            "soccer_spain_la_liga",
            "soccer_germany_bundesliga"
        ]

    def cargar_db(self):
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r") as f:
                    return json.load(f)
            except:
                return []
        return []

    def guardar_db(self):
        with open(self.db_file, "w") as f:
            json.dump(self.enviados, f, indent=4)

    def enviar_telegram(self, texto):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": texto, "parse_mode": "Markdown"}
        try:
            res = requests.post(url, json=payload, timeout=10)
            return res.status_code == 200
        except Exception as e:
            Logger.log(f"Error enviando a Telegram: {e}")
            return False

    def obtener_cuotas(self, liga):
        url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/?apiKey={self.api_key}&regions=us&markets=h2h,totals&oddsFormat=american"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                return res.json()
            else:
                Logger.log(f"Error API {liga}: Código {res.status_code}")
        except Exception as e:
            Logger.log(f"Error de conexión en API: {e}")
        return []

    def procesar_partidos(self):
        Logger.log("🔍 Iniciando escaneo de partidos...")
        
        for liga in self.ligas:
            partidos = self.obtener_cuotas(liga)
            time.sleep(1) # Evitar saturar la API consecutivamente
            
            for partido in partidos:
                id_partido = partido.get("id")
                
                # Si el partido ya se mandó hoy, lo saltamos
                if id_partido in self.enviados:
                    continue
                    
                home_team = partido.get("home_team")
                away_team = partido.get("away_team")
                bookmakers = partido.get("bookmakers", [])
                
                if not bookmakers:
                    continue
                    
                # Tomamos la primera casa de apuestas disponible
                bookie = bookmakers[0]
                markets = bookie.get("markets", [])
                
                for market in markets:
                    if market.get("key") == "h2h":
                        outcomes = market.get("outcomes", [])
                        if len(outcomes) >= 2:
                            # Estructura del pick clásico
                            home_odds = outcomes[0].get("price")
                            away_odds = outcomes[1].get("price")
                            
                            # Formatear momios visuales
                            h_txt = f"+{home_odds}" if home_odds > 0 else str(home_odds)
                            a_txt = f"+{away_odds}" if away_odds > 0 else str(away_odds)
                            
                            mensaje = (
                                f"🎯 *¡NUEVO PICK DETECTADO!* 🎯\n\n"
                                f"🏆 *Liga:* {liga.replace('_', ' ').upper()}\n"
                                f"⚔️ *Partido:* {away_team} vs {home_team}\n"
                                f"🏛️ *Casa:* {bookie.get('title')}\n\n"
                                f"🔥 *Opciones disponibles:*\n"
                                f"• Gana Local ({home_team}): `{h_txt}`\n"
                                f"• Gana Visitante ({away_team}): `{a_txt}`\n\n"
                                f"🤖 _Analizado por SniperBot_"
                            )
                            
                            if self.enviar_telegram(mensaje):
                                Logger.log(f"🚀 Pick enviado para el partido: {away_team} vs {home_team}")
                                self.enviados.append(id_partido)
                                self.guardar_db()
                                return # Manda uno solo y rompe para esperar al siguiente ciclo

    def run(self):
        # El bucle de toda la vida que tenías configurado antes
        while True:
            try:
                self.procesar_partidos()
            except Exception as e:
                Logger.log(f"💥 Error en el ciclo: {e}")
            
            Logger.log("💤 Esperando 10 minutos para el siguiente escaneo...")
            time.sleep(600)

if __name__ == "__main__":
    bot = SniperBot()
    bot.run()
