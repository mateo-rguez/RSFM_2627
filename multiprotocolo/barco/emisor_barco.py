"""Emisor del barco (Raspberry Pi): un solo programa para los tres protocolos.

Lee los sensores, crea el paquete común de 30 bytes (formato_paquete.py) y lo
envía por el protocolo elegido. Con --video también envía la cámara (solo
Wi-Fi HaLow y BLE).

Ejemplos:
    python3 emisor_barco.py --protocolo halow --broker 10.42.0.1 --video
    python3 emisor_barco.py --protocolo ble --video
    python3 emisor_barco.py --protocolo lora
"""

import argparse
import asyncio
import time

from collector import TelemetryCollector
from formato_paquete import TAMANO, empaquetar_desde_colector


PUERTO_SENSORES = (
    "/dev/serial/by-id/"
    "usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_01D95FFA-if00-port0"
)
PUERTO_CUBECELL = (
    "/dev/serial/by-id/"
    "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"
)

# Intervalo entre paquetes por defecto. LoRa: TTN permite 30 s de tiempo en el
# aire al día y la CubeCell transmite como mucho una vez por minuto.
INTERVALO_POR_DEFECTO_S = {"halow": 1.0, "ble": 1.0, "lora": 70.0}
INTERVALO_ESTADO_ENLACE_S = 10.0


def crear_enlace(args):
    if args.protocolo == "halow":
        from enlace_halow import EnlaceHalow
        return EnlaceHalow(args.broker, args.puerto_mqtt, args.qos, args.interfaz_halow)
    if args.protocolo == "lora":
        from enlace_lora import EnlaceLora
        return EnlaceLora(args.puerto_cubecell)
    from enlace_ble import EnlaceBle
    return EnlaceBle()


async def leer_sensores(colector, muestra_fresca):
    """Lee una muestra de la placa (en otro hilo, para no bloquear el vídeo).

    Con intervalos largos (LoRa) se vacía antes el búfer del puerto serie,
    porque si no se leería una muestra de hace un minuto.
    """
    if muestra_fresca and getattr(colector, "ser", None) is not None:
        colector.ser.reset_input_buffer()
        await asyncio.sleep(1.5)  # tiempo hasta que llega una muestra nueva
    return await asyncio.to_thread(colector.collect)


async def tarea_telemetria(enlace, colector, intervalo):
    seq = 0
    no_aceptados = 0
    while True:
        inicio = time.monotonic()
        lectura = await leer_sensores(colector, muestra_fresca=intervalo >= 5)
        if not lectura:
            # El colector devuelve {} si lee una línea que no es JSON.
            print("[SENSORES] Lectura vacía, se reintenta.")
            await asyncio.sleep(0.5)
            continue

        simulado = not getattr(colector, "hardware_active", True)
        # La hora de envío se toma justo antes de entregar el paquete al enlace.
        paquete = empaquetar_desde_colector(seq, lectura, time.time(), simulado)
        aceptado = await enlace.enviar_telemetria(paquete)

        altitud = lectura.get("altitude") or {}
        if aceptado:
            print("[{}] seq={} enviado ({} B) | altitud {} (dist. {} cm) | movimiento {}{}".format(
                enlace.nombre, seq, TAMANO,
                "válida" if altitud.get("valid") else "NO válida",
                altitud.get("distance_cm"),
                "válido" if (lectura.get("motion") or {}).get("valid") else "NO válido",
                " | SIMULADO" if simulado else "",
            ), flush=True)
            # seq solo avanza si el enlace aceptó el paquete: así un hueco en
            # el receptor es una pérdida del enlace, no del emisor.
            seq += 1
        else:
            no_aceptados += 1
            print("[{}] Paquete no aceptado por el enlace (total: {}).".format(
                enlace.nombre, no_aceptados))

        espera = intervalo - (time.monotonic() - inicio)
        if espera > 0:
            await asyncio.sleep(espera)


async def tarea_video(enlace, camara):
    if not await asyncio.to_thread(camara.abrir):
        return  # sin cámara, la telemetría sigue
    try:
        while True:
            inicio = time.monotonic()
            datos = await asyncio.to_thread(camara.capturar)
            if datos is None:
                print("[WARN] Error leyendo fotograma.")
            else:
                await enlace.enviar_video(datos)
            espera = 1.0 / camara.fps - (time.monotonic() - inicio)
            if espera > 0:
                await asyncio.sleep(espera)
    finally:
        camara.cerrar()


async def tarea_estado_enlace(enlace):
    while True:
        await enlace.enviar_estado_enlace()
        await asyncio.sleep(INTERVALO_ESTADO_ENLACE_S)


async def principal(args):
    enlace = crear_enlace(args)
    colector = TelemetryCollector(port=args.puerto_sensores, baudrate=38400)
    if not getattr(colector, "hardware_active", True):
        print("[AVISO] Placa de sensores no encontrada: se envían datos SIMULADOS.")

    tareas = []
    try:
        if not await enlace.iniciar():
            return
        intervalo = args.intervalo or INTERVALO_POR_DEFECTO_S[args.protocolo]
        print("[EMISOR] Protocolo {} | un paquete cada {} s.".format(enlace.nombre, intervalo))

        tareas.append(asyncio.create_task(tarea_telemetria(enlace, colector, intervalo)))
        tareas.append(asyncio.create_task(tarea_estado_enlace(enlace)))
        if args.video:
            if enlace.admite_video:
                from camara import Camara
                camara = Camara(args.camara, args.ancho, args.alto, args.fps, args.calidad)
                tareas.append(asyncio.create_task(tarea_video(enlace, camara)))
            else:
                print("[AVISO] {} no admite vídeo: se envía solo telemetría.".format(enlace.nombre))

        await asyncio.gather(*tareas)
    finally:
        for tarea in tareas:
            tarea.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)
        await enlace.detener()
        colector.close()
        print("[EMISOR] Detenido.")


def main():
    parser = argparse.ArgumentParser(description="Emisor de telemetría del barco.")
    parser.add_argument("--protocolo", required=True, choices=("halow", "lora", "ble"))
    parser.add_argument("--intervalo", type=float, default=None,
                        help="Segundos entre paquetes (por defecto: 1 s; LoRa 70 s).")
    parser.add_argument("--video", action="store_true", help="Enviar también vídeo (HaLow y BLE).")
    parser.add_argument("--puerto-sensores", default=PUERTO_SENSORES)
    # Wi-Fi HaLow
    parser.add_argument("--broker", default="10.42.0.1", help="IP del PC con Mosquitto.")
    parser.add_argument("--puerto-mqtt", type=int, default=1883)
    parser.add_argument("--qos", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--interfaz-halow", default=None,
                        help="Interfaz de red HaLow (p. ej. wlan1) para enviar señal y reintentos.")
    # LoRa
    parser.add_argument("--puerto-cubecell", default=PUERTO_CUBECELL)
    # Vídeo: los mismos valores por defecto en HaLow y BLE para comparar en igualdad.
    parser.add_argument("--camara", type=int, default=0, help="Número de /dev/videoN.")
    parser.add_argument("--ancho", type=int, default=160)
    parser.add_argument("--alto", type=int, default=120)
    parser.add_argument("--fps", type=float, default=5)
    parser.add_argument("--calidad", type=int, default=30, help="Calidad JPEG (1-100).")
    args = parser.parse_args()

    try:
        asyncio.run(principal(args))
    except KeyboardInterrupt:
        print("\n[EMISOR] Detenido por el usuario.")


if __name__ == "__main__":
    main()
