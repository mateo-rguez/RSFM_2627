WIFI HaLow + MQTT
=================

Esta carpeta contiene un emisor y un receptor de telemetría para enviar los
datos de los sensores del barco a través de MQTT sobre una red Wi-Fi HaLow.

Wi-Fi HaLow no es el protocolo de mensajes de estos programas. Su función es
proporcionar la conectividad IP entre el barco y la estación. MQTT se encarga
de publicar y recibir la telemetría mediante un broker, por ejemplo Mosquitto.

Flujo de comunicación
---------------------

    Sensores del barco
            |
            v
    emisor_wifi_halow.py
            |
            | MQTT/TCP sobre la red Wi-Fi HaLow
            v
    Broker MQTT (Mosquitto)
            |
            v
    receptor_wifi_halow.py
            |
            v
    telemetria_recibida.jsonl

Archivos
--------

emisor_wifi_halow.py
    Lee los sensores mediante el TelemetryCollector de la carpeta sensores,
    convierte cada muestra a JSON y la publica en MQTT.

receptor_wifi_halow.py
    Se suscribe al mismo topic MQTT, muestra las muestras recibidas y las
    guarda una por línea en telemetria_recibida.jsonl.

Requisitos
----------

Instalar Paho MQTT y pyserial:

    python3 -m pip install paho-mqtt pyserial

El receptor solo necesita paho-mqtt. El emisor usa pyserial si hay sensores
conectados; si no encuentra la placa, el TelemetryCollector utiliza datos
simulados.

Broker local con Mosquitto
--------------------------

En algunas instalaciones Ubuntu/Debian, AppArmor impide que el proceso de
Mosquitto lea configuraciones desde la carpeta del proyecto. En ese caso hay
que copiar la configuración a la carpeta permitida por el sistema:

    sudo install -m 644 mqtt/mosquitto.conf /etc/mosquitto/conf.d/wifi-halow.conf
    sudo systemctl restart mosquitto

Para comprobar el estado del servicio:

    sudo systemctl status mosquitto --no-pager

Si se quiere ejecutar Mosquitto en primer plano para ver los mensajes, primero
se puede detener el servicio y después usar la configuración principal del
sistema, que incluye los ficheros de conf.d:

    sudo systemctl stop mosquitto
    sudo mosquitto -c /etc/mosquitto/mosquitto.conf -v

No se debe usar directamente:

    mosquitto -c mqtt/mosquitto.conf -v

porque el perfil AppArmor puede bloquear el acceso a esa ruta, aunque el
archivo exista y tenga permisos de lectura.

La configuración actual escucha en el puerto 1883 y permite conexiones sin
usuario ni contraseña, por lo que solo debe utilizarse en una red controlada.

Ejecución local
---------------

Terminal 1, broker:

    mosquitto -c mqtt/mosquitto.conf -v

Terminal 2, receptor:

    python3 wifi-halow/receptor_wifi_halow.py

Terminal 3, emisor:

    python3 wifi-halow/emisor_wifi_halow.py

Por defecto ambos programas usan:

    Broker: 127.0.0.1
    Puerto: 1883
    Topic:  wifi-halow/telemetria

Ejecución entre barco y estación
---------------------------------

Si el broker se ejecuta en la estación con IP 10.42.0.1, el emisor del barco
debe conectarse a esa IP:

    python3 wifi-halow/emisor_wifi_halow.py \
        --broker 10.42.0.1 \
        --topic wifi-halow/telemetria

El receptor se ejecuta en la estación y se conecta al broker local:

    python3 wifi-halow/receptor_wifi_halow.py \
        --broker 127.0.0.1 \
        --topic wifi-halow/telemetria

Configuración del puerto serie
------------------------------

El emisor usa por defecto /dev/ttyUSB0 a 38400 baudios. Se puede cambiar con:

    python3 wifi-halow/emisor_wifi_halow.py \
        --sensor-port /dev/ttyACM0 \
        --baudrate 38400

Opciones útiles
---------------

Cambiar el intervalo de publicación:

    --interval 2

Cambiar el topic:

    --topic otro/topic

Usar autenticación MQTT sin escribir las credenciales en el código:

    export MQTT_USERNAME=usuario
    export MQTT_PASSWORD=contraseña
    python3 wifi-halow/emisor_wifi_halow.py --broker 10.42.0.1

El receptor acepta las mismas variables de entorno. También se pueden pasar
las opciones --username y --password directamente.

Formato de los datos
--------------------

El payload publicado es JSON y conserva la estructura del TelemetryCollector:

    {
      "timestamp": "30-10-2026 12:00:00",
      "altitude": {
        "distance_cm": 30.0,
        "altitude_m": 0.3,
        "valid": true
      },
      "motion": {
        "accel": {"x": 0.1, "y": 0.0, "z": 9.81},
        "gyro": {"x": 0.0, "y": 0.0, "z": 0.0},
        "valid": true
      }
    }

El QoS predeterminado es 1, es decir, MQTT intenta entregar cada mensaje al
menos una vez. El topic y el QoS deben coincidir entre emisor y receptor.

Seguridad
---------

No se deben guardar contraseñas, API keys ni certificados dentro del código.
Para una instalación real conviene configurar autenticación MQTT, TLS y una
política de acceso restringida en el broker.
