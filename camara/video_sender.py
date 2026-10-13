"""
Transmisor de vídeo en tiempo real para el barco.
Captura vídeo de la webcam, comprime los fotogramas y los transmite
vía UDP a la estación de control, inyectando un timestamp para calcular la latencia.
"""

import cv2
import socket
import struct
import time

# Configuración de red y resolución según requisitos del proyecto
SERVER_IP = "10.42.0.1"     # Cambiar por la IP de la estación de control
SERVER_PORT = 5005
FRAME_WIDTH = 640           # Resolución base 480p (640x480)
FRAME_HEIGHT = 480          # Resolución base 480p (640x480)
TARGET_FPS = 30
JPEG_QUALITY = 50           # Calidad de compresión (1-100) para no saturar el buffer UDP
MAX_PACKET_SIZE = 65000     # Límite seguro para un datagrama UDP


def run_sender():
    # 0 suele ser la webcam USB por defecto en Raspberry Pi (cambiar si no es así)
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)

    if not cap.isOpened():
        print("[ERROR] No se pudo acceder a la cámara.")
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[INFO] Emitiendo vídeo hacia {SERVER_IP}:{SERVER_PORT} vía UDP...")

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

    try:
        while True:
            start_time = time.time()
            ret, frame = cap.read()
            if not ret:
                print("[WARN] Error leyendo fotograma.")
                continue

            # Codificación a formato JPEG comprimido
            result, enc_img = cv2.imencode('.jpg', frame, encode_param)
            if not result:
                continue

            raw_bytes = enc_img.tobytes()

            # Verificación del tamaño máximo para un datagrama UDP
            if len(raw_bytes) > MAX_PACKET_SIZE:
                print(f"[WARN] Fotograma demasiado grande ({len(raw_bytes)} B). Omitido")
                continue

            # Cabecera: timestamp de envío
            send_timestamp = time.time()
            header = struct.pack("!d", send_timestamp)

            # Envío del paquete: [Cabecera Timestamp] + [Bytes de la imagen JPEG]
            sock.sendto(header + raw_bytes, (SERVER_IP, SERVER_PORT))

            # Control de frecuencia de emisión para estabilizar los FPS
            elapsed = time.time() - start_time
            sleep_time = (1.0 / TARGET_FPS) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[INFO] Transmisión detenida por el usuario.")
    finally:
        cap.release()
        sock.close()


if __name__ == "__main__":
    run_sender()