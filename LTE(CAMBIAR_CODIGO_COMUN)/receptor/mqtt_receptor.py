"""Capa de comunicación MQTT del receptor."""

import queue
import time

import paho.mqtt.client as mqtt

from .telemetria import decodificar_paquete, resumen_paquete


class ReceptorMQTT:
    """Gestiona la conexión MQTT y distribuye telemetría y vídeo."""

    def __init__(
        self,
        args,
        almacenamiento,
        estado_recepcion,
        log_callback=print,
        video_queue=None,
    ):
        self.args = args
        self.almacenamiento = almacenamiento
        self.estado_recepcion = estado_recepcion
        self.log = log_callback
        self.video_queue = video_queue
        self.cliente = mqtt.Client()

        if args.username is not None:
            self.cliente.username_pw_set(args.username, args.password)

        self.cliente.on_connect = self.on_connect
        self.cliente.on_message = self.on_message

    def establecer_log_callback(self, log_callback):
        """Cambia el destino de los logs, por ejemplo al abrir el dashboard."""
        self.log = log_callback

    def on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self.log("[ERROR] El broker rechazó la conexión: {}".format(rc))
            return

        client.subscribe(self.args.topic, qos=self.args.qos)

        if self.video_queue is not None:
            client.subscribe(self.args.video_topic, qos=self.args.video_mqtt_qos)

        if self.video_queue is None:
            self.log(
                "[MQTT] Suscrito a '{}'. Esperando datos...".format(
                    self.args.topic
                )
            )
        else:
            self.log(
                "[MQTT] Suscrito a telemetría '{}' y vídeo '{}'.".format(
                    self.args.topic,
                    self.args.video_topic,
                )
            )

    def on_message(self, client, userdata, mensaje):
        if (
            self.video_queue is not None
            and mensaje.topic == self.args.video_topic
        ):
            self._encolar_video(mensaje.payload)
            return

        try:
            paquete = decodificar_paquete(mensaje.payload)
            self.estado_recepcion["ultima_telemetria"] = time.monotonic()
            self.almacenamiento.guardar(paquete)
            self.log(resumen_paquete(paquete))
        except (
            UnicodeDecodeError,
            ValueError,
            OSError,
            AttributeError,
            TypeError,
        ) as error:
            self.log("[ERROR] Mensaje MQTT no válido: {}".format(error))

    def _encolar_video(self, payload):
        if len(payload) <= 8:
            self.log("[WARN] Fotograma MQTT demasiado pequeño.")
            return

        try:
            self.video_queue.put_nowait(payload)
        except queue.Full:
            try:
                self.video_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.video_queue.put_nowait(payload)
            except queue.Full:
                pass

    def conectar(self):
        self.cliente.connect(self.args.broker, self.args.port, keepalive=60)

    def desconectar(self):
        self.cliente.disconnect()

