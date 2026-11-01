import time
import threading
from datetime import datetime
import json
import os

from cyclonedds.domain import DomainParticipant
from cyclonedds.topic import Topic
from cyclonedds.sub import DataReader
from cyclonedds.qos import Qos, Policy

from Antiguo.DDS.telemetry_types import (
    AltitudeData,
    AccelerometerData,
    GyroscopeData,
)
from Antiguo.DDS.estacion.graficas import graficar_datos


datos_recibidos = []
datos_lock = threading.Lock()
ejecutando = True

FICHERO_JSON = os.path.join(
    os.path.dirname(__file__),
    "telemetria.jsonl",
)


def guardar_datos_json(datos):
    """Guarda una única muestra por línea."""
    try:
        with open(FICHERO_JSON, "a", encoding="utf-8") as fichero:
            json.dump(datos, fichero, ensure_ascii=False)
            fichero.write("\n")
    except OSError as e:
        print(f"[JSON] Error guardando los datos: {e}")


def crear_paquete_pendiente(timestamp_ms):
    """Crea la estructura inicial de una muestra de telemetría."""
    return {
        "recibidos": set(),
        "valid_accel": False,
        "valid_gyro": False,
        "datos": {
            "timestamp": datetime.fromtimestamp(
                timestamp_ms / 1000
            ).strftime("%d-%m-%Y %H:%M:%S"),
            "altitude": {
                "altitude_m": None,
                "distance_cm": None,
                "valid": False,
            },
            "motion": {
                "accel": {
                    "x": None,
                    "y": None,
                    "z": None,
                },
                "gyro": {
                    "x": None,
                    "y": None,
                    "z": None,
                },
                "valid": False,
            },
        },
    }


def muestra_valida(muestra):
    """Comprueba que la muestra contiene datos válidos."""
    info = getattr(muestra, "sample_info", None)
    return info is not None and info.valid_data


def recibir_datos_dds(
    altitude_reader,
    accelerometer_reader,
    gyroscope_reader,
):
    # Agrupa las muestras de los tres topics por timestamp.
    pendientes = {}

    while ejecutando:
        try:
            # Recibir altitud.
            for muestra in altitude_reader.take(N=10):
                if not muestra_valida(muestra):
                    continue

                t = muestra.timestamp_ms

                paquete = pendientes.setdefault(
                    t, crear_paquete_pendiente(t)
                )

                paquete["datos"]["altitude"] = {
                    "distance_cm": (
                        muestra.distance_cm
                        if muestra.available else None
                    ),
                    "altitude_m": (
                        muestra.altitude_m
                        if muestra.available else None
                    ),
                    "valid": muestra.valid,
                }

                paquete["recibidos"].add("altitude")

            # Recibir acelerómetro.
            for muestra in accelerometer_reader.take(N=10):
                if not muestra_valida(muestra):
                    continue

                t = muestra.timestamp_ms

                paquete = pendientes.setdefault(
                    t, crear_paquete_pendiente(t)
                )

                paquete["datos"]["motion"]["accel"] = {
                    "x": muestra.x if muestra.available else None,
                    "y": muestra.y if muestra.available else None,
                    "z": muestra.z if muestra.available else None,
                }

                paquete["valid_accel"] = (
                    muestra.available and muestra.valid
                )

                paquete["recibidos"].add("accelerometer")

            # Recibir giroscopio.
            for muestra in gyroscope_reader.take(N=10):
                if not muestra_valida(muestra):
                    continue

                t = muestra.timestamp_ms

                paquete = pendientes.setdefault(
                    t, crear_paquete_pendiente(t)
                )

                paquete["datos"]["motion"]["gyro"] = {
                    "x": muestra.x if muestra.available else None,
                    "y": muestra.y if muestra.available else None,
                    "z": muestra.z if muestra.available else None,
                }

                paquete["valid_gyro"] = (
                    muestra.available and muestra.valid
                )

                paquete["recibidos"].add("gyroscope")

            # Procesar las muestras que tengan los tres topics.
            for t in list(pendientes):
                paquete = pendientes[t]

                if paquete["recibidos"] == {
                    "altitude",
                    "accelerometer",
                    "gyroscope",
                }:
                    paquete["datos"]["motion"]["valid"] = (
                        paquete["valid_accel"]
                        and paquete["valid_gyro"]
                    )

                    with datos_lock:
                        datos_recibidos.append(paquete["datos"])
                        guardar_datos_json(paquete["datos"])

                    del pendientes[t]

            # Evitar acumular muestras incompletas indefinidamente.
            if len(pendientes) > 100:
                timestamps_antiguos = sorted(pendientes)[:-50]

                for t in timestamps_antiguos:
                    del pendientes[t]

            time.sleep(0.01)

        except Exception as e:
            print(f"[DDS] Error recibiendo telemetría: {e}")
            time.sleep(0.1)


def main():
    global ejecutando

    participant = DomainParticipant(0)

    altitude_topic = Topic(
        participant,
        "boat/altitude",
        AltitudeData,
    )

    accelerometer_topic = Topic(
        participant,
        "boat/accelerometer",
        AccelerometerData,
    )

    gyroscope_topic = Topic(
        participant,
        "boat/gyroscope",
        GyroscopeData,
    )

    qos = Qos(Policy.Reliability.BestEffort) # Best Effort garantiza que se reciban la mayoría de los datos, pero no todos. Es más rápido y tolerante a pérdidas de paquetes.

    # qos = Qos(Policy.Reliability.Reliable) Reliable garantiza que se reciban todos los datos, pero puede generar retrasos si hay pérdida de paquetes.

    altitude_reader = DataReader(
        participant, altitude_topic, qos=qos
    )
    accelerometer_reader = DataReader(
        participant, accelerometer_topic, qos=qos
    )
    gyroscope_reader = DataReader(
        participant, gyroscope_topic, qos=qos
    )

    hilo = threading.Thread(
        target=recibir_datos_dds,
        args=(
            altitude_reader,
            accelerometer_reader,
            gyroscope_reader,
        ),
        daemon=True,
    )

    hilo.start()

    print("[DDS] Estación iniciada. Esperando telemetría...")

    try:
        graficar_datos(datos_recibidos, datos_lock)

    except KeyboardInterrupt:
        print("\n[ESTACIÓN] Terminando...")

    finally:
        ejecutando = False
        hilo.join(timeout=1)


if __name__ == "__main__":
    main()