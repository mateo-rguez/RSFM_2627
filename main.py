```python
from comunicacion import (
    conectar_estacion,
    enviar_fichero,
    cerrar_conexion
)


SERVER_IP = "127.0.0.1"
SERVER_PORT = 8000


def main():

    socket_id = conectar_estacion(SERVER_IP, SERVER_PORT)

    if socket_id is None:
        return 1

    if not enviar_fichero(socket_id, "datos.txt"):
        cerrar_conexion(socket_id)
        return 1

    cerrar_conexion(socket_id)

    return 0


if __name__ == "__main__":
    main()
