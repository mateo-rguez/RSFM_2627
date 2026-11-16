# Módulos del emisor Wi‑Fi HaLow

Esta carpeta reúne la adquisición de sensores y la transmisión de telemetría y
vídeo del barco. El punto de entrada se mantiene en el directorio padre:
`../emisor_wifi_halow.py`, de forma paralela a la organización del receptor.

El emisor publica por MQTT sobre la red Wi‑Fi HaLow. La red proporciona la
conectividad IP y MQTT transporta los mensajes.

## Uso

Desde la raíz del proyecto:

```bash
python3 wifi-halow/emisor_wifi_halow.py
```

Solo telemetría, sin iniciar la cámara:

```bash
python3 wifi-halow/emisor_wifi_halow.py --no-video
```

Ejemplo con broker, puerto serie y frecuencia personalizados:

```bash
python3 wifi-halow/emisor_wifi_halow.py \
    --broker 192.168.200.1 \
    --sensor-port /dev/ttyACM0 \
    --baudrate 38400 \
    --interval 2
```

El emisor acepta también `MQTT_PORT`, `MQTT_TOPIC`, `MQTT_INTERVAL`,
`MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_VIDEO_TOPIC`, `MQTT_VIDEO_QOS`,
`VIDEO_CAMERA`, `VIDEO_WIDTH`, `VIDEO_HEIGHT`, `VIDEO_FPS` y
`VIDEO_JPEG_QUALITY`.

Dependencias mínimas: `paho-mqtt` y, si hay una placa conectada, `pyserial`.
Para vídeo se necesita además OpenCV. Si no se detecta la placa o no está
instalado `pyserial`, el `TelemetryCollector` usa datos simulados.

## Flujo y archivos

```text
altitude_sensor_Halow.py ─┐
motion_sensor_Halow.py  ──┼─> collector_Halow.py ──> emisor_wifi_halow.py
puerto serie              ─┘             │                  │
                                        │                  ├─> MQTT telemetría
video_sender_Halow.py ──────────────────┴──────────────────┴─> MQTT vídeo
```

| Archivo | Responsabilidad | Modificarlo cuando… |
| --- | --- | --- |
| `__init__.py` | Declara el paquete del emisor. | Se quieran exponer nombres públicos del paquete; normalmente no hace falta tocarlo. |
| `altitude_sensor_Halow.py` | Valida la distancia ultrasónica y calcula la altitud. | Cambien el rango válido, la conversión a metros o el comportamiento simulado. |
| `motion_sensor_Halow.py` | Valida aceleración y giroscopio y genera los datos simulados. | Cambien unidades, gravedad nominal, umbrales o reglas de validez. |
| `collector_Halow.py` | Lee las tramas JSON del puerto serie, coordina los sensores y construye el paquete de telemetría. | Cambie el formato que envía la placa, el puerto serie o la estructura JSON publicada. |
| `video_sender_Halow.py` | Captura la cámara, redimensiona, codifica JPEG y publica timestamp + JPEG por MQTT. | Cambien resolución, FPS, calidad, formato binario o tratamiento de errores de cámara. |

El programa de coordinación está en `../emisor_wifi_halow.py`. Hay que
modificarlo para cambiar broker, topics, argumentos CLI, intervalo de envío,
autenticación o el arranque/parada de los hilos de telemetría y vídeo.

## Qué archivo tocar según el cambio

- Lectura de la placa: `collector_Halow.py`.
- Distancia/altitud: `altitude_sensor_Halow.py`.
- Acelerómetro/giroscopio: `motion_sensor_Halow.py`.
- Broker, topic de telemetría, QoS o credenciales: `../emisor_wifi_halow.py`.
- Cámara, topic de vídeo, resolución, FPS o JPEG: `video_sender_Halow.py` y
  `../emisor_wifi_halow.py`.
- Estructura JSON de la telemetría: `collector_Halow.py` y el receptor
  (`receptor/telemetria.py`, `receptor/dashboard.py`).

Si se modifica el formato de telemetría, el cambio debe hacerse también en el
receptor. Si se modifica el payload de vídeo, deben actualizarse a la vez
`video_sender_Halow.py` y `receptor/video.py`.

## Formatos publicados

La telemetría se publica como JSON con `timestamp`, `altitude` y `motion`:

```json
{
  "timestamp": 1730289600.123,
  "altitude": {"distance_cm": 30.0, "altitude_m": 0.3, "valid": true},
  "motion": {
    "accel": {"x": 0.1, "y": 0.0, "z": 9.81},
    "gyro": {"x": 0.0, "y": 0.0, "z": 0.0},
    "valid": true
  }
}
```

El vídeo se publica en otro topic. Cada payload contiene un timestamp `!d` de
8 bytes seguido de los bytes JPEG; no usa Base64.

La carpeta `LTE(CAMBIAR_CODIGO_COMUN)/emisor` contiene una copia de estos
módulos para la otra variante. Los cambios comunes deben replicarse allí o
extraerse a una biblioteca compartida.

