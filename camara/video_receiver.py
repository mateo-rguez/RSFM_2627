"""
Receptor y monitor de vídeo para la estación
Recibe fotogramas por UDP, muestra el video por pantalla y
calcula métricas de rendimiento en tiempo real (FPS y latencia)
"""

import cv2
import socket
import struct
import numpy as np
import time

LISTEN_IP = "0.0.0.0"       # Escucha en todas las interfaces de red locales
LISTEN_PORT = 5005
BUFFER_SIZE = 65535         # Tamaño máximo del buffer para datagramas UDP


def run_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))
    print(f"[INFO] Estación a la escucha de vídeo en el puerto {LISTEN_PORT}...")

    # Variables para cálculo de prestaciones (métricas para el informe)
    prev_time = time.time()
    fps = 0.0
    frame_count = 0
    fps_timer = time.time()

    try:
        while True:
            # Recepción del datagrama UDP
            data, _ = sock.recvfrom(BUFFER_SIZE)

            recv_time = time.time()

            # Desempaquetar los primeros 8 bytes que corresponden al timestamp del barco
            header_size = struct.calcsize("!d")
            if len(data) < header_size:
                continue

            send_time = struct.unpack("!d", data[:header_size])[0]
            jpeg_bytes = data[header_size:]

            # Latencia calculada extremo a extremo en ms
            latency_ms = (recv_time - send_time) * 1000.0

            # Decodificar el array JPEG a imagen utilizable por OpenCV
            np_arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if frame is None:
                continue

            # Cálculo de FPS promedio recibido
            frame_count += 1
            if time.time() - fps_timer >= 1.0:
                fps = frame_count / (time.time() - fps_timer)
                frame_count = 0
                fps_timer = time.time()

            # Superponer métricas directamente sobre el vídeo (para monitorización)
            info_text = f"FPS: {fps:.1f} | Latencia: {latency_ms:.1f} ms"
            cv2.putText(frame, info_text, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            # Mostrar la ventana en la estación de control
            cv2.imshow("Estacion de Control - Video Barco Solar", frame)

            # Salir si se pulsa la tecla "q"
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        print("\n[INFO] Recepción finalizada.")
    finally:
        sock.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run_receiver()