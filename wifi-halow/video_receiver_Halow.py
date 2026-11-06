
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Receptor y monitor de vídeo mediante MQTT.

Recibe paquetes binarios desde el topic MQTT del vídeo, decodifica
los JPEG, muestra la imagen y calcula FPS y latencia.
"""

import queue
import struct
import time

try:
    import cv2
    import numpy as np

except ImportError:
    cv2 = None
    np = None


SOCKET_TIMEOUT_S = 0.05
TIMEOUT_SENAL_S = 2.0

TITULO_VENTANA = "Estacion de Control - Video Barco Solar"

ANCHO_AVISO = 640
ALTO_AVISO = 480

VIDEO_RECORD_FPS = 30.0

hay_senal = False


# ============================================================
# COMPROBACIÓN DE SEÑAL
# ============================================================

def comprobar_senal(
    ultimo_fotograma,
    titulo_ventana=TITULO_VENTANA
):
    """Muestra un aviso si no llegan fotogramas."""

    global hay_senal

    segundos = time.time() - ultimo_fotograma

    if segundos >= TIMEOUT_SENAL_S:

        if hay_senal:
            print("[WARN] Señal de vídeo perdida.")
            hay_senal = False

        aviso = np.zeros(
            (ALTO_AVISO, ANCHO_AVISO, 3),
            dtype=np.uint8
        )

        cv2.putText(
            aviso,
            "VIDEO NO DISPONIBLE",
            (110, 220),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 0, 255),
            2
        )

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

    return (cv2.waitKey(1) & 0xFF) == ord("q")


# ============================================================
# GRABACIÓN MP4
# ============================================================

def crear_grabador_mp4(
    output_path,
    frame,
    fps=VIDEO_RECORD_FPS
):
    """Crea un grabador MP4 usando el tamaño del primer fotograma."""

    height, width = frame.shape[:2]

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    grabador = cv2.VideoWriter(
        str(output_path),
        fourcc,
        fps,
        (width, height)
    )

    if not grabador.isOpened():

        grabador.release()

        print(
            "[ERROR] No se pudo crear el archivo de vídeo '{}'.".format(
                output_path
            )
        )

        return None

    print(
        "[INFO] Grabando vídeo MQTT en '{}'.".format(output_path)
    )

    return grabador


# ============================================================
# RECEPTOR DE VÍDEO
# ============================================================

def run_receiver(
    stop_event=None,
    show_window=True,
    mqtt_frame_queue=None,
    record_video=False,
    output_path=None,
    frame_callback=None
):
    """Recibe y decodifica fotogramas JPEG procedentes de MQTT.

    El formato de cada mensaje es:

        timestamp (double, 8 bytes) + JPEG

    En modo dashboard:
        - show_window=False
        - frame_callback recibe los fotogramas BGR.
        - Qt se encarga de mostrar la última imagen disponible.

    En modo original:
        - show_window=True
        - OpenCV muestra directamente el vídeo.

    En modo grabación:
        - record_video=True
        - Los fotogramas se guardan en MP4.
    """

    if cv2 is None or np is None:
        raise ImportError(
            "OpenCV y NumPy son necesarios para recibir vídeo."
        )

    if mqtt_frame_queue is None:
        raise ValueError(
            "Se necesita una cola con los fotogramas MQTT."
        )

    if record_video and not output_path:
        raise ValueError(
            "Se necesita una ruta de salida para grabar el vídeo."
        )

    global hay_senal

    hay_senal = False

    fps = 0.0
    frame_count = 0

    fps_timer = time.time()
    ultimo_fotograma = time.time()

    grabador = None

    header_size = struct.calcsize("!d")

    try:

        while stop_event is None or not stop_event.is_set():

            # ------------------------------------------------
            # OBTENER FOTOGRAMA
            # ------------------------------------------------

            try:

                data = mqtt_frame_queue.get(
                    timeout=SOCKET_TIMEOUT_S
                )

            except queue.Empty:

                if (
                    show_window
                    and comprobar_senal(ultimo_fotograma)
                ):
                    break

                continue

            recv_time = time.time()

            # ------------------------------------------------
            # COMPROBAR CABECERA
            # ------------------------------------------------

            if len(data) <= header_size:
                continue

            send_time = struct.unpack(
                "!d",
                data[:header_size]
            )[0]

            jpeg_bytes = data[header_size:]

            latency_ms = (
                recv_time - send_time
            ) * 1000.0

            # ------------------------------------------------
            # DECODIFICAR JPEG
            # ------------------------------------------------

            np_arr = np.frombuffer(
                jpeg_bytes,
                dtype=np.uint8
            )

            frame = cv2.imdecode(
                np_arr,
                cv2.IMREAD_COLOR
            )

            if frame is None:

                if (
                    show_window
                    and comprobar_senal(ultimo_fotograma)
                ):
                    break

                continue

            # ------------------------------------------------
            # GRABACIÓN MP4
            # ------------------------------------------------

            if record_video:

                if grabador is None:

                    grabador = crear_grabador_mp4(
                        output_path,
                        frame
                    )

                if grabador is not None:
                    grabador.write(frame)

            # ------------------------------------------------
            # ACTUALIZAR SEÑAL
            # ------------------------------------------------

            ultimo_fotograma = time.time()

            if not hay_senal:

                print(
                    "[INFO] Señal de vídeo MQTT recibida."
                )

                hay_senal = True

            # ------------------------------------------------
            # CÁLCULO FPS
            # ------------------------------------------------

            frame_count += 1

            tiempo_actual = time.time()

            if tiempo_actual - fps_timer >= 1.0:

                fps = frame_count / (
                    tiempo_actual - fps_timer
                )

                frame_count = 0
                fps_timer = tiempo_actual

            info_text = (
                "FPS: {:.1f} | Latencia: {:.1f} ms".format(
                    fps,
                    latency_ms
                )
            )

            # ------------------------------------------------
            # MOSTRAR O ENTREGAR FOTOGRAMA
            # ------------------------------------------------

            if show_window:

                cv2.putText(
                    frame,
                    info_text,
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2
                )

            if frame_callback is not None:

                # En dashboard solo entregamos el fotograma.
                # No se realiza ninguna operación de GUI aquí.
                frame_callback(frame)

            elif show_window:

                cv2.imshow(
                    TITULO_VENTANA,
                    frame
                )

                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break

    except KeyboardInterrupt:

        print(
            "\n[INFO] Recepción de vídeo finalizada."
        )

    finally:

        if grabador is not None:

            grabador.release()

            print(
                "[INFO] Archivo MP4 cerrado: '{}'.".format(
                    output_path
                )
            )

        if show_window:
            cv2.destroyAllWindows()


# ============================================================
# EJECUCIÓN DIRECTA
# ============================================================

if __name__ == "__main__":

    print(
        "[ERROR] Ejecute receptor_wifi_halow.py "
        "para recibir vídeo mediante MQTT."
    )
