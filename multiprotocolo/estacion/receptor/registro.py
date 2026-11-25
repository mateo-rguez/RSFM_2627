"""Registro en disco de cada prueba (para comparar protocolos después).

Por cada ejecución se crean dos ficheros en la carpeta de resultados:
    <protocolo>_<fecha>_muestras.jsonl   una línea por paquete recibido
    <protocolo>_<fecha>_resumen.json     prestaciones finales (comparar.py)
"""

import json
import threading
import time
from pathlib import Path


class Registro:
    def __init__(self, carpeta, protocolo, descripcion=""):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        fecha = time.strftime("%Y%m%d_%H%M%S")
        base = "{}_{}".format(protocolo, fecha)
        self.fichero_muestras = self.carpeta / (base + "_muestras.jsonl")
        self.fichero_resumen = self.carpeta / (base + "_resumen.json")
        self.descripcion = descripcion
        self.inicio = time.strftime("%Y-%m-%d %H:%M:%S")
        self._lock = threading.Lock()

    def guardar_muestra(self, muestra):
        with self._lock:
            with self.fichero_muestras.open("a", encoding="utf-8") as fichero:
                json.dump(muestra, fichero, ensure_ascii=False)
                fichero.write("\n")

    def guardar_resumen(self, resumen):
        datos = dict(resumen)
        datos["inicio"] = self.inicio
        datos["fin"] = time.strftime("%Y-%m-%d %H:%M:%S")
        datos["descripcion"] = self.descripcion
        with self._lock:
            with self.fichero_resumen.open("w", encoding="utf-8") as fichero:
                json.dump(datos, fichero, ensure_ascii=False, indent=2)
