import time

from cyclonedds.domain import DomainParticipant
from cyclonedds.topic import Topic
from cyclonedds.pub import DataWriter
from cyclonedds.qos import Qos, Policy

from DDS.telemetry_types import (
    AltitudeData,
    AccelerometerData,
    GyroscopeData,
)


class TelemetryPublisher:

    def __init__(self, domain_id=0):
        self.participant = DomainParticipant(domain_id)

        # Topic de altitud
        altitude_topic = Topic(
            self.participant,
            "boat/altitude",
            AltitudeData
        )

        # Topic de acelerómetro
        accelerometer_topic = Topic(
            self.participant,
            "boat/accelerometer",
            AccelerometerData
        )

        # Topic de giroscopio
        gyroscope_topic = Topic(
            self.participant,
            "boat/gyroscope",
            GyroscopeData
        )

        qos = Qos(Policy.Reliability.BestEffort) # Best Effort garantiza que se reciban la mayoría de los datos, pero no todos. Es más rápido y tolerante a pérdidas de paquetes.
        # qos = Qos(Policy.Reliability.Reliable) Reliable garantiza que se reciban todos los datos, pero puede generar retrasos si hay pérdida de paquetes.


        self.altitude_writer = DataWriter(
            self.participant, altitude_topic, qos=qos
        )
        self.accelerometer_writer = DataWriter(
            self.participant, accelerometer_topic, qos=qos
        )
        self.gyroscope_writer = DataWriter(
            self.participant, gyroscope_topic, qos=qos
        )

    def publish(self, packet):
        timestamp_ms = time.time_ns() // 1_000_000

        # -------------------------
        # Publicar altitud
        # -------------------------
        altitude = packet["altitude"]

        distance = altitude["distance_cm"]
        altitude_m = altitude["altitude_m"]

        altitude_available = (
            distance is not None and altitude_m is not None
        )

        self.altitude_writer.write(
            AltitudeData(
                timestamp_ms=timestamp_ms,
                distance_cm=(
                    float(distance) if distance is not None else 0.0
                ),
                altitude_m=(
                    float(altitude_m)
                    if altitude_m is not None else 0.0
                ),
                available=altitude_available,
                valid=bool(altitude["valid"])
            )
        )

        # -------------------------
        # Publicar acelerómetro
        # -------------------------
        motion = packet["motion"]
        accel = motion["accel"]

        accel_available = all(
            accel[axis] is not None for axis in ("x", "y", "z")
        )

        self.accelerometer_writer.write(
            AccelerometerData(
                timestamp_ms=timestamp_ms,
                x=float(accel["x"]) if accel["x"] is not None else 0.0,
                y=float(accel["y"]) if accel["y"] is not None else 0.0,
                z=float(accel["z"]) if accel["z"] is not None else 0.0,
                available=accel_available,
                valid=bool(motion["valid"])
            )
        )

        # -------------------------
        # Publicar giroscopio
        # -------------------------
        gyro = motion["gyro"]

        gyro_available = all(
            gyro[axis] is not None for axis in ("x", "y", "z")
        )

        self.gyroscope_writer.write(
            GyroscopeData(
                timestamp_ms=timestamp_ms,
                x=float(gyro["x"]) if gyro["x"] is not None else 0.0,
                y=float(gyro["y"]) if gyro["y"] is not None else 0.0,
                z=float(gyro["z"]) if gyro["z"] is not None else 0.0,
                available=gyro_available,
                valid=bool(motion["valid"])
            )
        )