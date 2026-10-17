import time

from DDS.barco.collector import TelemetryCollector
from DDS.dds_publisher import TelemetryPublisher


PERIOD = 1.0


def main():
    collector = None
    publisher = None

    try:
        print("Intentando conectar con los sensores...")
        collector = TelemetryCollector()

        print("Inicializando publicador DDS...")
        publisher = TelemetryPublisher(domain_id=0)

        print("Publicando datos mediante DDS...")
        print("Topics:")
        print("  - boat/altitude")
        print("  - boat/accelerometer")
        print("  - boat/gyroscope")

        while True:
            start = time.monotonic()

            # Leer los sensores y generar el paquete.
            packet = collector.collect()

            # Publicar las tres muestras DDS.
            publisher.publish(packet)

            # Registrar la hora con milisegundos para distinguir
            # publicaciones realizadas dentro del mismo segundo.
            timestamp = (
                time.strftime("%d-%m-%Y %H:%M:%S")
                + f".{int(time.time() * 1000) % 1000:03d}"
            )

            #print(
            #    f"[pid={__import__('os').getpid()}] "
            #    f"[wall={time.time():.3f}] "
            #    f"[monotonic={time.monotonic():.3f}] "
            #    "Telemetría publicada correctamente",
            #    flush=True,
            #)
            print(f"[{timestamp}] [DDS] Telemetría publicada correctamente")

            # El monotonic lo utilizo xq antes se mostraban las muestras algunas desordenadas. Gracias a esto puedo ver que se publican en orden y no hay retrasos.
            # Elapsed time es el tiempo que tarda en ejecutarse el bucle, si es mayor a 1 segundo, significa que hay un retraso en la publicación de datos.

            # Mantener un periodo aproximado de un segundo.
            elapsed = time.monotonic() - start
            time.sleep(max(0.0, PERIOD - elapsed))

    except KeyboardInterrupt:
        print("\nFinalizando publicación DDS...")

    except Exception as e:
        print(f"\n[ERROR] Error en el publicador DDS: {e}")

    finally:
        if publisher is not None:
            close = getattr(publisher, "close", None)
            if callable(close):
                close()

        if collector is not None:
            collector.close()

    return 0


if __name__ == "__main__":
    main()