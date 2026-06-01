import requests
import json
from datetime import datetime

API_KEY = "4b90f036a499cb44446f79edd3ef82b4" # ¡Pon tu llave de API-Sports aquí!
headers = {"x-apisports-key": API_KEY}
fecha_hoy = datetime.now().strftime("%Y-%m-%d")

print("🔍 Buscando juegos de MLB para hoy...")
res_games = requests.get("https://v1.baseball.api-sports.io/games", headers=headers, params={"league": "1", "season": "2026", "date": fecha_hoy}).json()
fixtures = res_games.get("response", [])

if not fixtures:
    print("❌ No encontré juegos. (Asegúrate de que el API Key esté correcto).")
else:
    fix_id = fixtures[0]["id"]
    home = fixtures[0]["teams"]["home"]["name"]
    away = fixtures[0]["teams"]["away"]["name"]
    print(f"✅ Juego encontrado: {home} vs {away} (ID: {fix_id})")
    
    print("\n📡 Extrayendo nombres exactos de los mercados...")
    res_odds = requests.get("https://v1.baseball.api-sports.io/odds", headers=headers, params={"fixture": fix_id}).json()
    
    datos = res_odds.get("response", [])
    if not datos:
        print("⚠️ No hay cuotas abiertas para este partido aún.")
    else:
        bookmakers = datos[0].get("bookmakers", [])
        if bookmakers:
            bets = bookmakers[0].get("bets", [])
            print("\n📋 === MERCADOS DISPONIBLES EN LA API ===")
            for bet in bets:
                print(f"- ID: {bet.get('id')} | Nombre de la apuesta: '{bet.get('name')}'")
            print("=========================================")
