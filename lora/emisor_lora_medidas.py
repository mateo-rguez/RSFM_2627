import math
import time
import struct
import serial
from collector import TelemetryCollector

# ---------------- Parámetros de la prueba (se cambian aquí) ----------------
PUERTO_SERIE_LORA = '/dev/ttyUSB0'   # igual que en emisor_lora.py
BAUDRATE = 115200
N_PAQUETES = 100                     # paquetes que se enviarán en la prueba
INTERVALO_ENVIO_S = 15.0             # segundos entre envíos (ver duty cycle más abajo)
SF_ESTIMADO = 7                      # factor de dispersión que se espera usar (solo para el aviso inicial)
FICHERO_LOG = "envios_lora.csv"

BYTES_CABECERA_LORAWAN = 13          # cabeceras y MIC que LoRaWAN añade a cada uplink


def valor(x):
    """Los datos no válidos del colector son None; se envían como NaN (número 'no válido')."""
    return float(x) if x is not None else float('nan')


def empaquetar_datos(seq, paquete):
    """
    Convierte el paquete del colector en 22 bytes:
      - seq:     número de secuencia del paquete (2 bytes) -> permite contar los paquetes perdidos
      - t_ms:    hora de envío en milisegundos desde 1970, solo los 32 bits bajos (4 bytes) -> permite medir la latencia
      - altitud, acel_x, acel_y, acel_z: 4 floats (16 bytes)
    '!' = orden de bytes de red; H = entero de 2 bytes; I = entero de 4 bytes; f = float de 4 bytes.
    """
    altitud = valor(paquete["altitude"]["altitude_m"])
    accel = paquete["motion"]["accel"]
    t_ms = int(time.time() * 1000) & 0xFFFFFFFF
    return struct.pack('!HIffff', seq, t_ms, altitud,
                       valor(accel["x"]), valor(accel["y"]), valor(accel["z"]))


def estimar_airtime_s(bytes_app, sf, bw=125000):
    """Tiempo en el aire aproximado de un uplink LoRaWAN (fórmula de Semtech; preámbulo de 8 símbolos, CR 4/5, CRC)."""
    pl = bytes_app + BYTES_CABECERA_LORAWAN
    t_simbolo = (2 ** sf) / bw
    de = 1 if t_simbolo > 0.016 else 0   # optimización de baja velocidad (SF11 y SF12)
    n_carga = 8 + max(math.ceil((8 * pl - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))) * 5, 0)
    return (12.25 + n_carga) * t_simbolo


def enviar_por_lorawan(ser, payload_bytes):
    """Envía la carga útil en hex al módulo Heltec CubeCell con el mismo comando AT que emisor_lora.py."""
    comando = f"AT+SendHex={payload_bytes.hex().upper()}\r\n"
    try:
        ser.write(comando.encode('utf-8'))
        return ser.read_until(b'\r\n').decode('utf-8', errors='ignore').strip()
    except Exception as e:
        return f"ERROR: {e}"


def iniciar_emisor_lora_medidas():
    colector = TelemetryCollector()

    # Aviso inicial: tiempo en el aire y límites de uso
    airtime = estimar_airtime_s(22, SF_ESTIMADO)
    print(f"[EMISOR LORA] 22 bytes de datos -> aprox. {airtime * 1000:.0f} ms en el aire con SF{SF_ESTIMADO}")
    print(f"[EMISOR LORA] Prueba completa: {N_PAQUETES * airtime:.1f} s de aire "
          f"(política de TTN: 30 s por dispositivo y día)")
    if INTERVALO_ENVIO_S < airtime * 99:
        print(f"[AVISO] Con duty cycle del 1 % el intervalo mínimo sería {airtime * 99:.1f} s")

    # El puerto serie se abre UNA vez para toda la prueba (abrirlo en cada envío puede reiniciar el módulo)
    try:
        ser = serial.Serial(PUERTO_SERIE_LORA, BAUDRATE, timeout=2)
    except Exception as e:
        print(f"[ERROR LORA] No se pudo abrir {PUERTO_SERIE_LORA}: {e}")
        colector.close()
        return

    print(f"[EMISOR LORA] Hora de la Raspberry: {time.strftime('%d-%m-%Y %H:%M:%S')} "
          f"(debe estar sincronizada con la del PC para medir la latencia)")
    print(f"[EMISOR LORA] Enviando {N_PAQUETES} paquetes, uno cada {INTERVALO_ENVIO_S} s (Ctrl+C para parar)")

    fallos = 0
    try:
        with open(FICHERO_LOG, "w", encoding="utf-8") as log:
            log.write("seq,t_envio_s,respuesta_modulo\n")
            for seq in range(N_PAQUETES):
                inicio = time.monotonic()

                # 1. Leer sensores  2. Empaquetar  3. Transmitir
                paquete = colector.collect()
                payload = empaquetar_datos(seq, paquete)
                t_envio = time.time()
                respuesta = enviar_por_lorawan(ser, payload)

                if "error" in respuesta.lower() or not respuesta:
                    fallos += 1
                print(f"[LORA] paquete {seq}: {payload.hex().upper()} -> módulo: {respuesta or '(sin respuesta)'}")
                log.write(f"{seq},{t_envio:.3f},{respuesta}\n")
                log.flush()

                # 4. Esperar hasta el siguiente envío
                time.sleep(max(0.0, INTERVALO_ENVIO_S - (time.monotonic() - inicio)))
    except KeyboardInterrupt:
        print("\n[EMISOR LORA] Prueba interrumpida.")
    finally:
        ser.close()
        colector.close()
        print(f"[EMISOR LORA] Fin. Respuestas de error o vacías del módulo: {fallos}. Detalle en '{FICHERO_LOG}'.")


if __name__ == "__main__":
    iniciar_emisor_lora_medidas()
