"""Dashboard Qt común a Wi-Fi HaLow, LoRa y BLE.

Muestra lo mismo sea cual sea el protocolo:
  - vídeo (si el protocolo lo admite),
  - gráficas de altitud, aceleración y latencia,
  - pestaña "Prestaciones": comunes, vídeo y exclusivas del protocolo,
  - pestañas "Sensores" y "Logs".
"""

import queue
import time

import matplotlib
matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFontDatabase, QImage, QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QScrollArea, QSizePolicy,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from .estado_sensores import ROJO, VERDE, estado_sensor
from .prestaciones import NOMBRES_PROTOCOLO, filas_resumen

# Paleta categórica (validada para daltonismo): mismo color = misma serie siempre.
AZUL, NARANJA_SERIE, AGUAMARINA = "#2a78d6", "#eb6834", "#1baf7a"
GRIS_EJES = "#8a8a85"


def tabla_html(titulo, filas):
    if not filas:
        return ""
    html = ["<h3 style='margin:4px 0'>{}</h3><table cellspacing='3'>".format(titulo)]
    for nombre, valor in filas:
        html.append("<tr><td style='padding-right:14px'>{}</td><td><b>{}</b></td></tr>".format(
            nombre, valor))
    html.append("</table>")
    return "".join(html)


class Dashboard(QMainWindow):
    def __init__(self, centro, adaptador, con_video, tiempo_sin_datos_s, al_guardar=None):
        super().__init__()
        self.centro = centro
        self.adaptador = adaptador
        self.protocolo = centro.protocolo
        self.con_video = con_video
        self.tiempo_sin_datos_s = tiempo_sin_datos_s
        self.al_guardar = al_guardar
        self.cola_logs = queue.Queue(maxsize=1000)
        self.video_mostrado = False

        self.setWindowTitle("Estación de Control - Barco Solar | {}".format(
            NOMBRES_PROTOCOLO[self.protocolo]))
        self.resize(1300, 880)
        self.crear_interfaz()
        self.crear_graficas()
        self.crear_temporizadores()
        centro.establecer_log(self.publicar_log)

    # --- Interfaz -----------------------------------------------------

    def crear_interfaz(self):
        texto = "Esperando vídeo..." if self.con_video else \
            "Vídeo no disponible con {}\n(solo telemetría)".format(NOMBRES_PROTOCOLO[self.protocolo])
        self.video = QLabel(texto)
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setStyleSheet("background-color: black; color: white;")
        self.video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.figura = Figure(figsize=(7, 6), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figura)

        arriba = QSplitter(Qt.Horizontal)
        arriba.addWidget(self.video)
        arriba.addWidget(self.canvas)
        arriba.setSizes([560, 740])

        # Pestaña de prestaciones: tres columnas (comunes, vídeo, exclusivas).
        zona = QWidget()
        columnas = QHBoxLayout(zona)
        self.lbl_comunes, self.lbl_video, self.lbl_especificas = QLabel(), QLabel(), QLabel()
        for etiqueta in (self.lbl_comunes, self.lbl_video, self.lbl_especificas):
            etiqueta.setTextFormat(Qt.RichText)
            etiqueta.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            etiqueta.setTextInteractionFlags(Qt.TextSelectableByMouse)
            columnas.addWidget(etiqueta)
        columnas.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidget(zona)
        desplazable.setWidgetResizable(True)

        zona_sensores = QWidget()
        capa_sensores = QVBoxLayout(zona_sensores)
        self.sensores = {}
        for nombre in ("Altímetro", "Acelerómetro"):
            etiqueta = QLabel("{}: ESPERANDO DATOS".format(nombre))
            etiqueta.setStyleSheet("color: {}; font-weight: bold;".format(ROJO))
            self.sensores[nombre] = etiqueta
            capa_sensores.addWidget(etiqueta)
        self.valores = QLabel()
        capa_sensores.addWidget(self.valores)
        capa_sensores.addStretch()

        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(3000)
        self.logs.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

        pestanas = QTabWidget()
        pestanas.addTab(desplazable, "Prestaciones")
        pestanas.addTab(zona_sensores, "Sensores")
        pestanas.addTab(self.logs, "Logs")

        central = QSplitter(Qt.Vertical)
        central.addWidget(arriba)
        central.addWidget(pestanas)
        central.setSizes([560, 320])
        self.setCentralWidget(central)

        self.estado = QLabel()
        self.statusBar().addWidget(self.estado)

    def crear_graficas(self):
        self.ax_alt, self.ax_acc, self.ax_lat = self.figura.subplots(3, 1, sharex=True)
        self.linea_alt, = self.ax_alt.plot([], [], "o-", color=AZUL, lw=2, ms=4)
        self.lineas_acc = [
            self.ax_acc.plot([], [], "o-", color=color, lw=2, ms=3, label=eje)[0]
            for color, eje in zip((AZUL, NARANJA_SERIE, AGUAMARINA), ("X", "Y", "Z"))
        ]
        self.linea_lat, = self.ax_lat.plot([], [], "o-", color=AZUL, lw=2, ms=4)

        self.figura.suptitle("Telemetría y latencia — {}".format(
            NOMBRES_PROTOCOLO[self.protocolo]), fontsize=10)
        # Nombre de cada gráfica encima (en vertical se solapan al encoger la ventana).
        for eje, titulo in ((self.ax_alt, "Altitud (m)"), (self.ax_acc, "Aceleración (m/s²)"),
                            (self.ax_lat, "Latencia (ms)")):
            eje.set_title(titulo, loc="left", fontsize=9, color="#3d3d3a")
        self.ax_acc.legend(loc="center right", fontsize=8, ncols=3, frameon=False)
        self.ax_lat.set_xlabel("Tiempo desde el inicio (s)", fontsize=9)
        for eje in (self.ax_alt, self.ax_acc, self.ax_lat):
            eje.ticklabel_format(axis="y", useOffset=False, style="plain")
            eje.grid(True, color="#e4e4e0", lw=0.8)
            eje.tick_params(colors=GRIS_EJES, labelsize=8)
            for borde in ("top", "right"):
                eje.spines[borde].set_visible(False)
            for borde in ("left", "bottom"):
                eje.spines[borde].set_color(GRIS_EJES)
        self.ultima_graficada = None

    def crear_temporizadores(self):
        self.temporizadores = []
        for funcion, ms in ((self.mostrar_video, 40), (self.actualizar_estado, 500),
                            (self.actualizar_graficas, 1000), (self.volcar_logs, 100),
                            (self.actualizar_prestaciones, 1000), (self._guardar, 10000)):
            temporizador = QTimer(self)
            temporizador.timeout.connect(funcion)
            temporizador.start(ms)
            self.temporizadores.append(temporizador)

    # --- Actualizaciones ----------------------------------------------

    def mostrar_video(self):
        fotograma = self.centro.tomar_fotograma()
        if fotograma is None:
            if (self.con_video and self.video_mostrado
                    and time.monotonic() - self.centro.ultimo_video > 2.0):
                self.video.clear()
                self.video.setText("VÍDEO NO DISPONIBLE\n(sin fotogramas desde hace más de 2 s)")
                self.video_mostrado = False
            return
        alto, ancho = fotograma.shape[:2]
        imagen = QImage(fotograma.data, ancho, alto, fotograma.strides[0], QImage.Format_BGR888)
        self.video.setPixmap(QPixmap.fromImage(imagen).scaled(
            self.video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.video_mostrado = True

    def actualizar_graficas(self):
        muestras = self.centro.muestras()
        if not muestras or muestras[-1] is self.ultima_graficada:
            return
        self.ultima_graficada = muestras[-1]
        t0 = self.centro.inicio
        tiempos = [m["hora_llegada"] - t0 for m in muestras]
        nan = float("nan")

        def serie(valores):
            return [nan if v is None else v for v in valores]

        self.linea_alt.set_data(tiempos, serie(m["altitude"]["altitude_m"] for m in muestras))
        for linea, eje in zip(self.lineas_acc, ("x", "y", "z")):
            linea.set_data(tiempos, serie(m["motion"]["accel"][eje] for m in muestras))
        self.linea_lat.set_data(tiempos, [m["latencia_ms"] for m in muestras])
        for eje in (self.ax_alt, self.ax_acc, self.ax_lat):
            eje.relim()
            eje.autoscale_view()
        self.canvas.draw_idle()

    def actualizar_sensores(self, muestra):
        if muestra is None:
            return
        for nombre, datos in (("Altímetro", muestra["altitude"]),
                              ("Acelerómetro", muestra["motion"]["accel"])):
            texto, color = estado_sensor(nombre, datos)
            self.sensores[nombre].setText(texto)
            self.sensores[nombre].setStyleSheet("color: {}; font-weight: bold;".format(color))
        acc = muestra["motion"]["accel"]
        self.valores.setText(
            "seq {} | altitud {} m (distancia {} cm) | aceleración X {} · Y {} · Z {} m/s²".format(
                muestra["seq"], muestra["altitude"]["altitude_m"],
                muestra["altitude"]["distance_cm"], acc["x"], acc["y"], acc["z"]))

    def actualizar_prestaciones(self):
        comunes, video, especificas = filas_resumen(self.centro.prestaciones.resumen())
        self.lbl_comunes.setText(tabla_html("Comunes (comparables)", comunes))
        self.lbl_video.setText(tabla_html("Vídeo", video) if self.con_video else
                               "<h3 style='margin:4px 0'>Vídeo</h3>No aplica")
        self.lbl_especificas.setText(tabla_html(
            "Exclusivas de {}".format(NOMBRES_PROTOCOLO[self.protocolo]), especificas))

    def actualizar_estado(self):
        def trozo(ok, texto):
            return '<span style="color:{}"><b>{}</b></span>'.format(VERDE if ok else ROJO, texto)

        conectado = self.adaptador.conectado
        partes = ["<b>{}</b>".format(NOMBRES_PROTOCOLO[self.protocolo]),
                  trozo(conectado, "Enlace: {}".format("conectado" if conectado else "desconectado"))]
        edad = time.monotonic() - self.centro.ultima_telemetria
        recibiendo = self.centro.ultima_telemetria and edad < self.tiempo_sin_datos_s
        partes.append(trozo(recibiendo, "Telemetría: {}".format(
            "recibiendo" if recibiendo else "sin datos")))
        if self.con_video:
            hay_video = self.centro.ultimo_video and time.monotonic() - self.centro.ultimo_video < 2.0
            partes.append(trozo(hay_video, "Vídeo: {}".format("recibiendo" if hay_video else "sin señal")))
        else:
            partes.append("<b>Vídeo: no aplica</b>")
        self.estado.setText(" | ".join(partes))
        self.actualizar_sensores(self.centro.ultima_muestra())

    def publicar_log(self, texto):
        """Se puede llamar desde cualquier hilo."""
        linea = "{} {}".format(time.strftime("%H:%M:%S"), texto)
        try:
            self.cola_logs.put_nowait(linea)
        except queue.Full:
            pass

    def volcar_logs(self):
        lineas = []
        for _ in range(50):
            try:
                lineas.append(self.cola_logs.get_nowait())
            except queue.Empty:
                break
        if lineas:
            self.logs.appendPlainText("\n".join(lineas))

    def _guardar(self):
        if self.al_guardar is not None:
            self.al_guardar()

    def closeEvent(self, evento):
        for temporizador in self.temporizadores:
            temporizador.stop()
        super().closeEvent(evento)
