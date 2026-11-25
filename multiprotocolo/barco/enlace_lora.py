"""Enlace LoRa: envía el paquete a la CubeCell por USB serie (protocolo HEX:).

La CubeCell (sketch CubeCell_Telemetria_v2.ino) lo pone en cola y lo
transmite por LoRaWAN a TTN.
"""

import asyncio
import queue
import threading
import time

import serial


ESPERA_ARRANQUE_S = 6  # la CubeCell se reinicia al abrir el puerto
RESPUESTAS = ("OK", "BUSY")


class EnlaceLora:
    nombre = "LoRa"
    admite_video = False

    def __init__(self, puerto):
        self.puerto = puerto
        self.ser = None
        self.respuestas = queue.Queue()
        self.parar = threading.Event()
        self.hilo = None

    async def iniciar(self):
        self.ser = serial.Serial(self.puerto, 115200, timeout=0.5, write_timeout=2)
        # Un hilo lee todo lo que escribe la CubeCell: las respuestas a HEX:
        # van a una cola y el resto (unión OTAA, TX_SOLICITADO...) se muestra.
        self.hilo = threading.Thread(target=self._leer, daemon=True)
        self.hilo.start()
        print("[LORA] Esperando {} s a que arranque la CubeCell...".format(ESPERA_ARRANQUE_S))
        await asyncio.sleep(ESPERA_ARRANQUE_S)
        return True

    def _leer(self):
        while not self.parar.is_set():
            try:
                linea = self.ser.readline().decode("ascii", errors="replace").strip()
            except serial.SerialException as error:
                print("[ERROR USB] {}".format(error))
                return
            if not linea:
                continue
            if linea in RESPUESTAS or linea.startswith("ERROR:"):
                self.respuestas.put(linea)
            else:
                print("[CUBECELL] {}".format(linea), flush=True)

    def _enviar(self, paquete):
        while not self.respuestas.empty():  # descarta respuestas antiguas
            self.respuestas.get_nowait()
        self.ser.write("HEX:{}\n".format(paquete.hex().upper()).encode("ascii"))
        self.ser.flush()
        try:
            return self.respuestas.get(timeout=5)
        except queue.Empty:
            return "SIN_RESPUESTA"

    async def enviar_telemetria(self, paquete):
        """Devuelve True si la CubeCell ha aceptado el paquete (OK)."""
        respuesta = await asyncio.to_thread(self._enviar, paquete)
        if respuesta == "OK":
            return True
        if respuesta == "BUSY":
            print("[LORA] La CubeCell aún tiene un paquete pendiente "
                  "(¿no se ha unido a TTN?). Se omite esta muestra.")
        elif respuesta == "ERROR:APPKEY":
            print("[LORA] Falta la AppKey en el sketch de la CubeCell.")
        elif respuesta == "ERROR:LONGITUD":
            print("[LORA] La CubeCell no acepta 30 bytes: carga CubeCell_Telemetria_v2.ino.")
        else:
            print("[LORA] Respuesta de la CubeCell: {}".format(respuesta))
        return False

    async def enviar_video(self, datos):
        pass  # LoRa no tiene ancho de banda para vídeo.

    async def enviar_estado_enlace(self):
        pass  # Las estadísticas de radio las da TTN (RSSI, SNR, SF...).

    async def detener(self):
        self.parar.set()
        if self.hilo is not None:
            self.hilo.join(timeout=1)
        if self.ser is not None:
            self.ser.close()
