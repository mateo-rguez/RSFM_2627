#!/usr/bin/env python3
"""Receptor de telemetría MQTT para la estación de control."""

import argparse
import json
import os
import threading
from pathlib import Path

import paho.mqtt.client as mqtt


DEFAULT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv("MQTT_TOPIC", "wifi-halow/telemetria")
DEFAULT_OUTPUT = Path(__file__).resolve().with_name(
    "telemetria_recibida.jsonl"
)


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
        "--username",
        default=os.getenv("MQTT_USERNAME")
    )

    parser.add_argument(
        "--password",
        default=os.getenv("MQTT_PASSWORD")
    )

    return parser


def main():
    args = build_parser().parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    output_lock = threading.Lock()

    # API compatible con Paho MQTT 1.x
    cliente = mqtt.Client()

    if args.username is not None:
        cliente.username_pw_set(args.username, args.password)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            print("[ERROR] El broker rechazó la conexión: {}".format(rc))
            return

        client.subscribe(args.topic, qos=args.qos)

        print(
            "[MQTT] Suscrito a '{}'. Esperando datos...".format(
                args.topic
            )
        )

    def on_message(client, userdata, mensaje):
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

    try:
        cliente.loop_forever()

    except KeyboardInterrupt:
        print("\n[RECEPTOR] Deteniendo la recepción...")

    finally:
        cliente.disconnect()
        print("[MQTT] Conexión cerrada.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
