"""Adaptador BLE: busca la Raspberry, se conecta y se suscribe a la
telemetría y al vídeo (notificaciones GATT). Usa Bleak en un hilo propio.

Prestaciones exclusivas que mide: MTU negociada, tiempo de descubrimiento y
conexión, RSSI del anuncio, desconexiones y fotogramas descartados.
"""

import asyncio
import threading
import time

from bleak import BleakClient, BleakScanner

from .video import ReensambladorVideo


CARACTERISTICA_TELEMETRIA = "87654321-4321-4321-4321-abcdef987654"
CARACTERISTICA_VIDEO = "abcdef12-3456-7890-abcd-ef1234567890"
# Trozo de vídeo: 4 B de cabecera + 450 B de datos; una notificación lleva
# como mucho MTU - 3 bytes, así que hace falta MTU >= 457.
MTU_NECESARIA = 4 + 450 + 3


class AdaptadorBle:
    def __init__(self, centro, nombre, con_video=True):
        self.centro = centro
        self.prest = centro.prestaciones
        self.nombre = nombre
        self.con_video = con_video
        self.conectado = False
        self.parar = threading.Event()
        self.hilo = None
        self.reensamblador = ReensambladorVideo()
        self.conexiones = 0

    def iniciar(self):
        self.prest.marcar_inicio_conexion()
        self.hilo = threading.Thread(target=lambda: asyncio.run(self._bucle()), daemon=True)
        self.hilo.start()

    def detener(self):
        self.parar.set()
        if self.hilo is not None:
            self.hilo.join(timeout=5)

    # --- Recepción (las llama Bleak en su hilo) ------------------------

    def _telemetria(self, _caracteristica, datos):
        self.centro.muestra_recibida(bytes(datos), time.time())

    def _video(self, _caracteristica, datos):
        llegada = time.time()
        resultado = self.reensamblador.anadir(datos)
        if resultado is None:
            return          # faltan trozos de este fotograma
        if resultado is False:
            self.centro.fotograma_descartado()
            return
        self.centro.fotograma_recibido(resultado, llegada)

    # --- Conexión -----------------------------------------------------

    async def _buscar(self):
        """Escanea 5 s y devuelve (dispositivo, rssi) o (None, None)."""
        encontrados = await BleakScanner.discover(timeout=5.0, return_adv=True)
        for dispositivo, anuncio in encontrados.values():
            if self.nombre in (anuncio.local_name, dispositivo.name):
                return dispositivo, anuncio.rssi
        return None, None

    async def _bucle(self):
        while not self.parar.is_set():
            self.centro.log("[BLE] Buscando '{}'...".format(self.nombre))
            inicio = time.monotonic()
            try:
                dispositivo, rssi = await self._buscar()
                if dispositivo is None:
                    self.centro.log("[BLE] Raspberry no encontrada; se reintenta.")
                    await asyncio.sleep(1)
                    continue
                self.prest.actualizar_especificas({"RSSI del anuncio": "{} dBm".format(rssi)})

                desconectado = asyncio.Event()
                async with BleakClient(dispositivo,
                                       disconnected_callback=lambda _: desconectado.set()) as cliente:
                    mtu = cliente.mtu_size
                    suscritas = []
                    if cliente.services.get_characteristic(CARACTERISTICA_TELEMETRIA):
                        await cliente.start_notify(CARACTERISTICA_TELEMETRIA, self._telemetria)
                        suscritas.append("telemetría")
                    if self.con_video and cliente.services.get_characteristic(CARACTERISTICA_VIDEO):
                        self.reensamblador = ReensambladorVideo()
                        await cliente.start_notify(CARACTERISTICA_VIDEO, self._video)
                        suscritas.append("vídeo")

                    ms = (time.monotonic() - inicio) * 1000
                    self.conexiones += 1
                    self.conectado = True
                    self.prest.actualizar_especificas({
                        "MTU negociada": "{} B{}".format(
                            mtu, "" if mtu >= MTU_NECESARIA or not self.con_video
                            else " (¡< {}: el vídeo llegará cortado!)".format(MTU_NECESARIA)),
                        "Carga útil máx. por notificación": "{} B".format(mtu - 3),
                        "Búsqueda + conexión + suscripción (última)": "{:.0f} ms".format(ms),
                        "Conexiones establecidas": self.conexiones,
                    })
                    self.centro.log("[BLE] Conectado (MTU {}) y suscrito a {} en {:.0f} ms.".format(
                        mtu, " + ".join(suscritas) or "nada", ms))

                    while not desconectado.is_set() and not self.parar.is_set():
                        await asyncio.sleep(0.2)

                self.conectado = False
                if not self.parar.is_set():
                    self.prest.sumar_especifica("Desconexiones")
                    self.centro.log("[BLE] Desconectado; se vuelve a buscar.")
            except Exception as error:  # Bleak lanza errores de muchos tipos
                self.conectado = False
                self.centro.log("[BLE] Error: {}: {}".format(type(error).__name__, error))
                await asyncio.sleep(2)
