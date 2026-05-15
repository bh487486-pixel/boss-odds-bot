while True:
    try:
        ahora = datetime.now(zona_mx)
        hora_actual = ahora.strftime("%H:%M:%S")

        print(f"⏳ Revisando... {hora_actual}")

        # 🔎 Consultar partidos de hoy
        fecha = ahora.strftime("%Y-%m-%d")

        url = "https://v3.football.api-sports.io/fixtures"

        headers = {
            "x-apisports-key": API_KEY
        }

        params = {
            "date": fecha
        }

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if "response" not in data or len(data["response"]) == 0:
            enviar(f"❌ No hay partidos hoy ({hora_actual})")
        else:
            enviado = False

            for partido in data["response"]:
                liga = partido["league"]["name"]
                equipo1 = partido["teams"]["home"]["name"]
                equipo2 = partido["teams"]["away"]["name"]

                id_partido = partido["fixture"]["id"]

                if id_partido == ultimo_partido_enviado:
                    continue

                if "Friendly" not in liga:

                    mensaje = f"""🔥 PICK DETECTADO 🔥

{equipo1} vs {equipo2}
Liga: {liga}

Hora CDMX: {hora_actual}
"""

                    enviar(mensaje)
                    ultimo_partido_enviado = id_partido
                    enviado = True
                    break

            if not enviado:
                enviar(f"❌ No hay partidos buenos disponibles ({hora_actual})")

        # 🔥 CLAVE: esperar 5 minutos reales
        time.sleep(300)

    except Exception as e:
        print("❌ ERROR:", e)
        time.sleep(60)
