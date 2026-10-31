import time
import random
import struct
import serial
from collector import TelemetryCollector

INTERVALO_ENVIO_S = 10.0  # En LoRaWAN se espacian más los envíos por el duty cycle (ej. cada 10s o 30s)

def empaquetar_datos(paquete):
    """
    Convierte el diccionario del colector en una estructura binaria compacta.
    Ejemplo: altitud (float), acel_x, acel_y, acel_z (floats).
    Ocupa muy pocos bytes, ideal para LoRaWAN.
    """
    altitud = paquete.get("altitud", 0.0)
    ax = paquete.get("acel_x", 0.0)
    ay = paquete.get("acel_y", 0.0)
    az = paquete.get("acel_z", 0.0)
    
    # '!ffff' = Network byte order, 4 floats (4 bytes cada uno = 16 bytes totales)
    return struct.pack('!ffff', altitud, ax, ay, az)

# Configurar el puerto serie según cómo lo tengas conectado a la Pi:
# - Por cable USB: normalmente '/dev/ttyUSB0' o '/dev/ttyACM0'
# - Por pines GPIO RX/TX: '/dev/ttyS0' o '/dev/ttyAMA0'
PUERTO_SERIE_LORA = '/dev/ttyUSB0'
BAUDRATE = 115200

def enviar_por_lorawan(payload_bytes):
    """
    Envía la carga útil en hex al módulo Heltec CubeCell mediante comandos AT por puerto serie.
    """
    hex_payload = payload_bytes.hex().upper()
    print(f"[LORA] Preparando envío de {len(payload_bytes)} bytes: {hex_payload}")
    
    try:
        with serial.Serial(PUERTO_SERIE_LORA, BAUDRATE, timeout=2) as ser:
            # Comando AT estándar de Heltec CubeCell para enviar datos (fport=1, unconfirmed)
            comando = f"AT+SendHex={hex_payload}\r\n"
            ser.write(comando.encode('utf-8'))
            
            # Leer respuesta del módulo
            respuesta = ser.read_until(b'\r\n').decode('utf-8', errors='ignore').strip()
            print(f"[LORA RESPUESTA] {respuesta}")
            
    except Exception as e:
        print(f"[ERROR LORA] Fallo al comunicarse con el módulo Heltec: {e}")
        
def iniciar_emisor_lora():
    colector = TelemetryCollector()
    print("[EMISOR LORA] Iniciando sistema de telemetría marítima vía LoRaWAN...")
    
    try:
        while True:
            # 1. Leer sensores
            paquete_dict = colector.collect()
            print(f"[SENSORES] Datos leídos: {paquete_dict}")
            
            # 2. Empaquetar en binario para LoRaWAN
            payload_binario = empaquetar_datos(paquete_dict)
            
            # 3. Transmitir por LoRa
            enviar_por_lorawan(payload_binario)
            
            # 4. Esperar el intervalo de envío (respetando restricciones de LoRaWAN)
            time.sleep(INTERVALO_ENVIO_S)
            
    except KeyboardInterrupt:
        print("\n[EMISOR LORA] Deteniendo transmisión...")
    finally:
        colector.close()
        print("[EMISOR LORA] Colector cerrado.")

if __name__ == "__main__":
    iniciar_emisor_lora()
