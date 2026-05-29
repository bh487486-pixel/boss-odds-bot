import os
import requests
import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from telegram import Bot
import google.generativeai as genai

# ==========================================
# 1. CONFIGURACIÓN Y CREDENCIALES
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not all([TELEGRAM_TOKEN, CHANNEL_ID, ODDS_API_KEY, GEMINI_API_KEY]):
    logger.error("Faltan variables de entorno. Verifica Render.")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash') 
bot = Bot(token=TELEGRAM_TOKEN)
MX_TZ = timezone(timedelta(hours=-6))

# ==========================================
# 2. RADARES DE LIGAS 
# ==========================================
LIGAS_FUTBOL = [
    "soccer_uefa_champions_league", "soccer_epl", "soccer_spain_la_liga", 
    "soccer_italy_serie_a", "soccer_germany_bundesliga", "soccer_mexico_ligamx", 
    "soccer_usa_mls", "soccer_conmebol_copa_libertadores", "soccer_conmebol_copa_sudamericana"
]
LIGAS_BEISBOL = ["baseball_mlb", "baseball_lmb"]
LIGAS_TODAS = LIGAS_FUTBOL + LIGAS_BEISBOL + ["tennis_atp_wimbledon", "basketball_nba"]

# ==========================================
# 3. EXTRACCIÓN DE DATOS (DEL DÍA)
# ==========================================
def obtener_mercados(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=us,eu&markets=h2h,spreads,totals&oddsFormat=decimal"
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            return res.json()
        return []
    except Exception as e:
        logger.error(f"Error conectando a API para {sport_key}: {e}")
        return []

def recolectar_cartelera(lista_ligas):
    """Junta todos los partidos disponibles ESTRICTAMENTE para EL DÍA DE HOY."""
    cartelera = []
    hoy_mx_fecha = datetime.now(MX_TZ).date() 

    for liga in lista_ligas:
        datos = obtener_mercados(liga)
        for partido in datos:
            try:
                fecha_utc = datetime.strptime(partido['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                fecha_mx = fecha_utc.astimezone(MX_TZ)
                
                # Filtro estricto: Solo si la fecha coincide con el día de hoy en México
                if fecha_mx.date() == hoy_mx_fecha:
                    cartelera.append(partido)
            except:
                pass
    return cartelera

# ==========================================
# 4. CEREBRO IA: TIPSTER PROFESIONAL
# ==========================================
def analizar_con_ia(cartelera, cantidad, es_stake_10=False):
    if not cartelera:
        return []

    datos_crudos = json.dumps(cartelera)[:25000] 

    if es_stake_10:
        instruccion = f"""
        Eres 'El Boss mexa', un tipster deportivo profesional y agresivo pero muy analítico.
        Analiza los siguientes datos JSON de cuotas de apuestas.
        Encuentra EL MEJOR ÚNICO PICK del día de hoy (La jugada segura, Stake 10). 
        Busca el mayor +EV (Valor Esperado) ya sea en ganador directo, hándicap o Over/Under. 
        Menciona la cuota disponible de manera neutral, sin atarla a ninguna casa de apuestas.
        """
    else:
        instruccion = f"""
        Eres 'El Boss mexa', un tipster deportivo profesional.
        Analiza estos datos JSON de cuotas. Selecciona estrictamente los {cantidad} picks con mayor probabilidad de éxito y valor (+EV) para el día de hoy.
        Evalúa mercados como Ganador Directo (h2h), Hándicap Asiático/Spread, y Altas/Bajas (Totals).
        Menciona la cuota disponible de manera neutral, sin atarla a ninguna casa de apuestas.
        """

    formato = """
    DEVUELVE ESTRICTAMENTE UN ARREGLO JSON CON ESTA ESTRUCTURA (SIN MARKDOWN NI TEXTO EXTRA):
    [
      {
        "deporte": "⚽ Fútbol (o ⚾ Béisbol, etc)",
        "partido": "Equipo A vs Equipo B",
        "pick": "Tu predicción exacta (Ej. Gana Equipo A, Over 2.5, Hándicap -1.5)",
        "cuota": 1.85,
        "stake": 3, 
        "analisis": "Análisis estadístico profesional de 2 líneas justificando el valor."
      }
    ]
    """
    
    prompt = instruccion + formato + "\n\nDATOS DE HOY:\n" + datos_crudos

    try:
        respuesta = model.generate_content(prompt)
        texto = respuesta.text.strip().replace("```json", "").replace("
```", "")
        return json.loads(texto)
    except Exception as e:
        logger.error(f"Error de Gemini al procesar picks: {e}")
        return []

# ==========================================
# 5. FORMATEADOR OFICIAL (EL BOSS MEXA)
# ==========================================
def formatear_mensaje(pick):
    estrellas = "⭐" * int(pick.get("stake", 3))
    
    msj = f"🔥 El Boss mexa – Pick del Día\n\n"
    msj += f"Deporte: {pick.get('deporte', 'Deporte')}\n"
    msj += f"Partido: {pick.get('partido', 'Partido no especificado')}\n"
    msj += f"Pick: {pick.get('pick', 'Selección de valor')}\n"
    msj += f"Cuota: {float(pick.get('cuota', 1.50)):.2f}\n"
    msj += f"Stake: {estrellas}\n\n"
    msj += f"📊 Análisis:\n{pick.get('analisis', 'Análisis reservado VIP.')}\n\n"
    msj += "¡Vamos con todo! 💰"
    return msj

# ==========================================
# 6. MOTOR DE ENVÍO Y EJECUCIÓN
# ==========================================
async def disparar_bloque(nombre, ligas, cantidad, mensaje_intro=None, es_stake_10=False):
    logger.info(f"--- Iniciando bloque: {nombre} ---")
    
    cartelera = recolectar_cartelera(ligas)
    if not cartelera:
        logger.warning(f"No hay partidos activos HOY para el bloque {nombre}.")
        return

    picks_seleccionados = analizar_con_ia(cartelera, cantidad, es_stake_10)
    
    if not picks_seleccionados:
        logger.warning(f"La IA no pudo estructurar los picks para {nombre}.")
        return

    if mensaje_intro:
        await bot.send_message(chat_id=CHANNEL_ID, text=mensaje_intro)
        await asyncio.sleep(3)

    for pick in picks_seleccionados:
        mensaje_final = formatear_mensaje(pick)
        await bot.send_message(chat_id=CHANNEL_ID, text=mensaje_final)
        await asyncio.sleep(3) 

# ==========================================
# 7. CRONOGRAMA MAESTRO (EL RELOJ)
# ==========================================
async def loop_principal():
    logger.info("Sistema EL BOSS MEXA V2.0 Iniciado y esperando horarios.")
    
    bloques_ejecutados = {
        "buenos_dias": None, "mlb": None, "futbol": None, 
        "lmb": None, "stake10": None, "reporte": None
    }

    while True:
        ahora = datetime.now(MX_TZ)
        fecha_str = ahora.strftime("%Y-%m-%d")

        try:
            # 07:45 AM
            if ahora.hour == 7 and 45 <= ahora.minute <= 50 and bloques_ejecutados["buenos_dias"] != fecha_str:
                msg = "¡Buenos días, Familia! ☀️ Arrancamos una nueva jornada de análisis deportivo. En breve salen las primeras jugadas del día. ¡A facturar hoy! 💸"
                await bot.send_message(chat_id=CHANNEL_ID, text=msg)
                bloques_ejecutados["buenos_dias"] = fecha_str
            
            # 08:00 AM
            elif ahora.hour == 8 and 0 <= ahora.minute <= 5 and bloques_ejecutados["mlb"] != fecha_str:
                await disparar_bloque("MLB", ["baseball_mlb"], 2)
                bloques_ejecutados["mlb"] = fecha_str

            # 09:00 AM
            elif ahora.hour == 9 and 0 <= ahora.minute <= 5 and bloques_ejecutados["futbol"] != fecha_str:
                await disparar_bloque("Fútbol M", LIGAS_FUTBOL, 2)
                bloques_ejecutados["futbol"] = fecha_str

            # 01:30 PM
            elif ahora.hour == 13 and 30 <= ahora.minute <= 35 and bloques_ejecutados["lmb"] != fecha_str:
                msg_lmb = "Familia, ya están abiertas las líneas. Aquí tienen los picks de la Liga Mexicana de Béisbol. ⚾️🔥"
                await disparar_bloque("LMB", ["baseball_lmb", "baseball_mlb"], 2, mensaje_intro=msg_lmb)
                bloques_ejecutados["lmb"] = fecha_str

            # 03:00 PM
            elif ahora.hour == 15 and 0 <= ahora.minute <= 5 and bloques_ejecutados["stake10"] != fecha_str:
                msg_s10 = "🚨 STAKE 10 DETECTADO 🚨\n\nInteligencia algorítmica aplicada para maximizar el retorno. Vamos pesados aquí:"
                await disparar_bloque("Stake 10", LIGAS_TODAS, 1, mensaje_intro=msg_s10, es_stake_10=True)
                bloques_ejecutados["stake10"] = fecha_str

            # 11:45 PM
            elif ahora.hour == 23 and 45 <= ahora.minute <= 50 and bloques_ejecutados["reporte"] != fecha_str:
                msg = "📊 El Boss mexa – Cierre de Jornada 📊\n\nTerminamos por hoy, familia. Pasen excelente noche, mañana regresamos a analizar los mercados con todo. 💰"
                await bot.send_message(chat_id=CHANNEL_ID, text=msg)
                bloques_ejecutados["reporte"] = fecha_str

        except Exception as e:
            logger.error(f"Error en el ciclo principal: {e}")
        
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(loop_principal())
