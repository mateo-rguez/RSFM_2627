"""
Módulo para la adquisición y validación de datos de altitud/distancia.
Compatible con el sensor de ultrasonidos conectado vía puerto serie (Metro).
"""

import random

# Rangos técnicos operativos del sensor ultrasónico Grove (en cm)
MIN_VALID_DISTANCE_CM = 2.0
MAX_VALID_DISTANCE_CM = 400.0


class AltitudeSensor:
    """Gestiona la lectura y validación de altitud respecto a la superficie."""

    def __init__(self, simulated=False):
        """
        :param simulated: Si es True, fuerza la generación de datos simulados.
        """
        self.simulated = simulated

    def read(self, raw_distance_cm=None):
        """
        Procesa la distancia medida y valida que se encuentre dentro del rango operativo.

        :param raw_distance_cm: Valor numérico recibido del sensor físico (o None si no hay).
        :return: Diccionario con la distancia en cm, altitud en metros y flag de validez.
        """
        if self.simulated:
            # Simulación: distancias plausibles sobre la superficie (20 a 50 cm)
            distance_cm = round(random.uniform(20.0, 50.0), 2)
            is_valid = True

        elif raw_distance_cm is None:
            return{
                "distance_cm": None,
                "altitude_m": None,
                "valid": False
            } 
        else:
            distance_cm = round(float(raw_distance_cm), 3)
            # Validación según criterios DoD: rango técnico operativo
            is_valid = (MIN_VALID_DISTANCE_CM <= distance_cm <= MAX_VALID_DISTANCE_CM)

        altitude_m = round(distance_cm / 100.0, 3) if is_valid else 0.0

        return {
            "distance_cm": distance_cm,
            "altitude_m": altitude_m,
            "valid": is_valid
        }
