"""
Módulo para la adquisición y validación de datos de movimiento.
Mide aceleraciones en tres ejes y velocidades de rotación.
"""

import math
import random

# Gravedad estándar en reposo ~ 9.81 m/s²
GRAVITY_NOMINAL = 9.81
# Umbrales plausibles de aceleración
# (Valores provisionales dado que aún no lo hemos probado)
MIN_TOTAL_ACCEL = 0.0
MAX_TOTAL_ACCEL = 100.0


class MotionSensor:
    """Gestiona la lectura y validación de inercia y movimiento."""

    def __init__(self, simulated=False):
        """
        :param simulated: Si es True, fuerza la generación de datos simulados.
        """
        self.simulated = simulated

    def read(self, raw_accel=None, raw_gyro=None):
        """
        Procesa los vectores de aceleración y rotación y valida su plausibilidad física.

        :param raw_accel: Diccionario con claves 'x', 'y', 'z' de aceleración real.
        :param raw_gyro: Diccionario con claves 'x', 'y', 'z' de velocidad angular real.
        :return: Diccionario con vectores y flag booleano de validez.
        """
        if self.simulated or raw_accel is None:
            # Simulación: Barco en reposo con suave oleaje
            ax = round(random.uniform(-0.1, 0.1), 3)
            ay = round(random.uniform(-0.1, 0.1), 3)
            az = GRAVITY_NOMINAL
            gx = round(random.uniform(-0.02, 0.02), 3)
            gy = round(random.uniform(-0.02, 0.02), 3)
            gz = round(random.uniform(-0.02, 0.02), 3)
        else:
            ax = float(raw_accel.get("x", 0.0))
            ay = float(raw_accel.get("y", 0.0))
            az = float(raw_accel.get("z", GRAVITY_NOMINAL))
            gx = float(raw_gyro.get("x", 0.0)) if raw_gyro else 0.0
            gy = float(raw_gyro.get("y", 0.0)) if raw_gyro else 0.0
            gz = float(raw_gyro.get("z", 0.0)) if raw_gyro else 0.0

        # Validación DoD: La magnitud del vector aceleración debe ser consistente con reposo/navegación
        total_accel = math.sqrt(ax**2 + ay**2 + az**2)
        is_valid = (MIN_TOTAL_ACCEL <= total_accel <= MAX_TOTAL_ACCEL)

        return {
            "accel": {"x": ax, "y": ay, "z": az},
            "gyro": {"x": gx, "y": gy, "z": gz},
            "valid": is_valid
        }