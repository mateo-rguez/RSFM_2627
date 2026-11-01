"""Receptor y monitor de vídeo para la estación.

Recibe fotogramas por UDP, muestra el vídeo por pantalla y calcula métricas
de rendimiento. Puede ejecutarse solo o junto con ``receptor_wifi_halow.py``.

El código es compatible con Python 3.5: no utiliza f-strings.
"""

import queue
import socket
import struct
import time

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

LISTEN_IP = "0.0.0.0"       # Escucha en todas las interfaces de red locales
LISTEN_PORT = 5005
BUFFER_SIZE = 65535         # Tamaño máximo del buffer para datagramas UDP
SOCKET_TIMEOUT_S = 0.5      # Espera máxima de recvfrom para poder comprobar si hay señal
TIMEOUT_SENAL_S = 2.0       # Tiempo sin fotogramas para considerar que no hay señal
TITULO_VENTANA = "Estacion de Control - Video Barco Solar"
ANCHO_AVISO = 640           # Tamaño de la imagen de aviso (igual que el vídeo del barco)
ALTO_AVISO = 480

hay_senal = False           # Compatibilidad con código que consulte este estado


def comprobar_senal(ultimo_fotograma, titulo_ventana=TITULO_VENTANA):
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
        cv2.putText(
            aviso,
            "Sin fotogramas desde hace {:.0f} s".format(segundos),
            (130, 270),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            1
        )
        cv2.imshow(titulo_ventana, aviso)

    return cv2.waitKey(1) & 0xFF == ord('q')


def run_receiver(stop_event=None, listen_ip=LISTEN_IP, listen_port=LISTEN_PORT,
                 show_window=True, mqtt_frame_queue=None):
    """Recibe vídeo hasta que se pulse ``q`` o se solicite una parada.

    ``stop_event`` permite ejecutar este receptor junto con el receptor MQTT
    en otro hilo. ``show_window=False`` sirve para estaciones sin interfaz
    gráfica, aunque las métricas seguirán calculándose internamente.
    ``mqtt_frame_queue`` permite mezclar fotogramas recibidos por MQTT con
    los que llegan por UDP. La cola debe contener paquetes ``timestamp + JPEG``.
    """
    if cv2 is None or np is None:
        raise ImportError(
            "OpenCV y NumPy son necesarios para recibir vídeo"
        )

    global hay_senal
    hay_senal = False

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((listen_ip, listen_port))
        timeout = SOCKET_TIMEOUT_S
        if mqtt_frame_queue is not None:
            # Permite atender con rapidez los fotogramas MQTT mientras se espera
            # un datagrama UDP.
            timeout = min(SOCKET_TIMEOUT_S, 0.05)
        sock.settimeout(timeout)   # Sin timeout, recvfrom se bloquearía al perder la señal
        print(
            "[INFO] Estación a la escucha de vídeo en {}:{}...".format(
                listen_ip,
                listen_port
            )
        )
    except OSError:
        sock.close()
        raise

    # Variables para cálculo de prestaciones (métricas para el informe)
    prev_time = time.time()
    fps = 0.0
    frame_count = 0
    fps_timer = time.time()
    ultimo_fotograma = time.time()
    ultimo_timestamp_enviado = None

    try:
        while stop_event is None or not stop_event.is_set():
            # Recepción del datagrama UDP
            data = None
            try:
                data, _ = sock.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                pass

            # Si no llegó UDP, se intenta obtener el último fotograma MQTT.
            # El emisor y el receptor usan exactamente el mismo paquete
            # binario: timestamp de 8 bytes seguido del JPEG.
            if data is None and mqtt_frame_queue is not None:
                try:
                    data = mqtt_frame_queue.get_nowait()
                except queue.Empty:
                    data = None

            if data is None:
                if show_window and comprobar_senal(ultimo_fotograma):
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
                if show_window and comprobar_senal(ultimo_fotograma):
                    break
                continue

            # UDP y MQTT transportan el mismo paquete. Si ambos llegan a la
            # estación, no se debe mostrar dos veces el mismo fotograma.
            if (ultimo_timestamp_enviado is not None and
                    send_time <= ultimo_timestamp_enviado):
                continue
            ultimo_timestamp_enviado = send_time

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
            if show_window:
                info_text = "FPS: {:.1f} | Latencia: {:.1f} ms".format(
                    fps,
                    latency_ms
                )
                cv2.putText(frame, info_text, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (0, 255, 0), 2)

            # Mostrar la ventana en la estación de control
            if show_window:
                cv2.imshow(TITULO_VENTANA, frame)

            # Salir si se pulsa la tecla "q"
            if show_window and cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        print("\n[INFO] Recepción finalizada.")
    except OSError as error:
        print("[ERROR] No se pudo recibir vídeo: {}".format(error))
    finally:
        sock.close()
        if show_window:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    run_receiver()
