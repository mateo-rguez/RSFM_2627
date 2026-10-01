from comunicacion import (
    conectar_estacion,
    enviar_fichero,
    cerrar_conexion
)

# Para ejecutar desde la carpeta barco: python3 main.py. Desde la raíz del proyecto se debe usar la siguiente línea de código:
# python3 -m barco.main



SERVER_IP = "127.0.0.1"
SERVER_PORT = 8000
FICHERO_A_ENVIAR = "datos_simulados.txt"


def main():

    print("Intentando conectar con la estación de control...")

    socket_id = conectar_estacion(SERVER_IP, SERVER_PORT)


    if socket_id is None:
        return 1

    if enviar_fichero(socket_id, FICHERO_A_ENVIAR):
        print("¡Fichero enviado con éxito!")
    else:
        print("Error al enviar el fichero")
        cerrar_conexion(socket_id)
        return 1

    cerrar_conexion(socket_id)

    return 0


if __name__ == "__main__":
    main()