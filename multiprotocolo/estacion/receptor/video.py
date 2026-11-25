"""Vídeo recibido: reensamblado de los trozos BLE y descodificación JPEG.

Formato de un fotograma completo: [hora de envío !d (8 B)] + [JPEG].
"""

import struct

try:
    import cv2
    import numpy as np
except ImportError:  # sin OpenCV solo se pierde el vídeo
    cv2 = None
    np = None


TROZO = struct.Struct("!HH")  # índice del trozo, total de trozos


def descodificar_fotograma(datos):
    """Devuelve (fotograma, hora_envio), o (None, None) si no es válido."""
    if cv2 is None or len(datos) <= 8:
        return None, None
    hora_envio = struct.unpack("!d", datos[:8])[0]
    fotograma = cv2.imdecode(np.frombuffer(datos, dtype=np.uint8, offset=8),
                             cv2.IMREAD_COLOR)
    if fotograma is None:
        return None, None
    return fotograma, hora_envio


class ReensambladorVideo:
    """Junta los trozos BLE de un fotograma: [índice (2 B)][total (2 B)][datos]."""

    def __init__(self):
        self.trozos = []
        self.total = None

    def anadir(self, datos):
        """Devuelve los bytes del fotograma completo, None si aún faltan
        trozos, o False si se ha perdido un trozo (fotograma descartado)."""
        datos = bytes(datos)
        if len(datos) <= TROZO.size:
            return False
        indice, total = TROZO.unpack(datos[:TROZO.size])
        trozo = datos[TROZO.size:]

        if indice == 0:
            descartado = bool(self.trozos)  # el anterior quedó a medias
            self.trozos = [trozo]
            self.total = total
        elif self.total == total and indice == len(self.trozos):
            self.trozos.append(trozo)
            descartado = False
        else:
            # Falta algún trozo: se descarta (se cuenta una sola vez).
            descartado = bool(self.trozos)
            self.trozos = []
            self.total = None
            return False if descartado else None

        if len(self.trozos) == self.total:
            completo = b"".join(self.trozos)
            self.trozos = []
            self.total = None
            return completo
        return False if descartado else None
