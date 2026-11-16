"""Configuración y argumentos de línea de comandos del receptor."""

import argparse
import os
from pathlib import Path


DEFAULT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv("MQTT_TOPIC", "lte/telemetria")
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "telemetria_recibida.jsonl"
DEFAULT_VIDEO_OUTPUT = Path(__file__).resolve().parent.parent / "video_recibido.mp4"
DEFAULT_VIDEO_TOPIC = os.getenv("MQTT_VIDEO_TOPIC", "lte/video")
DEFAULT_VIDEO_MQTT_QOS = int(os.getenv("MQTT_VIDEO_QOS", "0"))


def build_parser():
    """Construye el parser de opciones del receptor."""
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
        "--dashboard",
        action="store_true",
        help="Iniciar el panel de control gráfico."
    )
    parser.add_argument(
        "--video-output",
        type=Path,
        default=DEFAULT_VIDEO_OUTPUT,
        help="Archivo MP4 cuando se usa --no-video-window."
    )
    parser.add_argument("--video-topic", default=DEFAULT_VIDEO_TOPIC)
    parser.add_argument(
        "--video-mqtt-qos",
        type=int,
        choices=(0, 1, 2),
        default=DEFAULT_VIDEO_MQTT_QOS
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

