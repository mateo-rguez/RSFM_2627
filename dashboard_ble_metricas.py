import asyncio
import csv
import math
import struct
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from statistics import median

from bleak import BleakClient, BleakScanner
from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QLabel, QMainWindow, QPlainTextEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

NOMBRE = "Marítima_Telemetry_Pi"
CARACTERISTICA = "87654321-4321-4321-4321-abcdef987654"
PAQUETE_ANTERIOR = struct.Struct("!ffff")
PAQUETE = struct.Struct("!Iffff")
MASCARA_U32 = (1 << 32) - 1
VENTANA_CAUDAL_S = 10.0
PERIODO_S = 5.0
SILENCIO_S = 12.0


def hora_local():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def diferencia_u32(actual, anterior):
    """Diferencia con signo entre dos marcas de tiempo de 32 bits."""
    mitad = 1 << 31
    return ((actual - anterior + mitad) & MASCARA_U32) - mitad


def decodificar(datos, rx_us):
    if len(datos) == PAQUETE.size:
        tx_us, *valores = PAQUETE.unpack(datos)
        latencia_ms = diferencia_u32(rx_us, tx_us) / 1000
        return len(datos), valores, tx_us, rx_us, latencia_ms
    if len(datos) == PAQUETE_ANTERIOR.size:
        return len(datos), PAQUETE_ANTERIOR.unpack(datos), None, rx_us, None
    return None


def jitter_ms(anterior, actual):
    if anterior is None or anterior[-1] is None or actual[-1] is None:
        return None
    return abs(actual[-1] - anterior[-1])


def p95(valores):
    ordenados = sorted(valores)
    return ordenados[math.ceil(0.95 * len(ordenados)) - 1]


def texto_ms(valor):
    return "—" if valor is None else f"{valor:.2f} ms"


class ReceptorBLE(QThread):
    evento = pyqtSignal(str, float, str, object)

    def publicar(self, tipo, detalle=""):
        self.evento.emit(tipo, time.monotonic(), hora_local(), detalle)

    def recibir(self, _caracteristica, datos):
        rx_us = time.time_ns() // 1000
        llegada = time.monotonic()
        hora = hora_local()
        muestra = decodificar(datos, rx_us)
        if muestra is not None:
            self.evento.emit("muestra", llegada, hora, muestra)
        else:
            self.evento.emit("invalido", llegada, hora, len(datos))

    async def conectar(self):
        while True:
            self.publicar("buscando", NOMBRE)
            try:
                dispositivo = await BleakScanner.find_device_by_name(NOMBRE, timeout=8)
                if dispositivo is None:
                    self.publicar("aviso", "Raspberry Pi no encontrada")
                else:
                    desconectado = asyncio.Event()
                    async with BleakClient(
                        dispositivo,
                        disconnected_callback=lambda _: desconectado.set(),
                    ) as cliente:
                        await cliente.start_notify(CARACTERISTICA, self.recibir)
                        self.publicar("suscrito")
                        await desconectado.wait()
                        self.publicar("desconectado")
            except Exception as error:
                self.publicar("error", f"{type(error).__name__}: {error}")
            await asyncio.sleep(2)

    async def ejecutar(self):
        tarea = asyncio.create_task(self.conectar())
        try:
            while not self.isInterruptionRequested() and not tarea.done():
                await asyncio.sleep(0.2)
        finally:
            tarea.cancel()
            await asyncio.gather(tarea, return_exceptions=True)

    def run(self):
        asyncio.run(self.ejecutar())


class Dashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Estación de Control - Barco Solar | BLE")
        self.resize(980, 760)
        self.origen = time.monotonic()
        self.ultima = None
        self.suscrito = False
        self.cerrando = False
        self.muestras = deque(maxlen=40)
        self.inicio = self.fin = None
        self.filas = []
        self.llegadas = []
        self.invalidos = 0
        self.anterior = self.anterior_prueba = None
        self.jitter_actual = None
        self.bytes_prueba = 0
        self.latencias_prueba = []
        self.jitters_prueba = []
        self.ventana_rx = deque()
        self.caudal = deque(maxlen=180)
        self.retardos = deque(maxlen=40)
        self.siguiente_punto = self.origen

        figura = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(figura)
        self.ejes = figura.subplots(3, 1, sharex=True)
        altitud, aceleracion, intervalos = self.ejes
        self.curvas = [altitud.plot([], [], ".-", label="Altitud")[0]]
        for eje in "XYZ":
            linea, = aceleracion.plot([], [], ".-", label=eje)
            self.curvas.append(linea)
        self.curvas.append(intervalos.plot([], [], ".-")[0])
        altitud.set_ylabel("Altitud (m)")
        aceleracion.set_ylabel("Aceleración")
        aceleracion.legend(loc="upper right")
        intervalos.set_ylabel("Intervalo RX (s)")
        intervalos.set_xlabel("Segundos desde que se abrió el panel")
        intervalos.axhline(PERIODO_S, color="gray", linestyle="--")
        for eje in self.ejes:
            eje.grid(alpha=0.3)

        self.sensores = QLabel("Esperando muestras BLE")
        self.sensores.setWordWrap(True)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(2000)
        pestanas = QTabWidget()
        pestanas.addTab(self.canvas, "Telemetría")
        self.crear_graficas_rendimiento(pestanas)
        pestanas.addTab(self.sensores, "Sensores")
        pestanas.addTab(self.logs, "Logs")

        self.duracion = QSpinBox()
        self.duracion.setRange(10, 3600)
        self.duracion.setValue(300)
        self.duracion.setSuffix(" s")
        self.boton = QPushButton("Iniciar medición")
        self.boton.setEnabled(False)
        self.boton.clicked.connect(self.iniciar)
        self.resumen = QLabel("Conecta la Raspberry Pi para habilitar la medición.")
        self.resumen.setWordWrap(True)
        central = QWidget()
        layout = QVBoxLayout(central)
        self.indicadores = QLabel()
        self.indicadores.setWordWrap(True)
        layout.addWidget(self.indicadores)
        layout.addWidget(pestanas, 1)
        for widget in (self.duracion, self.boton, self.resumen):
            layout.addWidget(widget)
        self.setCentralWidget(central)

        self.receptor = ReceptorBLE(self)
        self.receptor.evento.connect(self.procesar)
        self.receptor.finished.connect(self.close)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.actualizar)
        self.timer.start(250)
        self.receptor.start()

    def crear_graficas_rendimiento(self, pestanas):
        figura = Figure(layout="constrained")
        self.canvas_rendimiento = FigureCanvasQTAgg(figura)
        self.ejes_rendimiento = figura.subplots(3, 1, sharex=True)
        latencia, regimen, jitter = self.ejes_rendimiento
        self.curva_latencia, = latencia.plot([], [], ".-", color="#2457a6")
        self.curva_regimen, = regimen.plot([], [], color="#237456")
        self.curva_jitter, = jitter.plot([], [], ".-", color="#a65222")
        latencia.set_ylabel("Latencia (ms)")
        regimen.set_ylabel("Régimen RX (paq/s)")
        jitter.set_ylabel("Jitter (ms)")
        jitter.set_xlabel("Segundos desde que se abrió el panel")
        for eje in self.ejes_rendimiento:
            eje.grid(alpha=0.3)
        pestanas.addTab(self.canvas_rendimiento, "Rendimiento BLE")

    def iniciar(self):
        self.inicio = time.monotonic()
        self.fin = self.inicio + self.duracion.value()
        self.filas.clear()
        self.llegadas.clear()
        self.invalidos = 0
        self.anterior_prueba = None
        self.bytes_prueba = 0
        self.latencias_prueba.clear()
        self.jitters_prueba.clear()
        self.boton.setEnabled(False)
        self.duracion.setEnabled(False)
        self.resumen.setText("Medición en curso…")

    def procesar(self, tipo, t, hora, dato):
        en_prueba = self.inicio is not None and self.inicio <= t < self.fin

        if tipo == "muestra":
            tamano, valores, tx_us, rx_us, latencia = dato
            self.jitter_actual = jitter_ms(self.anterior, dato)
            self.anterior = dato
            self.ventana_rx.append((t, tamano))
            self.retardos.append((t - self.origen, latencia, self.jitter_actual))

            if en_prueba:
                intervalo = t - self.llegadas[-1] if self.llegadas else None
                variacion = jitter_ms(self.anterior_prueba, dato)
                self.anterior_prueba = dato
                self.llegadas.append(t)
                self.bytes_prueba += tamano
                if latencia is not None:
                    self.latencias_prueba.append(latencia)
                if variacion is not None:
                    self.jitters_prueba.append(variacion)
                self.filas.append([
                    hora, t - self.inicio, tipo, tamano, intervalo, *valores,
                    tx_us, rx_us, latencia, variacion, "",
                ])

            intervalo = math.nan if self.ultima is None else t - self.ultima
            self.ultima = t
            self.muestras.append((t - self.origen, *valores, intervalo))
            nombres = ("Altitud (m)", "Aceleración X", "Aceleración Y", "Aceleración Z")
            lecturas = [f"{v:.3f}" if math.isfinite(v) else "Sin lectura" for v in valores]
            self.sensores.setText("   |   ".join(
                f"{nombre}: {valor}" for nombre, valor in zip(nombres, lecturas)
            ))
            self.redibujar()
            return

        if tipo in ("buscando", "desconectado", "error"):
            self.suscrito = False
            self.anterior = self.anterior_prueba = None
            self.jitter_actual = None
            if self.retardos:
                self.retardos.append((t - self.origen, None, None))
        elif tipo == "suscrito":
            self.suscrito = True

        detalle = f"{dato} bytes" if tipo == "invalido" else dato
        if en_prueba:
            self.invalidos += int(tipo == "invalido")
            self.filas.append([
                hora, t - self.inicio, tipo, dato if tipo == "invalido" else "",
                *[""] * 9, detalle,
            ])
        self.logs.appendPlainText(f"{hora}  {tipo.upper()} {detalle}")

    def redibujar(self):
        tiempos, *columnas = zip(*self.muestras)
        for curva, datos in zip(self.curvas, columnas):
            curva.set_data(tiempos, datos)
        for eje in self.ejes:
            eje.relim()
            eje.autoscale_view()
        self.canvas.draw_idle()

    def actualizar_rendimiento(self, ahora):
        ventana = min(VENTANA_CAUDAL_S, ahora - self.origen)
        if ventana <= 0:
            return
        while self.ventana_rx and self.ventana_rx[0][0] <= ahora - VENTANA_CAUDAL_S:
            self.ventana_rx.popleft()
        regimen = len(self.ventana_rx) / ventana
        caudal = sum(tamano for _, tamano in self.ventana_rx) / ventana

        latencia = self.anterior[-1] if self.anterior and self.suscrito else None
        jitter = self.jitter_actual
        if self.ultima is not None and ahora - self.ultima >= SILENCIO_S:
            latencia = jitter = None
        texto = (f"Latencia ida estimada: {texto_ms(latencia)}   |   "
                 f"Régimen RX: {regimen:.2f} paq/s · {caudal:.2f} B/s   |   "
                 f"Jitter: {texto_ms(jitter)}")
        if latencia is not None and latencia < 0:
            texto += "\nLatencia negativa: comprueba la sincronización Pi–PC."
        elif self.anterior is not None and self.anterior[2] is None:
            texto += "\nPaquete de 16 B: activa la marca TX en el emisor para medir latencia y jitter."
        self.indicadores.setText(texto)
        if ahora < self.siguiente_punto:
            return

        self.siguiente_punto = ahora + 1
        self.caudal.append((ahora - self.origen, regimen))
        self.curva_regimen.set_data(*zip(*self.caudal))
        if self.retardos:
            tiempos, latencias, jitters = zip(*self.retardos)
            self.curva_latencia.set_data(tiempos, latencias)
            self.curva_jitter.set_data(tiempos, jitters)
        for eje in self.ejes_rendimiento:
            eje.relim()
            eje.autoscale_view()
        self.canvas_rendimiento.draw_idle()

    def actualizar(self):
        ahora = time.monotonic()
        self.actualizar_rendimiento(ahora)
        edad = None if self.ultima is None else ahora - self.ultima
        enlace = "suscrito" if self.suscrito else "sin suscripción"
        flujo = "esperando" if edad is None else f"última muestra hace {edad:.1f} s"
        if edad is not None and edad >= SILENCIO_S:
            flujo = f"sin telemetría reciente ({edad:.1f} s)"
        self.statusBar().showMessage(f"Enlace BLE: {enlace}  |  Telemetría: {flujo}")

        if self.inicio is not None:
            restante = self.fin - ahora
            if restante > 0:
                self.resumen.setText(f"Quedan {math.ceil(restante)} s · {len(self.llegadas)} muestras")
            elif not self.cerrando and ahora >= self.fin + 0.25:
                self.guardar(self.fin)
        self.boton.setEnabled(self.suscrito and self.inicio is None and not self.cerrando)

    def guardar(self, fin):
        duracion = fin - self.inicio
        cantidad = len(self.llegadas)
        intervalos = sorted(b - a for a, b in zip(self.llegadas, self.llegadas[1:]))
        resumen = (f"{duracion:.2f} s | {cantidad} muestras | {self.invalidos} inválidas | "
                   f"{cantidad / duracion:.3f} paq/s | {self.bytes_prueba / duracion:.2f} B/s")
        for nombre, valores in (
            ("Latencia ida estimada", self.latencias_prueba), ("Jitter", self.jitters_prueba),
        ):
            if valores:
                resumen += (f" | {nombre}: mediana {texto_ms(median(valores))}, "
                            f"P95 {texto_ms(p95(valores))} (n={len(valores)})")
            else:
                resumen += f" | {nombre}: sin datos"
        if any(latencia < 0 for latencia in self.latencias_prueba):
            resumen += " | Latencias negativas: comprobar sincronización"
        if intervalos:
            resumen += (f" | Mediana {median(intervalos):.3f} s"
                        f" | P95 {p95(intervalos):.3f} s | Máx. {intervalos[-1]:.3f} s")

        ruta = Path.cwd() / f"ble_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"
        try:
            with ruta.open("x", newline="", encoding="utf-8-sig") as archivo:
                escritor = csv.writer(archivo)
                escritor.writerow([
                    "hora_pc", "segundos_prueba", "evento", "bytes", "intervalo_s",
                    "altitud_m", "ax", "ay", "az", "tx_us_mod_u32", "rx_unix_us",
                    "latencia_ida_estimada_ms", "jitter_ms", "detalle",
                ])
                escritor.writerows(self.filas)
                escritor.writerow([hora_local(), duracion, "resumen", *[""] * 10, resumen])
            resumen += f"\nCSV: {ruta}"
        except OSError as error:
            resumen += f"\nError al guardar CSV: {error}"
        self.resumen.setText(resumen)
        self.logs.appendPlainText(resumen)
        self.inicio = self.fin = None
        self.duracion.setEnabled(True)

    def closeEvent(self, evento):
        if self.receptor.isRunning():
            if not self.cerrando and self.inicio is not None:
                self.fin = min(self.fin, time.monotonic())
            self.cerrando = True
            self.receptor.requestInterruption()
            evento.ignore()
            return
        if self.inicio is not None:
            self.guardar(self.fin)
        self.timer.stop()
        super().closeEvent(evento)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = Dashboard()
    ventana.show()
    sys.exit(app.exec_())
