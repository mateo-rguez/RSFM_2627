"""Receptor de telemetría MQTT para la estación de control."""

import argparse
import json
import os
import queue
import threading
from pathlib import Path

import sys
import time
from collections import deque

import matplotlib

matplotlib.use("Qt5Agg")

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QFontDatabase
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTabWidget,
)

import paho.mqtt.client as mqtt

try:
    import cv2
except ImportError:
    cv2 = None

DEFAULT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEFAULT_TOPIC = os.getenv("MQTT_TOPIC", "wifi-halow/telemetria")
DEFAULT_OUTPUT = Path(__file__).resolve().with_name(
    "telemetria_recibida.jsonl"
)
DEFAULT_VIDEO_OUTPUT = Path(__file__).resolve().with_name(
    "video_recibido.mp4"
)
DEFAULT_VIDEO_TOPIC = os.getenv("MQTT_VIDEO_TOPIC", "wifi-halow/video")
DEFAULT_VIDEO_MQTT_QOS = int(os.getenv("MQTT_VIDEO_QOS", "0"))

MAX_MUESTRAS_GRAFICA = 40

datos_recibidos = deque(maxlen=MAX_MUESTRAS_GRAFICA)
datos_lock = threading.Lock()


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
        default=DEFAULT_VIDEO_TOPIC,
        help="Topic MQTT de los fotogramas de vídeo."
    )

    parser.add_argument(
        "--video-mqtt-qos",
        type=int,
        choices=(0, 1, 2),
        default=DEFAULT_VIDEO_MQTT_QOS,
        help="QoS MQTT del vídeo; debe coincidir con el emisor."
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


def cargar_receptor_video():
    """Carga el receptor de vídeo sin hacer obligatoria su dependencia."""
    try:
        from video_receiver_Halow import run_receiver, cv2, np
    except ImportError as error:
        print(
            "[ERROR] No se puede iniciar el vídeo. Instale OpenCV y NumPy: {}".format(
                error
            )
        )
        return None

    if cv2 is None or np is None:
        print(
            "[ERROR] No se puede iniciar el vídeo. Instale opencv-python y numpy."
        )
        return None

    return run_receiver



class Dashboard(QMainWindow):
    nueva_imagen = pyqtSignal(QImage)
    nuevo_log = pyqtSignal(str)

    def __init__(self, cliente, video_stop, figura, estado_recepcion):
        super().__init__()
        
        self.cliente = cliente
        self.video_stop = video_stop
        self.figura = figura
        self.estado_recepcion = estado_recepcion

        self.ultima_muestra = time.monotonic()
        self.ultimo_video = 0.0
        self.broker_conectado = False

        self.setWindowTitle("Estación de Control - Barco Solar")
        self.resize(1280, 800)

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

        self.nueva_imagen.connect(self.mostrar_imagen)

        # ---------------- GRÁFICAS ----------------

        arriba = QSplitter(Qt.Horizontal)
        arriba.addWidget(self.video)
        arriba.addWidget(figura.canvas)
        arriba.setSizes([640, 640])

        # ---------------- LOGS ----------------

        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(2000)
        self.logs.setFont(
            QFontDatabase.systemFont(
                QFontDatabase.FixedFont
            )
        )

        self.nuevo_log.connect(self.logs.appendPlainText)

        pestanas = QTabWidget()
        pestanas.addTab(self.logs, "Logs")

        # ---------------- VENTANA PRINCIPAL ----------------

        central = QSplitter(Qt.Vertical)
        central.addWidget(arriba)
        central.addWidget(pestanas)
        central.setSizes([600, 200])

        self.setCentralWidget(central)

        # ---------------- ESTADO ----------------

        self.estado = QLabel()
        self.statusBar().addWidget(self.estado)

        # Actualización de vídeo y estado
        self.timer_video = QTimer(self)
        self.timer_video.timeout.connect(self.actualizar_video)
        self.timer_video.start(10)

        self.timer_estado = QTimer(self)
        self.timer_estado.timeout.connect(self.actualizar_estado)
        self.timer_estado.start(500)

        # Actualización de gráficas
        self.timer_graficas = QTimer(self)
        self.timer_graficas.timeout.connect(self.actualizar_graficas)
        self.timer_graficas.start(2000)

        self.actualizar_estado()

    def publicar_log(self, texto):
        self.nuevo_log.emit(
            "{} {}".format(
                time.strftime("%H:%M:%S"),
                texto
            )
        )

    def recibir_fotograma(self, frame):
        # OpenCV entrega BGR; QImage necesita RGB.
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        alto, ancho = rgb.shape[:2]

        imagen = QImage(
            rgb.data,
            ancho,
            alto,
            rgb.strides[0],
            QImage.Format_RGB888
        ).copy()

        # La señal permite actualizar Qt desde el hilo de vídeo.
        self.nueva_imagen.emit(imagen)

    def mostrar_imagen(self, imagen):
        self.ultimo_video = time.monotonic()

        self.video.setPixmap(
            QPixmap.fromImage(imagen).scaled(
                self.video.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        )

    def actualizar_video(self):
        if self.ultimo_video == 0.0:
            self.video.setText("Esperando vídeo...")
            return

        segundos = time.monotonic() - self.ultimo_video

        if segundos > 2.0:
            self.video.setText(
                "VIDEO NO DISPONIBLE\n"
                "Sin fotogramas desde hace {:.1f} s".format(segundos)
            )

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
            estados.append('<span style="color:green"><b>Telemetría: recibiendo</b></span>')
        else:
            estados.append('<span style="color:red"><b>Telemetría: sin datos</b></span>')

        if self.ultimo_video != 0.0 and (
            time.monotonic() - self.ultimo_video < 2.0
        ):
            estados.append(
                '<span style="color:green"><b>Vídeo: recibiendo</b></span>'
            )
        else:
            estados.append(
                '<span style="color:red"><b>Vídeo: sin señal</b></span>'
            )

        self.estado.setText(" | ".join(estados))

    def actualizar_graficas(self):
        with datos_lock:
            muestras = list(datos_recibidos)

        if not muestras:
            return

        tiempos = []
        altitudes = []
        acc_x = []
        acc_y = []
        acc_z = []

        for paquete in muestras:
            timestamp = paquete.get("timestamp")

            if not isinstance(timestamp, (int, float)):
                continue

            altitude = paquete.get("altitude", {})
            motion = paquete.get("motion", {})
            accel = motion.get("accel", {})

            tiempos.append(
                time.strftime(
                    "%H:%M:%S",
                    time.localtime(timestamp)
                )
            )

            if altitude.get("valid", False):
                altitudes.append(
                    altitude.get("altitude_m", 0.0)
                )
            else:
                altitudes.append(float("nan"))

            acc_x.append(accel.get("x", 0.0))
            acc_y.append(accel.get("y", 0.0))
            acc_z.append(accel.get("z", 0.0))

        if not tiempos:
            return

        # Coordenadas numéricas para Matplotlib.
        posiciones = list(range(len(tiempos)))

        ax_alt, ax_acc = self.figura.axes

        ax_alt.clear()
        ax_acc.clear()

        # Gráfica de altitud.
        ax_alt.plot(
            posiciones,
            altitudes,
            marker="o",
            label="Altitud (m)"
        )

        ax_alt.set_ylabel("Altitud (m)")
        ax_alt.set_title("Telemetría MQTT")
        ax_alt.grid(True)
        ax_alt.legend()

        # Gráfica de aceleración.
        ax_acc.plot(posiciones, acc_x, label="Acc X")
        ax_acc.plot(posiciones, acc_y, label="Acc Y")
        ax_acc.plot(posiciones, acc_z, label="Acc Z")

        ax_acc.set_ylabel("Aceleración (m/s²)")
        ax_acc.set_xlabel("Tiempo")
        ax_acc.grid(True)
        ax_acc.legend()

        # Etiquetas temporales del eje X.
        indices = list(range(0, len(tiempos), 5))

        if len(tiempos) - 1 not in indices:
            indices.append(len(tiempos) - 1)

        ax_acc.set_xticks(indices)
        ax_acc.set_xticklabels(
            [tiempos[i] for i in indices],
            rotation=30
        )

        self.figura.tight_layout()
        self.figura.canvas.draw_idle()

    def closeEvent(self, evento):
        self.video_stop.set()

        self.timer_video.stop()
        self.timer_estado.stop()
        self.timer_graficas.stop()


        super().closeEvent(evento)


def main():
    args = build_parser().parse_args()

    estado_recepcion = {
        "ultima_telemetria": 0.0
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.no_video_window:
        args.video_output.parent.mkdir(parents=True, exist_ok=True)

    output_lock = threading.Lock()
    ultima_telemetria = 0.0
    dashboard_log = print

    # API compatible con Paho MQTT 1.x
    cliente = mqtt.Client()

    video_queue = None
    if not args.no_video:
        # Solo se conserva el último fotograma: si OpenCV tarda, no se forma
        # una cola creciente de imágenes antiguas.
        video_queue = queue.Queue(maxsize=1)

    if args.username is not None:
        cliente.username_pw_set(args.username, args.password)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            dashboard_log("[ERROR] El broker rechazó la conexión: {}".format(rc))
            return

        client.subscribe(args.topic, qos=args.qos)

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

    def on_message(client, userdata, mensaje):
        if video_queue is not None and mensaje.topic == args.video_topic:
            payload = mensaje.payload
            if len(payload) <= 8:
                dashboard_log("[WARN] Fotograma MQTT demasiado pequeño; descartado.")
                return

            try:
                video_queue.put_nowait(payload)
            except queue.Full:
                # Reemplaza el fotograma anterior por el más reciente.
                try:
                    video_queue.get_nowait()
                except queue.Empty:
                    pass

                try:
                    video_queue.put_nowait(payload)
                except queue.Full:
                    pass
            return

        try:
            paquete = json.loads(mensaje.payload.decode("utf-8"))
            estado_recepcion["ultima_telemetria"] = time.monotonic()

            with datos_lock:
                datos_recibidos.append(paquete)

            with output_lock:
                with args.output.open("a", encoding="utf-8") as fichero:
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
            AttributeError
        ) as error:

            dashboard_log(
                "[ERROR] Mensaje MQTT no válido: {}".format(error)
            )

    cliente.on_connect = on_connect
    cliente.on_message = on_message

    print(
        "[MQTT] Conectando a {}:{}...".format(
            args.broker,
            args.port
        )
    )

    try:
        cliente.connect(args.broker, args.port, keepalive=60)

    except OSError as error:
        print(
            "[ERROR] No se pudo conectar con el broker: {}".format(
                error
            )
        )
        return 1

    print(
        "[RECEPTOR] Guardando muestras en '{}'".format(
            args.output
        )
    )

    
    mqtt_loop_started = False
    video_stop = threading.Event()
    video_thread = None

    try:
        video_receiver = None

        if not args.no_video:
            video_receiver = cargar_receptor_video()

        # ==================================================
        # MODO DASHBOARD
        # ==================================================

        if args.dashboard:
            app = QApplication(sys.argv)

            # Crear las gráficas de Matplotlib.
            figura, (ax_alt, ax_acc) = plt.subplots(
                2, 1,
                figsize=(8, 6),
                sharex=True
            )

            figura.canvas.manager.set_window_title(
                "Estación de Control - Telemetría"
            )

            # Crear el dashboard.
            ventana = Dashboard(
                cliente,
                video_stop,
                figura,
                estado_recepcion
            )


            # Mostrar los mensajes MQTT también en el dashboard.
            dashboard_log = ventana.publicar_log



            # Iniciar el bucle MQTT en segundo plano.
            cliente.loop_start()
            mqtt_loop_started = True

            # Iniciar la recepción del vídeo en otro hilo.
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

            return app.exec()

        # ==================================================
        # MODO ORIGINAL (SIN DASHBOARD)
        # ==================================================

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

    finally:
        video_stop.set()

        if mqtt_loop_started:
            cliente.loop_stop()

        cliente.disconnect()

        print("[MQTT] Conexión cerrada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
