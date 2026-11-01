import paho.mqtt.client as mqtt
import json
import threading
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

BROKER_IP = "127.0.0.1"      # el broker MQTT corre en este mismo equipo (la estación)
BROKER_PORT = 1883
TOPIC = "barco/telemetria"
QOS = 1                      # 0 = como mucho una vez, 1 = al menos una vez, 2 = exactamente una vez
FICHERO_GUARDADO = "telemetria_recibida.json"

datos_recibidos = []
datos_lock = threading.Lock()

def on_connect(cliente, userdata, flags, reason_code, properties):
    """
    Función callback que se ejecuta cuando se establece la conexión con el broker.
    La suscripción se hace aquí para que se repita si la conexión se pierde y se recupera.
    """
    if reason_code.is_failure:
        print(f"[ERROR] El broker rechazó la conexión: {reason_code}")
    else:
        cliente.subscribe(TOPIC, qos=QOS)
        print(f"[MQTT] Suscrito a '{TOPIC}'. Esperando datos...")

def on_message(cliente, userdata, mensaje):
    """
    Función callback que se ejecuta automáticamente cada vez
    que llega un mensaje al topic 'barco/telemetria'.
    """
    try:
        payload_str = mensaje.payload.decode("utf-8")
        paquete = json.loads(payload_str)

        with datos_lock:
            datos_recibidos.append(paquete)

        # Guardar en disco a medida que llegan
        with open(FICHERO_GUARDADO, "a", encoding="utf-8") as f:
            json.dump(paquete, f)
            f.write("\n")

        print(f"[RECEPTOR] Muestra recibida por MQTT: {paquete.get('timestamp')}")
    except Exception as e:
        print(f"[ERROR RECEPCIÓN] {e}")

def graficar_datos(max_puntos=10):
    fig, (ax_alt, ax_acc) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    fig.canvas.manager.set_window_title('Estación de Control - Telemetría MQTT')

    def actualizar(frame):
        # Solo se necesitan las últimas muestras (ventana deslizante)
        with datos_lock:
            copia_datos = datos_recibidos[-max_puntos:]

        if not copia_datos:
            return

        tiempos = []
        altitudes = []
        acc_x, acc_y, acc_z = [], [], []

        for pkg in copia_datos:
            ts = pkg.get("timestamp")
            if not isinstance(ts, (int, float)):
                continue

            alt_data = pkg.get("altitude", {})
            motion_data = pkg.get("motion", {})

            # El eje horizontal usa la hora real de cada muestra, así los envíos
            # separados por intervalos distintos se ven a su distancia real
            tiempos.append(datetime.fromtimestamp(ts))

            if alt_data.get("valid", False):
                altitudes.append(alt_data.get("altitude_m", 0.0))
            else:
                altitudes.append(None)

            accel = motion_data.get("accel", {})
            acc_x.append(accel.get("x", 0.0))
            acc_y.append(accel.get("y", 0.0))
            acc_z.append(accel.get("z", 0.0))

        # 1. Altitud
        ax_alt.clear()
        ax_alt.plot(tiempos, altitudes, marker='o', color='tab:blue', linewidth=2, label='Altitud (m)')
        ax_alt.set_title(f"Telemetría MQTT en Tiempo Real (Últimas {len(tiempos)} muestras)")
        ax_alt.set_ylabel("Altitud (m)")
        ax_alt.grid(True, linestyle='--', alpha=0.6)
        ax_alt.legend(loc='upper left')

        # 2. Aceleraciones
        ax_acc.clear()
        ax_acc.plot(tiempos, acc_x, marker='.', label='Acc X', color='tab:red')
        ax_acc.plot(tiempos, acc_y, marker='.', label='Acc Y', color='tab:green')
        ax_acc.plot(tiempos, acc_z, marker='.', label='Acc Z', color='tab:purple')
        ax_acc.set_xlabel("Tiempo")
        ax_acc.set_ylabel("Aceleración (m/s²)")
        ax_acc.grid(True, linestyle='--', alpha=0.6)
        ax_acc.legend(loc='upper left')

        fig.autofmt_xdate()

    ani = FuncAnimation(fig, actualizar, interval=500, cache_frame_data=False)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    # Vaciar el fichero de guardado al iniciar
    open(FICHERO_GUARDADO, "w").close()

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    cliente.on_connect = on_connect
    cliente.on_message = on_message

    print("[MQTT] Conectando con el broker desde la estación de control...")
    try:
        cliente.connect(BROKER_IP, BROKER_PORT)
    except OSError as e:
        print(f"[ERROR] No se pudo conectar con el broker en {BROKER_IP}:{BROKER_PORT}: {e}")
        raise SystemExit(1)
    cliente.loop_start()    # hilo en segundo plano que gestiona la comunicación con el broker

    try:
        graficar_datos()
    except KeyboardInterrupt:
        print("\n[ESTACIÓN] Cerrando...")
    finally:
        cliente.loop_stop()
        cliente.disconnect()
        print("[MQTT] Conexión cerrada.")
