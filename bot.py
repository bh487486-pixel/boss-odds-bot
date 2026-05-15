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

# Variables de Entorno (Configurar en Render)
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Configuración de The Odds API
# Usamos 'h2h' (ganador) y 'totals' (over/under) de las casas de apuestas disponibles
API_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
REGIONS = "us,eu,uk"  # Incluye casas internacionales y americanas relevantes
MARKETS = "h2h,totals"

# Tiempos de control (Render Loop)
ENVIO_INTERVALO = 300       # Intenta enviar/buscar cada 5 minutos
ACTUALIZAR_API_INTERVALO = 1800 # Consulta la API cada 30 minutos para cuidar créditos

TZ_MEXICO = pytz.timezone("America/Mexico_City")

# Caché global
cache_picks_valor = []
ultimo_analisis_api = 0
picks_enviados = set()

def enviar_telegram(mensaje):
    """Envía las alertas de valor directamente a Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Faltan credenciales de Telegram en las variables de entorno.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logging.info("Alerta de valor enviada a Telegram.")
        else:
            logging.error(f"Error Telegram: {response.text}")
    except Exception as e:
        logging.error(f"Error de red con Telegram: {e}")

def escanear_mercado_en_busca_de_valor():
    """Analiza las cuotas del mercado buscando discrepancias de valor."""
    global cache_picks_valor, ultimo_analisis_api
    
    ahora = time.time()
    if cache_picks_valor and (ahora - ultimo_analisis_api < ACTUALIZAR_API_INTERVALO):
        return cache_picks_valor

    if not ODDS_API_KEY:
        logging.error("Falta ODDS_API_KEY.")
        return []

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": "decimal"
    }

    logging.info("Escaneando el mercado de casas de apuestas internacionales...")
    try:
        # Analizamos las ligas principales de fútbol disponibles en el día
        response = requests.get(f"{API_URL}?apiKey={ODDS_API_KEY}&regions={REGIONS}&markets={MARKETS}&oddsFormat=decimal", timeout=15)
        
        if response.status_code != 200:
            logging.error(f"Error en The Odds API: {response.status_code}")
            return cache_picks_valor

        partidos = response.json()
        encontramos_valor = []

        for partido in partidos:
            id_partido = partido.get("id")
            home_team = partido.get("home_team")
            away_team = partido.get("away_team")
            sport_title = partido.get("sport_title")
            bookmakers = partido.get("bookmakers", [])

            if len(bookmakers) < 3: 
                continue # Necesitamos al menos 3 casas para comparar y promediar

            # Diccionarios para acumular momios de este partido
            precios_local = []
            precios_visita = []
            precios_over = []

            for bookie in bookmakers:
                for market in bookie.get("markets", []):
                    if market["key"] == "h2h":
                        for outcome in market["outcomes"]:
                            if outcome["name"] == home_team:
                                precios_local.append((bookie["title"], outcome["price"]))
                            elif outcome["name"] == away_team:
                                precios_visita.append((bookie["title"], outcome["price"]))
                    
                    elif market["key"] == "totals":
                        for outcome in market["outcomes"]:
                            if outcome["name"] == "Over" and outcome.get("point") == 2.5:
                                precios_over.append((bookie["title"], outcome["price"]))

            # --- LÓGICA DE DETECCIÓN DE VALOR (DISCREPANCIA DE CUOTAS) ---
            # Si una casa paga significativamente más que el promedio del mercado, hay valor/error de línea.
            def analizar_mercado(lista_precios, tipo_pick):
                if not lista_precios: return None
                solo_valores = [p[1] for p in lista_precios]
                promedio = sum(solo_valores) / len(solo_valores)
                
                for casa, precio in lista_precios:
                    # Si el momio de esta casa es un 8% o más alto que el promedio, se considera un error/valor comercial
                    if precio > (promedio * 1.08): 
                        return {
                            "id": f"{id_partido}_{tipo_pick}",
                            "evento": f"{home_team} vs {away_team}",
                            "liga": sport_title,
                            "pick": f"{tipo_pick} (Momio: {precio})",
                            "casa_error": casa,
                            "promedio_mercado": round(promedio, 2),
                            "ventaja": round(((precio - promedio) / promedio) * 100, 1)
                        }
                return None

            # Escanear los 3 mercados principales de este partido
            for mercado, nombre in [(precios_local, f"Ganador Local: {home_team}"), 
                                    (precios_visita, f"Ganador Visitante: {away_team}"), 
                                    (precios_over, "Over 2.5 Goles")]:
                res = analizar_mercado(mercado, nombre)
                if res:
                    encontramos_valor.append(res)

        cache_picks_valor = encontramos_valor
        ultimo_analisis_api = ahora
        logging.info(f"Escaneo terminado. Se detectaron {len(cache_picks_valor)} oportunidades de valor.")
        return cache_picks_valor

    except Exception as e:
        logging.error(f"Error procesando el escaneo de mercado: {e}")
        return cache_picks_valor

def procesar_y_enviar_alerta():
    """Filtra las alertas encontradas y envía la mejor opción sin repetir."""
    global picks_enviados
    
    alertas = escanear_mercado_en_busca_de_valor()
    hora_cdmx = datetime.now(TZ_MEXICO).strftime("%H:%M")

    # Filtrar las que no se han mandado aún
    disponibles = [a for a in alertas if a["id"] not in picks_enviados]

    if not disponibles:
        # Si no hay errores de línea reales detectados en este ciclo
        logging.info("No se encontraron ineficiencias de cuotas en este bloque.")
        return 

    # Tomamos la ineficiencia que tenga la mayor ventaja matemática sobre el mercado
    alerta_seleccionada = max(disponibles, key=lambda x: x["ventaja"])
    picks_enviados.add(alerta_seleccionada["id"])

    # El stake se calcula matemáticamente basado en la ventaja detectada (Mayor ventaja = Mayor confianza)
    ventaja = alerta_seleccionada["ventaja"]
    if ventaja > 15: stake = 7
    elif ventaja > 10: stake = 6
    else: stake = 5

    mensaje = (
        "🔥 *ALERTA DE VALOR DETECTADA* 🔥\n"
        "─────────────────────\n"
        f"🎯 *Evento:* {alerta_seleccionada['evento']}\n"
        f"🏆 *Deporte/Liga:* {alerta_seleccionada['liga']}\n\n"
        "➡️ *Pick Recomendado:*\n"
        f"• {alerta_seleccionada['pick']}\n\n"
        f"⚠️ *Error de Línea en:* {alerta_seleccionada['casa_error']}\n"
        f"📊 *Promedio General:* {alerta_seleccionada['promedio_mercado']}\n"
        f"📈 *Ventaja Matemática:* +{ventaja}%\n\n"
        f"➡️ *Stake Sugerido:* {stake}/10\n\n"
        f"🕒 *Hora Escaneo CDMX:* {hora_cdmx}"
    )

    enviar_telegram(mensaje)

def main():
    logging.info("Bot de Ineficiencias de Mercado Iniciado con éxito.")
    while True:
        try:
            start_time = time.time()
            procesar_y_enviar_alerta()
            
            elapsed = time.time() - start_time
            sleep_time = max(0, ENVIO_INTERVALO - elapsed)
            time.sleep(sleep_time)
            
        except Exception as e:
            logging.error(f"Error en bucle principal: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
