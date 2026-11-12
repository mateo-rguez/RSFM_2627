"""Dashboard Qt para vídeo, telemetría, sensores y logs."""

import queue
import threading
import time

import matplotlib
matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFontDatabase, QImage, QPixmap
from PyQt5.QtWidgets import (
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .estado_sensores import NARANJA, ROJO, estado_sensor
from .video import cv2


MAX_MUESTRAS_GRAFICA = 40


class Dashboard(QMainWindow):
    """Ventana principal del receptor."""

    def __init__(
        self,
        cliente,
        video_stop,
        canvas,
        figura,
        ax_alt,
        ax_acc,
        almacenamiento,
        estado_recepcion,
    ):
        super().__init__()

        self.cliente = cliente
        self.video_stop = video_stop
        self.canvas = canvas
        self.figura = figura
        self.ax_alt = ax_alt
        self.ax_acc = ax_acc
        self.almacenamiento = almacenamiento
        self.estado_recepcion = estado_recepcion

        self.ultimo_video = 0.0
        self.ultimo_video_recibido = 0.0
        self.log_queue = queue.Queue(maxsize=500)
        self.ultimo_num_muestras = 0
        self.ultima_muestra_graficada = None
        self.video_mostrado = False
        self.ultima_imagen = None
        self.imagen_lock = threading.Lock()

        self.setWindowTitle("Estación de Control - Barco Solar")
        self.resize(1280, 850)

        self.crear_interfaz()
        self.crear_graficas()
        self.crear_temporizadores()
        self.actualizar_estado()

    def crear_interfaz(self):
        self.video = QLabel("Esperando vídeo...")
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setStyleSheet("background-color: black; color: white;")
        self.video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        zona_graficas = QWidget()
        layout_graficas = QVBoxLayout(zona_graficas)
        layout_graficas.setContentsMargins(0, 0, 0, 0)
        layout_graficas.addWidget(self.canvas)

        arriba = QSplitter(Qt.Horizontal)
        arriba.addWidget(self.video)
        arriba.addWidget(zona_graficas)
        arriba.setSizes([640, 640])

        self.sensores = {}
        zona_sensores = QWidget()
        layout_sensores = QVBoxLayout(zona_sensores)

        titulo_sensores = QLabel("ESTADO DE LOS SENSORES")
        titulo_sensores.setStyleSheet("font-weight: bold;")
        layout_sensores.addWidget(titulo_sensores)

        for nombre in ("Altímetro", "Acelerómetro", "Movimiento"):
            etiqueta = QLabel("{}: ESPERANDO DATOS".format(nombre))
            etiqueta.setStyleSheet(
                "color: {}; font-weight: bold;".format(ROJO)
            )
            self.sensores[nombre] = etiqueta
            layout_sensores.addWidget(etiqueta)

        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(2000)
        self.logs.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

        pestanas = QTabWidget()
        pestanas.addTab(self.logs, "Logs")
        pestanas.addTab(zona_sensores, "Sensores")

        central = QSplitter(Qt.Vertical)
        central.addWidget(arriba)
        central.addWidget(pestanas)
        central.setSizes([650, 200])
        self.setCentralWidget(central)

        self.estado = QLabel()
        self.statusBar().addWidget(self.estado)

    def crear_graficas(self):
        """Crea los ejes y prepara las líneas para blitting."""
        self.linea_altitud, = self.ax_alt.plot(
            [], [], marker="o", markersize=3, label="Altitud (m)", animated=True
        )
        self.linea_acc_x, = self.ax_acc.plot([], [], label="Acc X", animated=True)
        self.linea_acc_y, = self.ax_acc.plot([], [], label="Acc Y", animated=True)
        self.linea_acc_z, = self.ax_acc.plot([], [], label="Acc Z", animated=True)
        self.lineas_graficas = (
            self.linea_altitud,
            self.linea_acc_x,
            self.linea_acc_y,
            self.linea_acc_z,
        )

        self.ax_alt.set_ylabel("Altitud (m)")
        self.ax_alt.set_title("Telemetría MQTT")
        self.ax_alt.grid(True)
        self.ax_alt.legend()
        self.ax_acc.set_ylabel("Aceleración (m/s²)")
        self.ax_acc.set_xlabel("Tiempo")
        self.ax_acc.grid(True)
        self.ax_acc.legend()

        self.ax_alt.set_xlim(0, MAX_MUESTRAS_GRAFICA - 1)
        self.ax_alt.set_ylim(-1, 1)
        self.ax_acc.set_ylim(-1, 1)
        self.ax_acc.set_xticks([0, 10, 20, 30, 39])
        self.ax_acc.set_xticklabels(["", "", "", "", ""])

        self.fondo_graficas = None
        self.ultimo_refresco_ejes = 0.0
        self.ultimo_tiempo_eje = None
        self.figura.tight_layout()
        self.canvas.mpl_connect("draw_event", self._guardar_fondo_graficas)
        self.canvas.draw()

    def _guardar_fondo_graficas(self, evento):
        if evento.canvas is self.canvas:
            self.fondo_graficas = self.canvas.copy_from_bbox(self.figura.bbox)

    @staticmethod
    def _limites_si_necesarios(eje, valores):
        import math

        validos = []
        for valor in valores:
            try:
                numero = float(valor)
                if math.isfinite(numero):
                    validos.append(numero)
            except (TypeError, ValueError):
                pass
        if not validos:
            return False

        minimo, maximo = min(validos), max(validos)
        inferior, superior = eje.get_ylim()
        if minimo >= inferior and maximo <= superior:
            return False

        margen = max((maximo - minimo) * 0.15, 0.1)
        eje.set_ylim(minimo - margen, maximo + margen)
        return True

    def actualizar_graficas(self):
        muestras = self.almacenamiento.obtener_muestras()
        if not muestras:
            return
        if (
            len(muestras) == self.ultimo_num_muestras
            and muestras[-1] is self.ultima_muestra_graficada
        ):
            return

        self.ultimo_num_muestras = len(muestras)
        self.ultima_muestra_graficada = muestras[-1]
        tiempos, altitudes, acc_x, acc_y, acc_z = [], [], [], [], []

        for paquete in muestras:
            if not isinstance(paquete, dict):
                continue
            timestamp = paquete.get("timestamp")
            if not isinstance(timestamp, (int, float)):
                continue

            altitude = paquete.get("altitude") or {}
            motion = paquete.get("motion") or {}
            if not isinstance(altitude, dict):
                altitude = {}
            if not isinstance(motion, dict):
                motion = {}
            accel = motion.get("accel") or {}
            if not isinstance(accel, dict):
                accel = {}

            try:
                hora = time.strftime("%H:%M:%S", time.localtime(timestamp))
            except (OverflowError, OSError, ValueError):
                continue

            tiempos.append(hora)
            altitudes.append(
                altitude.get("altitude_m")
                if altitude.get("valid")
                else float("nan")
            )
            acc_x.append(accel.get("x", float("nan")))
            acc_y.append(accel.get("y", float("nan")))
            acc_z.append(accel.get("z", float("nan")))

        if not tiempos:
            return

        posiciones = list(range(len(tiempos)))
        for linea, valores in zip(
            self.lineas_graficas,
            (altitudes, acc_x, acc_y, acc_z),
        ):
            linea.set_data(posiciones, valores)

        ahora = time.monotonic()
        cambiar_ejes = False
        if (
            self.ultimo_tiempo_eje is None
            or ahora - self.ultimo_refresco_ejes >= 30
        ):
            indices = [i for i in (0, 10, 20, 30, 39) if i < len(tiempos)]
            etiquetas = [
                tiempos[i] if i in indices else ""
                for i in (0, 10, 20, 30, 39)
            ]
            self.ax_acc.set_xticklabels(etiquetas, rotation=30)
            self.ultimo_tiempo_eje = tiempos[-1]
            self.ultimo_refresco_ejes = ahora
            cambiar_ejes = True

        if self._limites_si_necesarios(self.ax_alt, altitudes):
            cambiar_ejes = True
        if self._limites_si_necesarios(
            self.ax_acc,
            acc_x + acc_y + acc_z,
        ):
            cambiar_ejes = True

        if cambiar_ejes or self.fondo_graficas is None:
            self.canvas.draw()

        if self.fondo_graficas is not None:
            self.canvas.restore_region(self.fondo_graficas)
            for linea in self.lineas_graficas:
                linea.axes.draw_artist(linea)
            self.canvas.blit(self.figura.bbox)

    def recibir_fotograma(self, frame):
        """Callback del hilo de vídeo; solo conserva el último fotograma."""
        with self.imagen_lock:
            self.ultima_imagen = frame
            self.ultimo_video_recibido = time.monotonic()

    def mostrar_ultima_imagen(self):
        """Muestra el último fotograma desde el hilo principal de Qt."""
        with self.imagen_lock:
            frame = self.ultima_imagen
            self.ultima_imagen = None

        if frame is None:
            return

        alto, ancho = frame.shape[:2]
        if hasattr(QImage, "Format_BGR888"):
            imagen = QImage(
                frame.data,
                ancho,
                alto,
                frame.strides[0],
                QImage.Format_BGR888,
            )
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            imagen = QImage(
                rgb.data,
                ancho,
                alto,
                rgb.strides[0],
                QImage.Format_RGB888,
            )

        pixmap = QPixmap.fromImage(imagen).scaled(
            self.video.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
        )
        self.video.setPixmap(pixmap)
        self.ultimo_video = time.monotonic()
        self.video_mostrado = True

    def actualizar_video(self):
        if self.ultimo_video_recibido == 0.0:
            if not self.video_mostrado:
                self.video.setText("Esperando vídeo...")
            return

        segundos = time.monotonic() - self.ultimo_video_recibido
        if segundos > 2.0:
            self.video.clear()
            self.video.setText(
                "VIDEO NO DISPONIBLE\n"
                "Sin fotogramas desde hace {:.1f} s".format(segundos)
            )
            self.video_mostrado = False

    def actualizar_sensores(self, paquete):
        if paquete is None:
            return

        altitude = paquete.get("altitude")
        motion = paquete.get("motion")
        accel = motion.get("accel") if isinstance(motion, dict) else None

        estados = {
            "Altímetro": estado_sensor("Altímetro", altitude),
            "Acelerómetro": estado_sensor("Acelerómetro", accel),
            "Movimiento": estado_sensor("Movimiento", motion),
        }

        for nombre, (texto, color) in estados.items():
            self.sensores[nombre].setText(texto)
            self.sensores[nombre].setStyleSheet(
                "color: {}; font-weight: bold;".format(color)
            )

    def publicar_log(self, texto):
        """Añade un log de forma segura desde cualquier hilo."""
        try:
            self.log_queue.put_nowait(
                "{} {}".format(time.strftime("%H:%M:%S"), texto)
            )
        except queue.Full:
            try:
                self.log_queue.get_nowait()
                self.log_queue.put_nowait(
                    "{} {}".format(time.strftime("%H:%M:%S"), texto)
                )
            except queue.Empty:
                pass

    def volcar_logs(self):
        lineas = []
        for _ in range(30):
            try:
                lineas.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if lineas:
            self.logs.appendPlainText("\n".join(lineas))

    def actualizar_estado(self):
        conectado = self.cliente.is_connected()
        paquete = self.almacenamiento.ultima_muestra()
        estados = []

        if conectado:
            estados.append(
                '<span style="color:green"><b>Broker: conectado</b></span>'
            )
        else:
            estados.append(
                '<span style="color:red"><b>Broker: desconectado</b></span>'
            )

        ultima_telemetria = self.estado_recepcion["ultima_telemetria"]
        if (
            ultima_telemetria != 0.0
            and time.monotonic() - ultima_telemetria < 5.0
        ):
            estados.append(
                '<span style="color:green"><b>Telemetría: recibiendo</b></span>'
            )
        else:
            estados.append(
                '<span style="color:red"><b>Telemetría: sin datos</b></span>'
            )

        if (
            self.ultimo_video_recibido != 0.0
            and time.monotonic() - self.ultimo_video_recibido < 2.0
        ):
            estados.append(
                '<span style="color:green"><b>Vídeo: recibiendo</b></span>'
            )
        else:
            estados.append(
                '<span style="color:red"><b>Vídeo: sin señal</b></span>'
            )

        self.estado.setText(" | ".join(estados))
        self.actualizar_sensores(paquete)

    def crear_temporizadores(self):
        self.timer_imagen = QTimer(self)
        self.timer_imagen.timeout.connect(self.mostrar_ultima_imagen)
        self.timer_imagen.setTimerType(Qt.PreciseTimer)
        self.timer_imagen.start(40)

        self.timer_video = QTimer(self)
        self.timer_video.timeout.connect(self.actualizar_video)
        self.timer_video.start(250)

        self.timer_estado = QTimer(self)
        self.timer_estado.timeout.connect(self.actualizar_estado)
        self.timer_estado.start(500)

        self.timer_graficas = QTimer(self)
        self.timer_graficas.timeout.connect(self.actualizar_graficas)
        self.timer_graficas.start(1000)

        self.timer_logs = QTimer(self)
        self.timer_logs.timeout.connect(self.volcar_logs)
        self.timer_logs.start(100)

    def closeEvent(self, evento):
        self.video_stop.set()
        self.timer_imagen.stop()
        self.timer_video.stop()
        self.timer_estado.stop()
        self.timer_graficas.stop()
        self.timer_logs.stop()
        super().closeEvent(evento)


def crear_dashboard(cliente, video_stop, almacenamiento, estado_recepcion):
    """Crea la ventana y los ejes Matplotlib del dashboard."""
    figura = Figure(figsize=(8, 6))
    ax_alt = figura.add_subplot(211)
    ax_acc = figura.add_subplot(212, sharex=ax_alt)
    canvas = FigureCanvasQTAgg(figura)
    ventana = Dashboard(
        cliente,
        video_stop,
        canvas,
        figura,
        ax_alt,
        ax_acc,
        almacenamiento,
        estado_recepcion,
    )
    return ventana

