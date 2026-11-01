"""
Coordinador principal de telemetría.
Se encarga de la interfaz de comunicaciones serie con el hardware (Adafruit Metro),
consulta los módulos de altitud y movimiento, genera el paquete de datos unificado
y lo almacena en un archivo local (datos.txt).
"""

import time
import json
from Antiguo.barco.datos_reales.altitude_sensor import AltitudeSensor
from Antiguo.barco.datos_reales.motion_sensor import MotionSensor

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
        """Lee y decodifica una trama JSON recibida desde el Arduino."""
        if not self.hardware_active or not self.ser:
            return {}

        latest_data = {}

        try:
            while self.ser.in_waiting > 0:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()

                if not line:
                    return {}

                # Ignorar mensajes informativos del Arduino
                if not line.startswith("{"):
                    print(f"[ARDUINO] {line}")
                    return {}

                try:
                    data = json.loads(line)
                    latest_data = data
                
                except json.JSONDecodeError:
                    continue 

        except OSError as e:
            print(f"[WARN] Error de comunicación serie: {e}")
            self.hardware_active = False

        except Exception as e:
            print(f"[WARN] Error leyendo puerto serie: {e}")

        return latest_data

    def collect(self):
        """
        Genera el paquete completo de telemetría con timestamp.
        Listo para enviar por Wi-Fi o registrar en disco.
        """
        raw = self._read_serial_data()

        # Extraemos valores para cada módulo si existen
        raw_dist = None
        raw_accel = None
        raw_gyro = None

        if raw:
            ultrasonic = raw.get("ultrasonic", {})
            raw_dist = ultrasonic.get("distance_cm")

            raw_accel = raw.get("accel")
            raw_gyro = raw.get("gyro")

        return {
            "timestamp": time.strftime("%d-%m-%Y %H:%M:%S"),
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
#        while True:
        packet = collector.collect()

        # Mostrar por consola
        print(f"[{packet['timestamp']}] "
            f"Altitud: {packet['altitude']['altitude_m']} m (OK: {packet['altitude']['valid']}) | "
            f"Accel Z: {packet['motion']['accel']['z']} m/s² (OK: {packet['motion']['valid']})")

        # Modo 'w' sobrescribe el archivo en cada iteración guardando solo el último registro
        with open(output_filename, mode="w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2)

#            time.sleep(period)

    except KeyboardInterrupt:
        print(f"\nLectura finalizada. Último estado conservado en '{output_filename}'.")
    finally:
        collector.close()
