    def ejecutar(self):
        # Creamos una bandera interna para que sepa si viene despertando del sueño largo
        viene_de_dormir = False

        while True:
            try:
                dt_mex = self._get_hora_mexico()
                fecha_hoy = dt_mex.strftime("%Y-%m-%d")
                hora_actual = dt_mex.hour

                # 🛌 BLOQUE DE SUEÑO EXACTO: De 11:00 PM a 7:00 AM MX
                if hora_actual >= 23 or hora_actual < 7:
                    if hora_actual == 23 and not self.db.chequeo_sistema(f"CIERRE_CANAL_{fecha_hoy}"):
                        Logger.log("🌙 Sincronizando cierre: Mandando Profit y Buenas Noches...")
                        self.enviar_reporte_profit_y_despedida(fecha_hoy)
                    
                    Logger.log("💤 Modo nocturno: El bot duerme sus 8 horas completas hasta las 7:00 AM.")
                    time.sleep(28800) # Duerme 8 horas clavadas
                    
                    # 🔥 Al pasar las 8 horas, activamos la bandera de que ya despertó legalmente
                    viene_de_dormir = True
                    continue

                # ☀️ SALUDO MOTIVACIONAL AL DESPERTAR (Solo si viene de cumplir sus 8 horas de sueño)
                if hora_actual == 7 and viene_de_dormir and not self.db.chequeo_sistema(f"DIAS_{fecha_hoy}"):
                    mensaje_buenos_dias = (
                        f"☀️ *【 ESCÁNER PREMIUM ABIERTO 】* ☀️\n\n"
                        f"¡Buenos días familia! 🚀 Empezamos con la jornada de los picks de hoy.\n\n"
                        f"El escáner ya está encendido buscando el máximo valor. ¡Mucho éxito a todos y a pintar el día de verde! 📈💰💚"
                    )
                    if self.tg.enviar(mensaje_buenos_dias):
                        self.db.marcar_sistema(f"DIAS_{fecha_hoy}", {"enviado": True})
                    
                    # Apagamos la bandera para todo el resto del día
                    viene_de_dormir = False

                # ⏱️ ASIGNACIÓN DINÁMICA DE TIEMPOS DE ESPERA
                if hora_actual >= 21 and hora_actual < 23:
                    # 🚀 MODO TURBO NOCTURNO (9:00 PM a 11:00 PM): Escanea cada 10 min buscando madrugadas
                    tiempo_espera = 600
                    Logger.log("⚡ MODO TURBO NOCTURNO ACTIVO (Frecuencia: 10 min) - Buscando Madrugadores...")
                else:
                    # ☀️ MODO REGULAR DE DÍA (7:00 AM a 9:00 PM): Escanea cada 35 min buscando la tardecita
                    tiempo_espera = 2100  # 35 minutos exactos
                    Logger.log("☀️ MODO REGULAR DE DÍA ACTIVO (Frecuencia: 35 min) - Buscando partidos de la tardecita...")

                # Corre el escáner con la hora actual para aplicar las reglas de filtrado
                self.escanear_mercados(fecha_hoy, hora_actual)

            except Exception as e: 
                Logger.log(f"💥 Error en el ciclo general: {e}")
                tiempo_espera = 2100
            
            time.sleep(tiempo_espera)
