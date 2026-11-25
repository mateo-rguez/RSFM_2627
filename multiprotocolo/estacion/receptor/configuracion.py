"""Argumentos de línea de comandos de la estación."""

import argparse
import os
from pathlib import Path


# Ventana para la disponibilidad (% de ventanas con algún paquete) y tiempo
# sin paquetes para avisar "sin datos". LoRa envía 1 paquete cada ~70 s.
VENTANA_DISPONIBILIDAD_S = {"halow": 5.0, "ble": 5.0, "lora": 150.0}
TIEMPO_SIN_DATOS_S = {"halow": 5.0, "ble": 5.0, "lora": 150.0}


def build_parser():
    parser = argparse.ArgumentParser(
        description="Estación de tierra: recibe la telemetría del barco por "
                    "Wi-Fi HaLow, LoRa o BLE y mide las prestaciones."
    )
    parser.add_argument("--protocolo", required=True, choices=("halow", "lora", "ble"))
    parser.add_argument("--sin-dashboard", action="store_true",
                        help="Solo consola (sin ventana).")
    parser.add_argument("--sin-video", action="store_true", help="No recibir vídeo.")
    parser.add_argument("--duracion", type=float, default=None,
                        help="Terminar la prueba tras estos segundos (solo sin dashboard).")
    parser.add_argument("--descripcion", default="",
                        help='Nota que se guarda en el resumen, p. ej. "exterior, 50 m".')
    parser.add_argument("--resultados", type=Path,
                        default=Path(__file__).resolve().parent.parent / "resultados")
    parser.add_argument("--ventana", type=float, default=None,
                        help="Ventana de disponibilidad en s (por defecto 5; LoRa 150).")

    halow = parser.add_argument_group("Wi-Fi HaLow (broker Mosquitto del PC)")
    halow.add_argument("--broker", default=os.getenv("MQTT_BROKER", "127.0.0.1"))
    halow.add_argument("--puerto", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    halow.add_argument("--qos", type=int, choices=(0, 1, 2), default=1)
    halow.add_argument("--usuario", default=os.getenv("MQTT_USERNAME"))
    halow.add_argument("--clave", default=os.getenv("MQTT_PASSWORD"))

    lora = parser.add_argument_group("LoRa (The Things Network)")
    lora.add_argument("--ttn-broker", default=os.getenv("TTN_MQTT_BROKER", "eu1.cloud.thethings.network"))
    lora.add_argument("--ttn-puerto", type=int, default=8883)
    lora.add_argument("--ttn-usuario", default=os.getenv("TTN_MQTT_USERNAME", "test-ttn-rsfm@ttn"),
                      help="<id de la aplicación>@ttn")
    # La API key se lee SIEMPRE de la variable de entorno TTN_MQTT_API_KEY.

    ble = parser.add_argument_group("BLE")
    ble.add_argument("--ble-nombre", default="Marítima_Telemetry_Pi")
    return parser
