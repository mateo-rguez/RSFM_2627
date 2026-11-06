
import argparse
import csv
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import time
import math

try:
    import psutil
except ImportError:
    print("ERROR: falta psutil. Instala con: pip3 install psutil")
    sys.exit(1)


# Procesos encontrados en ejecuciones anteriores del monitor.
PROCESOS_CACHE = {}


COLUMNAS = [
    "timestamp",
    "protocolo",
    "equipo",

    # Sistema
    "cpu_global_pct",
    "ram_global_pct",
    "ram_global_mb",
    "carga_1min",
    "temperatura_c",

    # Aplicacion
    "cpu_procesos_pct",
    "ram_procesos_mb",

    # Interfaz de red
    "red_tx_bytes_s",
    "red_rx_bytes_s",
    "red_tx_mbps",
    "red_rx_mbps",
    "red_tx_bytes_total",
    "red_rx_bytes_total",

    # ICMP
    "latencia_icmp_ms",
    "perdida_icmp_pct",

    # Radio
    "rssi_dbm",

    # Disco
    "disco_escritura_bytes_s",

    # Aplicacion: contadores propios
    "app_bytes_rx_total",
    "app_goodput_bytes_s",
    "app_mensajes_tx",
    "app_mensajes_rx",
    "app_perdida_pct",
    "app_latencia_ms"
]


# --------------------------------------------------
# ARGUMENTOS
# --------------------------------------------------

def argumentos():

    parser = argparse.ArgumentParser(
        description="Monitor comun para LoRa, BLE, WiFi HaLow y LTE."
    )

    parser.add_argument(
        "--protocolo",
        required=True,
        choices=["lora", "ble", "halow", "lte"]
    )

    parser.add_argument(
        "--equipo",
        required=True,
        help="Identificador del equipo: emisor, receptor, etc."
    )

    parser.add_argument(
        "--peer",
        default=None,
        help="IP del otro extremo. Si no se indica, no se realiza ping."
    )

    parser.add_argument(
        "--interfaz",
        default="none",
        help="Interfaz de red: wlan0, wwan0, eth0 o none."
    )

    parser.add_argument(
        "--duracion",
        type=int,
        default=300
    )

    parser.add_argument(
        "--intervalo",
        type=float,
        default=1.0
    )

    parser.add_argument(
        "--salida",
        default="resultados",
        help="Prefijo de los ficheros CSV y JSON."
    )

    parser.add_argument(
        "--procesos-pattern",
        default="",
        help="Expresion regular para localizar los procesos de la aplicacion."
    )

    parser.add_argument(
        "--rssi-command",
        default="",
        help="Comando opcional para consultar el RSSI."
    )

    parser.add_argument(
        "--app-stats",
        default="",
        help="Fichero JSON opcional con contadores de la aplicacion."
    )

    return parser.parse_args()


# --------------------------------------------------
# PROCESOS
# --------------------------------------------------

def obtener_procesos(pattern, pid_monitor):

    global PROCESOS_CACHE

    if not pattern:
        return []

    try:
        expresion = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return []

    encontrados = []
    pids_activos = set()

    for proceso in psutil.process_iter():

        try:

            if proceso.pid == pid_monitor:
                continue

            nombre = proceso.name()
            cmdline = " ".join(proceso.cmdline())

            texto = nombre + " " + cmdline

            if expresion.search(texto):

                pid = proceso.pid
                pids_activos.add(pid)

                if pid not in PROCESOS_CACHE:

                    PROCESOS_CACHE[pid] = proceso

                    # Primera lectura para inicializar cpu_percent.
                    proceso.cpu_percent(interval=None)

                encontrados.append(PROCESOS_CACHE[pid])

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess
        ):
            continue

    # Eliminar procesos que ya no existen o no coinciden.
    for pid in list(PROCESOS_CACHE.keys()):

        if pid not in pids_activos:
            del PROCESOS_CACHE[pid]

    return encontrados


def medir_procesos(pattern, pid_monitor):

    procesos = obtener_procesos(pattern, pid_monitor)

    cpu_total = 0.0
    ram_total = 0.0

    for proceso in procesos:

        try:

            cpu_total += proceso.cpu_percent(interval=None)

            ram_total += proceso.memory_info().rss

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess
        ):
            continue

    ram_mb = ram_total / (1024.0 * 1024.0)

    return cpu_total, ram_mb


# --------------------------------------------------
# RED
# --------------------------------------------------

def leer_interfaz(nombre):

    if not nombre or nombre.lower() == "none":
        return None

    try:

        interfaces = psutil.net_io_counters(pernic=True)

        if nombre in interfaces:
            return interfaces[nombre]

    except Exception:
        pass

    return None


def medir_ping(peer, interfaz):

    if not peer:
        return None

    comando = ["ping", "-n", "-c", "1", "-W", "1"]

    if interfaz and interfaz.lower() != "none":
        comando.extend(["-I", interfaz])

    comando.append(peer)

    try:

        salida = subprocess.check_output(
            comando,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=2.5
        )

        # Tratar expresamente latencias inferiores a 1 ms.
        if re.search(r"time<1\s*ms", salida):
            return 0.5

        coincidencia = re.search(
            r"time[=<]([\d.]+)\s*ms",
            salida
        )

        if coincidencia:
            return float(coincidencia.group(1))

    except Exception:
        pass

    return None


# --------------------------------------------------
# RADIO
# --------------------------------------------------

def medir_rssi(comando):

    if not comando:
        return None

    try:

        salida = subprocess.check_output(
            shlex.split(comando),
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=2.5
        )

        coincidencia = re.search(
            r"(-?\d+(?:\.\d+)?)\s*dBm",
            salida,
            re.IGNORECASE
        )

        if coincidencia:
            return float(coincidencia.group(1))

    except Exception:
        pass

    return None


# --------------------------------------------------
# TEMPERATURA
# --------------------------------------------------

def medir_temperatura():

    try:

        salida = subprocess.check_output(
            ["vcgencmd", "measure_temp"],
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=2
        )

        coincidencia = re.search(
            r"temp=([\d.]+)",
            salida
        )

        if coincidencia:
            return float(coincidencia.group(1))

    except Exception:
        pass

    return None


# --------------------------------------------------
# APLICACION
# --------------------------------------------------

def leer_app_stats(ruta):

    if not ruta:
        return {}

    try:

        with open(ruta, "r") as fichero:
            datos = json.load(fichero)

        return datos

    except Exception:
        return {}


# --------------------------------------------------
# ESTADISTICAS
# --------------------------------------------------

def estadisticas(valores):

    valores = [
        float(v) for v in valores
        if v is not None
    ]

    if not valores:
        return {}

    ordenados = sorted(valores)

    # Percentil 95 mediante el metodo de rango mas cercano.
    indice_p95 = int(math.ceil(0.95 * len(ordenados))) - 1

    resultado = {

        "media": statistics.mean(valores),

        "minimo": min(valores),

        "maximo": max(valores),

        "mediana": statistics.median(valores),

        "p95": ordenados[indice_p95]
    }

    if len(valores) > 1:

        resultado["desviacion_tipica"] = statistics.stdev(valores)

    else:

        resultado["desviacion_tipica"] = 0.0

    return resultado


def guardar_json(ruta, datos):

    with open(ruta, "w") as fichero:
        json.dump(datos, fichero, indent=4)


# --------------------------------------------------
# PROGRAMA PRINCIPAL
# --------------------------------------------------

def main():

    args = argumentos()

    if args.duracion <= 0 or args.intervalo <= 0:

        print("ERROR: duracion e intervalo deben ser positivos.")
        sys.exit(1)

    pid_monitor = os.getpid()

    ruta_csv = args.salida + ".csv"
    ruta_json = args.salida + ".json"

    # Inicializar medicion de CPU global.
    psutil.cpu_percent(interval=None)

    # Contadores iniciales de red.
    interfaz_anterior = leer_interfaz(args.interfaz)

    if interfaz_anterior is None and args.interfaz.lower() != "none":

        print("AVISO: no se puede consultar la interfaz:",
              args.interfaz)

    tiempo_red_anterior = time.monotonic()

    # Contadores iniciales de disco.
    disco_anterior = psutil.disk_io_counters()

    tiempo_disco_anterior = time.monotonic()

    # Contadores ICMP.
    ping_enviados = 0
    ping_recibidos = 0

    # Contadores de aplicacion.
    app_anterior = leer_app_stats(args.app_stats)

    app_bytes_rx_anterior = app_anterior.get("bytes_rx", 0)

    tiempo_app_anterior = time.monotonic()

    muestras = []
    valores = {}

    print("")
    print("==============================================")
    print(" MONITOR DE PRESTACIONES")
    print("==============================================")
    print("Protocolo: ", args.protocolo)
    print("Equipo:    ", args.equipo)
    print("Interfaz:  ", args.interfaz)
    print("Duracion:  ", args.duracion, "segundos")
    print("Intervalo: ", args.intervalo, "segundos")
    print("CSV:       ", ruta_csv)
    print("JSON:      ", ruta_json)
    print("==============================================")
    print("")

    inicio = time.monotonic()

    siguiente_muestra = inicio

    with open(ruta_csv, "w", newline="") as fichero_csv:

        escritor = csv.DictWriter(
            fichero_csv,
            fieldnames=COLUMNAS,
            delimiter=";"
        )

        escritor.writeheader()

        while True:

            ahora = time.monotonic()

            tiempo_transcurrido = ahora - inicio

            if tiempo_transcurrido >= args.duracion:
                break

            muestra = {}

            # --------------------------------------
            # 1. METRICAS GLOBALES DEL SISTEMA
            # --------------------------------------

            muestra["timestamp"] = time.strftime(
                "%d-%m-%Y %H:%M:%S"
            )

            muestra["protocolo"] = args.protocolo
            muestra["equipo"] = args.equipo

            muestra["cpu_global_pct"] = psutil.cpu_percent(
                interval=None
            )

            memoria = psutil.virtual_memory()

            muestra["ram_global_pct"] = memoria.percent

            muestra["ram_global_mb"] = (
                memoria.used / (1024.0 * 1024.0)
            )

            try:

                carga = os.getloadavg()

                muestra["carga_1min"] = carga[0]

            except Exception:

                muestra["carga_1min"] = None

            muestra["temperatura_c"] = medir_temperatura()

            # --------------------------------------
            # 2. METRICAS DE PROCESOS
            # --------------------------------------

            cpu_procesos, ram_procesos = medir_procesos(
                args.procesos_pattern,
                pid_monitor
            )

            muestra["cpu_procesos_pct"] = cpu_procesos

            muestra["ram_procesos_mb"] = ram_procesos

            # --------------------------------------
            # 3. TRAFICO DE RED
            # --------------------------------------

            tiempo_actual = time.monotonic()

            dt_red = tiempo_actual - tiempo_red_anterior

            interfaz_actual = leer_interfaz(args.interfaz)

            if (
                interfaz_actual is not None
                and interfaz_anterior is not None
                and dt_red > 0
            ):

                tx = (
                    interfaz_actual.bytes_sent
                    - interfaz_anterior.bytes_sent
                )

                rx = (
                    interfaz_actual.bytes_recv
                    - interfaz_anterior.bytes_recv
                )

                # Evitar valores negativos si se reinicia la interfaz.
                tx = max(0, tx)
                rx = max(0, rx)

                muestra["red_tx_bytes_s"] = tx / dt_red

                muestra["red_rx_bytes_s"] = rx / dt_red

                muestra["red_tx_mbps"] = (
                    tx * 8.0 / dt_red / 1000000.0
                )

                muestra["red_rx_mbps"] = (
                    rx * 8.0 / dt_red / 1000000.0
                )

                muestra["red_tx_bytes_total"] = (
                    interfaz_actual.bytes_sent
                )

                muestra["red_rx_bytes_total"] = (
                    interfaz_actual.bytes_recv
                )

            interfaz_anterior = interfaz_actual

            tiempo_red_anterior = tiempo_actual

            # --------------------------------------
            # 4. LATENCIA Y PERDIDA ICMP
            # --------------------------------------

            if args.peer:

                ping_enviados += 1

                latencia = medir_ping(
                    args.peer,
                    args.interfaz
                )

                if latencia is not None:

                    ping_recibidos += 1

                    muestra["latencia_icmp_ms"] = latencia

                muestra["perdida_icmp_pct"] = (
                    (ping_enviados - ping_recibidos)
                    * 100.0 / ping_enviados
                )

            # --------------------------------------
            # 5. RSSI
            # --------------------------------------

            muestra["rssi_dbm"] = medir_rssi(
                args.rssi_command
            )

            # --------------------------------------
            # 6. ESCRITURAS EN DISCO
            # --------------------------------------

            disco_actual = psutil.disk_io_counters()

            tiempo_actual = time.monotonic()

            dt_disco = tiempo_actual - tiempo_disco_anterior

            if (
                disco_actual is not None
                and disco_anterior is not None
                and dt_disco > 0
            ):

                delta_escritura = (
                    disco_actual.write_bytes
                    - disco_anterior.write_bytes
                )

                muestra["disco_escritura_bytes_s"] = (
                    max(0, delta_escritura) / dt_disco
                )

            disco_anterior = disco_actual

            tiempo_disco_anterior = tiempo_actual

            # --------------------------------------
            # 7. METRICAS DE LA APLICACION
            # --------------------------------------

            app_actual = leer_app_stats(args.app_stats)

            if app_actual:

                bytes_rx = app_actual.get("bytes_rx", 0)

                mensajes_tx = app_actual.get("mensajes_tx", 0)

                mensajes_rx = app_actual.get("mensajes_rx", 0)

                muestra["app_bytes_rx_total"] = bytes_rx

                tiempo_actual_app = time.monotonic()

                dt_app = tiempo_actual_app - tiempo_app_anterior

                if dt_app > 0:

                    delta_bytes = max(
                        0,
                        bytes_rx - app_bytes_rx_anterior
                    )

                    muestra["app_goodput_bytes_s"] = (
                        delta_bytes / dt_app
                    )

                muestra["app_mensajes_tx"] = mensajes_tx

                muestra["app_mensajes_rx"] = mensajes_rx

                if mensajes_tx > 0:

                    muestra["app_perdida_pct"] = (
                        max(0, mensajes_tx - mensajes_rx)
                        * 100.0 / mensajes_tx
                    )

                muestra["app_latencia_ms"] = app_actual.get(
                    "latencia_ms"
                )

                app_bytes_rx_anterior = bytes_rx

                tiempo_app_anterior = tiempo_actual_app

            # --------------------------------------
            # 8. GUARDAR MUESTRA
            # --------------------------------------

            fila = {}

            for columna in COLUMNAS:

                fila[columna] = muestra.get(columna)

            escritor.writerow(fila)

            muestras.append(muestra)

            # Acumular valores numericos para estadisticas.
            for clave, valor in muestra.items():

                if (
                    isinstance(valor, (int, float))
                    and not isinstance(valor, bool)
                ):

                    valores.setdefault(clave, []).append(valor)

            # El flush se hace para no perder los resultados
            # si el programa se interrumpe.
            fichero_csv.flush()

            # --------------------------------------
            # 9. MOSTRAR PROGRESO
            # --------------------------------------

            print(
                "[{0:6.1f}s] CPU: {1}% | RAM: {2}% | "
                "Temp: {3} | RTT: {4} | RX: {5}".format(

                    tiempo_transcurrido,

                    muestra.get("cpu_global_pct", "N/D"),

                    muestra.get("ram_global_pct", "N/D"),

                    muestra.get("temperatura_c", "N/D"),

                    muestra.get("latencia_icmp_ms", "N/D"),

                    muestra.get("red_rx_bytes_s", "N/D")
                )
            )

            # --------------------------------------
            # 10. CONTROL DEL INTERVALO
            # --------------------------------------

            siguiente_muestra += args.intervalo

            espera = siguiente_muestra - time.monotonic()

            if espera > 0:

                time.sleep(espera)

            else:

                # Si la muestra tarda demasiado, no acumular
                # retrasos para las siguientes iteraciones.
                siguiente_muestra = time.monotonic()

    # ----------------------------------------------
    # 11. RESUMEN FINAL
    # ----------------------------------------------

    resumen = {

        "protocolo": args.protocolo,

        "equipo": args.equipo,

        "duracion_s": args.duracion,

        "intervalo_s": args.intervalo,

        "interfaz": args.interfaz,

        "numero_muestras": len(muestras),

        "estadisticas": {}
    }

    for clave, lista in valores.items():

        resumen["estadisticas"][clave] = estadisticas(lista)

    resumen["ping"] = {

        "paquetes_enviados": ping_enviados,

        "paquetes_recibidos": ping_recibidos,

        "paquetes_perdidos": ping_enviados - ping_recibidos
    }

    guardar_json(ruta_json, resumen)

    print("")
    print("==============================================")
    print(" PRUEBA FINALIZADA")
    print("==============================================")
    print("Muestras: ", len(muestras))
    print("CSV:      ", ruta_csv)
    print("JSON:     ", ruta_json)
    print("==============================================")


if __name__ == "__main__":

    main()
