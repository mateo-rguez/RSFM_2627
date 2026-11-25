"""Adaptador Wi-Fi HaLow: recibe por MQTT del broker Mosquitto del PC.

Topics (los mismos que usa barco/enlace_halow.py):
    barco/telemetria  paquete común de 30 bytes
    barco/video       [hora de envío !d] + JPEG
    barco/enlace      JSON con señal, velocidad y reintentos de la radio HaLow
"""

import json
import time

import paho.mqtt.client as mqtt


TOPIC_TELEMETRIA = "barco/telemetria"
TOPIC_VIDEO = "barco/video"
TOPIC_ENLACE = "barco/enlace"

NOMBRES_ENLACE = {
    "senal_dbm": "Señal HaLow (en la Raspberry)",
    "tx_bitrate": "Velocidad física de transmisión",
    "rx_bitrate": "Velocidad física de recepción",
    "tx_reintentos": "Reintentos MAC acumulados",
    "tx_fallidos": "Transmisiones fallidas acumuladas",
    "tx_paquetes": "Tramas transmitidas acumuladas",
    "perdida_balizas": "Balizas perdidas",
}


class AdaptadorHalow:
    def __init__(self, centro, broker, puerto, qos, usuario=None, clave=None, con_video=True):
        self.centro = centro
        self.prest = centro.prestaciones
        self.broker = broker
        self.puerto = puerto
        self.qos = qos
        self.con_video = con_video
        self.inicio_intento = None
        self.conexiones = 0

        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if usuario:
            self.cliente.username_pw_set(usuario, clave)
        self.cliente.on_connect = self._on_connect
        self.cliente.on_disconnect = self._on_disconnect
        self.cliente.on_message = self._on_message

        self.prest.actualizar_especificas({
            "QoS MQTT de la suscripción": qos,
            "Broker": "{}:{}".format(broker, puerto),
        })

    @property
    def conectado(self):
        return self.cliente.is_connected()

    def iniciar(self):
        self.centro.log("[HALOW] Conectando al broker {}:{}...".format(self.broker, self.puerto))
        self.prest.marcar_inicio_conexion()
        self.inicio_intento = time.monotonic()
        # connect_async + loop_start: paho reintenta solo si el broker no responde.
        self.cliente.connect_async(self.broker, self.puerto, keepalive=30)
        self.cliente.loop_start()

    def detener(self):
        self.cliente.loop_stop()
        self.cliente.disconnect()

    def _on_connect(self, cliente, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.centro.log("[ERROR] El broker rechazó la conexión: {}".format(reason_code))
            return
        self.conexiones += 1
        if self.conexiones == 1:
            ms = (time.monotonic() - self.inicio_intento) * 1000
            self.prest.actualizar_especificas({"Tiempo de conexión MQTT": "{:.0f} ms".format(ms)})
        else:
            self.prest.sumar_especifica("Reconexiones MQTT")

        cliente.subscribe(TOPIC_TELEMETRIA, qos=self.qos)
        cliente.subscribe(TOPIC_ENLACE, qos=0)
        if self.con_video:
            cliente.subscribe(TOPIC_VIDEO, qos=0)
        self.centro.log("[HALOW] Suscrito a {}{}.".format(
            TOPIC_TELEMETRIA, " y " + TOPIC_VIDEO if self.con_video else ""))

    def _on_disconnect(self, cliente, userdata, flags, reason_code, properties):
        self.centro.log("[HALOW] Desconectado del broker: {}".format(reason_code))

    def _on_message(self, cliente, userdata, mensaje):
        llegada = time.time()  # lo primero, para no sumar tiempo de proceso
        if mensaje.topic == TOPIC_TELEMETRIA:
            self.centro.muestra_recibida(mensaje.payload, llegada)
        elif mensaje.topic == TOPIC_VIDEO:
            self.centro.fotograma_recibido(mensaje.payload, llegada)
        elif mensaje.topic == TOPIC_ENLACE:
            try:
                estado = json.loads(mensaje.payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return
            self.prest.actualizar_especificas({
                NOMBRES_ENLACE[clave]: valor
                for clave, valor in estado.items() if clave in NOMBRES_ENLACE
            })
