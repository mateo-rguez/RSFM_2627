from dataclasses import dataclass
from cyclonedds.idl import IdlStruct

# DDS NO PERMITE EL NO ENVIAR DATOS, POR LO QUE SE ENVIA UN BOOL PARA INDICAR SI HAY DATOS DISPONIBLES O NO
@dataclass
class AltitudeData(IdlStruct):
    timestamp_ms: int
    distance_cm: float
    altitude_m: float
    available: bool
    valid: bool


@dataclass
class AccelerometerData(IdlStruct):
    timestamp_ms: int
    x: float
    y: float
    z: float
    available: bool
    valid: bool


@dataclass
class GyroscopeData(IdlStruct):
    timestamp_ms: int
    x: float
    y: float
    z: float
    available: bool
    valid: bool