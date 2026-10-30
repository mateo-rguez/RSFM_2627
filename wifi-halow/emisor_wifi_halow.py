#!/usr/bin/env python3
"""Emisor de telemetría del barco por MQTT sobre una red Wi-Fi HaLow.

Wi-Fi HaLow solo proporciona la conectividad IP. El transporte de la
telemetría lo realiza MQTT mediante un broker accesible por la red.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt


# El collector existente no es un paquete Python, por lo que añadimos su
# carpeta al path para poder reutilizarlo sin duplicar la lógica de sensores.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SENSORS_DIR = PROJECT_ROOT / "sensores"
sys.path.insert(0, str(SENSORS_DIR))

from collector import TelemetryCollector  # noqa: E402


DEFAULT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv("MQTT_TOPIC", "wifi-halow/telemetria")
DEFAULT_INTERVAL = float(os.getenv("MQTT_INTERVAL", "1.0"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publica la telemetría de los sensores mediante MQTT."
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="IP o nombre del broker MQTT.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto MQTT (por defecto: 1883).")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Topic MQTT de publicación.")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Segundos entre muestras (por defecto: 1).",
    )
    parser.add_argument(
        "--sensor-port",
        default="/dev/ttyUSB0",
        help="Puerto serie de la placa de sensores.",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=38400,
        help="Velocidad del puerto serie.",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("MQTT_USERNAME"),
        help="Usuario MQTT; también puede definirse con MQTT_USERNAME.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("MQTT_PASSWORD"),
        help="Contraseña MQTT; también puede definirse con MQTT_PASSWORD.",
    )
    parser.add_argument("--qos", type=int, choices=(0, 1, 2), default=1)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.interval <= 0:
        raise SystemExit("--interval debe ser mayor que cero.")

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if args.username is not None:
        cliente.username_pw_set(args.username, args.password)

    print(f"[MQTT] Conectando a {args.broker}:{args.port}...")
    try:
        cliente.connect(args.broker, args.port, keepalive=60)
    except OSError as error:
        print(f"[ERROR] No se pudo conectar con el broker: {error}")
        return 1

    colector = TelemetryCollector(port=args.sensor_port, baudrate=args.baudrate)
    cliente.loop_start()

    print(f"[WIFI-HALOW] Publicando en '{args.topic}' cada {args.interval:.2f} s.")
    try:
        while True:
            paquete = colector.collect()
            payload = json.dumps(paquete, ensure_ascii=False, separators=(",", ":"))
            resultado = cliente.publish(args.topic, payload, qos=args.qos)
            resultado.wait_for_publish()

            if resultado.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"[ERROR] No se pudo publicar el mensaje. Código: {resultado.rc}")
            else:
                print(f"[EMISOR] Publicado en '{args.topic}': {payload}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[EMISOR] Deteniendo el envío...")
    finally:
        colector.close()
        cliente.loop_stop()
        cliente.disconnect()
        print("[MQTT] Conexión cerrada.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
