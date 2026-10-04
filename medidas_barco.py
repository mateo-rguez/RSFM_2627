"""

Envía a la estación paquetes con muchas lecturas de los sensores y mide el
régimen de transmisión, la latencia, la pérdida de paquetes y la disponibilidad
del enlace

"""

import json
import socket
import statistics
import time

#  Código para importar TelemetryCollector

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "sensores"))

from collector import TelemetryCollector
from comunicacion import conectar_estacion, cerrar_conexion

#Parámetros para la prueba 
SERVER_IP = "10.42.0.1"
SERVER_PORT = 5005
MUESTRAS_POR_PAQUETE = 50   # lecturas de sensores en cada paquete (más muestras = paquete más grande)
PERIODO_S = 0.5             # segundos entre paquetes (1 como máximo)
DURACION_S = 30             # duración de la prueba en segundos (número entero)
TIMEOUT_S = 0.5             # si la confirmación (ACK) tarda más que esto, el paquete se da por perdido


def construir_trama(paquete):

    """Convierte el paquete en bytes: 8 bytes con el tamaño del JSON + el JSON."""

    cuerpo = json.dumps(paquete, separators=(",", ":")).encode("utf-8")
    return len(cuerpo).to_bytes(8, byteorder="little") + cuerpo


def recibir_exacto(socket_id, n):

    """Lee exactamente n bytes. Devuelve None si se cierra la conexión."""

    datos = b""
    while len(datos) < n:
        fragmento = socket_id.recv(n - len(datos))
        if not fragmento:
            return None
        datos += fragmento
    return datos


def esperar_ack(socket_id, seq):

    """Espera la confirmación del paquete número 'seq'. Devuelve True si llega a tiempo y False si no."""

    while True:
        try:
            ack = recibir_exacto(socket_id, 8)

        except socket.timeout:
            return False
        
        if ack is None:
            raise ConnectionError("La estación cerró la conexión")
        
        if int.from_bytes(ack, byteorder="little") == seq:
            return True
        
        # Si el número no coincide, es la confirmación tardía de un paquete anterior:
        # se ignora y se sigue esperando la que corresponde.


def mostrar_informe(enviados, rtts, bytes_ofrecidos, bytes_entregados, segundos_con_datos, duracion):

    
    perdidos = enviados - len(rtts)
    print("\n========== INFORME DEL BARCO ==========")
    print(f"Duración de la prueba   : {duracion:.1f} s")
    print(f"Paquetes enviados       : {enviados}")
    print(f"Paquetes confirmados    : {len(rtts)}")
    print(f"Paquetes perdidos       : {perdidos} ({100 * perdidos / enviados:.2f} %)")
    print(f"Régimen ofrecido        : {bytes_ofrecidos * 8 / duracion / 1000:.1f} kbit/s")
    print(f"Régimen entregado       : {bytes_entregados * 8 / duracion / 1000:.1f} kbit/s")
    if rtts:
        print(f"RTT medio / mín / máx   : {statistics.mean(rtts):.2f} / {min(rtts):.2f} / {max(rtts):.2f} ms")
        print(f"Latencia estimada (RTT/2): {statistics.mean(rtts) / 2:.2f} ms")
        print(f"Jitter (desv. típica RTT): {statistics.pstdev(rtts):.2f} ms")
    else:
        print("Ningún paquete fue confirmado: no hay datos de latencia.")
    print(f"Disponibilidad          : {100 * len(segundos_con_datos) / DURACION_S:.1f} %")
    print("=======================================\n")


def main():

    # Sensores en modo simulado
    colector = TelemetryCollector()
    colector.altitude_sensor.simulated = True
    colector.motion_sensor.simulated = True

    print("Conectando con la estación de control...")
    socket_id = conectar_estacion(SERVER_IP, SERVER_PORT)
    if socket_id is None:
        return
    socket_id.settimeout(TIMEOUT_S)

    enviados = 0
    rtts = []                  # RTT en ms de cada paquete confirmado
    bytes_ofrecidos = 0        # bytes de todos los paquetes generados
    bytes_entregados = 0       # bytes de los paquetes confirmados
    segundos_con_datos = set() # segundos de la prueba en los que se confirmó algún paquete

    print(f"Prueba de {DURACION_S} s: {MUESTRAS_POR_PAQUETE} muestras por paquete, un paquete cada {PERIODO_S} segundos")

    inicio = time.perf_counter() # cronómetro de alta precisión

    while time.perf_counter() - inicio < DURACION_S:
        t_ciclo = time.perf_counter()

        """Se construye el paquete con tantas lecturas como se estabezca en
        MUESTRAS_POR_PAQUETE"""
        paquete = {
            "seq": enviados,
            "muestras": [colector.collect() for _ in range(MUESTRAS_POR_PAQUETE)]
        }
        trama = construir_trama(paquete)
        enviados += 1
        bytes_ofrecidos += len(trama)


        """Se envia y se espera su confirmación"""
        try:
            t_envio = time.perf_counter()
            socket_id.sendall(trama)
            confirmado = esperar_ack(socket_id, paquete["seq"])
        except OSError as e:
            print(f"[ERROR] Se perdió la conexión: {e}")
            break

        """Se anota el resultado"""
        if confirmado:
            rtts.append((time.perf_counter() - t_envio) * 1000)
            bytes_entregados += len(trama)
            segundos_con_datos.add(int(t_envio - inicio))

        else:
            print(f"[PERDIDO] paquete {paquete['seq']}")

        """Se espera hasta que toque el siguiente paquete"""
        espera = PERIODO_S - (time.perf_counter() - t_ciclo)
        if espera > 0:
            time.sleep(espera)

    duracion = time.perf_counter() - inicio
    cerrar_conexion(socket_id)
    mostrar_informe(enviados, rtts, bytes_ofrecidos, bytes_entregados, segundos_con_datos, duracion)


if __name__ == "__main__":
    main()
