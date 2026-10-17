import paho.mqtt.client as mqtt
import json
import random
import time
from collector import TelemetryCollector

BROKER_IP = "10.42.0.1"      # IP del equipo donde corre el broker MQTT (la estación)
BROKER_PORT = 1883
TOPIC = "barco/telemetria"
QOS = 1                      # 0 = como mucho una vez, 1 = al menos una vez, 2 = exactamente una vez
INTERVALO_MIN_S = 0.5        # tiempo mínimo entre dos envíos
INTERVALO_MAX_S = 1.5        # tiempo máximo entre dos envíos

def enviar_telemetria():
    # Conexión con el broker MQTT
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    print("[MQTT] Conectando con el broker...")
    try:
        cliente.connect(BROKER_IP, BROKER_PORT)
    except OSError as e:
        print(f"[ERROR] No se pudo conectar con el broker en {BROKER_IP}:{BROKER_PORT}: {e}")
        return
    cliente.loop_start()    # hilo en segundo plano que gestiona la comunicación (y reconecta si se corta)

    # Lectura de sensores (si no hay hardware conectado, el colector genera datos simulados)
    colector = TelemetryCollector()

    print("[EMISOR] Iniciando envío periódico de telemetría (Ctrl+C para salir)...")
    try:
        while True:
            # Leer los sensores y publicar el paquete en MQTT
            paquete = colector.collect()
            data_str = json.dumps(paquete)
            cliente.publish(TOPIC, data_str, qos=QOS)
            print(f"[EMISOR] Publicado en '{TOPIC}': {data_str}")

            # Esperar un tiempo aleatorio hasta el siguiente envío
            time.sleep(random.uniform(INTERVALO_MIN_S, INTERVALO_MAX_S))

    except KeyboardInterrupt:
        print("\n[EMISOR] Deteniendo el envío...")
    finally:
        colector.close()
        cliente.loop_stop()
        cliente.disconnect()
        print("[MQTT] Conexión cerrada.")

if __name__ == "__main__":
    enviar_telemetria()
