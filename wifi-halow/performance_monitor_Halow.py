
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Monitor de prestaciones del sistema RSFM.

Mide:
- CPU y RAM globales.
- CPU y RAM de procesos seleccionados.
- Trafico TX/RX de la interfaz WiFi HaLow.
- Escrituras en disco.
- Temperatura de la Raspberry Pi.
- Carga del sistema.

Compatible con Python 3.5.
"""

import argparse
import csv
import json
import os
import re
import time
import subprocess
from datetime import datetime

import psutil


def obtener_temperatura():
    """Obtiene la temperatura de la Raspberry Pi."""

    try:
        resultado = subprocess.check_output(
            ["vcgencmd", "measure_temp"],
            universal_newlines=True,
            stderr=subprocess.DEVNULL
        )

        valor = resultado.strip().split("=")[1]
        valor = valor.replace("'C", "")

        return float(valor)

    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        pass

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
    """Obtiene los contadores de una interfaz de red."""

    interfaces = psutil.net_io_counters(pernic=True)

    if interfaz not in interfaces:
        raise ValueError(
            "No se encuentra la interfaz '{}'. Interfaces disponibles: {}"
            .format(interfaz, ", ".join(interfaces.keys()))
        )

    return interfaces[interfaz]


def obtener_procesos(patron, pid):
    """
    Busca procesos mediante PID o expresion regular.

    Devuelve una lista de objetos psutil.Process.
    """

    procesos = []

    if pid is not None:
        try:
            proceso = psutil.Process(pid)

            if proceso.is_running():
                procesos.append(proceso)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return procesos

    if not patron:
        return procesos

    expresion = re.compile(patron, re.IGNORECASE)

    for proceso in psutil.process_iter():

        try:
            nombre = proceso.name()
            cmdline = " ".join(proceso.cmdline())

            texto = "{} {}".format(nombre, cmdline)

            if expresion.search(texto):
                procesos.append(proceso)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return procesos


def medir_procesos(patron, pid, procesos_anteriores):
    """
    Obtiene CPU y RAM de los procesos encontrados.

    CPU se expresa como porcentaje de un nucleo.
    """

    procesos = obtener_procesos(patron, pid)

    cpu_total = 0.0
    ram_total = 0
    numero_procesos = 0

    procesos_actuales = {}

    for proceso in procesos:

        try:
            proceso_id = proceso.pid

            # Inicializar el contador de CPU si es un proceso nuevo
            if proceso_id not in procesos_anteriores:
                proceso.cpu_percent(interval=None)

            cpu = proceso.cpu_percent(interval=None)
            ram = proceso.memory_info().rss

            cpu_total += cpu
            ram_total += ram
            numero_procesos += 1

            procesos_actuales[proceso_id] = proceso

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {
        "cpu": cpu_total if numero_procesos > 0 else None,
        "ram": ram_total if numero_procesos > 0 else None,
        "numero": numero_procesos
    }, procesos_actuales


def media(valores):
    """Calcula la media de una lista."""

    valores_validos = [
        valor for valor in valores if valor is not None
    ]

    if not valores_validos:
        return None

    return sum(valores_validos) / float(len(valores_validos))


def maximo(valores):
    """Calcula el maximo de una lista."""

    valores_validos = [
        valor for valor in valores if valor is not None
    ]

    if not valores_validos:
        return None

    return max(valores_validos)


def generar_resumen(muestras, duracion, interfaz):

    indicadores = [
        "cpu_sistema_pct",
        "ram_sistema_pct",
        "cpu_sensor_pct",
        "ram_sensor_bytes",
        "cpu_camara_pct",
        "ram_camara_bytes",
        "red_tx_bytes_s",
        "red_rx_bytes_s",
        "disco_escritura_bytes_s",
        "temperatura_c"
    ]

    resumen = {}

    for indicador in indicadores:

        valores = [
            muestra[indicador] for muestra in muestras
        ]

        resumen[indicador] = {
            "media": media(valores),
            "maximo": maximo(valores)
        }

    return {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duracion_s": duracion,
        "numero_muestras": len(muestras),
        "interfaz": interfaz,
        "indicadores": resumen
    }


def main():

    parser = argparse.ArgumentParser(
        description="Monitor de prestaciones del sistema RSFM"
    )

    parser.add_argument(
        "--duracion",
        type=int,
        default=300,
        help="Duracion de la prueba en segundos"
    )

    parser.add_argument(
        "--intervalo",
        type=float,
        default=1.0,
        help="Intervalo entre muestras en segundos"
    )

    parser.add_argument(
        "--interfaz",
        default="wlan0",
        help="Interfaz de red a monitorizar"
    )

    parser.add_argument(
        "--salida",
        default="resultados_performance",
        help="Directorio de resultados"
    )

    parser.add_argument(
        "--sensor-pattern",
        default="emisor_wifi_halow.py",
        help="Expresion regular para localizar el proceso de telemetria"
    )

    parser.add_argument(
        "--camera-pattern",
        default="video_sender_Halow.py",
        help="Expresion regular para localizar el proceso de video"
    )

    parser.add_argument(
        "--sensor-pid",
        type=int,
        default=None,
        help="PID del proceso de telemetria"
    )

    parser.add_argument(
        "--camera-pid",
        type=int,
        default=None,
        help="PID del proceso de video"
    )

    args = parser.parse_args()

    if args.duracion <= 0:
        parser.error("La duracion debe ser mayor que cero")

    if args.intervalo <= 0:
        parser.error("El intervalo debe ser mayor que cero")

    # Comprobar interfaz HaLow
    try:
        red_anterior = obtener_red(args.interfaz)

    except ValueError as error:
        parser.error(str(error))

    # Contador inicial de escrituras en disco
    disco_anterior = psutil.disk_io_counters().write_bytes

    # Inicializar medicion de CPU global
    psutil.cpu_percent(interval=None)

    # Directorio de resultados
    if not os.path.exists(args.salida):
        os.makedirs(args.salida)

    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")

    nombre_base = "performance_{}".format(fecha)

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
        "cpu_sistema_pct",
        "ram_sistema_pct",
        "cpu_sensor_pct",
        "ram_sensor_bytes",
        "procesos_sensor",
        "cpu_camara_pct",
        "ram_camara_bytes",
        "procesos_camara",
        "red_tx_bytes_s",
        "red_rx_bytes_s",
        "disco_escritura_bytes_s",
        "temperatura_c",
        "load_1",
        "load_5",
        "load_15"
    ]

    muestras = []

    procesos_sensor = {}
    procesos_camara = {}

    inicio = time.time()
    siguiente_muestra = inicio

    print("Iniciando monitor de prestaciones")
    print("Interfaz: {}".format(args.interfaz))
    print("Duracion: {} segundos".format(args.duracion))
    print("Intervalo: {} segundos".format(args.intervalo))
    print("Patron sensor: {}".format(args.sensor_pattern))
    print("Patron camara: {}".format(args.camera_pattern))

    try:

        with open(ruta_csv, "w") as fichero_csv:

            escritor = csv.DictWriter(
                fichero_csv,
                fieldnames=columnas
            )

            escritor.writeheader()

            while True:

                ahora = time.time()
                transcurrido = ahora - inicio

                if transcurrido >= args.duracion:
                    break

                # CPU y RAM globales
                cpu_sistema = psutil.cpu_percent(interval=None)
                ram_sistema = psutil.virtual_memory().percent

                # Procesos de telemetria
                sensor, procesos_sensor = medir_procesos(
                    args.sensor_pattern,
                    args.sensor_pid,
                    procesos_sensor
                )

                # Procesos de video
                camara, procesos_camara = medir_procesos(
                    args.camera_pattern,
                    args.camera_pid,
                    procesos_camara
                )

                # Trafico de red HaLow
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

                red_anterior = red_actual

                # Escrituras en disco
                disco_actual = psutil.disk_io_counters().write_bytes

                disco = (
                    disco_actual - disco_anterior
                ) / float(tiempo_muestra)

                disco_anterior = disco_actual

                # Temperatura
                temp = obtener_temperatura()

                # Carga del sistema
                try:
                    load_1, load_5, load_15 = os.getloadavg()

                except (AttributeError, OSError):
                    load_1 = None
                    load_5 = None
                    load_15 = None

                muestra = {
                    "segundo": round(transcurrido, 2),
                    "cpu_sistema_pct": cpu_sistema,
                    "ram_sistema_pct": ram_sistema,
                    "cpu_sensor_pct": sensor["cpu"],
                    "ram_sensor_bytes": sensor["ram"],
                    "procesos_sensor": sensor["numero"],
                    "cpu_camara_pct": camara["cpu"],
                    "ram_camara_bytes": camara["ram"],
                    "procesos_camara": camara["numero"],
                    "red_tx_bytes_s": tx,
                    "red_rx_bytes_s": rx,
                    "disco_escritura_bytes_s": disco,
                    "temperatura_c": temp,
                    "load_1": load_1,
                    "load_5": load_5,
                    "load_15": load_15
                }

                muestras.append(muestra)

                escritor.writerow(muestra)
                fichero_csv.flush()

                print(
                    "t={:.1f}s | CPU={:.1f}% | RAM={:.1f}% | "
                    "Sensor CPU={} | Video CPU={} | "
                    "TX={:.0f} B/s | RX={:.0f} B/s"
                    .format(
                        transcurrido,
                        cpu_sistema,
                        ram_sistema,
                        sensor["cpu"] if sensor["cpu"] is not None else "N/D",
                        camara["cpu"] if camara["cpu"] is not None else "N/D",
                        tx,
                        rx
                    )
                )

                # Esperar al siguiente intervalo
                siguiente_muestra += args.intervalo

                espera = siguiente_muestra - time.time()

                if espera > 0:
                    time.sleep(espera)

    except KeyboardInterrupt:
        print("\nMedicion interrumpida por el usuario")

    # Resumen final
    duracion_real = round(time.time() - inicio, 2)

    resumen = generar_resumen(
        muestras,
        duracion_real,
        args.interfaz
    )

    with open(ruta_json, "w") as fichero_json:

        json.dump(
            resumen,
            fichero_json,
            indent=4,
            ensure_ascii=False
        )

    print("\nMedicion finalizada")
    print("Muestras: {}".format(len(muestras)))
    print("Duracion real: {} segundos".format(duracion_real))
    print("CSV: {}".format(ruta_csv))
    print("JSON: {}".format(ruta_json))


if __name__ == "__main__":
    main()
