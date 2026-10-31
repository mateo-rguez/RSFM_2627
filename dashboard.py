"""
Panel de control de la estación.
Reúne en una sola ventana el vídeo del barco, las gráficas de telemetría MQTT
y los logs, reutilizando video_receiver.py y receptor_mqtt_v2.py sin
modificarlos: se importan como módulos y se sustituye solo la parte que abre
sus ventanas, de forma que el vídeo y las gráficas se muestran en este panel.
"""

import importlib.util
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_API", "pyqt6")    # Matplotlib debe usar el mismo Qt que el panel

import matplotlib
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QImage, QPixmap
from PyQt6.QtWidgets import (QApplication, QLabel, QMainWindow, QPlainTextEdit,
                             QSizePolicy, QSplitter, QTabWidget)

RAIZ = Path(__file__).resolve().parent
RUTA_VIDEO = RAIZ / "camara" / "video_receiver.py"
RUTA_RECEPTOR = RAIZ / "mqtt" / "receptor_mqtt_v2.py"

REFRESCO_VIDEO_MS = 33      # Periodo de refresco del panel de vídeo (unos 30 FPS)
REFRESCO_ESTADO_MS = 500    # Periodo de refresco de la barra de estado
MAX_LINEAS_LOG = 2000       # Las líneas más antiguas de cada pestaña se descartan
TIMEOUT_TELEMETRIA_S = 5.0  # Tiempo sin paquetes para considerar que el barco no emite
REINTENTO_VIDEO_S = 5.0     # Espera antes de reiniciar la recepción de vídeo tras un error

VERDE = "#2e7d32"           # Colores de los avisos de la barra de estado
NARANJA = "#e65100"
ROJO = "#c62828"


class ModuloSustituido:
    """Se comporta como el módulo original salvo en las funciones indicadas."""

    def __init__(self, original, **sustituciones):
        self._original = original
        self.__dict__.update(sustituciones)

    def __getattr__(self, nombre):
        return getattr(self._original, nombre)


class RegistroLogs(QObject):
    """Sustituye al print de un módulo y envía cada línea a su pestaña de logs."""

    nueva_linea = pyqtSignal(str)

    def escribir(self, *args, sep=" ", end="\n", file=None, flush=False):
        texto = sep.join(str(arg) for arg in args).strip()
        if texto:
            # La señal permite escribir desde cualquier hilo de forma segura
            self.nueva_linea.emit(f"{datetime.now():%H:%M:%S} {texto}")


class PuenteVideo:
    """Guarda el último fotograma recibido hasta que el panel lo muestra."""

    def __init__(self):
        self._lock = threading.Lock()
        self._fotograma = None
        self.error = None           # Último error de la recepción, para mostrarlo en el panel

    def publicar(self, titulo, fotograma):
        # Sustituye a cv2.imshow. Si el panel va retrasado se descarta el fotograma
        # anterior: en vídeo en directo interesa siempre el más reciente
        with self._lock:
            self._fotograma = fotograma
            self.error = None

    def tomar(self):
        with self._lock:
            fotograma, self._fotograma = self._fotograma, None
        return fotograma


def cargar_modulo(nombre, ruta):
    """Importa un script por su ruta. Su bloque __main__ no llega a ejecutarse."""
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def preparar_video(video_receiver, puente, registro):
    """Redirige la salida de video_receiver.py al panel y lo lanza en un hilo."""
    video_receiver.print = registro.escribir
    video_receiver.cv2 = ModuloSustituido(
        video_receiver.cv2,
        imshow=puente.publicar,
        waitKey=lambda retardo: -1,         # No se pulsa "q": se cierra desde el panel
        destroyAllWindows=lambda: None
    )

    def ejecutar():
        # Un fallo no debe dejar el panel sin vídeo hasta reiniciarlo (p. ej. puerto ocupado)
        while True:
            try:
                video_receiver.run_receiver()
            except Exception as e:
                puente.error = str(e)
                registro.escribir(f"[ERROR] Recepción de vídeo detenida: {e}. Reintentando...")
            time.sleep(REINTENTO_VIDEO_S)

    # Hilo daemon: el bucle no tiene fin, así termina al cerrar el programa
    threading.Thread(target=ejecutar, daemon=True).start()


def preparar_graficas(receptor):
    """Ejecuta graficar_datos() sin mostrar su ventana y devuelve figura y animación."""
    animaciones = []
    func_animation = receptor.FuncAnimation

    def crear_animacion(*args, **kwargs):
        # Dentro de graficar_datos() la animación es una variable local: hay que
        # conservar una referencia o se destruiría al terminar la función
        animaciones.append(func_animation(*args, **kwargs))
        return animaciones[-1]

    receptor.FuncAnimation = crear_animacion
    receptor.plt = ModuloSustituido(receptor.plt, show=lambda: None)
    receptor.graficar_datos()

    return receptor.plt.gcf(), animaciones[0]


def crear_cliente_mqtt(receptor, registro):
    """Prepara el cliente como el __main__ del receptor, sin conectarlo todavía."""
    receptor.print = registro.escribir

    # Ruta absoluta para no depender del directorio desde el que se lance el panel
    receptor.FICHERO_GUARDADO = RUTA_RECEPTOR.parent / receptor.FICHERO_GUARDADO
    open(receptor.FICHERO_GUARDADO, "w").close()

    cliente = receptor.mqtt.Client(receptor.mqtt.CallbackAPIVersion.VERSION2)
    cliente.on_connect = receptor.on_connect
    cliente.on_message = receptor.on_message
    cliente.reconnect_delay_set(min_delay=1, max_delay=10)

    return cliente


def conectar_mqtt(receptor, cliente, registro):
    # A diferencia del receptor, connect_async() no falla si el broker está caído:
    # el hilo de loop_start() sigue reintentando hasta conseguir la conexión
    registro.escribir(f"[MQTT] Conectando con el broker en {receptor.BROKER_IP}:{receptor.BROKER_PORT}...")
    cliente.connect_async(receptor.BROKER_IP, receptor.BROKER_PORT)
    cliente.loop_start()


def crear_panel_log(registro):
    panel = QPlainTextEdit()
    panel.setReadOnly(True)
    panel.setMaximumBlockCount(MAX_LINEAS_LOG)
    panel.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    registro.nueva_linea.connect(panel.appendPlainText)
    return panel


def estado_sensor(nombre, datos):
    """Devuelve el texto y el color que resumen la última lectura de un sensor."""
    if datos is None:
        return f"{nombre}: SIN DATOS", ROJO
    if not isinstance(datos, dict) or not datos.get("valid"):
        return f"{nombre}: NO DISPONIBLE", ROJO

    # Sin el campo no se puede afirmar que el dato sea real (emisor sin actualizar)
    if "simulated" not in datos:
        return f"{nombre}: ORIGEN DESCONOCIDO", NARANJA
    if datos["simulated"]:
        return f"{nombre}: SIMULADO", NARANJA

    # gyro_valid solo existe en el sensor de movimiento
    if datos.get("gyro_valid") is False:
        return f"{nombre}: REAL (sin giroscopio)", NARANJA
    return f"{nombre}: REAL", VERDE


class Dashboard(QMainWindow):
    def __init__(self, receptor, video_receiver, puente, cliente, figura, animacion,
                 log_sensores, log_camara):
        super().__init__()
        self.setWindowTitle("Estación de Control - Barco Solar")
        self.resize(1280, 800)

        self.receptor = receptor
        self.video_receiver = video_receiver
        self.puente = puente
        self.cliente = cliente
        self.animacion = animacion
        self.log_sensores = log_sensores
        self.broker_conectado = False
        self.muestras_previas = 0
        self.ultima_muestra = time.monotonic()

        self.estado = QLabel()
        self.statusBar().addWidget(self.estado)

        self.video = QLabel("Esperando vídeo...")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setStyleSheet("background-color: black; color: white;")
        # Ignored evita que el tamaño de la imagen fuerce a crecer la ventana
        self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        # El lienzo de Matplotlib ya es un widget de Qt: basta con moverlo al panel
        arriba = QSplitter(Qt.Orientation.Horizontal)
        arriba.addWidget(self.video)
        arriba.addWidget(figura.canvas)
        arriba.setSizes([640, 640])

        pestanas = QTabWidget()
        pestanas.addTab(crear_panel_log(log_sensores), "Sensores")
        pestanas.addTab(crear_panel_log(log_camara), "Cámara")

        central = QSplitter(Qt.Orientation.Vertical)
        central.addWidget(arriba)
        central.addWidget(pestanas)
        central.setSizes([560, 240])
        self.setCentralWidget(central)

        self.temporizador_video = QTimer(self)
        self.temporizador_video.timeout.connect(self.actualizar_video)
        self.temporizador_video.start(REFRESCO_VIDEO_MS)

        self.temporizador_estado = QTimer(self)
        self.temporizador_estado.timeout.connect(self.actualizar_estado)
        self.temporizador_estado.start(REFRESCO_ESTADO_MS)

        self.actualizar_estado()

    def actualizar_video(self):
        fotograma = self.puente.tomar()
        if fotograma is None:
            return

        alto, ancho = fotograma.shape[:2]
        imagen = QImage(fotograma.data, ancho, alto, fotograma.strides[0],
                        QImage.Format.Format_BGR888)    # colores BGR
        self.video.setPixmap(QPixmap.fromImage(imagen).scaled(
            self.video.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))

    def actualizar_estado(self):
        conectado = self.cliente.is_connected()
        if self.broker_conectado and not conectado:
            self.log_sensores.escribir("[MQTT] Conexión con el broker perdida. Reintentando...")
        self.broker_conectado = conectado

        with self.receptor.datos_lock:
            muestras = len(self.receptor.datos_recibidos)
            ultimo_paquete = self.receptor.datos_recibidos[-1] if muestras else None

        # Se mide con el reloj de la estación, porque el del barco puede no estar sincronizado
        ahora = time.monotonic()
        if muestras != self.muestras_previas:
            self.muestras_previas = muestras
            self.ultima_muestra = ahora
        segundos = ahora - self.ultima_muestra

        # El broker corre en la estación: estar conectado no implica que el barco esté emitiendo
        if muestras and segundos < TIMEOUT_TELEMETRIA_S:
            telemetria = (f"Telemetría: {muestras} muestras", VERDE)
        else:
            telemetria = (f"Telemetría: sin datos hace {segundos:.0f} s", ROJO)
            ultimo_paquete = None

        paquete = ultimo_paquete if isinstance(ultimo_paquete, dict) else {}
        estados = [
            ("Broker: conectado", VERDE) if conectado else ("Broker: desconectado", ROJO),
            telemetria,
            estado_sensor("Altitud", paquete.get("altitude")),
            estado_sensor("Movimiento", paquete.get("motion")),
            ("Vídeo: recibiendo", VERDE) if self.video_receiver.hay_senal else ("Vídeo: sin señal", ROJO)
        ]
        self.estado.setText(" | ".join(
            f'<span style="color: {color}"><b>{texto}</b></span>' for texto, color in estados
        ))

        # El aviso de falta de señal lo dibuja video_receiver.py. Esto cubre el caso en
        # que la recepción ni siquiera puede funcionar, como un puerto ocupado
        if self.puente.error:
            self.video.setText(f"ERROR DE VÍDEO\n{self.puente.error}")

    def closeEvent(self, evento):
        self.animacion.event_source.stop()
        self.cliente.disconnect()
        self.cliente.loop_stop()
        super().closeEvent(evento)


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)    # Permite cerrar con Ctrl+C desde la consola

    matplotlib.use("QtAgg")     # Debe fijarse antes de importar pyplot en el receptor

    video_receiver = cargar_modulo("video_receiver", RUTA_VIDEO)
    receptor = cargar_modulo("receptor_mqtt_v2", RUTA_RECEPTOR)

    # opencv-python para Linux apunta esta variable a su propio Qt, incompatible con PyQt6
    os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)

    app = QApplication(sys.argv)

    log_sensores = RegistroLogs()
    log_camara = RegistroLogs()
    puente = PuenteVideo()

    def registrar_excepcion(tipo, valor, traza):
        # Sin esto, PyQt cierra el programa ante cualquier excepción en un temporizador,
        # así que un paquete mal formado al dibujar las gráficas tiraría todo el panel
        sys.__excepthook__(tipo, valor, traza)
        log_sensores.escribir(f"[ERROR] {tipo.__name__}: {valor}")

    sys.excepthook = registrar_excepcion

    figura, animacion = preparar_graficas(receptor)
    cliente = crear_cliente_mqtt(receptor, log_sensores)

    # La ventana se crea antes de arrancar los hilos para no perder sus primeros logs
    ventana = Dashboard(receptor, video_receiver, puente, cliente, figura, animacion,
                        log_sensores, log_camara)
    conectar_mqtt(receptor, cliente, log_sensores)
    preparar_video(video_receiver, puente, log_camara)

    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
