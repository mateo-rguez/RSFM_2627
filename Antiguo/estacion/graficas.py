import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from datetime import datetime

MAX_PUNTOS = 10


def graficar_datos(datos_recibidos, datos_lock):

    fig, (ax_alt, ax_acc, ax_gyro) = plt.subplots(
        3, 1,
        figsize=(9, 8),
        sharex=True
    )

    fig.canvas.manager.set_window_title(
        "Estación de Control - Telemetría"
    )

    def actualizar(frame):

        with datos_lock:
            paquetes = datos_recibidos[-MAX_PUNTOS:]

        if not paquetes:
            return

        tiempos = [
            datetime.strptime(p["timestamp"], "%d-%m-%Y %H:%M:%S")
            for p in paquetes
        ]

        altitudes = [
            p["altitude"]["altitude_m"]
            for p in paquetes
        ]

        aceleraciones = [
            p["motion"]["accel"]
            for p in paquetes
        ]

        giros = [
            p["motion"]["gyro"]
            for p in paquetes
        ]

        # Altitud
        ax_alt.clear()

        ax_alt.plot(
            tiempos,
            altitudes,
            "o-",
            label="Altitud"
        )

        ax_alt.set_ylabel("Altitud (m)")
        ax_alt.grid()
        ax_alt.legend()

        # Aceleración
        ax_acc.clear()

        ax_acc.plot(
            tiempos,
            [a["x"] for a in aceleraciones],
            ".-",
            label="X"
        )

        ax_acc.plot(
            tiempos,
            [a["y"] for a in aceleraciones],
            ".-",
            label="Y"
        )

        ax_acc.plot(
            tiempos,
            [a["z"] for a in aceleraciones],
            ".-",
            label="Z"
        )

        ax_acc.set_ylabel("Aceleración (m/s²)")
        ax_acc.grid()
        ax_acc.legend()

        # Giroscopio
        ax_gyro.clear()

        ax_gyro.plot(
            tiempos,
            [g["x"] for g in giros],
            ".-",
            label="X"
        )

        ax_gyro.plot(
            tiempos,
            [g["y"] for g in giros],
            ".-",
            label="Y"
        )

        ax_gyro.plot(
            tiempos,
            [g["z"] for g in giros],
            ".-",
            label="Z"
        )

        ax_gyro.set_ylabel("Giro")
        ax_gyro.set_xlabel("Tiempo")
        ax_gyro.grid()
        ax_gyro.legend()

        fig.autofmt_xdate()

    # Es importante guardar la animación en una variable
    # para evitar el warning de Matplotlib.
    ani = FuncAnimation(
        fig,
        actualizar,
        interval=500,
        cache_frame_data=False
    )

    plt.tight_layout()
    plt.show()