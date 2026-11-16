# Módulos del receptor de la variante LTE

Esta carpeta contiene la implementación modular del receptor de la estación.
Aunque está dentro de la variante denominada `LTE(CAMBIAR_CODIGO_COMUN)`, el
código actual usa MQTT y los topics predeterminados `wifi-halow/telemetria` y
`wifi-halow/video`; la red subyacente solo proporciona la conectividad IP.

El programa se inicia desde `../receptor_wifi_halow.py`. Los módulos de esta
carpeta se cargan mediante imports relativos y no deben ejecutarse de forma
aislada.

## Flujo de datos

```text
Broker MQTT
   ├── telemetría ──> mqtt_receptor.py ──> telemetria.py
   │                                      └─> almacenamiento.py ──> JSONL
   └── vídeo ───────> mqtt_receptor.py ──> video.py ──> ventana/MP4

almacenamiento.py + video.py + estado_sensores.py ──> dashboard.py (opcional)
```

## Uso

Desde la raíz del proyecto:

```bash
python3 "LTE(CAMBIAR_CODIGO_COMUN)/receptor_wifi_halow.py"
```

Modos habituales:

```bash
# Solo telemetría
python3 "LTE(CAMBIAR_CODIGO_COMUN)/receptor_wifi_halow.py" --no-video

# Vídeo sin ventana y guardado en MP4
python3 "LTE(CAMBIAR_CODIGO_COMUN)/receptor_wifi_halow.py" \
    --no-video-window --video-output ./video_recibido.mp4

# Panel Qt con vídeo, gráficas, sensores y logs
python3 "LTE(CAMBIAR_CODIGO_COMUN)/receptor_wifi_halow.py" --dashboard
```

Los valores de broker, puerto, topics, QoS y archivos también se pueden pasar
con las opciones de línea de comandos. Los valores predeterminados de broker y
topics pueden recibirse desde `MQTT_BROKER`, `MQTT_PORT`, `MQTT_TOPIC`,
`MQTT_VIDEO_TOPIC` y `MQTT_VIDEO_QOS`; las credenciales pueden recibirse desde
`MQTT_USERNAME` y `MQTT_PASSWORD`.

Dependencias mínimas: `paho-mqtt`. Para recibir vídeo se necesitan OpenCV y
NumPy. El dashboard requiere además PyQt5 y Matplotlib.

## Qué contiene cada archivo

| Archivo | Responsabilidad | Modificarlo cuando… |
| --- | --- | --- |
| `__init__.py` | Declara el paquete Python del receptor. | Se necesite publicar nombres desde el paquete; normalmente no se modifica. |
| `configuracion.py` | Centraliza valores predeterminados, variables de entorno y argumentos CLI. | Se cambien broker, puerto, topics, QoS, rutas o se añada una opción. |
| `mqtt_receptor.py` | Gestiona la conexión MQTT, las suscripciones y el reparto de telemetría y vídeo. | Se cambie la comunicación MQTT, autenticación, QoS o validación de mensajes. |
| `telemetria.py` | Convierte el payload UTF-8/JSON en un diccionario y prepara el resumen de log. | Cambie el formato de los mensajes de sensores o el texto mostrado en consola. Revisar también el emisor. |
| `almacenamiento.py` | Conserva las últimas muestras en memoria y las añade a un JSONL. | Se cambien la persistencia, el límite de muestras o el formato de salida. |
| `video.py` | Decodifica timestamp + JPEG, muestra el vídeo y lo graba en MP4 cuando se solicita. | Cambie el protocolo de vídeo, códec, FPS, ventana o comportamiento ante pérdida de señal. |
| `estado_sensores.py` | Determina el texto y color de los estados de altímetro, acelerómetro y movimiento. | Cambien las reglas de estado de los sensores. |
| `dashboard.py` | Implementa el panel Qt con vídeo, gráficas, sensores y logs. | Se cambie la interfaz, gráficas o información presentada. |

La coordinación del proceso está en `../receptor_wifi_halow.py`: crea el parser,
las colas, el receptor MQTT y los hilos de vídeo, y decide entre modo consola y
dashboard. Ese archivo es el adecuado para cambios en el ciclo de vida o en la
integración global.

## Qué archivo tocar según el cambio

- Broker, puerto, topic o QoS: `configuracion.py`; para lógica de suscripción,
  también `mqtt_receptor.py`.
- Estructura de telemetría: `telemetria.py`, `dashboard.py` y el emisor.
- Persistencia y número de muestras almacenadas: `almacenamiento.py`.
- Formato, visualización o grabación del vídeo: `video.py` y el emisor de vídeo.
- Colores y reglas de sensores: `estado_sensores.py`.
- Diseño o gráficas de la interfaz: `dashboard.py`.
- Arranque, hilos, apagado o nuevos modos: `../receptor_wifi_halow.py`.

Existe un receptor monolítico anterior en
`../receptor_wifi_hallow_original.py`. Sirve como referencia histórica o como
implementación alternativa, pero no comparte automáticamente cambios con este
paquete. Para el desarrollo normal conviene modificar la implementación
modular y, si se conserva el archivo antiguo, actualizarlo por separado.

La carpeta `wifi-halow/receptor` contiene actualmente los mismos módulos. Si
ambas variantes deben seguir funcionando igual, cualquier cambio común debe
replicarse allí o extraerse a una única biblioteca compartida.

