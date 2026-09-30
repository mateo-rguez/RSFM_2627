import socket
import os


def conectar_estacion(ip, puerto):

    try:
        socket_id = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_id.connect((ip, puerto))

        return socket_id

    except OSError as e:
        print("ERROR DE CONEXIÓN:", e)
        return None


def enviar_fichero(socket_id, nombre_fichero):

    try:
        fichero = open(nombre_fichero, "rb")
    except OSError as e:
        print("ERROR AL ABRIR EL FICHERO:", e)
        return False

    # Obtener el tamaño del fichero
    fichero.seek(0, os.SEEK_END)
    tamano_fichero = fichero.tell()
    fichero.seek(0, os.SEEK_SET)

    try:
        # Enviar el tamaño del fichero
        socket_id.sendall(
            tamano_fichero.to_bytes(8, byteorder="little")
        )

        # Enviar el contenido del fichero
        while True:

            buffer = fichero.read(1024)

            if not buffer:
                break

            socket_id.sendall(buffer)

    except OSError as e:
        print("ERROR AL ENVIAR EL FICHERO:", e)
        fichero.close()
        return False

    fichero.close()

    return True


def cerrar_conexion(socket_id):

    socket_id.close()

if __name__ == "__main__":
    IP_ESTACION = "127.0.0.1"  # IP local para pruebas en la misma máquina
    PUERTO = 5005
    FICHERO_A_ENVIAR = "datos_simulados.txt"

    print("Intentando conectar con la estación de control...")
    sock = conectar_estacion(IP_ESTACION, PUERTO)

    if sock:
        exito = enviar_fichero(sock, FICHERO_A_ENVIAR)
        if exito:
            print("¡Fichero enviado con éxito!")
        cerrar_conexion(sock)