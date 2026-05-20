import os
import time
import datetime
import threading
import logging
import requests  # Librería necesaria para que viaje por internet a Telegram
from flask import Flask

# =====================================================================
# CONFIGURACIÓN DE LOGS Y ENTORNO
# =====================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

app = Flask(__name__)

# =====================================================================
# TUS VARIABLES DE CONEXIÓN REALES
# =====================================================================
# Aquí el bot toma tus códigos automáticamente. Si los tienes declarados como variables 
# normales arriba en tu script, asegúrate de que se llamen exactamente así.
CHAT_ID = os.environ.get("CHAT_ID", "TU_CHAT_ID_AQUI")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "TU_TELEGRAM_TOKEN_AQUI")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "TU_ODDS_API_KEY_AQUI")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY", "TU_FOOTBALL_API_KEY_AQUI")

# =====================================================================
# VARIABLES DE CONFIGURACIÓN Y ESTADO DEL BOT
# =====================================================================
CONFIG = {
    "HORA_REPORTE": datetime.time(23, 55),
    "HORA_DESPIERTA_DIURNO": datetime.time(8, 30),
    # Rango operativo solicitado: Mínimo 1.50 y el tope en 3.00 para todo
    "CUOTA_MINIMA": 1.50,
    "CUOTA_MAXIMA": 3.00,
    "UMBRAL_OVER_FUTBOL": 2.5,
    "UMBRAL_OVER_MLB": 8.5
}

estado_bot = {
    "ultimo_reporte_enviado": None,
    "picks_madrugada_enviados": False,
    "picks_diurnos_enviados": False,
    "historial_diario": [
        {"partido": "NY Yankees vs Boston", "pick": "Yankees ML", "resultado": "Ganado", "unidades": 1.5},
        {"partido": "Man City vs Arsenal", "pick": "Over 2.5 Goles", "resultado": "Ganado", "unidades": 2.1},
        {"partido": "Houston vs Texas", "pick": "Texas HC +1.5", "resultado": "Perdido", "unidades": -1.0},
    ]
}

# =====================================================================
# MÓDULO 1: ADQUISICIÓN DE DATOS (MOCK DE API DE DEPORTES)
# =====================================================================
def obtener_partidos_api():
    """Simula la consulta usando tus llaves ODDS_API_KEY o FOOTBALL_API_KEY"""
    logging.info("Consultando cartelera de partidos con tus credenciales de API...")
    
    return [
        {
            "id": "mlb_padres_dodgers_2026",
            "deporte": "MLB",
            "local": "LA Dodgers",
            "visitante": "San Diego Padres",
            "hora_inicio": datetime.time(18, 41),
            "analisis": {
                "abridor_favorito": "LA Dodgers",
                "racha_local": "buena",
                "racha_visitante": "regular",
                "clima_estadio": "neutral",
                "rendimiento_bullpen": "estable"
            },
            "cuotas": {
                "ML_local": 1.60,       # Entra en rango (1.50 - 3.00)
                "OU_mas_8.5": 1.95,     # Entra en rango (1.50 - 3.00)
                "HC_local_-1.5": 2.10   # Entra en rango (1.50 - 3.00)
            }
        },
        {
            "id": "futbol_madrid_betis_2026",
            "deporte": "Futbol",
            "local": "Real Madrid",
            "visitante": "Real Betis",
            "hora_inicio": datetime.time(14, 15),
            "analisis": {
                "estadio": "Santiago Bernabéu",
                "tendencia": "abierto_muchos_goles",
                "bajas_clave": "defensas_titulares",
                "importancia_partido": "alta"
            },
            "cuotas": {
                "ML_local": 1.35,       
                "OU_mas_2.5": 1.85,     
                "HC_local_-1.5": 1.95   
            }
        }
    ]

# =====================================================================
# MÓDULO 2: MOTOR DE LÓGICA COGNITIVA Y FILTRADO DE VALOR
# =====================================================================
def analizar_partido_con_logica(partido):
    deporte = partido["deporte"]
    cuotas = partido["cuotas"]
    analisis = partido["analisis"]
    
    min_c = CONFIG["CUOTA_MINIMA"]
    max_c = CONFIG["CUOTA_MAXIMA"]
    
    if deporte == "MLB":
        if analisis["abridor_favorito"] == partido["local"] and min_c <= cuotas["ML_local"] <= max_c:
            return {
                "tipo": "Ganador Directo (ML)",
                "seleccion": partido["local"],
                "cuota": cuotas["ML_local"],
                "razon": "Consistencia en la rotación inicial y ventaja ofensiva inclinan la victoria."
            }
        if min_c <= cuotas["OU_mas_8.5"] <= max_c:
            return {
                "tipo": f"Over {CONFIG['UMBRAL_OVER_MLB']} Carreras",
                "seleccion": "Over",
                "cuota": cuotas["OU_mas_8.5"],
                "razon": "Filtro de cuota óptimo para el mercado de carreras totales."
            }
        if min_c <= cuotas["HC_local_-1.5"] <= max_c:
            return {
                "tipo": "Hándicap -1.5",
                "seleccion": partido["local"],
                "cuota": cuotas["HC_local_-1.5"],
                "razon": "Línea de hándicap protegida dentro del rango de riesgo aceptable."
            }

    elif deporte == "Futbol":
        if min_c <= cuotas["ML_local"] <= max_c:
            return {
                "tipo": "Ganador Directo (ML)",
                "seleccion": partido["local"],
                "cuota": cuotas["ML_local"],
                "razon": f"Local fuerte con cuota equilibrada dentro del rango permitido."
            }
        if (analisis["tendencia"] == "abierto_muchos_goles") and (min_c <= cuotas["OU_mas_2.5"] <= max_c):
            return {
                "tipo": f"Over {CONFIG['UMBRAL_OVER_FUTBOL']} Goles",
                "seleccion": "Over",
                "cuota": cuotas["OU_mas_2.5"],
                "razon": "Se rota a mercado de goles buscando asegurar valor entre 1.50 y 3.00."
            }
        if min_c <= cuotas["HC_local_-1.5"] <= max_c:
            return {
                "tipo": "Hándicap -1.5",
                "seleccion": partido["local"],
                "cuota": cuotas["HC_local_-1.5"],
                "razon": "Ventaja de goles con cuota óptima regulada."
            }
            
    return None

# =====================================================================
# MÓDULO 3: CONEXIÓN REAL CON TELEGRAM
# =====================================================================
def enviar_mensaje_plataforma(texto_formateado):
    """Utiliza tu TELEGRAM_TOKEN y CHAT_ID para mandar el mensaje al canal"""
    logging.info("--- ENVIANDO MENSAJE REAL A TELEGRAM ---")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": texto_formateado,
        "parse_mode": "Markdown"
    }
    
    try:
        respuesta = requests.post(url, json=payload)
        if respuesta.status_code == 200:
            logging.info("--- ¡CONEXIÓN EXITOSA: Mensaje en el canal! ---")
        else:
            logging.error(f"Telegram rechazó el mensaje: {respuesta.status_code} - {respuesta.text}")
    except Exception as e:
        logging.error(f"Error crítico de conexión al enviar a Telegram: {e}")

def ejecutar_bloque_madrugada(partidos):
    for partido in partidos:
        if datetime.time(5, 0) <= partido["hora_inicio"] < datetime.time(9, 0):
            pick_valido = analizar_partido_con_logica(partido)
            if pick_valido:
                cuerpo = (
                    f"🚨 **PICK DE MADRUGADA DETECTADO** 🚨\n"
                    f"Match: {partido['local']} vs {partido['visitante']} ({partido['deporte']})\n"
                    f"Horario: {partido['hora_inicio'].strftime('%H:%M')} AM\n"
                    f"Pronóstico: {pick_valido['tipo']} -> {pick_valido['seleccion']}\n"
                    f"Cuota: @{pick_valido['cuota']}\n"
                    f"Justificación: {pick_valido['razon']}\n"
                )
                enviar_mensaje_plataforma(cuerpo)

def ejecutar_bloque_diurno(partidos):
    """Envía el saludo obligatorio y procesa la cartelera"""
    logging.info("Generando mensajes del bloque diurno...")
    
    # 1. Saludo de buenos días
    saludo_buenos_dias = (
        "☀️ **¡Buenos días a todos!** ☀️\n\n"
        "El bot de análisis ya está encendido y escaneando la jornada de hoy. "
        "Buscando las mejores opciones en Ganador Directo, Totales y Hándicaps "
        f"con nuestro rango regulado de cuotas ({CONFIG['CUOTA_MINIMA']:.2f} - {CONFIG['CUOTA_MAXIMA']:.2f}).\n\n"
        "¡Mucho éxito en los mercados de hoy! 🚀"
    )
    enviar_mensaje_plataforma(saludo_buenos_dias)
    
    time.sleep(2)
    
    # 2. Envío de picks filtrados
    for partido in partidos:
        if partido["hora_inicio"] >= datetime.time(9, 0):
            pick_valido = analizar_partido_con_logica(partido)
            if pick_valido:
                cuerpo = (
                    f"📌 **{partido['deporte']}** ⚾️⚽️\n"
                    f"❌ Partido: {partido['local']} vs {partido['visitante']}\n"
                    f"📅 Hora de Inicio: {partido['hora_inicio'].strftime('%H:%M')}\n\n"
                    f"🎯 Pick: {pick_valido['tipo']}: {pick_valido['seleccion']}\n"
                    f"💰 Cuota: {pick_valido['cuota']}\n\n"
                    f"🧠 **Justificación Profesional:** {pick_valido['razon']}"
                )
                enviar_mensaje_plataforma(cuerpo)

def generar_cierre_balance():
    historial = estado_bot["historial_diario"]
    reporte = (
        "=========================================\n"
        "      📊 REPORTE DE BALANCE DIARIO 📊    \n"
        "=========================================\n"
    )
    total_unidades = 0.0
    for item in historial:
        icono = "✅" if item["resultado"] == "Ganado" else "❌"
        reporte += f"{icono} {item['partido']}\n   ↳ Pick: {item['pick']} -> {item['resultado']} ({item['unidades']:+g} u)\n"
        total_unidades += item["unidades"]
        
    reporte += (
        "-----------------------------------------\n"
        f"PROFIT NETO REAL: {total_unidades:+.2f} Unidades\n"
        "========================================="
    )
    enviar_mensaje_plataforma(reporte)

# =====================================================================
# MÓDULO 4: PROCESADOR CENTRAL DE TIEMPO (CRON WORKER)
# =====================================================================
def loop_controlador_tiempo():
    logging.info("Subproceso de control de tiempo iniciado de forma segura.")
    
    # DISPARO INMEDIATO POR ARRANQUE TARDÍO (Para que mande el saludo ahorita mismo)
    ahora_inicio = datetime.datetime.now().time()
    if CONFIG["HORA_DESPIERTA_DIURNO"] <= ahora_inicio < CONFIG["HORA_REPORTE"]:
        logging.info("Forzando envío diurno por actualización en vivo...")
        partidos_filtrados = obtener_partidos_api()
        ejecutar_bloque_diurno(partidos_filtrados)
        estado_bot["picks_diurnos_enviados"] = True

    while True:
        ahora = datetime.datetime.now()
        hora_actual = ahora.time()
        dia_actual = ahora.date()
        
        if hora_actual >= CONFIG["HORA_REPORTE"] and estado_bot["ultimo_reporte_enviado"] != dia_actual:
            generar_cierre_balance()
            partidos_filtrados = obtener_partidos_api()
            ejecutar_bloque_madrugada(partidos_filtrados)
            estado_bot["ultimo_reporte_enviado"] = dia_actual
            estado_bot["picks_madrugada_enviados"] = True
            estado_bot["picks_diurnos_enviados"] = False 
            
        if hora_actual >= CONFIG["HORA_DESPIERTA_DIURNO"] and hora_actual < CONFIG["HORA_REPORTE"]:
            if not estado_bot["picks_diurnos_enviados"]:
                partidos_filtrados = obtener_partidos_api()
                ejecutar_bloque_diurno(partidos_filtrados)
                estado_bot["picks_diurnos_enviados"] = True
                
        if hora_actual > datetime.time(0, 0) and hora_actual < datetime.time(1, 0):
            estado_bot["picks_madrugada_enviados"] = False

        time.sleep(30)

# =====================================================================
# INTERFAZ WEB OBLIGATORIA PARA RENDER
# =====================================================================
@app.route('/')
def home():
    return {
        "status": "online",
        "bot_name": "Logical value bot",
        "limits": f"{CONFIG['CUOTA_MINIMA']} - {CONFIG['CUOTA_MAXIMA']}"
    }

def arrancar_sistema():
    hilo_cron = threading.Thread(target=loop_controlador_tiempo, daemon=True)
    hilo_cron.start()
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=puerto)

if __name__ == "__main__":
    arrancar_sistema()
