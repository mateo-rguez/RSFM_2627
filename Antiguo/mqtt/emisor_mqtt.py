import paho.mqtt.client as mqtt
import json
import time

BROKER_IP = "10.42.0.1"      # IP del equipo donde corre el broker MQTT (la estación)
BROKER_PORT = 1883
TOPIC = "barco/telemetria"
QOS = 1                      # 0 = como mucho una vez, 1 = al menos una vez, 2 = exactamente una vez
FICHERO_DATOS = "datos_simulados.txt"

def enviar_telemetria():
    # Configuración y conexión con el broker MQTT
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    print("[MQTT] Conectando con el broker...")
    try:
        cliente.connect(BROKER_IP, BROKER_PORT)
    except OSError as e:
        print(f"[ERROR] No se pudo conectar con el broker en {BROKER_IP}:{BROKER_PORT}: {e}")
        return
    cliente.loop_start()    # hilo en segundo plano que gestiona la comunicación con el broker

    try:
        with open(FICHERO_DATOS, "r", encoding="utf-8") as f:
            for linea in f:
                linea_limpia = linea.strip()
                if not linea_limpia:
                    continue

                # Validar que es un JSON correcto
                try:
                    paquete = json.loads(linea_limpia)
                except json.JSONDecodeError:
                    continue

                # Publicar el mensaje en MQTT
                data_str = json.dumps(paquete)
                info = cliente.publish(TOPIC, data_str, qos=QOS)
                info.wait_for_publish()    # espera a que el mensaje salga (y a que el broker lo confirme si QOS > 0)
                print(f"[EMISOR] Publicado en '{TOPIC}': {data_str}")

                # Simular intervalo de envío entre muestras (ej. 1 segundo)
                time.sleep(1)

    except FileNotFoundError:
        print(f"[ERROR] No se encontró el fichero '{FICHERO_DATOS}'")
    finally:
        cliente.loop_stop()
        cliente.disconnect()
        print("[MQTT] Conexión cerrada.")

if __name__ == "__main__":
    enviar_telemetria()
