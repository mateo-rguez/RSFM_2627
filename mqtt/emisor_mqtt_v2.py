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
    cliente.reconnect_delay_set(min_delay=1, max_delay=10)
    print("[MQTT] Conectando con el broker...")

    # connect_async() en lugar de connect(): con connect() el emisor terminaba si el
    # broker aún no estaba disponible, por ejemplo si el barco arranca antes que la
    # estación. Así el hilo de loop_start() sigue reintentando hasta conseguir conectar
    cliente.connect_async(BROKER_IP, BROKER_PORT)
    cliente.loop_start()    # hilo en segundo plano que gestiona la comunicación (y reconecta si se corta)

    # Lectura de sensores (si no hay hardware conectado, el colector genera datos simulados)
    colector = TelemetryCollector()

    print("[EMISOR] Iniciando envío periódico de telemetría (Ctrl+C para salir)...")
    try:
        while True:
            # Leer los sensores y publicar el paquete en MQTT
            paquete = colector.collect()
            data_str = json.dumps(paquete)

            # Sin conexión, paho guardaría los paquetes QoS 1 en memoria y los enviaría
            # todos de golpe al reconectar. Como la telemetría es en tiempo real, se
            # descartan: la estación recibirá solo datos actuales al recuperar la conexión
            if cliente.is_connected():
                cliente.publish(TOPIC, data_str, qos=QOS)
                print(f"[EMISOR] Publicado en '{TOPIC}': {data_str}")
            else:
                print("[WARN] Sin conexión con el broker. Paquete descartado.")

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
