import os
import time
import datetime
import threading
import logging
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
# VARIABLES DE CONFIGURACIÓN Y ESTADO INDEPENDIENTE
# =====================================================================
CONFIG = {
    "HORA_REPORTE": datetime.time(23, 55),
    "HORA_DESPIERTA_DIURNO": datetime.time(8, 30),
    # Rango flexible: mínimo 1.50 y tope máximo de 2.00 para todos los mercados
    "CUOTA_MINIMA": 1.50,
    "CUOTA_MAXIMA": 2.00,
    "UMBRAL_OVER_FUTBOL": 2.5,
    "UMBRAL_OVER_MLB": 8.5
}

# Simulación de persistencia de estado para evitar duplicados
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
    """
    Simula la consulta a una API externa de cuotas (ej. OddsAPI)
    Devuelve la cartelera con los datos analíticos necesarios.
    """
    logging.info("Consultando cartelera de partidos y cuotas actualizadas...")
    
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
                "ML_local": 1.60,       # Entra perfectamente en el rango de 1.50 a 2.00
                "OU_mas_8.5": 1.95,
                "HC_local_-1.5": 2.10   
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
    """
    Aplica el algoritmo de descarte secuencial validando que las cuotas
    se mantengan estrictamente en el rango de 1.50 a 2.00.
    """
    deporte = partido["deporte"]
    cuotas = partido["cuotas"]
    analisis = partido["analisis"]
    
    min_c = CONFIG["CUOTA_MINIMA"]
    max_c = CONFIG["CUOTA_MAXIMA"]
    
    # --- PROCESAMIENTO ESTRATÉGICO MLB ---
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

    # --- PROCESAMIENTO ESTRATÉGICO FÚTBOL ---
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
                "razon": "Se rota a mercado de goles buscando asegurar valor entre 1.50 y 2.00."
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
# MÓDULO 3: SISTEMA DE EMISIÓN DE SELECCIONES Y REPORTES
# =====================================================================
def enviar_mensaje_plataforma(texto_formateado):
    """Simulación del envío de mensajes a tus canales correspondientes"""
    logging.info("--- ENVIANDO MENSAJE A CANALES ---")
    print(texto_formateado)
    logging.info("--- MENSAJE ENVIADO CORRECTAMENTE ---")

def ejecutar_bloque_madrugada(partidos):
    """Filtra y despacha partidos de madrugada (5:00 AM - 9:00 AM)"""
    logging.info("Iniciando escaneo de bloques nocturnos para la madrugada...")
    
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
    """Envía el saludo obligatorio de buenos días y procesa los picks del día"""
    logging.info("Activando tareas del bloque diurno...")
    
    # 1. MENSAJE OBLIGATORIO DE BUENOS DÍAS
    saludo_buenos_dias = (
        "☀️ **¡Buenos días a todos!** ☀️\n\n"
        "El bot de análisis ya está encendido y escaneando la jornada de hoy. "
        "Buscando las mejores opciones en Ganador Directo, Totales y Hándicaps "
        f"con nuestro rango regulado de cuotas ({CONFIG['CUOTA_MINIMA']:.2f} - {CONFIG['CUOTA_MAXIMA']:.2f}).\n\n"
        "¡Mucho éxito en los mercados de hoy! 🚀"
    )
    enviar_mensaje_plataforma(saludo_buenos_dias)
    
    # Reposo breve para no encimar mensajes
    time.sleep(2)
    
    # 2. ESCANEO DE PICKS
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
    """Genera el reporte de balance automatizado con formato limpio"""
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
    """Bucle infinito que controla las ejecuciones cronométricas en Render"""
    logging.info("Subproceso de control de tiempo iniciado de forma segura.")
    
    # --- LANZAMIENTO FORZADO INICIAL (Ajuste para hoy) ---
    # Si arranca entre las 8:30 AM y las 11:55 PM, dispara el saludo y picks de una vez
    ahora_inicio = datetime.datetime.now().time()
    if CONFIG["HORA_DESPIERTA_DIURNO"] <= ahora_inicio < CONFIG["HORA_REPORTE"]:
        logging.info("Detección de inicio tardío: Ejecutando bloque diurno inmediatamente por hoy...")
        partidos_filtrados = obtener_partidos_api()
        ejecutar_bloque_diurno(partidos_filtrados)
        estado_bot["picks_diurnos_enviados"] = True

    while True:
        ahora = datetime.datetime.now()
        hora_actual = ahora.time()
        dia_actual = ahora.date()
        
        # --- CONTROL DE MEDIANOCHE (23:55) ---
        if hora_actual >= CONFIG["HORA_REPORTE"] and estado_bot["ultimo_reporte_enviado"] != dia_actual:
            logging.info("Activando tareas automáticas de cierre de jornada...")
            generar_cierre_balance()
            
            partidos_filtrados = obtener_partidos_api()
            ejecutar_bloque_madrugada(partidos_filtrados)
            
            estado_bot["ultimo_reporte_enviado"] = dia_actual
            estado_bot["picks_madrugada_enviados"] = True
            estado_bot["picks_diurnos_enviados"] = False 
            
        # --- CONTROL DIURNO NORMAL (8:30 AM) ---
        if hora_actual >= CONFIG["HORA_DESPIERTA_DIURNO"] and hora_actual < CONFIG["HORA_REPORTE"]:
            if not estado_bot["picks_diurnos_enviados"]:
                partidos_filtrados = obtener_partidos_api()
                ejecutar_bloque_diurno(partidos_filtrados)
                estado_bot["picks_diurnos_enviados"] = True
                
        if hora_actual > datetime.time(0, 0) and hora_actual < datetime.time(1, 0):
            estado_bot["picks_madrugada_enviados"] = False

        time.sleep(30)

# =====================================================================
# INTERFAZ WEB OBLIGATORIA PARA DESPLIEGUE EN RENDER
# =====================================================================
@app.route('/')
def home():
    return {
        "status": "online",
        "bot_name": "Logical value bot",
        "limits": f"{CONFIG['CUOTA_MINIMA']} - {CONFIG['CUOTA_MAXIMA']}",
        "diurnal_scanned_today": estado_bot["picks_diurnos_enviados"]
    }

def arrancar_sistema():
    hilo_cron = threading.Thread(target=loop_controlador_tiempo, daemon=True)
    hilo_cron.start()
    
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=puerto)

if __name__ == "__main__":
    arrancar_sistema()
