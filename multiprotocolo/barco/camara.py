"""Captura de la cámara USB y compresión JPEG (común a Wi-Fi HaLow y BLE).

Cada fotograma se envía como: [hora de envío !d (8 bytes)] + [JPEG].
"""

import struct
import time

import cv2


class Camara:
    def __init__(self, indice=0, ancho=160, alto=120, fps=5, calidad_jpeg=30):
        self.indice = indice
        self.ancho = ancho
        self.alto = alto
        self.fps = fps
        self.calidad_jpeg = calidad_jpeg
        self.cap = None

    def abrir(self):
        """Abre la cámara. Devuelve True si se ha podido abrir."""
        self.cap = cv2.VideoCapture(self.indice, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.ancho)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.alto)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        if not self.cap.isOpened():
            print("[ERROR] No se pudo abrir la cámara /dev/video{}.".format(self.indice))
            print("        Si pone 'Permission denied': sudo usermod -aG video $USER y reinicia la sesión.")
            return False
        print("[VIDEO] Cámara abierta: {}x{}, {} fps, calidad JPEG {}.".format(
            self.ancho, self.alto, self.fps, self.calidad_jpeg))
        return True

    def capturar(self):
        """Lee un fotograma y lo devuelve listo para enviar, o None si falla.

        Espera a la cámara: llamarla con asyncio.to_thread() para no bloquear.
        """
        ok, fotograma = self.cap.read()
        if not ok:
            return None
        ok, jpeg = cv2.imencode(
            ".jpg", fotograma, [int(cv2.IMWRITE_JPEG_QUALITY), self.calidad_jpeg]
        )
        if not ok:
            return None
        # Hora real (como time.time() en el PC) para calcular la latencia.
        return struct.pack("!d", time.time()) + jpeg.tobytes()

    def cerrar(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
