#!/usr/bin/env python3
"""Receptor de telemetría MQTT para la estación de control."""

import argparse
import json
import os
import queue
import threading
from pathlib import Path

import paho.mqtt.client as mqtt


DEFAULT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv("MQTT_TOPIC", "wifi-halow/telemetria")
DEFAULT_OUTPUT = Path(__file__).resolve().with_name(
    "telemetria_recibida.jsonl"
)
DEFAULT_VIDEO_OUTPUT = Path(__file__).resolve().with_name(
    "video_recibido.mp4"
)
DEFAULT_VIDEO_TOPIC = os.getenv("MQTT_VIDEO_TOPIC", "wifi-halow/video")
DEFAULT_VIDEO_MQTT_QOS = int(os.getenv("MQTT_VIDEO_QOS", "0"))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Recibe y guarda la telemetría MQTT del barco."
    )

    parser.add_argument("--broker", default=DEFAULT_BROKER)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--qos", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    parser.add_argument(
        "--no-video",
        action="store_true",
        help="No iniciar la recepción de vídeo."
    )

    parser.add_argument(
        "--no-video-window",
        action="store_true",
        help="No abrir ventana y guardar el vídeo recibido en MP4."
    )

    parser.add_argument(
        "--video-output",
        type=Path,
        default=DEFAULT_VIDEO_OUTPUT,
        help="Archivo MP4 cuando se usa --no-video-window."
    )

    parser.add_argument(
        "--video-topic",
        default=DEFAULT_VIDEO_TOPIC,
        help="Topic MQTT de los fotogramas de vídeo."
    )

    parser.add_argument(
        "--video-mqtt-qos",
        type=int,
        choices=(0, 1, 2),
        default=DEFAULT_VIDEO_MQTT_QOS,
        help="QoS MQTT del vídeo; debe coincidir con el emisor."
    )

    parser.add_argument(
        "--username",
        default=os.getenv("MQTT_USERNAME")
    )

    parser.add_argument(
        "--password",
        default=os.getenv("MQTT_PASSWORD")
    )

    return parser


def cargar_receptor_video():
    """Carga el receptor de vídeo sin hacer obligatoria su dependencia."""
    try:
        from video_receiver_Halow import run_receiver, cv2, np
    except ImportError as error:
        print(
            "[ERROR] No se puede iniciar el vídeo. Instale OpenCV y NumPy: {}".format(
                error
            )
        )
        return None

    if cv2 is None or np is None:
        print(
            "[ERROR] No se puede iniciar el vídeo. Instale opencv-python y numpy."
        )
        return None

    return run_receiver


def main():
    args = build_parser().parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.no_video_window:
        args.video_output.parent.mkdir(parents=True, exist_ok=True)

    output_lock = threading.Lock()

    # API compatible con Paho MQTT 1.x
    cliente = mqtt.Client()

    video_queue = None
    if not args.no_video:
        # Solo se conserva el último fotograma: si OpenCV tarda, no se forma
        # una cola creciente de imágenes antiguas.
        video_queue = queue.Queue(maxsize=1)

    if args.username is not None:
        cliente.username_pw_set(args.username, args.password)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            print("[ERROR] El broker rechazó la conexión: {}".format(rc))
            return

        client.subscribe(args.topic, qos=args.qos)

        if video_queue is not None:
            client.subscribe(
                args.video_topic,
                qos=args.video_mqtt_qos
            )

        if video_queue is None:
            print(
                "[MQTT] Suscrito a '{}'. Esperando datos...".format(
                    args.topic
                )
            )
        else:
            print(
                "[MQTT] Suscrito a telemetría '{}' y vídeo '{}'.".format(
                    args.topic,
                    args.video_topic
                )
            )

    def on_message(client, userdata, mensaje):
        if video_queue is not None and mensaje.topic == args.video_topic:
            payload = mensaje.payload
            if len(payload) <= 8:
                print("[WARN] Fotograma MQTT demasiado pequeño; descartado.")
                return

            try:
                video_queue.put_nowait(payload)
            except queue.Full:
                # Reemplaza el fotograma anterior por el más reciente.
                try:
                    video_queue.get_nowait()
                except queue.Empty:
                    pass

                try:
                    video_queue.put_nowait(payload)
                except queue.Full:
                    pass
            return

        try:
            paquete = json.loads(
                mensaje.payload.decode("utf-8")
            )

            with output_lock:
                with args.output.open("a", encoding="utf-8") as fichero:
                    json.dump(
                        paquete,
                        fichero,
                        ensure_ascii=False
                    )
                    fichero.write("\n")

            altitude = paquete.get("altitude", {})
            motion = paquete.get("motion", {})
            accel = motion.get("accel", {})

            print(
                "[RECEPTOR] timestamp={} | altitud={} m | "
                "aceleración=({}, {}, {})".format(
                    paquete.get("timestamp"),
                    altitude.get("altitude_m"),
                    accel.get("x"),
                    accel.get("y"),
                    accel.get("z")
                )
            )

        except (
            UnicodeDecodeError,
            ValueError,
            OSError,
            AttributeError
        ) as error:

            print(
                "[ERROR] Mensaje MQTT no válido: {}".format(error)
            )

    cliente.on_connect = on_connect
    cliente.on_message = on_message

    print(
        "[MQTT] Conectando a {}:{}...".format(
            args.broker,
            args.port
        )
    )

    try:
        cliente.connect(args.broker, args.port, keepalive=60)

    except OSError as error:
        print(
            "[ERROR] No se pudo conectar con el broker: {}".format(
                error
            )
        )
        return 1

    print(
        "[RECEPTOR] Guardando muestras en '{}'".format(
            args.output
        )
    )

    mqtt_loop_started = False

    try:
        video_receiver = None
        if not args.no_video:
            video_receiver = cargar_receptor_video()

        if video_receiver is None:
            # Sin vídeo, el bucle MQTT puede ejecutarse en el hilo principal.
            cliente.loop_forever()
        else:
            # OpenCV/HighGUI funciona de forma más fiable en el hilo principal.
            # MQTT queda atendido en segundo plano mientras se recibe el vídeo.
            cliente.loop_start()
            mqtt_loop_started = True
            video_receiver(
                show_window=not args.no_video_window,
                mqtt_frame_queue=video_queue,
                record_video=args.no_video_window,
                output_path=args.video_output
            )

    except KeyboardInterrupt:
        print("\n[RECEPTOR] Deteniendo la recepción...")

    except Exception as error:
        print("[ERROR] Fallo en el receptor de vídeo: {}".format(error))

    finally:
        if mqtt_loop_started:
            cliente.loop_stop()
        cliente.disconnect()
        print("[MQTT] Conexión cerrada.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
