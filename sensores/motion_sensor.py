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
        :return: Diccionario con vectores, flags booleanos de validez y origen de los datos.
        """
        gyro_valid = True

        if self.simulated:
            # Simulación: Barco en reposo con suave oleaje
            ax = round(random.uniform(-0.1, 0.1), 3)
            ay = round(random.uniform(-0.1, 0.1), 3)
            az = GRAVITY_NOMINAL
            gx = round(random.uniform(-0.02, 0.02), 3)
            gy = round(random.uniform(-0.02, 0.02), 3)
            gz = round(random.uniform(-0.02, 0.02), 3)
        else:
            # Un eje ausente o no numérico invalida la lectura: no se rellena con
            # valores por defecto porque parecerían medidas reales
            try:
                ax = float(raw_accel["x"]) * GRAVITY_NOMINAL
                ay = float(raw_accel["y"]) * GRAVITY_NOMINAL
                az = float(raw_accel["z"]) * GRAVITY_NOMINAL
            except (KeyError, TypeError, ValueError):
                return {
                    "accel": {"x": None, "y": None, "z": None},
                    "gyro": {"x": None, "y": None, "z": None},
                    "valid": False,
                    "gyro_valid": False,
                    "simulated": False
                }

            # El giroscopio se valida aparte para conservar la aceleración si solo falla él
            try:
                gx = float(raw_gyro["x"])
                gy = float(raw_gyro["y"])
                gz = float(raw_gyro["z"])
            except (KeyError, TypeError, ValueError):
                gx = gy = gz = None
                gyro_valid = False

        # Validación DoD: La magnitud del vector aceleración debe ser consistente con reposo/navegación
        total_accel = math.hypot(ax, ay, az)
        is_valid = (MIN_TOTAL_ACCEL <= total_accel <= MAX_TOTAL_ACCEL)

        return {
            "accel": {"x": ax, "y": ay, "z": az},
            "gyro": {"x": gx, "y": gy, "z": gz},
            "valid": is_valid,
            "gyro_valid": gyro_valid,
            "simulated": self.simulated     # Permite a la estación saber si el dato es real
        }
