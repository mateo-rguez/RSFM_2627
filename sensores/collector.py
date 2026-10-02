"""
Coordinador principal de telemetría.
Se encarga de la interfaz de comunicaciones serie con el hardware (Adafruit Metro),
consulta los módulos de altitud y movimiento, genera el paquete de datos unificado
y lo almacena en un archivo local (datos.txt).
"""

import time
import json
from altitude_sensor import AltitudeSensor
from motion_sensor import MotionSensor

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


class TelemetryCollector:
    """Gestiona la lectura coordinada de todos los sensores."""

    def __init__(self, port='/dev/ttyUSB0', baudrate=38400):
        self.ser = None
        self.hardware_active = False

        if SERIAL_AVAILABLE:
            try:
                self.ser = serial.Serial(port, baudrate, timeout=0.05)
                self.ser.reset_input_buffer()
                self.hardware_active = True
                print(f"[INFO] Conexión serie activa en {port}")
            except Exception as e:
                print(f"[WARN] No se detectó hardware en {port}: {e}. Iniciando modo SIMULACIÓN.")
        else:
            print("[WARN] Librería pyserial no disponible. Modo SIMULACIÓN activo.")

        # Instanciamos los módulos independientes
        self.altitude_sensor = AltitudeSensor(simulated=not self.hardware_active)
        self.motion_sensor = MotionSensor(simulated=not self.hardware_active)

    def _read_serial_data(self):
        """Lee la trama de texto más reciente recibida desde la placa Arduino/Metro."""
        raw_data = {}
        if self.hardware_active and self.ser and self.ser.in_waiting > 0:
            try:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()

                # Espera formato: DIST:24.5,AX:0.01,AY:0.02,AZ:9.80
                parts = line.split(',')
                for p in parts:
                    if ':' in p:
                        k, v = p.split(':', 1)
                        raw_data[k.strip()] = float(v.strip())
            except Exception:
                pass
        return raw_data

    def collect(self):
        """
        Genera el paquete completo de telemetría con timestamp.
        Listo para enviar por Wi-Fi o registrar en disco.
        """
        raw = self._read_serial_data()

        # Extraemos valores para cada módulo si existen
        raw_dist = raw.get("DIST")
        raw_accel = {"x": raw["AX"], "y": raw["AY"], "z": raw["AZ"]} if "AZ" in raw else None
        raw_gyro = {"x": raw["GX"], "y": raw["GY"], "z": raw["GZ"]} if "GZ" in raw else None

        return {
            "timestamp": round(time.time(), 3),
            "altitude": self.altitude_sensor.read(raw_distance_cm=raw_dist),
            "motion": self.motion_sensor.read(raw_accel=raw_accel, raw_gyro=raw_gyro)
        }

    def close(self):
        """Cierra el puerto de forma segura."""
        if self.ser and self.ser.is_open:
            self.ser.close()


if __name__ == "__main__":
    collector = TelemetryCollector()
    output_filename = "datos.json"

    # Periodo de actualización de datos (en segundos)
    period = 1.0

    print(f"Iniciando adquisición a ({1/period:.1f} Hz) Hz. Guardando en '{output_filename}'")

    try:
        while True:
            packet = collector.collect()

            # Mostrar por consola
            print(f"[{packet['timestamp']}] "
               f"Altitud: {packet['altitude']['altitude_m']} m (OK: {packet['altitude']['valid']}) | "
               f"Accel Z: {packet['motion']['accel']['z']} m/s² (OK: {packet['motion']['valid']})")

            # Modo 'w' sobrescribe el archivo en cada iteración guardando solo el último registro
            with open(output_filename, mode="w", encoding="utf-8") as f:
                json.dump(packet, f, indent=2)

            time.sleep(period)

    except KeyboardInterrupt:
        print(f"\nLectura finalizada. Último estado conservado en '{output_filename}'.")
    finally:
        collector.close()
