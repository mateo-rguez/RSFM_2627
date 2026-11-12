"""Almacenamiento en memoria y en JSONL de la telemetría recibida."""

import json
import threading
from collections import deque
from pathlib import Path


class AlmacenamientoTelemetria:
    """Mantiene las últimas muestras y las persiste en un archivo JSONL."""

    def __init__(self, output_path, max_muestras=40):
        self.output_path = Path(output_path)
        self.muestras = deque(maxlen=max_muestras)
        self._memoria_lock = threading.Lock()
        self._archivo_lock = threading.Lock()

    def guardar(self, paquete):
        """Añade una muestra al buffer y la escribe en disco."""
        with self._memoria_lock:
            self.muestras.append(paquete)

        with self._archivo_lock:
            with self.output_path.open("a", encoding="utf-8") as fichero:
                json.dump(paquete, fichero, ensure_ascii=False)
                fichero.write("\n")

    def obtener_muestras(self):
        """Devuelve una instantánea consistente para las gráficas."""
        with self._memoria_lock:
            return list(self.muestras)

    def ultima_muestra(self):
        with self._memoria_lock:
            return self.muestras[-1] if self.muestras else None

