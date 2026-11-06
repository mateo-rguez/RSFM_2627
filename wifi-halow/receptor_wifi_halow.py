
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Receptor de telemetría MQTT para la estación de control."""

import argparse
import json
import os
import queue
import threading
import sys
import time
import struct
import signal

from pathlib import Path
from collections import deque

import matplotlib
matplotlib.use("Qt5Agg")

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage, QFontDatabase
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QWidget,
    QVBoxLayout,
)

import paho.mqtt.client as mqtt

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


# ============================================================
# CONFIGURACIÓN
# ============================================================

DEFAULT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv("MQTT_TOPIC", "wifi-halow/telemetria")

DEFAULT_OUTPUT = Path(__file__).resolve().with_name(
    "telemetria_recibida.jsonl"
)

DEFAULT_VIDEO_OUTPUT = Path(__file__).resolve().with_name(
    "video_recibido.mp4"
)

DEFAULT_VIDEO_TOPIC = os.getenv(
    "MQTT_VIDEO_TOPIC", "wifi-halow/video"
)

DEFAULT_VIDEO_MQTT_QOS = int(
    os.getenv("MQTT_VIDEO_QOS", "0")
)

MAX_MUESTRAS_GRAFICA = 40

# Colores de los estados de los sensores.
VERDE = "#2eaf50"
NARANJA = "#e69b24"
ROJO = "#e53935"

datos_recibidos = deque(maxlen=MAX_MUESTRAS_GRAFICA)
datos_lock = threading.Lock()


# ============================================================
# ARGUMENTOS
# ============================================================

def build_parser():
    parser = argparse.ArgumentParser(
        description="Recibe y guarda la telemetría MQTT del barco."
    )

    parser.add_argument("--broker", default=DEFAULT_BROKER)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--qos", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    parser.add_argument(
        "--no-video",
        action="store_true",
        help="No iniciar la recepción de vídeo."
    )

    parser.add_argument(
        "--no-video-window",
        action="store_true",
        help="No abrir ventana y guardar el vídeo recibido en MP4."
    )

    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Iniciar el panel de control gráfico."
    )

    parser.add_argument(
        "--video-output",
        type=Path,
        default=DEFAULT_VIDEO_OUTPUT,
        help="Archivo MP4 cuando se usa --no-video-window."
    )

    parser.add_argument(
        "--video-topic",
        default=DEFAULT_VIDEO_TOPIC
    )

    parser.add_argument(
        "--video-mqtt-qos",
        type=int,
        choices=(0, 1, 2),
        default=DEFAULT_VIDEO_MQTT_QOS
    )

    parser.add_argument(
        "--username",
        default=os.getenv("MQTT_USERNAME")
    )

    parser.add_argument(
        "--password",
        default=os.getenv("MQTT_PASSWORD")
    )

    return parser


# ============================================================
# CARGA DEL RECEPTOR DE VÍDEO
# ============================================================

def cargar_receptor_video():
    """Receptor integrado; no depende de video_receiver_Halow.py."""
    if cv2 is None or np is None:
        print("[ERROR] Instala python3-opencv y python3-numpy.")
        return None
    return run_receiver_integrado


def run_receiver_integrado(stop_event=None, show_window=True,
                           mqtt_frame_queue=None, record_video=False,
                           output_path=None, frame_callback=None):
    """Lee timestamp double (!d) + JPEG, igual que el receptor original."""
    if mqtt_frame_queue is None:
        raise ValueError("No se ha creado la cola MQTT de vídeo")
    if record_video and output_path is None:
        raise ValueError("Falta la ruta del MP4")
    writer = None
    ultimo = time.monotonic()
    senal = False
    titulo = "Estacion de Control - Video Barco Solar"
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                payload = mqtt_frame_queue.get(timeout=0.05)
            except queue.Empty:
                if show_window:
                    if time.monotonic() - ultimo > 2:
                        if senal:
                            print("[WARN] Señal de vídeo perdida.")
                            senal = False
                        aviso = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(aviso, "VIDEO NO DISPONIBLE", (90, 230),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        cv2.imshow(titulo, aviso)
                    if (cv2.waitKey(1) & 0xFF) == ord("q"):
                        break
                continue
            if len(payload) <= 8:
                continue
            try:
                instante_emision = struct.unpack("!d", payload[:8])[0]
                frame = cv2.imdecode(np.frombuffer(payload[8:], dtype=np.uint8),
                                     cv2.IMREAD_COLOR)
            except (ValueError, struct.error, cv2.error):
                continue
            if frame is None:
                continue
            ultimo = time.monotonic()
            if not senal:
                print("[INFO] Señal de vídeo MQTT recibida.")
                senal = True
            if record_video:
                if writer is None:
                    alto, ancho = frame.shape[:2]
                    writer = cv2.VideoWriter(str(output_path),
                        cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (ancho, alto))
                    if not writer.isOpened():
                        writer.release()
                        writer = None
                        print("[ERROR] No se pudo abrir el MP4: {}".format(output_path))
                        record_video = False
                if writer is not None:
                    writer.write(frame)
            if frame_callback is not None:
                frame_callback(frame)
            elif show_window:
                latencia = (time.time() - instante_emision) * 1000
                cv2.putText(frame, "Latencia: {:.1f} ms".format(latencia),
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 255, 0), 2)
                cv2.imshow(titulo, frame)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
    finally:
        if writer is not None:
            writer.release()
            print("[INFO] MP4 guardado en '{}'".format(output_path))
        if show_window:
            cv2.destroyAllWindows()


# ============================================================
# ESTADO DE LOS SENSORES
# ============================================================

def estado_sensor(nombre, datos):
    """Devuelve el texto y el color que resumen la última lectura."""

    if datos is None:
        return "{}: SIN DATOS".format(nombre), ROJO

    if not isinstance(datos, dict) or not datos.get("valid"):
        return "{}: NO DISPONIBLE".format(nombre), ROJO

    # Si no existe simulated, no podemos conocer el origen.
    if "simulated" not in datos:
        return "{}: ORIGEN DESCONOCIDO".format(nombre), NARANJA

    if datos["simulated"]:
        return "{}: SIMULADO".format(nombre), NARANJA

    # gyro_valid solo existe en el sensor de movimiento.
    if datos.get("gyro_valid") is False:
        return "{}: REAL (sin giroscopio)".format(nombre), NARANJA

    return "{}: REAL".format(nombre), VERDE


# ============================================================
# DASHBOARD
# ============================================================

class Dashboard(QMainWindow):

    def __init__(
        self,
        cliente,
        video_stop,
        canvas,
        figura,
        ax_alt,
        ax_acc,
        estado_recepcion
    ):
        super().__init__()

        self.cliente = cliente
        self.video_stop = video_stop
        self.canvas = canvas
        self.figura = figura
        self.ax_alt = ax_alt
        self.ax_acc = ax_acc
        self.estado_recepcion = estado_recepcion

        self.ultimo_video = 0.0
        self.ultimo_video_recibido = 0.0
        self.log_queue = queue.Queue(maxsize=500)
        self.ultimo_num_muestras = 0
        self.ultima_muestra_graficada = None
        self.video_mostrado = False

        # Último fotograma pendiente de mostrar.
        self.ultima_imagen = None
        self.imagen_lock = threading.Lock()

        self.setWindowTitle("Estación de Control - Barco Solar")
        self.resize(1280, 850)

        self.crear_interfaz()
        self.crear_graficas()
        self.crear_temporizadores()

        self.actualizar_estado()

    # --------------------------------------------------------
    # INTERFAZ
    # --------------------------------------------------------

    def crear_interfaz(self):

        # ---------------- VÍDEO ----------------

        self.video = QLabel("Esperando vídeo...")
        self.video.setAlignment(Qt.AlignCenter)

        self.video.setStyleSheet(
            "background-color: black; color: white;"
        )

        self.video.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Ignored
        )

        # ---------------- GRÁFICAS ----------------

        zona_graficas = QWidget()
        layout_graficas = QVBoxLayout(zona_graficas)
        layout_graficas.setContentsMargins(0, 0, 0, 0)
        layout_graficas.addWidget(self.canvas)

        arriba = QSplitter(Qt.Horizontal)
        arriba.addWidget(self.video)
        arriba.addWidget(zona_graficas)
        arriba.setSizes([640, 640])

        # ---------------- ESTADO DE SENSORES ----------------

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

        # ---------------- LOGS ----------------

        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(2000)

        self.logs.setFont(
            QFontDatabase.systemFont(
                QFontDatabase.FixedFont
            )
        )

        pestanas = QTabWidget()
        pestanas.addTab(self.logs, "Logs")
        pestanas.addTab(zona_sensores, "Sensores")

        # ---------------- VENTANA PRINCIPAL ----------------

        central = QSplitter(Qt.Vertical)
        central.addWidget(arriba)
        central.addWidget(pestanas)
        central.setSizes([650, 200])

        self.setCentralWidget(central)

        # ---------------- ESTADO GENERAL ----------------

        self.estado = QLabel()
        self.statusBar().addWidget(self.estado)

    # --------------------------------------------------------
    # GRÁFICAS
    # --------------------------------------------------------

    def crear_graficas(self):
        """Crea los ejes una vez y prepara las líneas para blitting."""
        self.linea_altitud, = self.ax_alt.plot(
            [], [], marker="o", markersize=3, label="Altitud (m)", animated=True
        )
        self.linea_acc_x, = self.ax_acc.plot(
            [], [], label="Acc X", animated=True
        )
        self.linea_acc_y, = self.ax_acc.plot(
            [], [], label="Acc Y", animated=True
        )
        self.linea_acc_z, = self.ax_acc.plot(
            [], [], label="Acc Z", animated=True
        )
        self.lineas_graficas = (
            self.linea_altitud, self.linea_acc_x,
            self.linea_acc_y, self.linea_acc_z
        )

        self.ax_alt.set_ylabel("Altitud (m)")
        self.ax_alt.set_title("Telemetría MQTT")
        self.ax_alt.grid(True)
        self.ax_alt.legend()
        self.ax_acc.set_ylabel("Aceleración (m/s²)")
        self.ax_acc.set_xlabel("Tiempo")
        self.ax_acc.grid(True)
        self.ax_acc.legend()

        # Escala horizontal estable: evita recalcular ticks en cada muestra.
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
        """Regenera el fondo al redibujar o cambiar el tamaño de la figura."""
        if evento.canvas is self.canvas:
            self.fondo_graficas = self.canvas.copy_from_bbox(self.figura.bbox)

    @staticmethod
    def _limites_si_necesarios(eje, valores):
        """Cambia los límites solo si los datos salen de la zona visible."""
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
        """Actualiza únicamente las líneas con blitting; redibuja ejes si hace falta."""
        with datos_lock:
            muestras = list(datos_recibidos)

        if not muestras:
            return
        if (len(muestras) == self.ultimo_num_muestras
                and muestras[-1] is self.ultima_muestra_graficada):
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
            altitudes.append(altitude.get("altitude_m") if altitude.get("valid") else float("nan"))
            acc_x.append(accel.get("x", float("nan")))
            acc_y.append(accel.get("y", float("nan")))
            acc_z.append(accel.get("z", float("nan")))

        if not tiempos:
            return
        posiciones = list(range(len(tiempos)))
        for linea, valores in zip(
            self.lineas_graficas, (altitudes, acc_x, acc_y, acc_z)
        ):
            linea.set_data(posiciones, valores)

        # Las etiquetas temporales se actualizan como máximo cada 30 s.
        # Así no forzamos un renderizado completo en cada refresco.
        ahora = time.monotonic()
        cambiar_ejes = False
        if (self.ultimo_tiempo_eje is None
                or ahora - self.ultimo_refresco_ejes >= 30):
            indices = [i for i in (0, 10, 20, 30, 39) if i < len(tiempos)]
            etiquetas = [tiempos[i] if i in indices else "" for i in (0, 10, 20, 30, 39)]
            self.ax_acc.set_xticklabels(etiquetas, rotation=30)
            self.ultimo_tiempo_eje = tiempos[-1]
            self.ultimo_refresco_ejes = ahora
            cambiar_ejes = True

        if self._limites_si_necesarios(self.ax_alt, altitudes):
            cambiar_ejes = True
        if self._limites_si_necesarios(self.ax_acc, acc_x + acc_y + acc_z):
            cambiar_ejes = True

        # draw() reconstruye el fondo solo si cambian ejes/etiquetas.
        if cambiar_ejes or self.fondo_graficas is None:
            self.canvas.draw()

        # El fondo contiene títulos, ejes, ticks, cuadrícula y leyendas.
        # Solo pintamos encima las cuatro líneas que cambian.
        if self.fondo_graficas is not None:
            self.canvas.restore_region(self.fondo_graficas)
            for linea in self.lineas_graficas:
                linea.axes.draw_artist(linea)
            self.canvas.blit(self.figura.bbox)

    # --------------------------------------------------------
    # VÍDEO
    # --------------------------------------------------------

    def recibir_fotograma(self, frame):
        """
        Callback ejecutado por el hilo de vídeo.

        Solo almacena el último fotograma. No realiza conversiones
        ni operaciones gráficas en este hilo.
        """

        with self.imagen_lock:
            self.ultima_imagen = frame
            self.ultimo_video_recibido = time.monotonic()

    def mostrar_ultima_imagen(self):
        """
        Se ejecuta en el hilo principal de Qt.

        Si hay un fotograma nuevo, lo muestra. Los anteriores
        se descartan automáticamente.
        """

        with self.imagen_lock:
            frame = self.ultima_imagen
            self.ultima_imagen = None

        if frame is None:
            return

        alto, ancho = frame.shape[:2]
        if hasattr(QImage, "Format_BGR888"):
            imagen = QImage(frame.data, ancho, alto, frame.strides[0],
                            QImage.Format_BGR888)
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            imagen = QImage(rgb.data, ancho, alto, rgb.strides[0],
                            QImage.Format_RGB888)

        pixmap = QPixmap.fromImage(imagen)

        pixmap = pixmap.scaled(
            self.video.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation
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

    # --------------------------------------------------------
    # ESTADO DE SENSORES
    # --------------------------------------------------------

    def actualizar_sensores(self, paquete):

        if paquete is None:
            return

        altitude = paquete.get("altitude")
        motion = paquete.get("motion")

        accel = (
            motion.get("accel")
            if isinstance(motion, dict)
            else None
        )

        estados = {
            "Altímetro": estado_sensor("Altímetro", altitude),
            "Acelerómetro": estado_sensor("Acelerómetro", accel),
            "Movimiento": estado_sensor("Movimiento", motion)
        }

        for nombre, (texto, color) in estados.items():

            self.sensores[nombre].setText(texto)

            self.sensores[nombre].setStyleSheet(
                "color: {}; font-weight: bold;".format(color)
            )

    # --------------------------------------------------------
    # LOGS
    # --------------------------------------------------------

    def publicar_log(self, texto):
        """Seguro desde cualquier hilo: no toca widgets Qt."""
        try:
            self.log_queue.put_nowait("{} {}".format(time.strftime("%H:%M:%S"), texto))
        except queue.Full:
            try:
                self.log_queue.get_nowait()
                self.log_queue.put_nowait("{} {}".format(time.strftime("%H:%M:%S"), texto))
            except queue.Empty:
                pass

    def volcar_logs(self):
        """Solo el hilo de Qt escribe en QPlainTextEdit."""
        lineas = []
        for _ in range(30):
            try:
                lineas.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if lineas:
            self.logs.appendPlainText("\n".join(lineas))

    # --------------------------------------------------------
    # ESTADO GENERAL
    # --------------------------------------------------------

    def actualizar_estado(self):

        conectado = self.cliente.is_connected()

        with datos_lock:
            paquete = (
                datos_recibidos[-1]
                if datos_recibidos
                else None
            )

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

    # --------------------------------------------------------
    # TEMPORIZADORES
    # --------------------------------------------------------

    def crear_temporizadores(self):

        # El vídeo se muestra como máximo unas 30 veces por segundo.
        self.timer_imagen = QTimer(self)
        self.timer_imagen.timeout.connect(
            self.mostrar_ultima_imagen
        )
        self.timer_imagen.setTimerType(Qt.PreciseTimer)
        self.timer_imagen.start(40)

        # Comprobación de pérdida de vídeo.
        self.timer_video = QTimer(self)
        self.timer_video.timeout.connect(
            self.actualizar_video
        )
        self.timer_video.start(250)

        # Estado general.
        self.timer_estado = QTimer(self)
        self.timer_estado.timeout.connect(
            self.actualizar_estado
        )
        self.timer_estado.start(500)

        # Gráficas: actualización cada 2 segundos.
        self.timer_graficas = QTimer(self)
        self.timer_graficas.timeout.connect(
            self.actualizar_graficas
        )
        self.timer_graficas.start(1000)

        self.timer_logs = QTimer(self)
        self.timer_logs.timeout.connect(self.volcar_logs)
        self.timer_logs.start(100)

    # --------------------------------------------------------
    # CIERRE
    # --------------------------------------------------------

    def closeEvent(self, evento):

        self.video_stop.set()

        self.timer_imagen.stop()
        self.timer_video.stop()
        self.timer_estado.stop()
        self.timer_graficas.stop()
        self.timer_logs.stop()

        super().closeEvent(evento)


# ============================================================
# MAIN
# ============================================================

def main():

    args = build_parser().parse_args()

    # Ctrl+C se gestiona por Qt para evitar interrumpir el dibujo de Matplotlib.
    estado_recepcion = {
        "ultima_telemetria": 0.0
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if args.no_video_window:
        args.video_output.parent.mkdir(
            parents=True,
            exist_ok=True
        )

    output_lock = threading.Lock()

    dashboard_log = print

    cliente = mqtt.Client()

    video_queue = None

    if not args.no_video:
        # Solo conservamos el último fotograma pendiente.
        video_queue = queue.Queue(maxsize=1)

    if args.username is not None:
        cliente.username_pw_set(
            args.username,
            args.password
        )

    # --------------------------------------------------------
    # CALLBACK MQTT: CONEXIÓN
    # --------------------------------------------------------

    def on_connect(client, userdata, flags, rc):

        if rc != 0:
            dashboard_log(
                "[ERROR] El broker rechazó la conexión: {}".format(rc)
            )
            return

        client.subscribe(
            args.topic,
            qos=args.qos
        )

        if video_queue is not None:
            client.subscribe(
                args.video_topic,
                qos=args.video_mqtt_qos
            )

        if video_queue is None:
            dashboard_log(
                "[MQTT] Suscrito a '{}'. Esperando datos...".format(
                    args.topic
                )
            )
        else:
            dashboard_log(
                "[MQTT] Suscrito a telemetría '{}' y vídeo '{}'.".format(
                    args.topic,
                    args.video_topic
                )
            )

    # --------------------------------------------------------
    # CALLBACK MQTT: MENSAJES
    # --------------------------------------------------------

    def on_message(client, userdata, mensaje):

        # ---------------- VÍDEO ----------------

        if (
            video_queue is not None
            and mensaje.topic == args.video_topic
        ):

            payload = mensaje.payload

            if len(payload) <= 8:
                dashboard_log(
                    "[WARN] Fotograma MQTT demasiado pequeño."
                )
                return

            try:
                video_queue.put_nowait(payload)

            except queue.Full:

                # Eliminamos el fotograma antiguo.
                try:
                    video_queue.get_nowait()
                except queue.Empty:
                    pass

                try:
                    video_queue.put_nowait(payload)
                except queue.Full:
                    pass

            return

        # ---------------- TELEMETRÍA ----------------

        try:

            paquete = json.loads(
                mensaje.payload.decode("utf-8")
            )

            estado_recepcion["ultima_telemetria"] = time.monotonic()

            with datos_lock:
                datos_recibidos.append(paquete)

            with output_lock:

                with args.output.open(
                    "a",
                    encoding="utf-8"
                ) as fichero:

                    json.dump(
                        paquete,
                        fichero,
                        ensure_ascii=False
                    )

                    fichero.write("\n")

            altitude = paquete.get("altitude", {})
            motion = paquete.get("motion", {})
            accel = motion.get("accel", {})

            dashboard_log(
                "[RECEPTOR] timestamp={} | altitud={} m | "
                "aceleración=({}, {}, {})".format(
                    paquete.get("timestamp"),
                    altitude.get("altitude_m"),
                    accel.get("x"),
                    accel.get("y"),
                    accel.get("z")
                )
            )

        except (
            UnicodeDecodeError,
            ValueError,
            OSError,
            AttributeError,
            TypeError
        ) as error:

            dashboard_log(
                "[ERROR] Mensaje MQTT no válido: {}".format(error)
            )

    cliente.on_connect = on_connect
    cliente.on_message = on_message

    # --------------------------------------------------------
    # CONEXIÓN
    # --------------------------------------------------------

    print(
        "[MQTT] Conectando a {}:{}...".format(
            args.broker,
            args.port
        )
    )

    try:
        cliente.connect(
            args.broker,
            args.port,
            keepalive=60
        )

    except OSError as error:

        print(
            "[ERROR] No se pudo conectar con el broker: {}".format(error)
        )

        return 1

    print(
        "[RECEPTOR] Guardando muestras en '{}'".format(args.output)
    )

    mqtt_loop_started = False
    video_stop = threading.Event()
    video_thread = None
    ventana = None
    resultado = 0

    try:

        video_receiver = None

        if not args.no_video:
            video_receiver = cargar_receptor_video()

        # ==================================================
        # MODO DASHBOARD
        # ==================================================

        if args.dashboard:

            app = QApplication(sys.argv)
            signal.signal(signal.SIGINT, lambda *_: app.quit())
            timer_sigint = QTimer()
            timer_sigint.timeout.connect(lambda: None)
            timer_sigint.start(250)

            # Creamos la figura directamente, sin pyplot.
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
                estado_recepcion
            )

            dashboard_log = ventana.publicar_log

            # Iniciamos MQTT en segundo plano.
            cliente.loop_start()
            mqtt_loop_started = True

            # Receptor de vídeo en otro hilo.
            if video_receiver is not None:

                video_thread = threading.Thread(
                    target=video_receiver,
                    kwargs={
                        "stop_event": video_stop,
                        "show_window": False,
                        "mqtt_frame_queue": video_queue,
                        "record_video": False,
                        "output_path": args.video_output,
                        "frame_callback": ventana.recibir_fotograma
                    },
                    daemon=True
                )

                video_thread.start()

            ventana.show()

            resultado = app.exec()

        # ==================================================
        # MODO ORIGINAL (SIN DASHBOARD)
        # ==================================================

        else:

            if video_receiver is None:
                cliente.loop_forever()

            else:

                cliente.loop_start()
                mqtt_loop_started = True

                video_receiver(
                    show_window=not args.no_video_window,
                    mqtt_frame_queue=video_queue,
                    record_video=args.no_video_window,
                    output_path=args.video_output
                )

    except KeyboardInterrupt:

        print("\n[RECEPTOR] Deteniendo la recepción...")

    except Exception as error:

        print("[ERROR] Fallo en el receptor: {}".format(error))
        resultado = 1

    finally:

        video_stop.set()

        if video_thread is not None:
            video_thread.join(timeout=2.0)

        if mqtt_loop_started:
            cliente.loop_stop()

        cliente.disconnect()

        print("[MQTT] Conexión cerrada.")

    return resultado


if __name__ == "__main__":
    raise SystemExit(main())
