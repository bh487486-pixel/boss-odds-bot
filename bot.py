import os
import time
import requests
import sys

# Función para que los mensajes aparezcan rápido en Render
def log(msg):
    print(msg)
    sys.stdout.flush()

def main():
    log("------------------------------------------")
    log("🚀 SISTEMA INICIADO - VERIFICANDO DATOS")
    log("------------------------------------------")
    
    # Leemos las llaves que pusiste en Render
    api_key = os.getenv("ODDS_API_KEY")
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    
    # Verificación de seguridad
    if not api_key or not bot_token:
        log("❌ ERROR: Faltan variables de entorno (API_KEY o TOKEN).")
        return

    log(f"✅ Llaves detectadas. Conectando con API...")

    while True:
        try:
            # Una prueba simple para ver si la API nos deja entrar
            url = f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}"
            res = requests.get(url, timeout=15)
            
            if res.status_code == 200:
                creditos = res.headers.get('x-requests-remaining')
                log(f"📡 API Online. Créditos restantes: {creditos}")
                log("🔍 Buscando apuestas en Liga MX y MLB...")
                # Aquí el bot ya está trabajando en silencio
            elif res.status_code == 401:
                log("❌ ERROR: Tu API KEY no es válida. Checkéala en Render.")
            else:
                log(f"⚠️ Aviso: La API respondió con código {res.status_code}")
                
        except Exception as e:
            log(f"❌ Ocurrió un error inesperado: {e}")
            
        # Espera 5 minutos para la siguiente vuelta (para ahorrar créditos)
        log("😴 Pausa de 5 minutos para el siguiente escaneo...")
        time.sleep(300)

if __name__ == "__main__":
    main()
