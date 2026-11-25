"""Formato común del paquete de telemetría.

Es EXACTAMENTE el mismo en Wi-Fi HaLow, LoRa y BLE, para que la comparación
entre protocolos sea justa (todos llevan los mismos 30 bytes).
Este fichero debe ser idéntico en la Raspberry (barco/) y en el PC (estacion/).

Estructura (big-endian, 30 bytes):

    | versión | seq    | t_envio  | altitud | acc_x  | acc_y  | acc_z  | flags |
    | 1 B (B) | 4 B (I)| 8 B (d)  | 4 B (f) | 4 B (f)| 4 B (f)| 4 B (f)| 1 B   |

- seq: número de secuencia (0, 1, 2...). Un hueco = paquete perdido.
- t_envio: hora de envío (segundos desde 1970, como time.time()). Con los
  relojes sincronizados por NTP, latencia = hora de llegada - t_envio.
- Un valor no válido se envía como NaN.
- flags: bit 0 = altitud válida, bit 1 = aceleración válida,
         bit 2 = sensores simulados (no hay placa conectada).
"""

import math
import struct

VERSION = 1
FORMATO = struct.Struct("!BIdffffB")
TAMANO = FORMATO.size  # 30 bytes

ALTITUD_VALIDA = 0x01
ACELERACION_VALIDA = 0x02
SIMULADO = 0x04

NAN = float("nan")


def _numero_o_nan(valor):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return NAN
    return numero if math.isfinite(numero) else NAN


def _valido_o_none(valor):
    """NaN -> None. Se redondea a 4 decimales porque un float de 4 bytes
    no guarda exactamente valores como 0.42."""
    return round(valor, 4) if math.isfinite(valor) else None


def empaquetar(seq, t_envio, altitud, acc_x, acc_y, acc_z, simulado=False):
    """Crea el paquete de 30 bytes. Los valores None o NaN = no válidos."""
    altitud = _numero_o_nan(altitud)
    acc = [_numero_o_nan(v) for v in (acc_x, acc_y, acc_z)]

    flags = 0
    if not math.isnan(altitud):
        flags |= ALTITUD_VALIDA
    if not any(math.isnan(v) for v in acc):
        flags |= ACELERACION_VALIDA
    if simulado:
        flags |= SIMULADO

    return FORMATO.pack(
        VERSION, seq & 0xFFFFFFFF, t_envio, altitud, acc[0], acc[1], acc[2], flags
    )


def empaquetar_desde_colector(seq, lectura, t_envio, simulado=False):
    """Crea el paquete a partir del diccionario de TelemetryCollector.

    Se mira el campo "valid" de cada sensor: altitude_sensor.py pone
    altitude_m = 0.0 cuando la distancia está fuera de rango.
    """
    altitude = lectura.get("altitude") or {}
    motion = lectura.get("motion") or {}
    accel = motion.get("accel") or {}

    altitud = altitude.get("altitude_m") if altitude.get("valid") else None
    if motion.get("valid"):
        acc = (accel.get("x"), accel.get("y"), accel.get("z"))
    else:
        acc = (None, None, None)

    return empaquetar(seq, t_envio, altitud, *acc, simulado=simulado)


def desempaquetar(datos):
    """Convierte los 30 bytes en un diccionario.

    Devuelve el mismo formato que usaban los dashboards anteriores
    ("timestamp", "altitude", "motion"), más "seq" y "t_envio".
    Lanza ValueError si el paquete no tiene el formato correcto.
    """
    datos = bytes(datos)
    if len(datos) != TAMANO:
        raise ValueError(
            "Paquete de {} bytes (se esperaban {})".format(len(datos), TAMANO)
        )
    version, seq, t_envio, alt, ax, ay, az, flags = FORMATO.unpack(datos)
    if version != VERSION:
        raise ValueError("Versión de paquete {} desconocida".format(version))

    simulado = bool(flags & SIMULADO)
    altitud = _valido_o_none(alt) if flags & ALTITUD_VALIDA else None
    acc_valida = bool(flags & ACELERACION_VALIDA)
    acc = [_valido_o_none(v) if acc_valida else None for v in (ax, ay, az)]

    return {
        "seq": seq,
        "t_envio": t_envio,
        "timestamp": t_envio,
        "altitude": {
            "distance_cm": round(altitud * 100, 1) if altitud is not None else None,
            "altitude_m": altitud,
            "valid": altitud is not None,
            "simulated": simulado,
        },
        "motion": {
            "accel": {"x": acc[0], "y": acc[1], "z": acc[2],
                      "valid": acc_valida, "simulated": simulado},
            "gyro": None,  # El paquete común no lleva el giroscopio.
            "valid": acc_valida,
            "gyro_valid": False,
            "simulated": simulado,
        },
        "simulated": simulado,
    }
