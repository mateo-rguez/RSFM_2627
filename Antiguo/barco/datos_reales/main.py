import time
import json
from Antiguo.barco.datos_reales.comunicacion import (
    conectar_estacion,
    enviar_fichero,
    cerrar_conexion
)
from Antiguo.barco.datos_reales.collector import TelemetryCollector

# Para ejecutar desde la carpeta barco: python3 main.py. Desde la raíz del proyecto se debe usar la siguiente línea de código:
# python3 -m barco.main


# SERVER_IP = "10.42.0.1"
SERVER_IP = "127.0.0.1"
SERVER_PORT = 5005
FICHERO_A_ENVIAR = "datos.json"
PERIOD=1.0


def main():
    print("Intentado conectar con los sensores")
    collector = TelemetryCollector()

    print("Intentando conectar con la estación de control...")

    socket_id = conectar_estacion(SERVER_IP, SERVER_PORT)


    if socket_id is None:
        return 1

    try:
        while True:
            paquete = collector.collect()
            with open(FICHERO_A_ENVIAR, "w",encoding="utf-8") as f:
                json.dump(paquete,f)
            
            if enviar_fichero(socket_id, FICHERO_A_ENVIAR):
                print("¡Fichero enviado con éxito!")
            else:
                print("Error al enviar el fichero")
                cerrar_conexion(socket_id)
                return 1
            time.sleep(PERIOD)
    except KeyboardInterrupt:
        print("\nTerminando envío")
    finally:
        cerrar_conexion(socket_id)
        collector.close()
    return 0


if __name__ == "__main__":
    main()
