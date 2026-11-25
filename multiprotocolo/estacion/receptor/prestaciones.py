"""Prestaciones comunes a los tres protocolos, calculadas igual para todos.

Gracias al paquete común (seq + hora de envío) se puede medir lo mismo en
Wi-Fi HaLow, LoRa y BLE:

- Pérdidas: huecos en el número de secuencia (seq).
- Latencia: hora de llegada al PC - hora de envío en la Raspberry
  (necesita los relojes sincronizados por NTP).
- Jitter: media de la variación de latencia entre paquetes seguidos.
- Régimen útil: bits de telemetría recibidos por segundo.
- Disponibilidad: % de ventanas de tiempo con al menos un paquete.
- Tiempo hasta el primer dato: desde que el PC empieza a conectarse.

Las prestaciones exclusivas de cada protocolo las rellena su adaptador en
el diccionario "especificas" (nombre -> valor ya formateado).
"""

import math
import threading
import time
from collections import deque


def _media(valores):
    return sum(valores) / len(valores) if valores else None


def _percentil(valores, p):
    if not valores:
        return None
    ordenados = sorted(valores)
    k = (len(ordenados) - 1) * p / 100.0
    inferior = math.floor(k)
    superior = math.ceil(k)
    if inferior == superior:
        return ordenados[int(k)]
    return ordenados[inferior] + (ordenados[superior] - ordenados[inferior]) * (k - inferior)


def _jitter(latencias):
    """Media de |L(i) - L(i-1)|: cuánto varía la latencia de un paquete al siguiente."""
    if len(latencias) < 2:
        return None
    return _media([abs(b - a) for a, b in zip(latencias, latencias[1:])])


class Prestaciones:
    def __init__(self, protocolo, ventana_disponibilidad_s):
        self.protocolo = protocolo
        self.ventana_s = ventana_disponibilidad_s
        self._lock = threading.Lock()

        self.inicio_conexion = time.time()
        self.primera_llegada = None
        self.ultima_llegada = None
        self.ultimo_seq = None

        self.recibidos = 0
        self.perdidos = 0
        self.duplicados = 0
        self.reinicios_emisor = 0
        self.bytes_recibidos = 0
        self.bytes_primero = 0
        self.latencias_ms = []      # todas, para el resumen final
        self.llegadas = []          # horas de llegada, para el intervalo medio
        self.ventanas = set()

        self.video_llegadas = deque(maxlen=50)  # (llegada, bytes) para fps y kbit/s
        self.video_latencias_ms = []
        self.video_fotogramas = 0
        self.video_bytes = 0
        self.video_descartados = 0

        self.especificas = {}

    # --- Entradas -----------------------------------------------------

    def marcar_inicio_conexion(self):
        with self._lock:
            self.inicio_conexion = time.time()

    def registrar_muestra(self, seq, t_envio, hora_llegada, num_bytes):
        """Registra un paquete. Devuelve (latencia_ms, perdidos_justo_antes)."""
        with self._lock:
            perdidos = 0
            if self.ultimo_seq is not None:
                if seq == self.ultimo_seq:
                    self.duplicados += 1
                    return None, 0
                if seq > self.ultimo_seq:
                    perdidos = seq - self.ultimo_seq - 1
                else:
                    # seq vuelve a empezar: se ha reiniciado el emisor.
                    self.reinicios_emisor += 1
            self.ultimo_seq = seq
            self.perdidos += perdidos
            self.recibidos += 1
            self.bytes_recibidos += num_bytes

            if self.primera_llegada is None:
                self.primera_llegada = hora_llegada
                self.bytes_primero = num_bytes
            self.ultima_llegada = hora_llegada
            self.llegadas.append(hora_llegada)
            self.ventanas.add(int((hora_llegada - self.primera_llegada) // self.ventana_s))

            latencia_ms = (hora_llegada - t_envio) * 1000.0
            self.latencias_ms.append(latencia_ms)
            return latencia_ms, perdidos

    def registrar_fotograma(self, num_bytes, t_envio, hora_llegada):
        with self._lock:
            self.video_fotogramas += 1
            self.video_bytes += num_bytes
            self.video_llegadas.append((hora_llegada, num_bytes))
            self.video_latencias_ms.append((hora_llegada - t_envio) * 1000.0)

    def fotograma_descartado(self):
        with self._lock:
            self.video_descartados += 1

    def actualizar_especificas(self, valores):
        with self._lock:
            self.especificas.update(valores)

    def sumar_especifica(self, nombre, cantidad=1):
        with self._lock:
            self.especificas[nombre] = self.especificas.get(nombre, 0) + cantidad

    # --- Salidas ------------------------------------------------------

    def resumen(self, ahora=None):
        """Diccionario con todas las prestaciones (se guarda en JSON)."""
        if ahora is None:
            ahora = time.time()
        with self._lock:
            esperados = self.recibidos + self.perdidos
            duracion = (self.ultima_llegada - self.primera_llegada
                        if self.recibidos >= 2 else None)
            intervalos = [b - a for a, b in zip(self.llegadas, self.llegadas[1:])]
            latencias = list(self.latencias_ms)

            disponibilidad = None
            if self.primera_llegada is not None:
                total_ventanas = int((ahora - self.primera_llegada) // self.ventana_s) + 1
                disponibilidad = 100.0 * len(self.ventanas) / total_ventanas

            comunes = {
                "paquetes_recibidos": self.recibidos,
                "paquetes_perdidos": self.perdidos,
                "perdida_pct": 100.0 * self.perdidos / esperados if esperados else None,
                "duplicados": self.duplicados,
                "reinicios_emisor": self.reinicios_emisor,
                "latencia_ultima_ms": latencias[-1] if latencias else None,
                "latencia_media_ms": _media(latencias),
                "latencia_min_ms": min(latencias) if latencias else None,
                "latencia_p95_ms": _percentil(latencias, 95),
                "latencia_max_ms": max(latencias) if latencias else None,
                "jitter_ms": _jitter(latencias),
                "intervalo_medio_s": _media(intervalos),
                # Bits recibidos después del primer paquete / tiempo entre el
                # primero y el último (si no, con pocas muestras sale inflado).
                "regimen_util_bps": ((self.bytes_recibidos - self.bytes_primero) * 8 / duracion
                                     if duracion else None),
                "disponibilidad_pct": disponibilidad,
                "tiempo_primer_dato_s": (self.primera_llegada - self.inicio_conexion
                                         if self.primera_llegada else None),
                "segundos_desde_ultimo": (ahora - self.ultima_llegada
                                          if self.ultima_llegada else None),
                "duracion_s": duracion,
            }

            video = None
            if self.video_fotogramas or self.video_descartados:
                llegadas = list(self.video_llegadas)
                fps = kbps = None
                if len(llegadas) >= 2:
                    tramo = llegadas[-1][0] - llegadas[0][0]
                    if tramo > 0:
                        fps = (len(llegadas) - 1) / tramo
                        kbps = sum(b for _, b in llegadas[1:]) * 8 / tramo / 1000
                total = self.video_fotogramas + self.video_descartados
                video = {
                    "fotogramas": self.video_fotogramas,
                    "descartados": self.video_descartados,
                    "descartados_pct": 100.0 * self.video_descartados / total if total else None,
                    "fps": fps,
                    "regimen_kbps": kbps,
                    "latencia_media_ms": _media(self.video_latencias_ms),
                    "latencia_p95_ms": _percentil(self.video_latencias_ms, 95),
                    "bytes_por_fotograma": (self.video_bytes / self.video_fotogramas
                                            if self.video_fotogramas else None),
                }

            return {
                "protocolo": self.protocolo,
                "comunes": comunes,
                "video": video,
                "especificas": dict(self.especificas),
            }


# --- Presentación (dashboard, consola y comparar.py) -------------------

NOMBRES_PROTOCOLO = {"halow": "Wi-Fi HaLow", "lora": "LoRa", "ble": "BLE"}

# (clave, texto, formato)
FILAS_COMUNES = [
    ("paquetes_recibidos", "Paquetes recibidos", "{:d}"),
    ("paquetes_perdidos", "Paquetes perdidos (huecos de seq)", "{:d}"),
    ("perdida_pct", "Tasa de pérdida", "{:.2f} %"),
    ("latencia_ultima_ms", "Latencia (última)", "{:.1f} ms"),
    ("latencia_media_ms", "Latencia media", "{:.1f} ms"),
    ("latencia_min_ms", "Latencia mínima", "{:.1f} ms"),
    ("latencia_p95_ms", "Latencia percentil 95", "{:.1f} ms"),
    ("latencia_max_ms", "Latencia máxima", "{:.1f} ms"),
    ("jitter_ms", "Jitter", "{:.1f} ms"),
    ("intervalo_medio_s", "Intervalo medio entre paquetes", "{:.2f} s"),
    ("regimen_util_bps", "Régimen útil de telemetría", "{:.1f} bit/s"),
    ("disponibilidad_pct", "Disponibilidad", "{:.1f} %"),
    ("tiempo_primer_dato_s", "Tiempo hasta el primer dato", "{:.1f} s"),
    ("duplicados", "Duplicados", "{:d}"),
    ("reinicios_emisor", "Reinicios del emisor", "{:d}"),
]

FILAS_VIDEO = [
    ("fotogramas", "Fotogramas recibidos", "{:d}"),
    ("descartados", "Fotogramas descartados", "{:d}"),
    ("descartados_pct", "Fotogramas descartados (%)", "{:.1f} %"),
    ("fps", "Fotogramas por segundo", "{:.1f} fps"),
    ("regimen_kbps", "Régimen de vídeo", "{:.1f} kbit/s"),
    ("latencia_media_ms", "Latencia media del vídeo", "{:.1f} ms"),
    ("latencia_p95_ms", "Latencia p95 del vídeo", "{:.1f} ms"),
    ("bytes_por_fotograma", "Tamaño medio de fotograma", "{:.0f} B"),
]


def formatear(valor, formato):
    if valor is None:
        return "—"
    try:
        if "{:d}" in formato:
            valor = int(valor)
        return formato.format(valor)
    except (TypeError, ValueError):
        return str(valor)


def filas_resumen(resumen):
    """Devuelve tres listas de (texto, valor): comunes, vídeo y específicas."""
    comunes = [(texto, formatear(resumen["comunes"].get(clave), fmt))
               for clave, texto, fmt in FILAS_COMUNES]
    video = []
    if resumen.get("video"):
        video = [(texto, formatear(resumen["video"].get(clave), fmt))
                 for clave, texto, fmt in FILAS_VIDEO]
    especificas = [(nombre, "—" if valor is None else str(valor))
                   for nombre, valor in resumen.get("especificas", {}).items()]
    return comunes, video, especificas
