# Receptores LoRaWAN

Esta carpeta contiene dos receptores MQTT para The Things Network (TTN). TTN
recibe los uplinks LoRaWAN y los expone mediante MQTT; estos programas no se
conectan directamente a una radio LoRa.

## Qué programa usar

| Programa | Uso | Salida principal |
| --- | --- | --- |
| `receptor_lora.py` | Prueba sencilla de recepción. Decodifica un payload de 16 bytes con cuatro `float` (`!ffff`) y muestra altitud y aceleración. | Mensajes en consola. |
| `receptor_lora_medidas.py` | Pruebas reproducibles de rendimiento. Decodifica secuencia, timestamp y cuatro `float`, calcula pérdidas, duplicados, latencias, RSSI, SNR, spreading factor, airtime y disponibilidad. | Informe en consola y `resultados_lora.csv`. |

Para las mediciones debe usarse `receptor_lora_medidas.py`; el receptor simple
no guarda resultados ni calcula métricas.

## Ejecución

Instalar la dependencia:

```bash
python3 -m pip install paho-mqtt
```

Receptor sencillo:

```bash
python3 lora/receptor/receptor_lora.py
```

Receptor de medidas, usando TLS y una API key fuera del código:

```bash
export TTN_API_KEY="NNSXS.xxxxx"
python3 lora/receptor/receptor_lora_medidas.py
```

En PowerShell, la variable equivalente es:

```powershell
$env:TTN_API_KEY = "NNSXS.xxxxx"
python lora/receptor/receptor_lora_medidas.py
```

La aplicación, el clúster TTN y el topic se forman con las constantes de cada
archivo. La API key debe tener permisos de lectura MQTT. El receptor de medidas
usa el puerto 8883 y `tls_set()`; no se debe cambiar al puerto 1883 en una
instalación real porque enviaría la API key sin cifrar.

## Formatos de payload

`receptor_lora.py` espera exactamente 16 bytes después de decodificar
`uplink_message.frm_payload` desde Base64:

```text
!ffff  = altitud, aceleración X, aceleración Y, aceleración Z
```

`receptor_lora_medidas.py` espera exactamente 22 bytes:

```text
!HIffff = secuencia uint16, timestamp uint32,
          altitud float, aceleración X float,
          aceleración Y float, aceleración Z float
```

El formato debe coincidir con el emisor LoRa. Si se cambia el orden, el tamaño o
el tipo de un campo, hay que modificar el `struct.unpack()` del receptor y el
codificador del emisor al mismo tiempo.

## Qué modificar

### `receptor_lora.py`

- Broker o puerto: `BROKER_TTN` y `BROKER_PORT`.
- Aplicación y topic: `APP_ID` y `TOPIC_SUSCRIPCION`.
- Credenciales: el archivo contiene una API key escrita en el código. No se
  debe reutilizar; hay que revocarla/rotarla en TTN y pasar una nueva mediante
  una variable de entorno antes de usar este receptor.
- Decodificación de datos: `on_message()` y su `struct.unpack()`.
- Nuevas acciones por paquete, como guardar o graficar: `on_message()`.

### `receptor_lora_medidas.py`

- Credenciales: `TTN_API_KEY` en el entorno; no escribirla en el archivo.
- Aplicación, usuario, broker y topic: `APP_ID`, `USUARIO`, `BROKER_TTN`,
  `BROKER_PORT` y `TOPIC_SUSCRIPCION`.
- Parámetros que deben coincidir con la prueba/emisor:
  `INTERVALO_ENVIO_S`, `TOTAL_ESPERADO`, `K_CORTE`, `INACTIVIDAD_S` y
  `BYTES_APP`.
- Formato binario: `BYTES_APP` y el `struct.unpack()` de `on_message()`.
- Métricas del informe: `paquetes_en_corte()`, `mostrar_informe()` y el
  diccionario `reg` construido en `on_message()`.
- Nombre o ubicación del CSV: `FICHERO_CSV`.

## Flujo del receptor de medidas

```text
MQTT TTN -> JSON TTN -> Base64 -> bytes LoRaWAN -> métricas por paquete
                                             -> registros
                                             -> informe + resultados_lora.csv
```

La prueba termina cuando recibe `TOTAL_ESPERADO` paquetes o cuando pasa
`INACTIVIDAD_S` sin recibir datos. Si se cambia el número de paquetes o el
intervalo del emisor, deben actualizarse los parámetros correspondientes para
que las pérdidas y el régimen calculados sean correctos.

## Seguridad y mantenimiento

No guardar API keys en el repositorio. Si una clave aparece en el historial o
en un archivo versionado, debe considerarse comprometida y revocarse desde TTN.
Para nuevas pruebas se recomienda partir de `receptor_lora_medidas.py`, que ya
usa TLS y obtiene la clave desde `TTN_API_KEY`.

