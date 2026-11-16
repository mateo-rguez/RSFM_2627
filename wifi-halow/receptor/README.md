# Módulos del receptor Wi‑Fi HaLow

Esta carpeta contiene el receptor modular de telemetría y vídeo. El transporte
de los datos lo realiza MQTT sobre la red Wi‑Fi HaLow; Wi‑Fi HaLow proporciona
la conectividad IP, pero no define el formato de los mensajes.

El punto de entrada está un nivel por encima, en
`wifi-halow/receptor_wifi_halow.py`. Los archivos de esta carpeta se importan
como paquete y no están pensados para ejecutarse directamente.

## Flujo de datos

```text
MQTT telemetría ──> mqtt_receptor.py ──> telemetria.py
                                      └─> almacenamiento.py ──> telemetria_recibida.jsonl

MQTT vídeo ───────> mqtt_receptor.py ──> video.py ──> ventana o vídeo MP4

almacenamiento.py + video.py + estado_sensores.py ──> dashboard.py (opcional)
```

## Uso

Desde la raíz del proyecto:

```bash
python3 wifi-halow/receptor_wifi_halow.py
```

Solo telemetría, sin cargar OpenCV ni NumPy:

```bash
python3 wifi-halow/receptor_wifi_halow.py --no-video
```

Vídeo sin ventana, guardándolo en MP4:

```bash
python3 wifi-halow/receptor_wifi_halow.py \
    --no-video-window --video-output ./video_recibido.mp4
```

Panel gráfico con vídeo, gráficas, estado de sensores y logs:

```bash
python3 wifi-halow/receptor_wifi_halow.py --dashboard
```

Se pueden cambiar los parámetros sin editar el código:

```bash
python3 wifi-halow/receptor_wifi_halow.py \
    --broker 127.0.0.1 \
    --port 1883 \
    --topic wifi-halow/telemetria \
    --output ./datos/telemetria.jsonl
```

También se admiten `MQTT_BROKER`, `MQTT_PORT`, `MQTT_TOPIC`,
`MQTT_VIDEO_TOPIC`, `MQTT_VIDEO_QOS`, `MQTT_USERNAME` y `MQTT_PASSWORD`.

Dependencias mínimas: `paho-mqtt`. Para vídeo se necesitan OpenCV y NumPy; para
`--dashboard`, además, PyQt5 y Matplotlib.

## Qué contiene cada archivo

| Archivo | Responsabilidad | Modificarlo cuando… |
| --- | --- | --- |
| `__init__.py` | Marca la carpeta como paquete Python. | Se necesite exponer una API pública del paquete. Normalmente no hace falta tocarlo. |
| `configuracion.py` | Define valores predeterminados, variables de entorno y todos los argumentos de línea de comandos. | Se quiera cambiar broker, puerto, topics, QoS, rutas de salida o añadir una opción nueva. |
| `mqtt_receptor.py` | Conecta con MQTT, se suscribe a telemetría/vídeo y reparte cada mensaje al componente adecuado. | Se cambie la conexión MQTT, autenticación, suscripciones, QoS o el tratamiento de errores de recepción. |
| `telemetria.py` | Decodifica el JSON de telemetría y genera el resumen que aparece en los logs. | Cambie el formato JSON, se añadan campos o se quiera modificar el texto de los logs. Si cambia el contrato del mensaje, revisar también el emisor. |
| `almacenamiento.py` | Mantiene las últimas 40 muestras en memoria y añade cada muestra al archivo JSONL. | Se cambie la persistencia, el límite de muestras, el formato del archivo o la política de concurrencia. |
| `video.py` | Desempaqueta los 8 bytes de timestamp y el JPEG, muestra los fotogramas y opcionalmente crea un MP4. | Cambie el formato binario del vídeo, la ventana, el códec, los FPS de grabación o la detección de pérdida de señal. |
| `estado_sensores.py` | Convierte los campos `valid`, `simulated` y `gyro_valid` en texto y colores de estado. | Cambien las reglas para clasificar un sensor como real, simulado, inválido o sin datos. |
| `dashboard.py` | Construye la interfaz Qt, gráficas de altitud/aceleración, vídeo, sensores y logs. | Se cambie la interfaz, las gráficas, los nombres de sensores o la información mostrada. |

El arranque y la coordinación de hilos están en
`../receptor_wifi_halow.py`. Hay que modificarlo si se cambia el orden de
arranque/parada, la creación de colas, la integración del dashboard o el ciclo
principal del receptor.

## Formato esperado

La telemetría se recibe como JSON. La estructura que consumen las gráficas y el
estado de sensores es, aproximadamente:

```json
{
  "timestamp": 1730289600,
  "altitude": {
    "altitude_m": 0.3,
    "valid": true,
    "simulated": false
  },
  "motion": {
    "accel": {"x": 0.1, "y": 0.0, "z": 9.81},
    "valid": true,
    "simulated": false,
    "gyro_valid": true
  }
}
```

El vídeo usa el topic configurado en `--video-topic`. Cada payload contiene un
timestamp binario de 8 bytes en orden de red (`!d`) seguido de los bytes de una
imagen JPEG. Si se modifica este formato, deben cambiarse conjuntamente el
emisor, `mqtt_receptor.py` si cambia el topic y `video.py`.

## Guía rápida de modificación

- Conexión o topics MQTT: `configuracion.py` y `mqtt_receptor.py`.
- Campos de telemetría: `telemetria.py`, `dashboard.py` y, si procede,
  `estado_sensores.py`.
- Archivo histórico o número de muestras: `almacenamiento.py`.
- Ventana, MP4 o formato de fotograma: `video.py`.
- Aspecto y contenido del panel: `dashboard.py`.
- Hilos, modo de ejecución o nuevas opciones globales: `../receptor_wifi_halow.py`
  y `configuracion.py`.

La carpeta `LTE(CAMBIAR_CODIGO_COMUN)/receptor` contiene actualmente la misma
implementación. Si el cambio debe aplicarse a las dos variantes, hay que
replicarlo en ambas carpetas o unificar posteriormente el código común.

