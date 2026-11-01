import socket
import os
import json
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# ==========================================
# 1. SERVIDOR TCP - INICIALIZACIÓN
# ==========================================
def iniciar_servidor(ip: str, puerto: int) -> socket.socket | None:
    """
    Crea el socket servidor TCP, habilita la reutilización de puerto,
    se vincula a la IP/puerto y aguarda la conexión del barco.
    """
    try:
        servidor_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        servidor_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor_socket.bind((ip, puerto))
        servidor_socket.listen(1)
        print(f"[SERVIDOR] Escuchando en {ip}:{puerto}...")
        
        # Bloquea hasta que el barco ejecuta conectar_estacion()
        socket_cliente, direccion = servidor_socket.accept()
        print(f"[SERVIDOR] Conexión establecida desde: {direccion}")
        
        servidor_socket.close() # Cerramos la escucha tras aceptar al cliente
        return socket_cliente
    
    except OSError as e:
        print(f"[ERROR] No se pudo iniciar el servidor: {e}")
        return None

# ==========================================
# 2. RECEPCIÓN Y GUARDADO DEL FICHERO
# ==========================================
def recibir_fichero(socket_id: socket.socket, nombre_fichero_destino: str) -> bool:
    """
    Lee la cabecera de 8 bytes (tamaño) y el payload del socket TCP, 
    guardando el archivo JSON recibido en el disco local.
    """
    try:
        # 1. Leer tamaño del fichero (8 bytes, little-endian)
        bytes_tamano = socket_id.recv(8)
        if not bytes_tamano or len(bytes_tamano) < 8:
            print("[ERROR] Cabecera de tamaño incompleta.")
            return False
        
        tamano_fichero = int.from_bytes(bytes_tamano, byteorder='little')
        print(f"[RECEPCIÓN] Recibiendo fichero JSON ({tamano_fichero} bytes)...")

        # 2. Recepción del contenido por bloques
        with open(nombre_fichero_destino, "wb") as fichero:
            bytes_recibidos = 0
            while bytes_recibidos < tamano_fichero:
                bytes_pendientes = tamano_fichero - bytes_recibidos
                buffer_size = min(1024, bytes_pendientes)
                
                chunk = socket_id.recv(buffer_size)
                if not chunk:
                    print("[ERROR] Conexión cortada durante la recepción.")
                    return False
                
                fichero.write(chunk)
                bytes_recibidos += len(chunk)
                
        print(f"[ÉXITO] Guardado correctamente en '{nombre_fichero_destino}'.")
        return True

    except OSError as e:
        print(f"[ERROR] Error al recibir el fichero: {e}")
        return False

# ==========================================
# 3. VISUALIZACIÓN LEYENDO JSON LINES (\n)
# ==========================================
def graficar_datos_tiempo_real(nombre_fichero: str, max_puntos: int = 10) -> None:
    """
    Lee el archivo JSON Lines (un JSON por línea), extrae altitud y aceleraciones 
    usando el timestamp en el eje X y muestra únicamente las últimas 'max_puntos' muestras.
    """
    fig, (ax_alt, ax_acc) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    fig.canvas.manager.set_window_title('Estación de Control - Telemetría Barco')

    def actualizar(frame):
        if not os.path.exists(nombre_fichero):
            return

        paquetes = []
        with open(nombre_fichero, "r", encoding="utf-8") as f:
            for linea in f:
                linea_limpia = linea.strip()
                if linea_limpia:
                    try:
                        paquetes.append(json.loads(linea_limpia))
                    except json.JSONDecodeError:
                        # Ignora líneas corruptas o incompletas si se lee mientras se escribe
                        continue

        if not paquetes:
            return

        timestamps_labels = []
        altitudes = []
        acc_x, acc_y, acc_z = [], [], []

        for pkg in paquetes:
            ts = pkg.get("timestamp")
            
            if ts:
                hora_str = datetime.fromtimestamp(ts).strftime('%H:%M:%S')
            else:
                hora_str = "--:--:--"

            alt_data = pkg.get("altitude", {})
            motion_data = pkg.get("motion", {})
            
            timestamps_labels.append(hora_str)
            
            if alt_data.get("valid", False):
                altitudes.append(alt_data.get("altitude_m", 0.0))
            else:
                altitudes.append(None)

            accel = motion_data.get("accel", {})
            acc_x.append(accel.get("x", 0.0))
            acc_y.append(accel.get("y", 0.0))
            acc_z.append(accel.get("z", 0.0))

        # Aplicar ventana deslizante (últimas N muestras)
        timestamps_labels = timestamps_labels[-max_puntos:]
        altitudes = altitudes[-max_puntos:]
        acc_x = acc_x[-max_puntos:]
        acc_y = acc_y[-max_puntos:]
        acc_z = acc_z[-max_puntos:]

        # 1. Gráfica Superior: Altitud
        ax_alt.clear()
        ax_alt.plot(timestamps_labels, altitudes, marker='o', color='tab:blue', linewidth=2, label='Altitud (m)')
        ax_alt.set_title(f"Telemetría en Tiempo Real (Últimas {len(timestamps_labels)} muestras)")
        ax_alt.set_ylabel("Altitud (m)")
        ax_alt.grid(True, linestyle='--', alpha=0.6)
        ax_alt.legend(loc='upper left')

        # 2. Gráfica Inferior: Aceleraciones (X, Y, Z)
        ax_acc.clear()
        ax_acc.plot(timestamps_labels, acc_x, marker='.', label='Acc X', color='tab:red')
        ax_acc.plot(timestamps_labels, acc_y, marker='.', label='Acc Y', color='tab:green')
        ax_acc.plot(timestamps_labels, acc_z, marker='.', label='Acc Z', color='tab:purple')
        ax_acc.set_xlabel("Tiempo (HH:MM:SS)")
        ax_acc.set_ylabel("Aceleración (m/s²)")
        ax_acc.grid(True, linestyle='--', alpha=0.6)
        ax_acc.legend(loc='upper left')

        plt.xticks(rotation=25)

    ani = FuncAnimation(fig, actualizar, interval=500, cache_frame_data=False)
    plt.tight_layout()
    plt.show()

def cerrar_conexion(socket_id: socket.socket | None) -> None:
    if socket_id:
        socket_id.close()
        print("[SERVIDOR] Conexión cerrada.")

# ==========================================
# 4. EJECUCIÓN
# ==========================================
if __name__ == "__main__":
    SERVER_IP = "0.0.0.0"
    SERVER_PORT = 5005
    FICHERO_GUARDADO = "telemetria_recibida.json"

    socket_barco = iniciar_servidor(SERVER_IP, SERVER_PORT)
    
    if socket_barco:
        exito = recibir_fichero(socket_barco, FICHERO_GUARDADO)
        cerrar_conexion(socket_barco)
        
        if exito:
            print("[GRÁFICA] Desplegando interfaz gráfica...")
            graficar_datos_tiempo_real(FICHERO_GUARDADO)