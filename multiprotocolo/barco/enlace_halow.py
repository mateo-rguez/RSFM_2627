"""Enlace Wi-Fi HaLow: publica por MQTT en el broker Mosquitto del PC."""

import asyncio
import json
import subprocess
import time

import paho.mqtt.client as mqtt


TOPIC_TELEMETRIA = "barco/telemetria"
TOPIC_VIDEO = "barco/video"
TOPIC_ENLACE = "barco/enlace"


class EnlaceHalow:
    nombre = "Wi-Fi HaLow"
    admite_video = True

    def __init__(self, broker, puerto=1883, qos=1, interfaz=None):
        self.broker = broker
        self.puerto = puerto
        self.qos = qos
        self.interfaz = interfaz  # p. ej. "wlan1"; para leer las estadísticas de radio
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.cliente.on_connect = self._on_connect
        self.cliente.on_disconnect = self._on_disconnect
        self.conectado = False

    def _on_connect(self, cliente, userdata, flags, reason_code, properties):
        self.conectado = not reason_code.is_failure
        print("[HALOW] Conexión con el broker: {}".format(reason_code))

    def _on_disconnect(self, cliente, userdata, flags, reason_code, properties):
        self.conectado = False
        print("[HALOW] Desconectado del broker: {}".format(reason_code))

    async def iniciar(self):
        print("[HALOW] Conectando a {}:{}...".format(self.broker, self.puerto))
        self.cliente.connect(self.broker, self.puerto, keepalive=30)
        self.cliente.loop_start()  # paho atiende la red en su propio hilo
        for _ in range(100):
            if self.conectado:
                return True
            await asyncio.sleep(0.1)
        print("[ERROR] No se pudo conectar con el broker en 10 s.")
        return False

    async def enviar_telemetria(self, paquete):
        """Devuelve True si paho ha aceptado el mensaje."""
        info = self.cliente.publish(TOPIC_TELEMETRIA, paquete, qos=self.qos)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    async def enviar_video(self, datos):
        # El vídeo va con QoS 0: un fotograma retrasado ya no sirve.
        self.cliente.publish(TOPIC_VIDEO, datos, qos=0)

    async def enviar_estado_enlace(self):
        """Publica las estadísticas de radio de la interfaz HaLow (si se indicó)."""
        if not self.interfaz:
            return
        estado = await asyncio.to_thread(leer_estadisticas_wifi, self.interfaz)
        if estado:
            estado["t"] = time.time()
            self.cliente.publish(TOPIC_ENLACE, json.dumps(estado), qos=0)

    async def detener(self):
        self.cliente.loop_stop()
        self.cliente.disconnect()


def leer_estadisticas_wifi(interfaz):
    """Lee señal, velocidad física y reintentos con `iw dev <interfaz> station dump`.

    Funciona si el módulo HaLow aparece como interfaz de red en Linux.
    Devuelve un diccionario (vacío si no se puede leer).
    """
    try:
        salida = subprocess.run(
            ["iw", "dev", interfaz, "station", "dump"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    campos = {
        "signal": "senal_dbm",
        "tx bitrate": "tx_bitrate",
        "rx bitrate": "rx_bitrate",
        "tx retries": "tx_reintentos",
        "tx failed": "tx_fallidos",
        "tx packets": "tx_paquetes",
        "beacon loss": "perdida_balizas",
    }
    estado = {}
    for linea in salida.splitlines():
        if ":" not in linea:
            continue
        clave, valor = linea.strip().split(":", 1)
        if clave in campos:
            estado[campos[clave]] = valor.strip()
    return estado
