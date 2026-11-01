"""Transmisor de vídeo en tiempo real para el barco.

El vídeo se envía por UDP y, opcionalmente, por un topic MQTT separado del
topic de telemetría. El módulo puede ejecutarse solo o ser arrancado desde
``emisor_wifi_halow.py``.

El código evita f-strings y otras construcciones posteriores a Python 3.5.
"""

import socket
import struct
import time

try:
    import cv2
except ImportError:
    cv2 = None

# Configuración de red y resolución según requisitos del proyecto
SERVER_IP = "10.42.0.1"     # Cambiar por la IP de la estación de control
SERVER_PORT = 5005
FRAME_WIDTH = 640           # Resolución base 480p (640x480)
FRAME_HEIGHT = 480          # Resolución base 480p (640x480)
TARGET_FPS = 30
JPEG_QUALITY = 50           # Calidad de compresión (1-100) para no saturar el buffer UDP
MAX_PACKET_SIZE = 65000     # Límite seguro para un datagrama UDP


def run_sender(stop_event=None, server_ip=SERVER_IP, server_port=SERVER_PORT,
               camera_index=0, frame_width=FRAME_WIDTH,
               frame_height=FRAME_HEIGHT, target_fps=TARGET_FPS,
               jpeg_quality=JPEG_QUALITY, mqtt_client=None,
               mqtt_topic=None, mqtt_qos=0):
    """Captura y envía vídeo hasta recibir una orden de parada.

    ``stop_event`` permite ejecutar el transmisor en un hilo junto con el
    emisor MQTT. Si se proporciona ``mqtt_client`` y ``mqtt_topic``, cada
    paquete ``timestamp + JPEG`` también se publica como payload binario MQTT.
    Se mantiene opcional para conservar la ejecución directa del módulo.
    """
    if cv2 is None:
        raise ImportError(
            "OpenCV no está instalado; instale opencv-python"
        )

    # 0 suele ser la webcam USB por defecto en Raspberry Pi (cambiar si no es así)
    cap = cv2.VideoCapture(camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
    cap.set(cv2.CAP_PROP_FPS, target_fps)

    if not cap.isOpened():
        print("[ERROR] No se pudo acceder a la cámara.")
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(
        "[INFO] Emitiendo vídeo hacia {}:{} vía UDP...".format(
            server_ip,
            server_port
        )
    )
    if mqtt_client is not None and mqtt_topic:
        print(
            "[INFO] Publicando también vídeo en MQTT '{}'.".format(
                mqtt_topic
            )
        )

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]

    try:
        while stop_event is None or not stop_event.is_set():
            start_time = time.time()
            ret, frame = cap.read()
            if not ret:
                print("[WARN] Error leyendo fotograma.")
                if stop_event is not None:
                    stop_event.wait(0.05)
                continue

            # Codificación a formato JPEG comprimido
            result, enc_img = cv2.imencode('.jpg', frame, encode_param)
            if not result:
                continue

            raw_bytes = enc_img.tobytes()

            # Verificación del tamaño máximo para un datagrama UDP
            if len(raw_bytes) > MAX_PACKET_SIZE:
                print(
                    "[WARN] Fotograma demasiado grande ({} B). Omitido".format(
                        len(raw_bytes)
                    )
                )
                continue

            # Cabecera: timestamp de envío
            send_timestamp = time.time()
            header = struct.pack("!d", send_timestamp)

            # Paquete común para UDP y MQTT: [Timestamp] + [JPEG]
            packet = header + raw_bytes

            # Envío UDP (canal de baja latencia)
            sock.sendto(packet, (server_ip, server_port))

            # MQTT admite payloads binarios, por lo que no hace falta aplicar
            # Base64 y se evita aumentar el tamaño del fotograma un 33 %.
            if mqtt_client is not None and mqtt_topic:
                result = mqtt_client.publish(
                    mqtt_topic,
                    packet,
                    qos=mqtt_qos
                )
                if result.rc != 0:
                    print(
                        "[WARN] No se pudo publicar el fotograma por MQTT: {}".format(
                            result.rc
                        )
                    )

            # Control de frecuencia de emisión para estabilizar los FPS
            elapsed = time.time() - start_time
            sleep_time = (1.0 / target_fps) - elapsed
            if sleep_time > 0:
                if stop_event is None:
                    time.sleep(sleep_time)
                else:
                    stop_event.wait(sleep_time)

    except KeyboardInterrupt:
        print("\n[INFO] Transmisión detenida por el usuario.")
    except OSError as error:
        print("[ERROR] No se pudo enviar vídeo: {}".format(error))
    finally:
        cap.release()
        sock.close()


if __name__ == "__main__":
    run_sender()
