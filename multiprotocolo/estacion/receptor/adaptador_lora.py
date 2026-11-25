"""Adaptador LoRa: recibe los uplinks de The Things Network por MQTT (TLS).

TTN envía un JSON con:
  - uplink_message.frm_payload: el paquete común de 30 bytes en base64,
  - metadatos de radio (RSSI, SNR, SF, pasarelas, tiempo en el aire...),
  - received_at: hora a la que TTN recibió la trama.

Con t_envio (del paquete) y received_at se separa la latencia en dos tramos:
  radio + red de TTN = received_at - t_envio
  nube -> estación   = llegada al PC - received_at
(ambos necesitan que el PC y la Raspberry estén en hora real por NTP).
"""

import base64
import calendar
import json
import time

import paho.mqtt.client as mqtt


LIMITE_TIEMPO_AIRE_DIA_S = 30.0  # política de uso justo de TTN
PUERTO_LORA = 2                  # appPort del sketch de la CubeCell


def hora_ttn_a_segundos(texto):
    """"2026-11-18T10:15:30.123456789Z" -> segundos desde 1970 (o None)."""
    if not isinstance(texto, str) or not texto.endswith("Z"):
        return None
    texto = texto[:-1]
    segundos, _, fraccion = texto.partition(".")
    try:
        return calendar.timegm(time.strptime(segundos, "%Y-%m-%dT%H:%M:%S")) + \
            float("0." + (fraccion or "0"))
    except ValueError:
        return None


def _media(valores):
    valores = [v for v in valores if v is not None]
    return sum(valores) / len(valores) if valores else None


class AdaptadorLora:
    def __init__(self, centro, broker, puerto, usuario, api_key):
        self.centro = centro
        self.prest = centro.prestaciones
        self.usuario = usuario
        self.broker = broker
        self.puerto = puerto
        self.topic = "v3/{}/devices/+/up".format(usuario)
        self.inicio_intento = None

        self.ultimo_f_cnt = None
        self.tramas = 0
        self.tramas_perdidas = 0
        self.tramas_sin_datos = 0
        self.rssi = []
        self.snr = []
        self.lat_radio_ms = []
        self.lat_nube_ms = []
        self.dia = None
        self.tiempo_aire_dia = 0.0
        self.conteo_sf = {}
        self.ultimo_tiempo_aire = None
        self.ultimo_enlace = {}

        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.cliente.username_pw_set(usuario, api_key)
        self.cliente.tls_set()  # TTN exige MQTT cifrado (puerto 8883)
        self.cliente.on_connect = self._on_connect
        self.cliente.on_disconnect = self._on_disconnect
        self.cliente.on_message = self._on_message

    @property
    def conectado(self):
        return self.cliente.is_connected()

    def iniciar(self):
        self.centro.log("[LORA] Conectando a TTN ({}:{})...".format(self.broker, self.puerto))
        self.prest.marcar_inicio_conexion()
        self.inicio_intento = time.monotonic()
        self.cliente.connect_async(self.broker, self.puerto, keepalive=60)
        self.cliente.loop_start()

    def detener(self):
        self.cliente.loop_stop()
        self.cliente.disconnect()

    def _on_connect(self, cliente, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.centro.log("[ERROR] TTN rechazó la conexión: {}. Revisa el usuario "
                            "(<aplicación>@ttn) y TTN_MQTT_API_KEY.".format(reason_code))
            return
        cliente.subscribe(self.topic, qos=0)
        self.centro.log("[LORA] Suscrito a '{}'. Esperando uplinks (1 cada ~70 s)...".format(self.topic))

    def _on_disconnect(self, cliente, userdata, flags, reason_code, properties):
        self.centro.log("[LORA] Desconectado de TTN: {}".format(reason_code))

    def _on_message(self, cliente, userdata, mensaje):
        llegada = time.time()
        try:
            datos_ttn = json.loads(mensaje.payload.decode("utf-8"))
            uplink = datos_ttn["uplink_message"]
        except (UnicodeDecodeError, ValueError, KeyError, TypeError):
            self.centro.log("[ERROR] Mensaje de TTN no válido.")
            return

        simulado = bool(datos_ttn.get("simulated") or uplink.get("simulated"))
        self._contar_trama(uplink, simulado)

        payload = base64.b64decode(uplink.get("frm_payload") or "")
        if not payload:
            self.tramas_sin_datos += 1
            self.centro.log("[LORA] Trama f_cnt={} sin datos (solo comandos MAC).".format(
                uplink.get("f_cnt")))
            self._actualizar()
            return
        if uplink.get("f_port") != PUERTO_LORA:
            self.centro.log("[AVISO] Uplink en el puerto {} ignorado.".format(uplink.get("f_port")))
            return

        enlace = self._metadatos(uplink, simulado)
        self.ultimo_enlace = enlace
        muestra = self.centro.muestra_recibida(payload, llegada, extras=enlace)
        if muestra is not None and enlace["hora_ttn"]:
            self.lat_radio_ms.append((enlace["hora_ttn"] - muestra["t_envio"]) * 1000)
            self.lat_nube_ms.append((llegada - enlace["hora_ttn"]) * 1000)
        self._actualizar()

    def _contar_trama(self, uplink, simulado):
        """Pérdidas a nivel LoRaWAN, con el contador de tramas f_cnt."""
        if simulado:
            return  # "Simulate uplink" usa un f_cnt escrito a mano
        f_cnt = uplink.get("f_cnt", 0)
        if self.ultimo_f_cnt is not None and f_cnt > self.ultimo_f_cnt:
            self.tramas_perdidas += f_cnt - self.ultimo_f_cnt - 1
        self.ultimo_f_cnt = f_cnt
        self.tramas += 1

        tiempo_aire = uplink.get("consumed_airtime")  # "0.066816s"
        try:
            tiempo_aire = float(str(tiempo_aire).rstrip("s"))
        except ValueError:
            tiempo_aire = 0.0
        dia = time.strftime("%Y-%m-%d", time.gmtime())
        if dia != self.dia:
            self.dia = dia
            self.tiempo_aire_dia = 0.0
        self.tiempo_aire_dia += tiempo_aire
        self.ultimo_tiempo_aire = tiempo_aire

    def _metadatos(self, uplink, simulado):
        ajustes = uplink.get("settings") or {}
        lora = (ajustes.get("data_rate") or {}).get("lora") or {}
        pasarelas = [p for p in uplink.get("rx_metadata") or [] if isinstance(p, dict)]
        mejor = max(pasarelas, key=lambda p: p.get("rssi", -1000), default={})

        sf = lora.get("spreading_factor")
        if sf:
            self.conteo_sf[sf] = self.conteo_sf.get(sf, 0) + 1
        self.rssi.append(mejor.get("rssi"))
        self.snr.append(mejor.get("snr"))
        return {
            "f_cnt": uplink.get("f_cnt"),
            "rssi_dbm": mejor.get("rssi"),
            "snr_db": mejor.get("snr"),
            "sf": sf,
            "ancho_banda_khz": (lora.get("bandwidth") or 0) / 1000 or None,
            "frecuencia_mhz": int(ajustes.get("frequency", 0)) / 1e6 or None,
            "pasarela": (mejor.get("gateway_ids") or {}).get("gateway_id"),
            "num_pasarelas": len(pasarelas),
            "tiempo_aire_s": self.ultimo_tiempo_aire,
            "hora_ttn": hora_ttn_a_segundos(uplink.get("received_at")),
            "simulado_ttn": simulado,
        }

    def _actualizar(self):
        """Pasa las prestaciones exclusivas de LoRa al dashboard."""
        def num(valor, formato):
            return "—" if valor is None else formato.format(valor)

        esperadas = self.tramas + self.tramas_perdidas
        ultimo_rssi = self.rssi[-1] if self.rssi else None
        ultimo_snr = self.snr[-1] if self.snr else None
        self.prest.actualizar_especificas({
            "RSSI (último / medio)": "{} / {}".format(
                num(ultimo_rssi, "{:.0f} dBm"), num(_media(self.rssi), "{:.1f} dBm")),
            "SNR (último / medio)": "{} / {}".format(
                num(ultimo_snr, "{:.1f} dB"), num(_media(self.snr), "{:.1f} dB")),
            "SF usados (nº de tramas)": ", ".join(
                "SF{}: {}".format(sf, n) for sf, n in sorted(self.conteo_sf.items())) or "—",
            "Tramas LoRaWAN (f_cnt) recibidas / perdidas": "{} / {} ({})".format(
                self.tramas, self.tramas_perdidas,
                num(100.0 * self.tramas_perdidas / esperadas if esperadas else None, "{:.1f} %")),
            "Tramas sin datos (solo MAC)": self.tramas_sin_datos,
            "Latencia radio + red TTN (media)": num(_media(self.lat_radio_ms), "{:.0f} ms"),
            "Latencia TTN → estación (media)": num(_media(self.lat_nube_ms), "{:.0f} ms"),
            "Pasarela (mejor RSSI) / nº que oyen la trama": "{} / {}".format(
                self.ultimo_enlace.get("pasarela") or "—",
                num(self.ultimo_enlace.get("num_pasarelas"), "{}")),
            "Modulación (última trama)": "SF{} · {} · {}".format(
                num(self.ultimo_enlace.get("sf"), "{}"),
                num(self.ultimo_enlace.get("ancho_banda_khz"), "{:.0f} kHz"),
                num(self.ultimo_enlace.get("frecuencia_mhz"), "{:.1f} MHz")),
            "Tiempo en el aire (última trama)": num(
                self.ultimo_tiempo_aire * 1000 if self.ultimo_tiempo_aire is not None else None,
                "{:.1f} ms"),
            "Tiempo en el aire hoy (UTC)": "{:.2f} s de {:.0f} s ({:.1f} %)".format(
                self.tiempo_aire_dia, LIMITE_TIEMPO_AIRE_DIA_S,
                100.0 * self.tiempo_aire_dia / LIMITE_TIEMPO_AIRE_DIA_S),
        })
