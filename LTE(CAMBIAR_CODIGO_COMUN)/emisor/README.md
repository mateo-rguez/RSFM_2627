# Módulos del emisor de la variante LTE

Esta carpeta contiene los módulos de adquisición y transmisión del emisor para
la variante `LTE(CAMBIAR_CODIGO_COMUN)`. El punto de entrada se mantiene en
`../emisor_wifi_halow.py`, siguiendo la misma organización que el receptor.

El código actual usa MQTT y conserva los topics predeterminados
`wifi-halow/telemetria` y `wifi-halow/video`; la red subyacente es la que aporta
la conectividad IP.

## Uso

Desde la raíz del proyecto:

```bash
python3 "LTE(CAMBIAR_CODIGO_COMUN)/emisor_wifi_halow.py"
```

Modos habituales:

```bash
# Solo telemetría
python3 "LTE(CAMBIAR_CODIGO_COMUN)/emisor_wifi_halow.py" --no-video

# Cambiar broker, puerto de sensores y periodo de publicación
python3 "LTE(CAMBIAR_CODIGO_COMUN)/emisor_wifi_halow.py" \
    --broker 192.168.200.1 \
    --sensor-port /dev/ttyACM0 \
    --interval 2
```

También se pueden configurar mediante variables de entorno el puerto, topic,
intervalo, credenciales MQTT y parámetros de vídeo. Consulta
`../emisor_wifi_halow.py` para la lista completa de opciones CLI.

Dependencias mínimas: `paho-mqtt` y, cuando se usa hardware, `pyserial`. La
transmisión de vídeo necesita OpenCV. Si la placa no está disponible, el
colector entra en modo de simulación.

## Qué contiene cada archivo

| Archivo | Responsabilidad | Modificarlo cuando… |
| --- | --- | --- |
| `__init__.py` | Declara el paquete Python del emisor. | Se necesite exponer una API pública; normalmente no se modifica. |
| `altitude_sensor_Halow.py` | Valida la distancia ultrasónica y calcula la altitud. | Cambien rangos, unidades o simulación del altímetro. |
| `motion_sensor_Halow.py` | Valida acelerómetros y giroscopio y genera simulación. | Cambien unidades, umbrales, gravedad o reglas de validez. |
| `collector_Halow.py` | Lee la placa, coordina los sensores y genera el paquete JSON. | Cambie el formato de la trama serie o la estructura de telemetría. |
| `video_sender_Halow.py` | Captura, codifica y publica los fotogramas JPEG por MQTT. | Cambien cámara, resolución, FPS, calidad o formato del payload. |

El archivo `../emisor_wifi_halow.py` coordina el conjunto. Es el lugar para
cambiar broker, topics, QoS, autenticación, opciones de línea de comandos,
intervalo de publicación y ciclo de vida de los hilos.

## Qué archivo modificar según el objetivo

- Cambiar la lectura de sensores: `collector_Halow.py`.
- Cambiar altitud o distancia: `altitude_sensor_Halow.py`.
- Cambiar aceleración o giroscopio: `motion_sensor_Halow.py`.
- Cambiar MQTT de telemetría: `../emisor_wifi_halow.py`.
- Cambiar vídeo: `video_sender_Halow.py` y `../emisor_wifi_halow.py`.
- Cambiar el formato JSON: `collector_Halow.py` y el receptor modular
  (`../receptor/telemetria.py`, `../receptor/dashboard.py`).

El receptor monolítico `../receptor_wifi_hallow_original.py` no se actualiza
automáticamente cuando cambia el formato; si se sigue usando, hay que revisarlo
por separado.

## Formatos publicados

La telemetría se publica como JSON con los bloques `altitude` y `motion`. El
vídeo se publica en un topic separado como `!d` (timestamp de 8 bytes) seguido
de una imagen JPEG. No se usa Base64.

Los módulos de esta carpeta son actualmente equivalentes a los de
`wifi-halow/emisor`. Si el comportamiento debe mantenerse igual en ambas
variantes, cualquier cambio común debe aplicarse a las dos carpetas.

