"""Centro de datos: une el adaptador del protocolo con las prestaciones,
el registro en disco y el dashboard.

Los adaptadores (uno por protocolo) solo tienen que llamar a:
    centro.muestra_recibida(bytes_del_paquete, hora_llegada, extras)
    centro.fotograma_recibido(bytes_del_fotograma, hora_llegada)
    centro.fotograma_descartado()
    centro.log(texto)
"""

import threading
import time
from collections import deque

import formato_paquete
from .video import descodificar_fotograma


class CentroDatos:
    def __init__(self, protocolo, prestaciones, registro, max_muestras=60, log=print):
        self.protocolo = protocolo
        self.prestaciones = prestaciones
        self.registro = registro
        self._log = log
        self._lock = threading.Lock()
        self._muestras = deque(maxlen=max_muestras)
        self._fotograma = None
        self.ultima_telemetria = 0.0   # time.monotonic() de la última muestra
        self.ultimo_video = 0.0        # time.monotonic() del último fotograma
        self.inicio = time.time()

    def establecer_log(self, funcion):
        self._log = funcion

    def log(self, texto):
        self._log(texto)

    # --- Telemetría ---------------------------------------------------

    def muestra_recibida(self, datos, hora_llegada, extras=None):
        """Procesa un paquete común de 30 bytes. Devuelve la muestra o None."""
        try:
            muestra = formato_paquete.desempaquetar(datos)
        except ValueError as error:
            self.log("[ERROR] Paquete no válido: {}".format(error))
            return None

        latencia_ms, perdidos = self.prestaciones.registrar_muestra(
            muestra["seq"], muestra["t_envio"], hora_llegada, len(datos)
        )
        if latencia_ms is None:
            self.log("[AVISO] Paquete duplicado seq={}".format(muestra["seq"]))
            return None
        if perdidos:
            self.log("[PÉRDIDA] {} paquete(s) perdido(s) antes de seq={}".format(
                perdidos, muestra["seq"]))

        muestra["protocolo"] = self.protocolo
        muestra["hora_llegada"] = hora_llegada
        muestra["latencia_ms"] = latencia_ms
        if extras:
            muestra["enlace"] = extras

        with self._lock:
            self._muestras.append(muestra)
            self.ultima_telemetria = time.monotonic()
        try:
            self.registro.guardar_muestra(muestra)
        except OSError as error:
            self.log("[ERROR] No se pudo guardar la muestra: {}".format(error))

        alt = muestra["altitude"]["altitude_m"]
        acc = muestra["motion"]["accel"]
        self.log("[RX] seq={} | latencia {:.1f} ms | altitud {} m | acc ({}, {}, {}){}".format(
            muestra["seq"], latencia_ms,
            "—" if alt is None else alt, acc["x"], acc["y"], acc["z"],
            " | SIMULADO" if muestra["simulated"] else "",
        ))
        if latencia_ms < 0:
            self.log("[AVISO] Latencia negativa: los relojes del PC y la "
                     "Raspberry no están sincronizados (revisa chrony).")
        return muestra

    def muestras(self):
        with self._lock:
            return list(self._muestras)

    def ultima_muestra(self):
        with self._lock:
            return self._muestras[-1] if self._muestras else None

    # --- Vídeo --------------------------------------------------------

    def fotograma_recibido(self, datos, hora_llegada):
        fotograma, hora_envio = descodificar_fotograma(datos)
        if fotograma is None:
            self.fotograma_descartado()
            return
        self.prestaciones.registrar_fotograma(len(datos), hora_envio, hora_llegada)
        with self._lock:
            self._fotograma = fotograma
            self.ultimo_video = time.monotonic()

    def fotograma_descartado(self):
        self.prestaciones.fotograma_descartado()

    def tomar_fotograma(self):
        """Devuelve el último fotograma nuevo (o None) para mostrarlo."""
        with self._lock:
            fotograma, self._fotograma = self._fotograma, None
        return fotograma
