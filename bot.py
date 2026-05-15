import os
import time
import requests
import sys

def log(msg):
    print(msg)
    sys.stdout.flush()

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            log("📱 [Telegram] ¡Mensaje de alerta enviado con éxito!")
        else:
            log(f"❌ [Telegram] Error al enviar: {res.status_code} - {res.text}")
    except Exception as e:
        log(f"❌ [Telegram] Error de conexión: {e}")

def buscar_apuestas(api_key, bot_token, chat_id):
    # Monitoreamos MLB y Liga MX (para cuando haya partidos)
    sports = ["baseball_mlb", "soccer_mexico_ligamx"]
    
    for sport in sports:
        log(f"🔍 Escaneando cuotas para: {sport}...")
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions=us,eu&markets=h2h"
        
        try:
            res = requests.get(url, timeout=15)
            if res.status_code != 200:
                log(f"⚠️ API no respondió bien para {sport}: Código {res.status_code}")
                continue
            
            partidos = res.json()
            
            for partido in partidos:
                home_team = partido.get("home_team")
                away_team = partido.get("away_team")
                bookmakers = partido.get("bookmakers", [])
                
                # Necesitamos al menos 3 casinos para poder sacar un promedio real
                if len(bookmakers) < 3:
                    continue
                
                odds_home = []
                odds_away = []
                
                # Extraemos los momios de cada casino
                for bookie in bookmakers:
                    for market in bookie.get("markets", []):
                        if market.get("key") == "h2h":
                            for outcome in market.get("outcomes", []):
                                if outcome.get("name") == home_team:
                                    odds_home.append((bookie.get("title"), outcome.get("price")))
                                elif outcome.get("name") == away_team:
                                    odds_away.append((bookie.get("title"), outcome.get("price")))
                
                if not odds_home or not odds_away:
                    continue
                
                # Calculamos el promedio del mercado
                avg_home = sum([o[1] for o in odds_home]) / len(odds_home)
                avg_away = sum([o[1] for o in odds_away]) / len(odds_away)
                
                # REGLA DEL 3%: Si un casino ofrece un momio 3% más alto que el promedio, se manda
                for casino, precio in odds_home:
                    ventaja = (precio / avg_home) - 1
                    if ventaja >= 0.03: 
                        msg = (
                            f"🚨 *¡PICK DE VALOR ENCONTRADO!* 🚨\n\n"
                            f"⚾️ *Deporte:* {sport.replace('_', ' ').upper()}\n"
                            f"⚔️ *Partido:* {away_team} vs {home_team}\n"
                            f"🎯 *Apuesta:* Gana {home_team} (Local)\n"
                            f"🏛 *Casino:* {casino}\n"
                            f"📈 *Momio Ofrecido:* {precio}\n"
                            f"📊 *Promedio Mercado:* {avg_home:.2f}\n"
                            f"💰 *Ventaja Real:* {ventaja*100:.1f}%"
                        )
                        send_telegram(bot_token, chat_id, msg)
                        
                for casino, precio in odds_away:
                    ventaja = (precio / avg_away) - 1
                    if ventaja >= 0.03:
                        msg = (
                            f"🚨 *¡PICK DE VALOR ENCONTRADO!* 🚨\n\n"
                            f"⚾️ *Deporte:* {sport.replace('_', ' ').upper()}\n"
                            f"⚔️ *Partido:* {away_team} vs {home_team}\n"
                            f"🎯 *Apuesta:* Gana {away_team} (Visitante)\n"
                            f"🏛 *Casino:* {casino}\n"
                            f"📈 *Momio Ofrecido:* {precio}\n"
                            f"📊 *Promedio Mercado:* {avg_away:.2f}\n"
                            f"💰 *Ventaja Real:* {ventaja*100:.1f}%"
                        )
                        send_telegram(bot_token, chat_id, msg)
                        
        except Exception as e:
            log(f"❌ Error procesando datos de {sport}: {e}")

def main():
    log("------------------------------------------")
    log("🚀 BOT ACTIVADO - MODO FRANCOTIRADOR")
    log("------------------------------------------")
    
    api_key = os.getenv("ODDS_API_KEY")
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    
    if not api_key or not bot_token or not chat_id:
        log("❌ ERROR CRÍTICO: Faltan variables de entorno en Render.")
        return

    while True:
        try:
            # Revisamos rápido los créditos consumidos
            url = f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}"
            res = requests.get(url, timeout=15)
            if res.status_code == 200:
                creditos = res.headers.get('x-requests-remaining')
                log(f"📡 API Conectada. Créditos restantes: {creditos}")
                
                # Ejecutamos el buscador real
                buscar_apuestas(api_key, bot_token, chat_id)
            else:
                log(f"⚠️ Error de conexión con API: {res.status_code}")
        except Exception as e:
            log(f"❌ Error en ciclo principal: {e}")
            
        log("😴 Escaneo terminado. Pausa de 5 minutos...")
        time.sleep(300)

if __name__ == "__main__":
    main()
