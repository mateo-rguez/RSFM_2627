#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Punto de entrada del receptor de telemetría MQTT para la estación de control."""

import queue
import signal
import sys
import threading

from receptor.almacenamiento import AlmacenamientoTelemetria
from receptor.configuracion import build_parser
from receptor.mqtt_receptor import ReceptorMQTT
from receptor.video import cargar_receptor_video


MAX_MUESTRAS_GRAFICA = 40


def main():
    args = build_parser().parse_args()
    estado_recepcion = {"ultima_telemetria": 0.0}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.no_video_window:
        args.video_output.parent.mkdir(parents=True, exist_ok=True)

    video_queue = None
    if not args.no_video:
        video_queue = queue.Queue(maxsize=1)

    almacenamiento = AlmacenamientoTelemetria(
        args.output,
        max_muestras=MAX_MUESTRAS_GRAFICA,
    )
    receptor_mqtt = ReceptorMQTT(
        args,
        almacenamiento,
        estado_recepcion,
        log_callback=print,
        video_queue=video_queue,
    )
    cliente = receptor_mqtt.cliente

    print("[MQTT] Conectando a {}:{}...".format(args.broker, args.port))
    try:
        receptor_mqtt.conectar()
    except OSError as error:
        print("[ERROR] No se pudo conectar con el broker: {}".format(error))
        return 1

    print("[RECEPTOR] Guardando muestras en '{}'".format(args.output))

    mqtt_loop_started = False
    video_stop = threading.Event()
    video_thread = None
    ventana = None
    resultado = 0

    try:
        video_receiver = None
        if not args.no_video:
            video_receiver = cargar_receptor_video()

        if args.dashboard:
            from PyQt5.QtCore import QTimer
            from PyQt5.QtWidgets import QApplication
            from receptor.dashboard import crear_dashboard

            app = QApplication(sys.argv)
            signal.signal(signal.SIGINT, lambda *_: app.quit())
            timer_sigint = QTimer()
            timer_sigint.timeout.connect(lambda: None)
            timer_sigint.start(250)

            ventana = crear_dashboard(
                cliente,
                video_stop,
                almacenamiento,
                estado_recepcion,
            )
            receptor_mqtt.establecer_log_callback(ventana.publicar_log)

            cliente.loop_start()
            mqtt_loop_started = True

            if video_receiver is not None:
                video_thread = threading.Thread(
                    target=video_receiver,
                    kwargs={
                        "stop_event": video_stop,
                        "show_window": False,
                        "mqtt_frame_queue": video_queue,
                        "record_video": False,
                        "output_path": args.video_output,
                        "frame_callback": ventana.recibir_fotograma,
                    },
                    daemon=True,
                )
                video_thread.start()

            ventana.show()
            resultado = app.exec()
        else:
            if video_receiver is None:
                cliente.loop_forever()
            else:
                cliente.loop_start()
                mqtt_loop_started = True
                video_receiver(
                    show_window=not args.no_video_window,
                    mqtt_frame_queue=video_queue,
                    record_video=args.no_video_window,
                    output_path=args.video_output,
                )

    except KeyboardInterrupt:
        print("\n[RECEPTOR] Deteniendo la recepción...")
    except Exception as error:
        print("[ERROR] Fallo en el receptor: {}".format(error))
        resultado = 1
    finally:
        video_stop.set()

        if video_thread is not None:
            video_thread.join(timeout=2.0)

        if mqtt_loop_started:
            cliente.loop_stop()

        receptor_mqtt.desconectar()

    print("[MQTT] Conexión cerrada.")
    return resultado


if __name__ == "__main__":
    raise SystemExit(main())
