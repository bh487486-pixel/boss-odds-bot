import requests
import time
import os
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

enviado_hoy = False

def enviar(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def generar_pick():
    return f"""🔥 PICKS VIP 🔥

📅 {datetime.now().strftime("%d/%m/%Y")}
⏰ {datetime.now().strftime("%I:%M %p")}

➡️ Evento: Partido del día
➡️ Tipo: Over 2.5 goles
➡️ Cuota: 1.85
➡️ Stake: 7/10

Confía en el sistema 💰
"""

while True:
    hora = datetime.now().strftime("%H:%M")

    # ⏰ ENVÍA UNA VEZ AL DÍA (ejemplo 7:00 PM)
    if hora == "19:00" and not enviado_hoy:
        enviar(generar_pick())
        print("✅ PICK ENVIADO")
        enviado_hoy = True

    # 🔁 Reset diario
    if hora == "00:00":
        enviado_hoy = False

    time.sleep(30)
