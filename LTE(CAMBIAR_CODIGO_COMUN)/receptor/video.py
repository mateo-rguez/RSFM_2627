"""Recepción, decodificación y grabación del vídeo MQTT."""

import queue
import struct
import time

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


def cargar_receptor_video():
    """Devuelve el receptor integrado si están disponibles OpenCV y NumPy."""
    if cv2 is None or np is None:
        print("[ERROR] Instala python3-opencv y python3-numpy.")
        return None
    return run_receiver_integrado


def run_receiver_integrado(
    stop_event=None,
    show_window=True,
    mqtt_frame_queue=None,
    record_video=False,
    output_path=None,
    frame_callback=None,
):
    """Lee timestamp double (!d) + JPEG, igual que el receptor original."""
    if mqtt_frame_queue is None:
        raise ValueError("No se ha creado la cola MQTT de vídeo")
    if record_video and output_path is None:
        raise ValueError("Falta la ruta del MP4")

    writer = None
    ultimo = time.monotonic()
    senal = False
    titulo = "Estacion de Control - Video Barco Solar"

    try:
        while stop_event is None or not stop_event.is_set():
            try:
                payload = mqtt_frame_queue.get(timeout=0.05)
            except queue.Empty:
                if show_window:
                    if time.monotonic() - ultimo > 2:
                        if senal:
                            print("[WARN] Señal de vídeo perdida.")
                            senal = False
                        aviso = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(
                            aviso,
                            "VIDEO NO DISPONIBLE",
                            (90, 230),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            (0, 0, 255),
                            2,
                        )
                        cv2.imshow(titulo, aviso)
                    if (cv2.waitKey(1) & 0xFF) == ord("q"):
                        break
                continue

            if len(payload) <= 8:
                continue

            try:
                instante_emision = struct.unpack("!d", payload[:8])[0]
                frame = cv2.imdecode(
                    np.frombuffer(payload[8:], dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
            except (ValueError, struct.error, cv2.error):
                continue

            if frame is None:
                continue

            ultimo = time.monotonic()
            if not senal:
                print("[INFO] Señal de vídeo MQTT recibida.")
                senal = True

            if record_video:
                if writer is None:
                    alto, ancho = frame.shape[:2]
                    writer = cv2.VideoWriter(
                        str(output_path),
                        cv2.VideoWriter_fourcc(*"mp4v"),
                        30.0,
                        (ancho, alto),
                    )
                    if not writer.isOpened():
                        writer.release()
                        writer = None
                        print("[ERROR] No se pudo abrir el MP4: {}".format(output_path))
                        record_video = False
                if writer is not None:
                    writer.write(frame)

            if frame_callback is not None:
                frame_callback(frame)
            elif show_window:
                latencia = (time.time() - instante_emision) * 1000
                cv2.putText(
                    frame,
                    "Latencia: {:.1f} ms".format(latencia),
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow(titulo, frame)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
    finally:
        if writer is not None:
            writer.release()
            print("[INFO] MP4 guardado en '{}'".format(output_path))
        if show_window:
            cv2.destroyAllWindows()

