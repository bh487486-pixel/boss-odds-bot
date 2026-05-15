import os
import time
import random
import logging
from datetime import datetime
import pytz
import requests

# Configuración de Logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# Variables de Entorno
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Configuración de The Odds API
API_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
REGIONS = "us,eu,uk" 
MARKETS = "h2h,totals"

# CONFIGURACIÓN PERSONALIZADA
UMBRAL_VALOR = 1.04         # Cambiado a 4% (para 3% usa 1.03)
ENVIO_INTERVALO = 300       # 5 minutos
ACTUALIZAR_API_INTERVALO = 1800 

TZ_MEXICO = pytz.timezone("America/Mexico_City")

cache_picks_valor = []
ultimo_analisis_api = 0
picks_enviados = set()

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def escanear_mercado_en_busca_de_valor():
    global cache_picks_valor, ultimo_analisis_api
    ahora = time.time()
    
    if cache_picks_valor and (ahora - ultimo_analisis_api < ACTUALIZAR_API_INTERVALO):
        return cache_picks_valor

    if not ODDS_API_KEY:
        return []

    try:
        response = requests.get(f"{API_URL}?apiKey={ODDS_API_KEY}&regions={REGIONS}&markets={MARKETS}&oddsFormat=decimal", timeout=15)
        if response.status_code != 200:
            return cache_picks_valor

        partidos = response.json()
        encontramos_valor = []

        for partido in partidos:
            id_partido = partido.get("id")
            home_team = partido.get("home_team")
            away_team = partido.get("away_team")
            sport_title = partido.get("sport_title")
            
            # --- NUEVO: OBTENER HORA DE INICIO ---
            commence_time_raw = partido.get("commence_time") # UTC
            dt_utc = datetime.strptime(commence_time_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            dt_mx = dt_utc.astimezone(TZ_MEXICO)
            hora_inicio_partido = dt_mx.strftime("%H:%M")

            bookmakers = partido.get("bookmakers", [])
            if len(bookmakers) < 3: continue

            precios_local, precios_visita, precios_over = [], [], []

            for bookie in bookmakers:
                for market in bookie.get("markets", []):
                    if market["key"] == "h2h":
                        for outcome in market["outcomes"]:
                            if outcome["name"] == home_team: precios_local.append((bookie["title"], outcome["price"]))
                            elif outcome["name"] == away_team: precios_visita.append((bookie["title"], outcome["price"]))
                    elif market["key"] == "totals":
                        for outcome in market["outcomes"]:
                            if outcome["name"] == "Over" and outcome.get("point") == 2.5:
                                precios_over.append((bookie["title"], outcome["price"]))

            def analizar_mercado(lista_precios, tipo_pick):
                if not lista_precios: return None
                solo_valores = [p[1] for p in lista_precios]
                promedio = sum(solo_valores) / len(solo_valores)
                for casa, precio in lista_precios:
                    # USANDO EL NUEVO UMBRAL DE 4%
                    if precio > (promedio * UMBRAL_VALOR): 
                        return {
                            "id": f"{id_partido}_{tipo_pick}",
                            "evento": f"{home_team} vs {away_team}",
                            "liga": sport_title,
                            "pick": f"{tipo_pick} (Momio: {precio})",
                            "casa_error": casa,
                            "promedio_mercado": round(promedio, 2),
                            "ventaja": round(((precio - promedio) / promedio) * 100, 1),
                            "hora_partido": hora_inicio_partido
                        }
                return None

            for mercado, nombre in [(precios_local, f"Local: {home_team}"), 
                                    (precios_visita, f"Visita: {away_team}"), 
                                    (precios_over, "Over 2.5 Goles")]:
                res = analizar_mercado(mercado, nombre)
                if res: encontramos_valor.append(res)

        cache_picks_valor = encontramos_valor
        ultimo_analisis_api = ahora
        return cache_picks_valor
    except:
        return cache_picks_valor

def procesar_y_enviar_alerta():
    global picks_enviados
    alertas = escanear_mercado_en_busca_de_valor()
    hora_cdmx = datetime.now(TZ_MEXICO).strftime("%H:%M")

    disponibles = [a for a in alertas if a["id"] not in picks_enviados]
    if not disponibles: return 

    alerta = max(disponibles, key=lambda x: x["ventaja"])
    picks_enviados.add(alerta["id"])

    # Stake dinámico según la ventaja
    v = alerta["ventaja"]
    stake = 4 if v < 5 else (5 if v < 10 else 6)

    mensaje = (
        "🚀 *NUEVA OPORTUNIDAD DETECTADA* 🚀\n"
        "─────────────────────\n"
        f"⚽ *Evento:* {alerta['evento']}\n"
        f"🏆 *Liga:* {alerta['liga']}\n"
        f"⏰ *Inicia (CDMX):* {alerta['hora_partido']}\n\n"
        "➡️ *Pick:*\n"
        f"• {alerta['pick']}\n\n"
        f"🏛️ *Casa:* {alerta['casa_error']}\n"
        f"📊 *Promedio Mercado:* {alerta['promedio_mercado']}\n"
        f"📈 *Ventaja:* +{alerta['ventaja']}%\n\n"
        f"➡️ *Stake Sugerido:* {stake}/10\n\n"
        f"🕒 *Escaneado a las:* {hora_cdmx}"
    )
    enviar_telegram(mensaje)

def main():
    logging.info("Bot actualizado: Umbral 4% + Hora de partido.")
    while True:
        try:
            start_time = time.time()
            procesar_y_enviar_alerta()
            sleep_time = max(0, ENVIO_INTERVALO - (time.time() - start_time))
            time.sleep(sleep_time)
        except:
            time.sleep(60)

if __name__ == "__main__":
    main()
