#!/usr/bin/env python3
"""Receptor de telemetría MQTT para la estación de control."""

from __future__ import annotations

import argparse
import json
import os
import threading
from pathlib import Path

import paho.mqtt.client as mqtt


DEFAULT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv("MQTT_TOPIC", "wifi-halow/telemetria")
DEFAULT_OUTPUT = Path(__file__).resolve().with_name("telemetria_recibida.jsonl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recibe y guarda la telemetría MQTT del barco."
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="IP o nombre del broker MQTT.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto MQTT.")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Topic MQTT de suscripción.")
    parser.add_argument("--qos", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Fichero JSON Lines de salida.",
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_lock = threading.Lock()

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if args.username is not None:
        cliente.username_pw_set(args.username, args.password)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[ERROR] El broker rechazó la conexión: {reason_code}")
            return

        client.subscribe(args.topic, qos=args.qos)
        print(f"[MQTT] Suscrito a '{args.topic}'. Esperando datos...")

    def on_message(client, userdata, mensaje):
        try:
            paquete = json.loads(mensaje.payload.decode("utf-8"))

            with output_lock:
                with args.output.open("a", encoding="utf-8") as fichero:
                    json.dump(paquete, fichero, ensure_ascii=False)
                    fichero.write("\n")

            altitude = paquete.get("altitude", {})
            motion = paquete.get("motion", {})
            accel = motion.get("accel", {})
            print(
                f"[RECEPTOR] timestamp={paquete.get('timestamp')} | "
                f"altitud={altitude.get('altitude_m')} m | "
                f"aceleración=({accel.get('x')}, {accel.get('y')}, {accel.get('z')})"
            )
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, AttributeError) as error:
            print(f"[ERROR] Mensaje MQTT no válido: {error}")

    cliente.on_connect = on_connect
    cliente.on_message = on_message

    print(f"[MQTT] Conectando a {args.broker}:{args.port}...")
    try:
        cliente.connect(args.broker, args.port, keepalive=60)
    except OSError as error:
        print(f"[ERROR] No se pudo conectar con el broker: {error}")
        return 1

    print(f"[RECEPTOR] Guardando muestras en '{args.output}'")
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
