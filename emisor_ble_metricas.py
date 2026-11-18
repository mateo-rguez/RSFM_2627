import time
import asyncio
import struct
import logging
from bless import (
    BlessServer,
    GATTCharacteristicProperties,
    GATTAttributePermissions,
)
from collector import TelemetryCollector

# Definir UUIDs únicos para el servicio y la característica BLE
SERVICE_UUID = "12345678-1234-5678-1234-567890abcdef"
CHAR_UUID = "87654321-4321-4321-4321-abcdef987654"

def empaquetar_datos(paquete):
    """Convierte el diccionario del colector en una estructura binaria compacta."""
    altitud = paquete["altitude"]["altitude_m"]
    accel = paquete["motion"]["accel"]
    valores = [altitud, accel["x"], accel["y"], accel["z"]]
    valores = [float("nan") if v is None else v for v in valores]
    return struct.pack('!Isffff', *valores)

async def run_server(loop):
    colector = TelemetryCollector()
    print("[BLE SERVIDOR] Iniciando servidor de telemetría en la Raspberry Pi...")

    # Inicializar el servidor BLE con un nombre visible
    server = BlessServer(name="Marítima_Telemetry_Pi", loop=loop)

    # Definir el servicio y la característica de lectura/notificación
    await server.add_new_service(SERVICE_UUID)
    
    char_flags = (
        GATTCharacteristicProperties.read
        | GATTCharacteristicProperties.notify
    )
    permissions = GATTAttributePermissions.readable

    await server.add_new_characteristic(
        SERVICE_UUID,
        CHAR_UUID,
        char_flags,
        bytearray(20),
        permissions,
    )

    caracteristica = server.get_characteristic(CHAR_UUID)

    await server.start()
    print("[BLE SERVIDOR] Servidor publicando y listo para conexiones.")

    try:
        while True:
            # 1. Leer sensores
            paquete_dict = colector.collect()
            print(f"[SENSORES] Datos leídos: {paquete_dict}")
            
            # 2. Empaquetar en binario
            # Empaqueta las cuatro lecturas como hasta ahora (16 bytes).
            payload_sensores = empaquetar_datos(paquete_dict)

            # Añade 4 bytes con los bits bajos de la hora Unix en microsegundos.
            tx_us = (time.time_ns() // 1_000) & 0xFFFFFFFF
            payload_binario = struct.pack("!I", tx_us) + payload_sensores

            caracteristica.value = bytearray(payload_binario)
            server.update_value(SERVICE_UUID, CHAR_UUID)
            print(f"[BLE] Paquete actualizado y disponible para el ordenador: {payload_binario.hex().upper()}")
            
            # Intervalo de actualización (ej. cada 5 segundos)
            await asyncio.sleep(5.0)

    except asyncio.CancelledError:
        pass
    finally:
        colector.close()
        await server.stop()
        print("[BLE SERVIDOR] Servidor detenido.")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_server(loop))