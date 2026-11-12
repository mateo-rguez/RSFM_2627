"""Decodificación y presentación de paquetes de telemetría."""

import json


def decodificar_paquete(payload):
    """Convierte el payload MQTT UTF-8 en un diccionario JSON."""
    paquete = json.loads(payload.decode("utf-8"))
    if not isinstance(paquete, dict):
        raise ValueError("El paquete de telemetría no es un objeto JSON")
    return paquete


def resumen_paquete(paquete):
    """Genera el texto de log para una muestra de telemetría."""
    altitude = paquete.get("altitude", {})
    motion = paquete.get("motion", {})
    accel = motion.get("accel", {}) if isinstance(motion, dict) else {}

    if not isinstance(altitude, dict):
        altitude = {}
    if not isinstance(accel, dict):
        accel = {}

    return (
        "[RECEPTOR] timestamp={} | altitud={} m | "
        "aceleración=({}, {}, {})".format(
            paquete.get("timestamp"),
            altitude.get("altitude_m"),
            accel.get("x"),
            accel.get("y"),
            accel.get("z")
        )
    )

