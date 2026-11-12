"""Interpretación del estado de los sensores."""


VERDE = "#2eaf50"
NARANJA = "#e69b24"
ROJO = "#e53935"


def estado_sensor(nombre, datos):
    """Devuelve el texto y el color que resumen la última lectura."""
    if datos is None:
        return "{}: SIN DATOS".format(nombre), ROJO

    if not isinstance(datos, dict) or not datos.get("valid"):
        return "{}: NO DISPONIBLE".format(nombre), ROJO

    if "simulated" not in datos:
        return "{}: ORIGEN DESCONOCIDO".format(nombre), NARANJA

    if datos["simulated"]:
        return "{}: SIMULADO".format(nombre), NARANJA

    if datos.get("gyro_valid") is False:
        return "{}: REAL (sin giroscopio)".format(nombre), NARANJA

    return "{}: REAL".format(nombre), VERDE

