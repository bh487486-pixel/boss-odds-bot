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
    "CUOTA_MINIMA_ML": 1.70,
    "CUOTA_MINIMA_HC": 1.85,
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
    
    # Datos estructurados para análisis profundo
    return [
        {
            "id": "mlb_padres_dodgers_2026",
            "deporte": "MLB",
            "local": "LA Dodgers",
            "visitante": "San Diego Padres",
            "hora_inicio": datetime.time(6, 30),  # Madrugada
            "analisis": {
                "abridor_favorito": "LA Dodgers",
                "racha_local": "buena",
                "racha_visitante": "regular",
                "clima_estadio": "viento_a_favor_del_bateo",
                "rendimiento_bullpen": "desgastado"
            },
            "cuotas": {
                "ML_local": 1.45,  # Cuota baja sin valor directo
                "ML_visitante": 2.75,
                "OU_mas_8.5": 1.95,
                "HC_local_-1.5": 2.10
            }
        },
        {
            "id": "futbol_madrid_betis_2026",
            "deporte": "Futbol",
            "local": "Real Madrid",
            "visitante": "Real Betis",
            "hora_inicio": datetime.time(14, 15),  # Tarde (Bloque Diurno)
            "analisis": {
                "estadio": "Santiago Bernabéu",
                "tendencia": "abierto_muchos_goles",
                "bajas_clave": "defensas_titulares",
                "importancia_partido": "alta"
            },
            "cuotas": {
                "ML_local": 1.35,  # Favorito claro pero cuota muy baja
                "OU_mas_2.5": 1.85,
                "HC_local_-1.5": 1.95
            }
        },
        {
            "id": "mlb_yankees_redsox_2026",
            "deporte": "MLB",
            "local": "NY Yankees",
            "visitante": "Boston Red Sox",
            "hora_inicio": datetime.time(18, 5),  # CORREGIDO: Se quitó el cero inicial (05 -> 5) para evitar el SyntaxError
            "analisis": {
                "abridor_favorito": "NY Yankees",
                "racha_local": "excelente",
                "racha_visitante": "mala",
                "clima_estadio": "neutral",
                "rendimiento_bullpen": "stable"
            },
            "cuotas": {
                "ML_local": 1.75,  # ¡Tiene valor directo!
                "OU_mas_9.0": 1.90,
                "HC_local_-1.5": 2.40
            }
        }
    ]

# =====================================================================
# MÓDULO 2: MOTOR DE LÓGICA COGNITIVA Y FILTRADO DE VALOR
# =====================================================================
def analizar_partido_con_logica(partido):
    """
    Aplica el algoritmo de descarte secuencial:
    1. Ganador Directo (Si hay favorito claro y paga bien)
    2. Totales/Goles/Carreras (Si la dinámica del juego lo justifica)
    3. Hándicaps (Como última alternativa de valor)
    """
    deporte = partido["deporte"]
    cuotas = partido["cuotas"]
    analisis = partido["analisis"]
    
    # --- PROCESAMIENTO ESTRATÉGICO MLB ---
    if deporte == "MLB":
        # Paso 1: Evaluar Ganador Directo
        if analisis["abridor_favorito"] == partido["local"] and cuotas["ML_local"] >= CONFIG["CUOTA_MINIMA_ML"]:
            return {
                "tipo": "Ganador Directo (ML)",
                "seleccion": partido["local"],
                "cuota": cuotas["ML_local"],
                "razon": f"Claro favorito por abridor y racha {analisis['racha_local']} con cuota rentable."
            }
        
        # Paso 2: Si el ML no paga, evaluar Totales (Over/Under) por clima/bullpen
        if analisis["clima_estadio"] == "viento_a_favor_del_bateo" or analisis["rendimiento_bullpen"] == "desgastado":
            return {
                "tipo": f"Over {CONFIG['UMBRAL_OVER_MLB']} Carreras",
                "seleccion": "Over",
                "cuota": cuotas["OU_mas_8.5"],
                "razon": "Cuota regular en ML descartada. Filtro lógico activa el Over por viento a favor y desgaste en pitcheo."
            }
            
        # Paso 3: Evaluar Hándicap si las condiciones previas no alcanzaron el umbral
        if cuotas["HC_local_-1.5"] >= CONFIG["CUOTA_MINIMA_HC"] and analisis["racha_local"] == "excelente":
            return {
                "tipo": "Hándicap -1.5",
                "seleccion": partido["local"],
                "cuota": cuotas["HC_local_-1.5"],
                "razon": "Buscamos exprimir valor con hándicap por racha dominante del local."
            }

    # --- PROCESAMIENTO ESTRATÉGICO FÚTBOL ---
    elif deporte == "Futbol":
        # Paso 1: Evaluar Ganador Directo
        if cuotas["ML_local"] >= CONFIG["CUOTA_MINIMA_ML"]:
            return {
                "tipo": "Ganador Directo (ML)",
                "seleccion": partido["local"],
                "cuota": cuotas["ML_local"],
                "razon": f"Local fuerte en el estadio {analisis['estadio']} con cuota dentro del umbral."
            }
            
        # Paso 2: Evaluar Goles si es un partido abierto o hay bajas defensivas
        if analisis["tendencia"] == "abierto_muchos_goles" or "defensas_titulares" in analisis["bajas_clave"]:
            return {
                "tipo": f"Over {CONFIG['UMBRAL_OVER_FUTBOL']} Goles",
                "seleccion": "Over",
                "cuota": cuotas["OU_mas_2.5"],
                "razon": f"ML paga poco. Se rota a goles por expectativa de juego abierto y bajas en defense."
            }
            
        # Paso 3: Hándicap alternativo
        if cuotas["HC_local_-1.5"] >= 1.80:
            return {
                "tipo": "Hándicap -1.5",
                "seleccion": partido["local"],
                "cuota": cuotas["HC_local_-1.5"],
                "razon": "Ventaja clara para cubrir el hándicap por disparidad de planteles."
            }
            
    return None

# =====================================================================
# MÓDULO 3: SISTEMA DE EMISIÓN DE SELECCIONES Y REPORTES
# =====================================================================
def enviar_mensaje_plataforma(texto_formateado):
    """
    Simulación del conector de salida para mensajería.
    En producción aquí se integra requests.post() a la API de destino.
    """
    logging.info("--- ENVIANDO MENSAJE A CANALES ---")
    print(texto_formateado)
    logging.info("--- MENSAJE ENVIADO CORRECTAMENTE ---")

def ejecutar_bloque_madrugada(partidos):
    """Filtra y despacha partidos que juegan exclusivamente de 5:00 AM a 9:00 AM"""
    logging.info("Iniciando escaneo de bloques nocturnos para la madrugada...")
    mensajes_enviados = 0
    
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
                    f"Lógica aplicada: {pick_valido['razon']}\n"
                )
                enviar_mensaje_plataforma(cuerpo)
                mensajes_enviados += 1
                
    if mensajes_enviados == 0:
        logging.info("No se encontraron oportunidades con valor real para la madrugada.")

def ejecutar_bloque_diurno(partidos):
    """Filtra y despacha partidos que juegan a partir de las 9:00 AM en adelante"""
    logging.info("Iniciando escaneo de bloques diurnos (A partir de las 8:30 AM)...")
    
    for partido in partidos:
        if partido["hora_inicio"] >= datetime.time(9, 0):
            pick_valido = analizar_partido_con_logica(partido)
            if pick_valido:
                cuerpo = (
                    f"💰 **NUEVO PICK DIURNO CON VALOR** 💰\n"
                    f"Partido: {partido['local']} vs {partido['visitante']} | {partido['deporte']}\n"
                    f"Hora de Inicio: {partido['hora_inicio'].strftime('%H:%M')}\n"
                    f"Pick Recomendado: {pick_valido['tipo']}\n"
                    f"Cuota de entrada: @{pick_valido['cuota']}\n"
                    f"Análisis Técnico: {pick_valido['razon']}\n"
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
        f"PROFIT NETO DEL BOT: {total_unidades:+.2f} Unidades\n"
        "========================================="
    )
    enviar_mensaje_plataforma(reporte)

# =====================================================================
# MÓDULO 4: PROCESADOR CENTRAL DE TIEMPO (CRON WORKER)
# =====================================================================
def loop_controlador_tiempo():
    """
    Bucle infinito que controla las ejecuciones cronométricas en Render.
    Usa pasadas de 30 segundos para evitar sobrecarga de CPU.
    """
    logging.info("Subproceso de control de tiempo iniciado de forma segura.")
    
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
            
        # --- CONTROL DIURNO (A partir de las 8:30 AM) ---
        if hora_actual >= CONFIG["HORA_DESPIERTA_DIURNO"] and hora_actual < CONFIG["HORA_REPORTE"]:
            if not estado_bot["picks_diurnos_enviados"]:
                logging.info("Activando tareas del bloque diurno...")
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
    """Mantiene el puerto HTTP de Render activo para evitar Webhook Timeout errors"""
    return {
        "status": "online",
        "bot_name": "Logical value bot",
        "last_report_date": str(estado_bot["ultimo_reporte_enviado"]),
        "diurnal_scanned_today": estado_bot["picks_diurnos_enviados"]
    }

def arrancar_sistema():
    # Iniciar el procesador de horas en un hilo secundario independiente
    hilo_cron = threading.Thread(target=loop_controlador_tiempo, daemon=True)
    hilo_cron.start()
    
    # Iniciar el servidor web de Flask usando el puerto asignado por Render
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=puerto)

if __name__ == "__main__":
    arrancar_sistema()
