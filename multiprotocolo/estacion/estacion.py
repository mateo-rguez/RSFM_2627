"""Estación de tierra común para Wi-Fi HaLow, LoRa y BLE (pruebas por turnos).

Ejemplos (PowerShell):
    py estacion.py --protocolo halow
    py estacion.py --protocolo ble
    $env:TTN_MQTT_API_KEY = "NNSXS...."; py estacion.py --protocolo lora

Cada prueba guarda sus resultados en la carpeta "resultados". Después,
comparar.py junta los resúmenes de los tres protocolos.
"""

import os
import signal
import sys
import time

from receptor.centro import CentroDatos
from receptor.configuracion import TIEMPO_SIN_DATOS_S, VENTANA_DISPONIBILIDAD_S, build_parser
from receptor.prestaciones import NOMBRES_PROTOCOLO, Prestaciones, filas_resumen
from receptor.registro import Registro


def crear_adaptador(args, centro, con_video):
    if args.protocolo == "halow":
        from receptor.adaptador_halow import AdaptadorHalow
        return AdaptadorHalow(centro, args.broker, args.puerto, args.qos,
                              args.usuario, args.clave, con_video)
    if args.protocolo == "lora":
        from receptor.adaptador_lora import AdaptadorLora
        return AdaptadorLora(centro, args.ttn_broker, args.ttn_puerto,
                             args.ttn_usuario, os.getenv("TTN_MQTT_API_KEY"))
    from receptor.adaptador_ble import AdaptadorBle
    return AdaptadorBle(centro, args.ble_nombre, con_video)


def imprimir_resumen(resumen):
    comunes, video, especificas = filas_resumen(resumen)
    for titulo, filas in (("Comunes", comunes), ("Vídeo", video),
                          ("Exclusivas de " + NOMBRES_PROTOCOLO[resumen["protocolo"]], especificas)):
        if filas:
            print("\n  " + titulo)
            for nombre, valor in filas:
                print("    {:<46} {}".format(nombre, valor))


def main():
    args = build_parser().parse_args()
    if args.protocolo == "lora" and not os.getenv("TTN_MQTT_API_KEY"):
        print("[ERROR] Define la API key de TTN: $env:TTN_MQTT_API_KEY = \"NNSXS....\"")
        return 1

    con_video = args.protocolo != "lora" and not args.sin_video
    ventana = args.ventana or VENTANA_DISPONIBILIDAD_S[args.protocolo]
    prestaciones = Prestaciones(args.protocolo, ventana)
    registro = Registro(args.resultados, args.protocolo, args.descripcion)
    centro = CentroDatos(args.protocolo, prestaciones, registro)
    adaptador = crear_adaptador(args, centro, con_video)

    def guardar():
        try:
            registro.guardar_resumen(prestaciones.resumen())
        except OSError as error:
            centro.log("[ERROR] No se pudo guardar el resumen: {}".format(error))

    print("[ESTACIÓN] Protocolo {} | resultados en '{}'".format(
        NOMBRES_PROTOCOLO[args.protocolo], registro.carpeta))
    resultado = 0
    try:
        if args.sin_dashboard:
            adaptador.iniciar()
            fin = time.monotonic() + args.duracion if args.duracion else None
            ultimo_guardado = time.monotonic()
            while fin is None or time.monotonic() < fin:
                time.sleep(0.5)
                if time.monotonic() - ultimo_guardado >= 10:
                    guardar()
                    ultimo_guardado = time.monotonic()
        else:
            from PyQt5.QtCore import QTimer
            from PyQt5.QtWidgets import QApplication
            from receptor.dashboard import Dashboard

            app = QApplication(sys.argv)
            signal.signal(signal.SIGINT, lambda *_: app.quit())
            temporizador = QTimer()               # deja a Python atender Ctrl+C
            temporizador.timeout.connect(lambda: None)
            temporizador.start(250)

            ventana_qt = Dashboard(centro, adaptador, con_video,
                                   TIEMPO_SIN_DATOS_S[args.protocolo], al_guardar=guardar)
            adaptador.iniciar()
            ventana_qt.show()
            resultado = app.exec_()
    except KeyboardInterrupt:
        print("\n[ESTACIÓN] Deteniendo...")
    finally:
        adaptador.detener()
        guardar()

    print("\n[ESTACIÓN] Prestaciones finales ({}):".format(NOMBRES_PROTOCOLO[args.protocolo]))
    imprimir_resumen(prestaciones.resumen())
    print("\n[ESTACIÓN] Resumen guardado en '{}'".format(registro.fichero_resumen))
    return resultado


if __name__ == "__main__":
    raise SystemExit(main())
