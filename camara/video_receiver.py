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
SOCKET_TIMEOUT_S = 0.5      # Espera máxima de recvfrom para poder comprobar si hay señal
TIMEOUT_SENAL_S = 2.0       # Tiempo sin fotogramas para considerar que no hay señal
TITULO_VENTANA = "Estacion de Control - Video Barco Solar"
ANCHO_AVISO = 640           # Tamaño de la imagen de aviso (igual que el vídeo del barco)
ALTO_AVISO = 480

hay_senal = False           # Indica si llegan fotogramas válidos (también lo consulta el panel)


def comprobar_senal(ultimo_fotograma):
    """
    Si lleva un tiempo sin llegar vídeo, muestra un aviso en lugar de dejar
    congelada la última imagen, que parecería vídeo en directo.
    Devuelve True si se ha pulsado la tecla "q".
    """
    global hay_senal
    segundos = time.time() - ultimo_fotograma

    if segundos >= TIMEOUT_SENAL_S:
        if hay_senal:
            print("[WARN] Señal de vídeo perdida.")
            hay_senal = False

        # La fuente de OpenCV no admite tildes ni "ñ", por eso se evitan en el texto
        aviso = np.zeros((ALTO_AVISO, ANCHO_AVISO, 3), dtype=np.uint8)
        cv2.putText(aviso, "VIDEO NO DISPONIBLE", (110, 220),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.putText(aviso, f"Sin fotogramas desde hace {segundos:.0f} s", (130, 270),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
        cv2.imshow(TITULO_VENTANA, aviso)

    return cv2.waitKey(1) & 0xFF == ord('q')


def run_receiver():
    global hay_senal

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))
    sock.settimeout(SOCKET_TIMEOUT_S)   # Sin timeout, recvfrom se bloquearía al perder la señal
    print(f"[INFO] Estación a la escucha de vídeo en el puerto {LISTEN_PORT}...")

    # Variables para cálculo de prestaciones (métricas para el informe)
    prev_time = time.time()
    fps = 0.0
    frame_count = 0
    fps_timer = time.time()
    ultimo_fotograma = time.time()

    try:
        while True:
            # Recepción del datagrama UDP
            try:
                data, _ = sock.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                if comprobar_senal(ultimo_fotograma):
                    break
                continue

            recv_time = time.time()

            # Desempaquetar los primeros 8 bytes que corresponden al timestamp del barco.
            # Un paquete sin imagen se descarta porque cv2.imdecode falla con datos vacíos
            header_size = struct.calcsize("!d")
            if len(data) <= header_size:
                continue

            send_time = struct.unpack("!d", data[:header_size])[0]
            jpeg_bytes = data[header_size:]

            # Latencia calculada extremo a extremo en ms
            latency_ms = (recv_time - send_time) * 1000.0

            # Decodificar el array JPEG a imagen utilizable por OpenCV
            np_arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            # Los paquetes corruptos también cuentan como falta de señal
            if frame is None:
                if comprobar_senal(ultimo_fotograma):
                    break
                continue

            ultimo_fotograma = time.time()
            if not hay_senal:
                print("[INFO] Señal de vídeo recibida.")
                hay_senal = True

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
            cv2.imshow(TITULO_VENTANA, frame)

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