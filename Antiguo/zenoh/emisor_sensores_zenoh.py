import zenoh
import json
import random
import time
from collector import TelemetryCollector

KEY_EXPRESSION = "barco/telemetria"
INTERVALO_MIN_S = 0.5       # tiempo mínimo entre dos envíos
INTERVALO_MAX_S = 1.5       # tiempo máximo entre dos envíos

def enviar_telemetria():
    # Configuración de Zenoh añadiendo el endpoint de conexión hacia el receptor
    conf = zenoh.Config()
    conf.insert_json5("connect/endpoints", '["tcp/10.42.0.1:7447"]')
    
    print("[ZENOH] Abriendo sesión y conectando al receptor...")
    session = zenoh.open(conf)
    
    # Inicialización del colector de sensores
    colector = TelemetryCollector()
    
    print("[EMISOR] Iniciando envío periódico de telemetría (Ctrl+C para salir)...")
    try:
        while True:
            # Obtener los datos reales o simulados del colector de sensores
            paquete = colector.collect()
            
            # Serializar el diccionario a JSON y publicarlo en Zenoh
            data_str = json.dumps(paquete)
            session.put(KEY_EXPRESSION, data_str)
            print(f"[EMISOR] Publicado en '{KEY_EXPRESSION}': {data_str}")
            
            # Esperar un tiempo aleatorio hasta el siguiente envío
            time.sleep(random.uniform(INTERVALO_MIN_S, INTERVALO_MAX_S))
                
    except KeyboardInterrupt:
        print("\n[EMISOR] Deteniendo el envío...")
    finally:
        colector.close()
        session.close()
        print("[ZENOH] Sesión cerrada.")

if __name__ == "__main__":
    enviar_telemetria()