import os
import time

print("------------------------------------------")
print("🚀 PROBANDO MOTOR DEL BOT...")
print(f"Buscando API KEY: {os.getenv('ODDS_API_KEY')[:5]}****")
print("------------------------------------------")

while True:
    ahora = time.strftime("%H:%M:%S")
    print(f"[{ahora}] Bot encendido y rastreando ligas... (No hay picks de valor aún)")
    time.sleep(10) # Te avisará cada 10 segundos en Render
