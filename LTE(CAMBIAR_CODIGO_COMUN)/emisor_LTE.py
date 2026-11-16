"""Emisor de telemetría del barco por MQTT sobre una red Wi-Fi HaLow.

Wi-Fi HaLow proporciona la conectividad IP.
El transporte de telemetría lo realiza MQTT mediante un broker.
"""

import argparse
import json
import os
import threading
import time

import paho.mqtt.client as mqtt

from emisor.collector_LTE import TelemetryCollector


# IP fija del broker MQTT en la estación de control.
# Cámbiala aquí si cambia la dirección de la estación.
DEFAULT_BROKER = "100.83.36.20"
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv(
    "MQTT_TOPIC",
    "lte/telemetria"
)
DEFAULT_INTERVAL = float(os.getenv("MQTT_INTERVAL", "1.0"))
DEFAULT_VIDEO_CAMERA = int(os.getenv("VIDEO_CAMERA", "0"))
DEFAULT_VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "320"))
DEFAULT_VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "240"))
DEFAULT_VIDEO_FPS = float(os.getenv("VIDEO_FPS", "15"))
DEFAULT_VIDEO_QUALITY = int(os.getenv("VIDEO_JPEG_QUALITY", "35"))
DEFAULT_VIDEO_TOPIC = os.getenv("MQTT_VIDEO_TOPIC", "lte/video")
DEFAULT_VIDEO_MQTT_QOS = int(os.getenv("MQTT_VIDEO_QOS", "0"))


def build_parser():

    parser = argparse.ArgumentParser(
        description="Publica la telemetría de los sensores mediante MQTT."
    )

    parser.add_argument(
        "--broker",
        default=DEFAULT_BROKER,
        help="IP o nombre del broker MQTT."
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Puerto MQTT (por defecto: 1883)."
    )

    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help="Topic MQTT de publicación."
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Segundos entre muestras (por defecto: 1)."
    )

    parser.add_argument(
        "--sensor-port",
        default="/dev/ttyUSB0",
        help="Puerto serie de la placa de sensores."
    )

    parser.add_argument(
        "--baudrate",
        type=int,
        default=38400,
        help="Velocidad del puerto serie."
    )

    parser.add_argument(
        "--username",
        default=os.getenv("MQTT_USERNAME"),
        help="Usuario MQTT."
    )

    parser.add_argument(
        "--password",
        default=os.getenv("MQTT_PASSWORD"),
        help="Contraseña MQTT."
    )

    parser.add_argument(
        "--qos",
        type=int,
        choices=(0, 1, 2),
        default=1
    )

    parser.add_argument(
        "--no-video",
        action="store_true",
        help="No iniciar la transmisión de vídeo."
    )

    parser.add_argument(
        "--camera",
        type=int,
        default=DEFAULT_VIDEO_CAMERA,
        help="Índice de la cámara (por defecto: 0)."
    )

    parser.add_argument(
        "--video-width",
        type=int,
        default=DEFAULT_VIDEO_WIDTH
    )

    parser.add_argument(
        "--video-height",
        type=int,
        default=DEFAULT_VIDEO_HEIGHT
    )

    parser.add_argument(
        "--video-fps",
        type=float,
        default=DEFAULT_VIDEO_FPS
    )

    parser.add_argument(
        "--video-quality",
        type=int,
        default=DEFAULT_VIDEO_QUALITY,
        help="Calidad JPEG entre 1 y 100."
    )

    parser.add_argument(
        "--video-topic",
        default=DEFAULT_VIDEO_TOPIC,
        help="Topic MQTT para los fotogramas de vídeo."
    )

    parser.add_argument(
        "--video-mqtt-qos",
        type=int,
        choices=(0, 1, 2),
        default=DEFAULT_VIDEO_MQTT_QOS,
        help="QoS MQTT del vídeo; se recomienda 0."
    )

    return parser


def iniciar_video(args, mqtt_client):
    """Arranca el transmisor MQTT en segundo plano."""
    try:
        from emisor.video_sender_LTE import run_sender, cv2
    except ImportError as error:
        print(
            "[ERROR] No se puede iniciar el vídeo. Instale OpenCV: {}".format(
                error
            )
        )
        return None, None

    if cv2 is None:
        print(
            "[ERROR] No se puede iniciar el vídeo. Instale opencv-python."
        )
        return None, None

    stop_event = threading.Event()

    def worker():
        try:
            run_sender(
                stop_event=stop_event,
                camera_index=args.camera,
                frame_width=args.video_width,
                frame_height=args.video_height,
                target_fps=args.video_fps,
                jpeg_quality=args.video_quality,
                mqtt_client=mqtt_client,
                mqtt_topic=args.video_topic,
                mqtt_qos=args.video_mqtt_qos
            )
        except Exception as error:
            print("[ERROR] Fallo en el transmisor de vídeo: {}".format(error))

    thread = threading.Thread(target=worker, name="video-sender")
    thread.daemon = True
    thread.start()
    return stop_event, thread


def main():

    args = build_parser().parse_args()

    if args.interval <= 0:
        raise SystemExit(
            "--interval debe ser mayor que cero."
        )

    if args.video_fps <= 0:
        raise SystemExit("--video-fps debe ser mayor que cero.")

    if not 1 <= args.video_quality <= 100:
        raise SystemExit("--video-quality debe estar entre 1 y 100.")

    # Cliente compatible con Paho MQTT 1.x
    cliente = mqtt.Client()

    if args.username is not None:
        cliente.username_pw_set(
            args.username,
            args.password
        )

    print(
        "[MQTT] Conectando a {}:{}...".format(
            args.broker,
            args.port
        )
    )

    try:
        cliente.connect(
            args.broker,
            args.port,
            keepalive=60
        )

    except OSError as error:

        print(
            "[ERROR] No se pudo conectar con el broker: {}".format(
                error
            )
        )

        return 1

    colector = None
    video_stop_event = None
    video_thread = None

    try:

        # Inicialización del colector de sensores
        colector = TelemetryCollector(
            port=args.sensor_port,
            baudrate=args.baudrate
        )

        # Inicia el bucle MQTT en segundo plano
        cliente.loop_start()

        if not args.no_video:
            video_stop_event, video_thread = iniciar_video(args, cliente)

        print(
            "[WIFI-HALOW] Publicando en '{}' cada {:.2f} s.".format(
                args.topic,
                args.interval
            )
        )

        while True:

            # Recogida de datos de los sensores
            paquete = colector.collect()

            # Conversión a JSON
            payload = json.dumps(
                paquete,
                ensure_ascii=False,
                separators=(",", ":")
            )

            # Publicación MQTT
            resultado = cliente.publish(
                args.topic,
                payload,
                qos=args.qos
            )

            # Esperar a que se complete el envío
            resultado.wait_for_publish()

            if resultado.rc != mqtt.MQTT_ERR_SUCCESS:

                print(
                    "[ERROR] No se pudo publicar el mensaje. "
                    "Código: {}".format(resultado.rc)
                )

            else:

                print(
                    "[EMISOR] Publicado en '{}': {}".format(
                        args.topic,
                        payload
                    )
                )

            time.sleep(args.interval)

    except KeyboardInterrupt:

        print("\n[EMISOR] Deteniendo el envío...")

    except Exception as error:

        print(
            "[ERROR] Fallo en el emisor: {}".format(error)
        )

        return 1

    finally:

        if colector is not None:
            colector.close()

        if video_stop_event is not None:
            video_stop_event.set()

        if video_thread is not None:
            video_thread.join(2.0)

        cliente.loop_stop()
        cliente.disconnect()

        print("[MQTT] Conexión cerrada.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
