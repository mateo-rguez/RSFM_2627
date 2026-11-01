"""Emisor de telemetría del barco por MQTT sobre una red Wi-Fi HaLow.

Wi-Fi HaLow proporciona la conectividad IP.
El transporte de telemetría lo realiza MQTT mediante un broker.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt


# El collector existente no es un paquete Python.
# Añadimos su carpeta al path para reutilizar la lógica de sensores.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SENSORS_DIR = PROJECT_ROOT / "sensores"

sys.path.insert(0, str(SENSORS_DIR))

from collector_Halow import TelemetryCollector


DEFAULT_BROKER = os.getenv("MQTT_BROKER", "192.168.200.1")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv(
    "MQTT_TOPIC",
    "wifi-halow/telemetria"
)
DEFAULT_INTERVAL = float(os.getenv("MQTT_INTERVAL", "1.0"))


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

    return parser


def main():

    args = build_parser().parse_args()

    if args.interval <= 0:
        raise SystemExit(
            "--interval debe ser mayor que cero."
        )

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

    try:

        # Inicialización del colector de sensores
        colector = TelemetryCollector(
            port=args.sensor_port,
            baudrate=args.baudrate
        )

        # Inicia el bucle MQTT en segundo plano
        cliente.loop_start()

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

        cliente.loop_stop()
        cliente.disconnect()

        print("[MQTT] Conexión cerrada.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
