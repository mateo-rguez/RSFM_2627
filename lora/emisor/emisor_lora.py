import time
import random
import struct
from collector import TelemetryCollector

# NOTA: Dependiendo de tu hardware LoRa (por ejemplo, un módulo conectado por UART con comandos AT 
# o una librería SPI como CircuitPython/LMIC), la función de envío real variará. 
# Aquí simulamos la interfaz de transmisión LoRaWAN.

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

def enviar_por_lorawan(payload_bytes):
    """
    Función que interactúa con tu módulo LoRa para transmitir los bytes.
    Aquí iría la llamada a tu librería de hardware (ej. puerto serie AT commands o SPI).
    """
    # SIMULACIÓN DE ENVÍO LORA:
    print(f"[LORA TRANSMISIÓN] Enviando {len(payload_bytes)} bytes al aire...")
    # Ejemplo real con módulo UART/AT: serial_port.write(b"AT+CMSGHEX=" + payload_bytes.hex().encode() + b"\r\n")

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