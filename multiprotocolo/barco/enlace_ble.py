"""Enlace BLE: servidor GATT (bless) con dos características, telemetría y vídeo."""

import asyncio
import math
import struct

from bless import BlessServer, GATTCharacteristicProperties, GATTAttributePermissions

from formato_paquete import TAMANO


NOMBRE_BLE = "Marítima_Telemetry_Pi"
SERVICIO = "12345678-1234-5678-1234-567890abcdef"
CARACTERISTICA_TELEMETRIA = "87654321-4321-4321-4321-abcdef987654"
CARACTERISTICA_VIDEO = "abcdef12-3456-7890-abcd-ef1234567890"

# Cada fotograma se trocea: [índice (2 B)][total (2 B)][hasta 450 B de datos].
# El PC necesita una MTU BLE de al menos 4 + 450 + 3 = 457 bytes.
TAMANO_TROZO = 450
PAUSA_ENTRE_TROZOS_S = 0.005


def _leer(caracteristica, **kwargs):
    return caracteristica.value or b""


def _escribir(caracteristica, valor, **kwargs):
    pass


class EnlaceBle:
    nombre = "BLE"
    admite_video = True

    def __init__(self, nombre=NOMBRE_BLE):
        self.nombre_ble = nombre
        self.servidor = None

    async def iniciar(self):
        self.servidor = BlessServer(name=self.nombre_ble)
        self.servidor.read_request_func = _leer
        self.servidor.write_request_func = _escribir

        await self.servidor.add_new_service(SERVICIO)
        propiedades = GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify
        for uuid, valor in ((CARACTERISTICA_TELEMETRIA, bytearray(TAMANO)),
                            (CARACTERISTICA_VIDEO, b"")):
            await self.servidor.add_new_characteristic(
                SERVICIO, uuid, propiedades, valor, GATTAttributePermissions.readable
            )
        await self.servidor.start()
        print("[BLE] Servidor anunciándose como '{}'.".format(self.nombre_ble))
        return True

    def _notificar(self, uuid, datos):
        # En bless, update_value() no recibe el dato: primero se guarda el
        # valor en la característica y luego se avisa a los suscritos.
        self.servidor.get_characteristic(uuid).value = bytearray(datos)
        return self.servidor.update_value(SERVICIO, uuid)

    async def enviar_telemetria(self, paquete):
        self._notificar(CARACTERISTICA_TELEMETRIA, paquete)
        return True

    async def enviar_video(self, datos):
        total = math.ceil(len(datos) / TAMANO_TROZO)
        for i in range(total):
            trozo = datos[i * TAMANO_TROZO:(i + 1) * TAMANO_TROZO]
            self._notificar(CARACTERISTICA_VIDEO, struct.pack("!HH", i, total) + trozo)
            # Pausa para no saturar el adaptador Bluetooth.
            await asyncio.sleep(PAUSA_ENTRE_TROZOS_S)

    async def enviar_estado_enlace(self):
        pass  # MTU, conexión y descartes se miden en el PC.

    async def detener(self):
        if self.servidor is not None:
            await self.servidor.stop()
