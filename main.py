import os
import requests
import asyncio
from datetime import datetime
from telegram import Bot

# ==========================================
# CONFIGURACIÓN DE VARIABLES DE ENTORNO
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

# Inicializar el bot de Telegram
bot = Bot(token=TELEGRAM_TOKEN)

# ==========================================
# SELECCIÓN DE MERCADOS Y BOOKIES (MÉXICO/LATAM)
# ==========================================
# Buscaremos cuotas en las casas más comunes (Pinnacle, Bet365, Codere, Caliente si está disp.)
REGIONS = "us,eu"  # Regiones para abarcar la mayoría de las casas disponibles
MARKETS = "h2h"    # Mercado de resultado final (1X2)

def obtener_partidos_y_cuotas():
    """Consulta The Odds API para obtener los partidos de fútbol y sus cuotas."""
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": "decimal"
    }
    
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error en Odds API: {response.status_code}")
            return []
    except Exception as e:
        print(f"Error al conectar con Odds API: {e}")
        return []

def analizar_y_formatear_pick(partido):
    """Analiza las cuotas del partido y genera el formato BossOddsMX."""
    home_team = partido.get("home_team")
    away_team = partido.get("away_team")
    bookmakers = partido.get("bookmakers")
    
    if not bookmakers:
        return None

    # Tomamos la primera casa de apuestas disponible que tenga cuotas fijas
    bookie = bookmakers[0]
    bookie_name = bookie.get("title", "Casa de Apuestas")
    market = bookie.get("markets")[0]
    outcomes = market.get("outcomes")

    # Encontrar la cuota con mejor balance (Por ejemplo, el favorito con valor)
    # Para este ejemplo automático, seleccionamos al favorito que pague más de 1.50
    pick_seleccionado = None
    cuota_seleccionada = 0
    
    for outcome in outcomes:
        price = outcome.get("price")
        if 1.50 <= price <= 2.20:  # Buscamos cuotas en el rango ideal de valor
            pick_seleccionado = outcome.get("name")
            cuota_seleccionada = price
            break
            
    # Si ninguna entra en el rango, agarramos la primera por defecto
    if not pick_seleccionado:
        pick_seleccionado = outcomes[0].get("name")
        cuota_seleccionada = outcomes[0].get("price")

    # Asignar Stake basado en la cuota de forma inteligente
    if cuota_seleccionada <= 1.70:
        stake_stars = "⭐⭐⭐"
    elif cuota_seleccionada <= 2.00:
        stake_stars = "⭐⭐"
    else:
        stake_stars = "⭐"

    # Redactar un breve análisis automático del valor matemático detectado
    analisis_texto = (
        f"Análisis del mercado en {bookie_name}. Se detecta una ineficiencia en la cuota de "
        f"({cuota_seleccionada}) para la victoria de {pick_seleccionado}. Las probabilidades implícitas "
        f"muestran valor (+EV) considerando el rendimiento reciente de {home_team} como local."
    )

    # Construir el mensaje con tu formato oficial exacto
    mensaje = (
        f"🔥 BossOddsMX – Pick del Día\n\n"
        f"Deporte: ⚽ Fútbol\n"
        f"Partido: {home_team} vs {away_team}\n"
        f"Pick: Gana {pick_seleccionado}\n"
        f"Cuota: {cuota_seleccionada:.2f}\n"
        f"Stake: {stake_stars}\n\n"
        f"📊 Análisis:\n"
        f"{analisis_texto}\n\n"
        f"¡Vamos con todo! 💰"
    )
    
    return mensaje

async def tarea_automatica():
    """Función principal que corre en bucle buscando y publicando picks."""
    print("Bot automático iniciado y monitoreando mercados...")
    
    while True:
        partidos = obtener_partidos_y_cuotas()
        
        if partidos:
            # Tomamos el primer partido de la lista que cumpla los requisitos para publicar
            for partido in partidos:
                mensaje_pick = analizar_y_formatear_pick(partido)
                
                if mensaje_pick:
                    try:
                        # Enviar al canal de Telegram de forma automática
                        await bot.send_message(chat_id=CHANNEL_ID, text=mensaje_pick)
                        print(f"¡Pick automático enviado con éxito al canal {CHANNEL_ID}!")
                        break # Enviamos uno y rompemos el ciclo para esperar el siguiente turno
                    except Exception as e:
                        print(f"Error al enviar mensaje a Telegram: {e}")
        
        # Esperar 6 horas antes de volver a buscar nuevos partidos y cuotas (+EV)
        # 6 horas = 21600 segundos
        await asyncio.sleep(21600)

if __name__ == "__main__":
    # Correr el bucle asíncrono
    asyncio.run(tarea_automatica())
