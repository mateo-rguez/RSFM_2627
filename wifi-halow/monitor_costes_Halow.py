
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Monitor de costes computacionales del sistema.

Mide:
- Uso de CPU.
- Uso de memoria RAM.
- Temperatura de la Raspberry Pi.
- Trafico de red TX/RX de la interfaz indicada (por defecto wlan0).
- Bytes escritos en disco por segundo.

Compatible con Python 3.5.
"""

import argparse
import csv
import json
import os
import time
import subprocess
from datetime import datetime

import psutil


def temperatura():
    """
    Obtiene la temperatura de la Raspberry Pi.

    Primero intenta utilizar vcgencmd.
    Si no esta disponible, prueba con psutil.
    Devuelve la temperatura en grados Celsius o None.
    """

    # Metodo habitual en Raspberry Pi
    try:
        resultado = subprocess.check_output(
            ["vcgencmd", "measure_temp"],
            universal_newlines=True,
            stderr=subprocess.DEVNULL
        )

        # Formato habitual: temp=45.2'C
        valor = resultado.strip().split("=")[1]
        valor = valor.replace("'C", "")

        return float(valor)

    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        pass

    # Metodo alternativo mediante psutil
    try:
        temperaturas = psutil.sensors_temperatures()

        for sensores in temperaturas.values():
            for sensor in sensores:
                if sensor.current is not None:
                    return float(sensor.current)

    except (AttributeError, OSError):
        pass

    return None


def obtener_red(interfaz):
    """
    Obtiene los contadores de red de una interfaz concreta.

    Por defecto se utiliza wlan0, correspondiente a WiFi HaLow.
    """

    interfaces = psutil.net_io_counters(pernic=True)

    if interfaz not in interfaces:
        disponibles = ", ".join(interfaces.keys())

        raise ValueError(
            "No se encuentra la interfaz '{}'. Interfaces disponibles: {}"
            .format(interfaz, disponibles)
        )

    return interfaces[interfaz]


def calcular_media(valores):
    """Calcula la media de una lista de valores."""

    if not valores:
        return None

    return sum(valores) / float(len(valores))


def calcular_maximo(valores):
    """Calcula el valor maximo de una lista."""

    if not valores:
        return None

    return max(valores)


def crear_resumen(escenario, duracion_real, muestras):
    """
    Genera el resumen estadistico de las mediciones.
    """

    indicadores = [
        "cpu_pct",
        "ram_pct",
        "temperatura_c",
        "red_tx_bytes_s",
        "red_rx_bytes_s",
        "disco_escritura_bytes_s"
    ]

    resumen_indicadores = {}

    for indicador in indicadores:

        valores = []

        for muestra in muestras:
            valor = muestra[indicador]

            if valor is not None:
                valores.append(valor)

        resumen_indicadores[indicador] = {
            "media": calcular_media(valores),
            "maximo": calcular_maximo(valores)
        }

    return {
        "escenario": escenario,
        "duracion_real_s": duracion_real,
        "muestras": len(muestras),
        "indicadores": resumen_indicadores
    }


def main():

    parser = argparse.ArgumentParser(
        description="Monitor de costes computacionales del sistema"
    )

    parser.add_argument(
        "escenario",
        choices=["E0", "E1", "E2", "E3"],
        help="Escenario de pruebas"
    )

    parser.add_argument(
        "--duracion",
        type=int,
        default=300,
        help="Duracion de la prueba en segundos (por defecto: 300)"
    )

    parser.add_argument(
        "--intervalo",
        type=float,
        default=1.0,
        help="Intervalo entre mediciones en segundos (por defecto: 1)"
    )

    parser.add_argument(
        "--salida",
        default="resultados_costes",
        help="Directorio donde guardar los resultados"
    )

    parser.add_argument(
        "--interfaz",
        default="wlan0",
        help="Interfaz de red que se desea monitorizar (por defecto: wlan0)"
    )

    args = parser.parse_args()

    if args.duracion <= 0:
        parser.error("La duracion debe ser mayor que cero")

    if args.intervalo <= 0:
        parser.error("El intervalo debe ser mayor que cero")

    # Comprobar que existe la interfaz de red
    try:
        red_anterior = obtener_red(args.interfaz)
    except ValueError as error:
        parser.error(str(error))

    # Contadores iniciales de disco
    disco_anterior = psutil.disk_io_counters().write_bytes

    # Inicializar medicion de CPU
    psutil.cpu_percent(interval=None)

    # Crear directorio de salida
    if not os.path.exists(args.salida):
        os.makedirs(args.salida)

    # Identificador para los ficheros de resultados
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")

    nombre_base = "costes_{}_{}".format(args.escenario, fecha)

    ruta_csv = os.path.join(
        args.salida,
        nombre_base + ".csv"
    )

    ruta_json = os.path.join(
        args.salida,
        nombre_base + ".json"
    )

    columnas = [
        "segundo",
        "cpu_pct",
        "ram_pct",
        "temperatura_c",
        "red_tx_bytes_s",
        "red_rx_bytes_s",
        "disco_escritura_bytes_s"
    ]

    muestras = []

    inicio = time.time()
    siguiente_muestra = inicio

    print("Iniciando monitor de costes")
    print("Escenario: {}".format(args.escenario))
    print("Interfaz de red: {}".format(args.interfaz))
    print("Duracion: {} segundos".format(args.duracion))
    print("Intervalo: {} segundos".format(args.intervalo))
    print("CSV: {}".format(ruta_csv))

    try:

        with open(ruta_csv, "w") as fichero_csv:

            escritor = csv.DictWriter(
                fichero_csv,
                fieldnames=columnas
            )

            escritor.writeheader()

            while True:

                ahora = time.time()
                tiempo_transcurrido = ahora - inicio

                if tiempo_transcurrido >= args.duracion:
                    break

                # CPU y memoria
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent

                # Temperatura
                temp = temperatura()

                # Red: solamente la interfaz HaLow
                red_actual = obtener_red(args.interfaz)

                tiempo_muestra = ahora - siguiente_muestra + args.intervalo

                if tiempo_muestra <= 0:
                    tiempo_muestra = args.intervalo

                tx = (
                    red_actual.bytes_sent - red_anterior.bytes_sent
                ) / float(tiempo_muestra)

                rx = (
                    red_actual.bytes_recv - red_anterior.bytes_recv
                ) / float(tiempo_muestra)

                # Disco
                disco_actual = psutil.disk_io_counters().write_bytes

                disco = (
                    disco_actual - disco_anterior
                ) / float(tiempo_muestra)

                # Actualizar contadores anteriores
                red_anterior = red_actual
                disco_anterior = disco_actual

                muestra = {
                    "segundo": round(tiempo_transcurrido, 2),
                    "cpu_pct": cpu,
                    "ram_pct": ram,
                    "temperatura_c": temp,
                    "red_tx_bytes_s": tx,
                    "red_rx_bytes_s": rx,
                    "disco_escritura_bytes_s": disco
                }

                muestras.append(muestra)

                # Guardar muestra en CSV
                escritor.writerow(muestra)
                fichero_csv.flush()

                print(
                    "t={:.1f}s | CPU={:.1f}% | RAM={:.1f}% | "
                    "Temp={} | TX={:.0f} B/s | RX={:.0f} B/s"
                    .format(
                        tiempo_transcurrido,
                        cpu,
                        ram,
                        temp if temp is not None else "N/D",
                        tx,
                        rx
                    )
                )

                # Esperar hasta la siguiente medicion
                siguiente_muestra += args.intervalo

                espera = siguiente_muestra - time.time()

                if espera > 0:
                    time.sleep(espera)

    except KeyboardInterrupt:
        print("\nMedicion interrumpida por el usuario")

    except Exception as error:
        print("\nError durante la medicion: {}".format(error))
        raise

    # Calcular duracion real
    duracion_real = round(time.time() - inicio, 2)

    # Generar resumen
    resumen = crear_resumen(
        args.escenario,
        duracion_real,
        muestras
    )

    resumen["interfaz_red"] = args.interfaz

    # Guardar JSON
    with open(ruta_json, "w") as fichero_json:

        json.dump(
            resumen,
            fichero_json,
            indent=4,
            ensure_ascii=False
        )

    print("\nMedicion finalizada")
    print("Muestras recogidas: {}".format(len(muestras)))
    print("Duracion real: {} segundos".format(duracion_real))
    print("Resultados guardados en:")
    print("  {}".format(ruta_csv))
    print("  {}".format(ruta_json))


if __name__ == "__main__":
    main()
