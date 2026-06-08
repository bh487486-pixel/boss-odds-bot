def obtener_juegos(league_id):
    headers = {
        "x-apisports-key": API_KEY
    }

    from datetime import datetime, timedelta

    hoy = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

    logging.info(f"Fecha consultada API: {hoy}")

    params = {
        "league": league_id,
        "season": 2026,
        "date": hoy
    }

    try:
        r = requests.get(
            f"{BASE_URL}/games",
            headers=headers,
            params=params,
            timeout=30
        )

        r.raise_for_status()

        data = r.json()

        juegos = []

        for game in data.get("response", []):

            status = game.get("status", {}).get("short")

            if status != "NS":
                continue

            home = game["teams"]["home"]["name"]
            away = game["teams"]["away"]["name"]

            juegos.append(
                f"{away} vs {home}"
            )

        return juegos

    except Exception as e:
        logging.error(f"Error API: {e}")
        return []
