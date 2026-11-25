# Sistema de telemetría multiprotocolo (Wi-Fi HaLow · LoRa · BLE)

Pruebas **por turnos**: el barco envía por un protocolo y la estación mide las
mismas prestaciones para los tres. Todos usan el **mismo paquete de 30 bytes**
(`formato_paquete.py`), con número de secuencia y hora de envío.

```
barco/      -> Raspberry Pi   (copiar junto a collector.py, altitude_sensor.py, motion_sensor.py)
estacion/   -> PC con Windows
```

`formato_paquete.py` está en las dos carpetas y **debe ser idéntico** en ambas.

## Requisitos

- Raspberry: `pip install paho-mqtt pyserial bless opencv-python` (en el entorno virtual).
- PC: `py -m pip install paho-mqtt bleak PyQt5 matplotlib opencv-python numpy` (Python ≥ 3.13).
- Relojes sincronizados por NTP (chrony en la Raspberry contra el PC) para medir la latencia.

## Una prueba

1. En el PC: arrancar la estación **antes** que el emisor.
2. En la Raspberry: arrancar el emisor con el mismo protocolo.
3. Cerrar la ventana (o Ctrl+C) al terminar. El resumen queda en `estacion/resultados/`.

| Protocolo | PC (estación) | Raspberry (barco) |
|---|---|---|
| Wi-Fi HaLow | `py estacion.py --protocolo halow` | `python3 emisor_barco.py --protocolo halow --broker <IP del PC> --video` |
| BLE | `py estacion.py --protocolo ble` | `python3 emisor_barco.py --protocolo ble --video` |
| LoRa | `$env:TTN_MQTT_API_KEY="NNSXS..."` y `py estacion.py --protocolo lora` | `python3 emisor_barco.py --protocolo lora` |

Opciones útiles: `--descripcion "exterior, 50 m"` (se guarda en el resumen),
`--sin-dashboard --duracion 600` (prueba de 10 min solo en consola),
`--intervalo 70` en el emisor (misma cadencia que LoRa en los tres, para comparar en igualdad),
`--interfaz-halow wlan1` en el emisor (envía señal, velocidad y reintentos de la radio HaLow).

## Comparar

```
py comparar.py
```

Toma el resumen más reciente de cada protocolo y genera `resultados/comparativa.csv`
y `resultados/comparativa.png`.

## LoRa: cambios en la CubeCell

Cargar `barco/CubeCell_Telemetria_v2.ino` (acepta 30 bytes) **después de pegar la AppKey**
(está a ceros a propósito). En la consola de TTN se puede pegar `barco/formateador_ttn.js`
como *Uplink payload formatter* para ver los datos legibles en *Live data*.
