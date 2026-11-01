import socket
import json
import threading

SERVER_IP = "0.0.0.0"
SERVER_PORT = 5005
FICHERO_GUARDADO = "telemetria_recibida.json"

datos_recibidos = []
datos_lock = threading.Lock()
ejecutando = True


def iniciar_servidor(ip: str, puerto: int) -> socket.socket | None:
    try:
        servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind((ip, puerto))
        servidor.listen(1)

        print(f"[SERVIDOR] Escuchando en {ip}:{puerto}...")

        cliente, direccion = servidor.accept()
        print(f"[SERVIDOR] Conexión desde {direccion}")

        servidor.close()

        return cliente

    except OSError as e:
        print(f"[ERROR] {e}")
        return None


def recibir_fichero(socket_id: socket.socket) -> dict | None:
    try:
        cabecera = socket_id.recv(8)

        if len(cabecera) < 8:
            return None

        tamano = int.from_bytes(cabecera, byteorder="little")

        datos = bytearray()

        while len(datos) < tamano:
            chunk = socket_id.recv(min(1024, tamano - len(datos)))

            if not chunk:
                return None

            datos.extend(chunk)

        paquete = json.loads(datos.decode("utf-8"))

        with open(FICHERO_GUARDADO, "a", encoding="utf-8") as fichero:
            json.dump(paquete, fichero)
            fichero.write("\n")

        return paquete

    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR] {e}")
        return None


def recibir_datos(socket_id: socket.socket):
    global ejecutando

    while ejecutando:

        paquete = recibir_fichero(socket_id)

        if paquete is None:
            ejecutando = False
            break

        with datos_lock:
            datos_recibidos.append(paquete)

        print(f"[RECEPCIÓN] Datos recibidos: {paquete}")


def cerrar_conexion(socket_id: socket.socket | None):
    if socket_id:
        socket_id.close()
        print("[SERVIDOR] Conexión cerrada.")


if __name__ == "__main__":

    open(FICHERO_GUARDADO, "w").close()

    socket_barco = iniciar_servidor(SERVER_IP, SERVER_PORT)

    if socket_barco is None:
        exit(1)

    hilo = threading.Thread(
        target=recibir_datos,
        args=(socket_barco,),
        daemon=True
    )

    hilo.start()

    try:
        from Antiguo.estacion.graficas import graficar_datos
        graficar_datos(datos_recibidos, datos_lock)

    except KeyboardInterrupt:
        print("\n[ESTACIÓN] Terminando...")

    finally:
        ejecutando = False
        cerrar_conexion(socket_barco)