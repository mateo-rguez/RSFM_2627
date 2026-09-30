import socket
import os

def iniciar_servidor(ip, puerto):
    """Crea el socket servidor TCP y espera la conexión del barco."""
    try:
        servidor_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Permite reutilizar la dirección/puerto si se reinicia rápido el script
        servidor_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor_socket.bind((ip, puerto))
        servidor_socket.listen(1)
        print(f"Servidor escuchando en {ip}:{puerto}...")
        
        # Acepta la conexión entrante
        socket_cliente, direccion = servidor_socket.accept()
        print(f"Conexión establecida desde {direccion}")
        
        # Cerramos el socket del servidor para no aceptar más conexiones
        servidor_socket.close()
        return socket_cliente
    
    except OSError as e:
        print("ERROR AL INICIAR EL SERVIDOR:", e)
        return None

def recibir_fichero(socket_id, nombre_fichero_destino):
    """Recibe el fichero respetando la cabecera de 8 bytes y el buffer."""
    try:
        # 1. Leer exactamente los primeros 8 bytes para obtener el tamaño del fichero
        bytes_tamano = socket_id.recv(8)
        if not bytes_tamano or len(bytes_tamano) < 8:
            print("ERROR: No se recibió la cabecera completa del tamaño.")
            return False
        
        tamano_fichero = int.from_bytes(bytes_tamano, byteorder='little')
        print(f"Tamaño del fichero a recibir: {tamano_fichero} bytes")

        # 2. Abrir el fichero de destino para escritura binaria
        with open(nombre_fichero_destino, "wb") as fichero:
            bytes_recibidos = 0
            
            # 3. Bucle de recepción hasta completar el tamaño esperado
            while bytes_recibidos < tamano_fichero:
                # Calculamos cuánto falta para no leer de más si hay conexiones persistentes
                bytes_pendientes = tamano_fichero - bytes_recibidos
                buffer_size = min(1024, bytes_pendientes)
                
                chunk = socket_id.recv(buffer_size)
                if not chunk:
                    print("ERROR: La conexión se cerró inesperadamente durante la recepción.")
                    return False
                
                fichero.write(chunk)
                bytes_recibidos += len(chunk)
                
        print(f"Fichero recibido correctamente y guardado en '{nombre_fichero_destino}'.")
        return True

    except OSError as e:
        print("ERROR AL RECIBIR EL FICHERO:", e)
        return False

def cerrar_conexion(socket_id):
    """Cierra la conexión activa."""
    if socket_id:
        socket_id.close()

# Ejemplo de uso
if __name__ == "__main__":
    IP_ESTACION = "0.0.0.0"  # Escucha en todas las interfaces de red locales
    PUERTO = 5005
    FICHERO_GUARDADO = "telemetria_recibida.txt"

    socket_barco = iniciar_servidor(IP_ESTACION, PUERTO)
    
    if socket_barco:
        exito = recibir_fichero(socket_barco, FICHERO_GUARDADO)
        cerrar_conexion(socket_barco)