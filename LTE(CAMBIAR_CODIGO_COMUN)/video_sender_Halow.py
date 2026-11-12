"""Transmisor de vídeo del barco mediante MQTT.

Cada fotograma se codifica como JPEG y se publica en un topic MQTT
separado del topic de telemetría. El paquete contiene un timestamp
de 8 bytes seguido de los bytes JPEG.

El código es compatible con Python 3.5.
"""

import struct
import time

try:
    import cv2
except ImportError:
    cv2 = None


FRAME_WIDTH = 320
FRAME_HEIGHT = 240
TARGET_FPS = 15
JPEG_QUALITY = 35


def run_sender(stop_event=None, camera_index=0, frame_width=FRAME_WIDTH,
               frame_height=FRAME_HEIGHT, target_fps=TARGET_FPS,
               jpeg_quality=JPEG_QUALITY, mqtt_client=None,
               mqtt_topic=None, mqtt_qos=0):
    """Captura y publica vídeo hasta recibir una orden de parada."""

    if cv2 is None:
        raise ImportError(
            "OpenCV no está instalado; instale opencv-python"
        )

    if mqtt_client is None or not mqtt_topic:
        raise ValueError(
            "Se necesita un cliente MQTT y un topic para transmitir vídeo"
        )

    if target_fps <= 0:
        raise ValueError("Los FPS deben ser mayores que cero")

    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("La resolución debe ser mayor que cero")

    if jpeg_quality < 0 or jpeg_quality > 100:
        raise ValueError("La calidad JPEG debe estar entre 0 y 100")

    cap = cv2.VideoCapture(camera_index)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
    cap.set(cv2.CAP_PROP_FPS, target_fps)

    if not cap.isOpened():
        print("[ERROR] No se pudo acceder a la cámara.")
        cap.release()
        return

    print(
        "[INFO] Publicando vídeo únicamente en MQTT '{}'.".format(
            mqtt_topic
        )
    )

    print(
        "[VIDEO] Resolución: {}x{} | FPS objetivo: {} | Calidad JPEG: {}".format(
            frame_width,
            frame_height,
            target_fps,
            jpeg_quality
        )
    )

    encode_param = [
        int(cv2.IMWRITE_JPEG_QUALITY),
        jpeg_quality
    ]

    intervalo = 1.0 / target_fps

    try:
        while stop_event is None or not stop_event.is_set():

            start_time = time.time()

            ret, frame = cap.read()

            if not ret:
                print("[WARN] Error leyendo fotograma.")

                if stop_event is not None:
                    stop_event.wait(0.05)
                else:
                    time.sleep(0.05)

                continue

            # Comprobar y reducir la resolución si es necesario.
            alto, ancho = frame.shape[:2]

            if ancho != frame_width or alto != frame_height:
                frame = cv2.resize(
                    frame,
                    (frame_width, frame_height),
                    interpolation=cv2.INTER_AREA
                )

            # Codificar el fotograma en JPEG.
            result, enc_img = cv2.imencode(
                '.jpg',
                frame,
                encode_param
            )

            if not result:
                continue

            raw_bytes = enc_img.tobytes()

            # Añadir timestamp de 8 bytes al principio del paquete.
            send_timestamp = time.time()
            packet = struct.pack("!d", send_timestamp) + raw_bytes

            # Publicar mediante MQTT.
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

            # Limitar la frecuencia de envío.
            elapsed = time.time() - start_time
            sleep_time = intervalo - elapsed

            if sleep_time > 0:
                if stop_event is None:
                    time.sleep(sleep_time)
                else:
                    stop_event.wait(sleep_time)

    except KeyboardInterrupt:
        print("\n[INFO] Transmisión detenida por el usuario.")

    finally:
        cap.release()
        print("[INFO] Cámara liberada.")


if __name__ == "__main__":
    print(
        "[ERROR] Ejecute emisor_wifi_halow.py para publicar vídeo mediante MQTT."
    )

