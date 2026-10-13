"""

Recibe los paquetes de prueba enviados desde el barco, confirma cada uno (ACK) y, al terminar la prueba,
muestra cuántos paquetes llegaron y a qué régimen.

"""

import json
import socket
import time

from recepcion import iniciar_servidor, cerrar_conexion

IP_ESTACION = "10.42.0.1"
PUERTO = 5005
ESPERA_MAX_S = 10    # si pasan 10 s sin recibir nada, se da la prueba por terminada


def recibir_exacto(socket_id, n):

    """Mismo funcionamiento que en medidas_barco.py"""

    datos = b""
    while len(datos) < n:
        fragmento = socket_id.recv(n - len(datos))
        if not fragmento:
            return None
        datos += fragmento
    return datos


def main():

    socket_barco = iniciar_servidor(IP_ESTACION, PUERTO)
    if socket_barco is None:
        return
    socket_barco.settimeout(ESPERA_MAX_S)

    inicio = time.perf_counter()    # la prueba empieza cuando el barco se conecta
    recibidos = 0
    bytes_recibidos = 0
    ultimo_seq = -1
    t_fin = inicio

    try:
        while True:

            # Cada trama está compuesta de 8 bytes para el tamaño más el JSON del paquete
            cabecera = recibir_exacto(socket_barco, 8)

            if cabecera is None:
                t_fin = time.perf_counter()  # el barco cerró la conexión: fin normal de la prueba
                break
            
            tamano = int.from_bytes(cabecera, byteorder="little")

            cuerpo = recibir_exacto(socket_barco, tamano)

            if cuerpo is None:
                break

            paquete = json.loads(cuerpo)

            # Se envía un ACK al barco
            socket_barco.sendall(paquete["seq"].to_bytes(8, byteorder="little"))

            recibidos += 1
            bytes_recibidos += 8 + tamano
            ultimo_seq = max(ultimo_seq, paquete["seq"])
            t_fin = time.perf_counter()
            
    except socket.timeout:
        print(f"[AVISO] Pasaron {ESPERA_MAX_S} s sin recibir datos; se da la prueba por terminada.")
    except OSError as e:
        print(f"[AVISO] Conexión interrumpida: {e}")

    cerrar_conexion(socket_barco)

    if recibidos == 0:
        print("No se recibió ningún paquete.")
        return

    duracion = t_fin - inicio
    huecos = ultimo_seq + 1 - recibidos
    print("\n========== INFORME DE LA ESTACIÓN ==========")
    print(f"Paquetes recibidos        : {recibidos}")
    print(f"Huecos en la numeración   : {huecos}")
    print(f"Bytes recibidos           : {bytes_recibidos}")
    print(f"Duración                  : {duracion:.1f} s")
    print(f"Régimen recibido          : {bytes_recibidos * 8 / duracion / 1000:.1f} kbit/s")
    print("============================================\n")


if __name__ == "__main__":
    main()
