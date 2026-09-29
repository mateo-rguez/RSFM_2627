import time
import math
import random

# Intento de importar las librerías oficiales de Emlid Navio2
# Enlace oficial: https://docs.emlid.com/navio2/configuring-raspberry-pi
# Si falla, se imprime un warn y se activa un modo simulación con datos de prueba
try:
    import navio.ms5611 as ms5611 # Medidor de altura (barómetro y termómetro)
    import navio.mpu9250 as mpu9250 # Medidor de inercia
    HARDWARE_AVAILABLE = True
except (ImportError, AttributeError):
    HARDWARE_AVAILABLE = False


class SensorCollector:
    def __init__(self, p0=1013.25):
        self.p0 = p0  # Presión de referencia a nivel del mar (hPa)
        self.hardware_mode = HARDWARE_AVAILABLE
        
        if self.hardware_mode:
            # Inicialización Barómetro MS5611
            self.baro = ms5611.MS5611()
            self.baro.initialize()
            
            # Inicialización IMU MPU9250
            self.imu = mpu9250.MPU9250()
            if not self.imu.testConnection():
                raise RuntimeError("No se detecta conexión con el chip MPU9250")
            self.imu.initialize()
            print("[INFO] Conectado a los sensores Navio2 físicos.")
        else:
            print("[WARN] Hardware no detectado. Ejecutando en MODO SIMULACIÓN.")

    def get_altitude_data(self):
        """Lectura y validación de datos de altitud (MS5611)"""
        if self.hardware_mode:
            self.baro.refreshPressure()
            time.sleep(0.01)
            self.baro.readPressure()
            
            self.baro.refreshTemperature()
            time.sleep(0.01)
            self.baro.readTemperature()
            
            self.baro.calculate()
            pressure = self.baro.readPressure()  # en hPa o mbar
            temp = self.baro.readTemperature()   # en °C
        else:
            # DATOS SIMULADOS con leve variación
            pressure = self.p0 + random.uniform(-0.5, 0.5)
            temp = 20.0 + random.uniform(-0.2, 0.2)

        # Cálculo de altitud barométrica
        altitude = 44330.0 * (1.0 - math.pow(pressure / self.p0, 0.1902949))

        # Criterio DoD: Validación de rangos plausibles
        # Rango operativo de presión en superficie marina: 800 - 1100 hPa
        is_valid = (800.0 <= pressure <= 1100.0) and (-10.0 <= altitude <= 500.0)

        return {
            "pressure_hpa": round(pressure, 2),
            "temperature_c": round(temp, 2),
            "altitude_m": round(altitude, 2),
            "valid": is_valid
        }

    def get_motion_data(self):
        """Lectura y validación de aceleración y rotación (MPU9250)"""
        if self.hardware_mode:
            # Lecturas reales: ax, ay, az en m/s^2; gx, gy, gz en rad/s
            ax, ay, az = self.imu.getAcceleration()
            gx, gy, gz = self.imu.getRotation()
        else:
            # DATOS SIMULADOS con leve variación Z cercano a 9.8 m/s^2, ruido en X e Y
            ax = random.uniform(-0.1, 0.1)
            ay = random.uniform(-0.1, 0.1)
            az = 9.81 + random.uniform(-0.1, 0.1)
            gx = random.uniform(-0.02, 0.02)
            gy = random.uniform(-0.02, 0.02)
            gz = random.uniform(-0.02, 0.02)

        # Criterio DoD: Magnitud de aceleración esperada cerca de reposo ~ 9.8 m/s^2
        total_accel = math.sqrt(ax**2 + ay**2 + az**2)
        is_valid = (5.0 <= total_accel <= 15.0)

        return {
            "accel": {"x": round(ax, 3), "y": round(ay, 3), "z": round(az, 3)},
            "gyro": {"x": round(gx, 3), "y": round(gy, 3), "z": round(gz, 3)},
            "valid": is_valid
        }

    def read_all(self):
        """Genera el paquete de medidas consolidado con timestamp"""
        return {
            "timestamp": time.time(),
            "altitude": self.get_altitude_data(),
            "motion": self.get_motion_data()
        }


if __name__ == "__main__":
    collector = SensorCollector()
    
    # Bucle periódico de prueba a 10 Hz (cada 100 ms)
    # Compatible con el requisito de latencia de telemetría (< 500 ms)
    try:
        while True:
            sample = collector.read_all()
            print(f"[{sample['timestamp']:.2f}] Altitud: {sample['altitude']['altitude_m']}m "
                  f"(OK: {sample['altitude']['valid']}) | "
                  f"Accel Z: {sample['motion']['accel']['z']} m/s² "
                  f"(OK: {sample['motion']['valid']})")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nLectura detenida por el usuario.")