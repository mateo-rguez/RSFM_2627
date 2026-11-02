import paho.mqtt.client as mqtt
import json
import base64
import struct
import os
import re
import csv
import time
import statistics
from datetime import datetime

# Configuración del broker MQTT de The Things Network (clúster de Europa)
BROKER_TTN = "eu1.cloud.thethings.network"
BROKER_PORT = 8883                       # 8883 = conexión cifrada (TLS). El 1883 enviaría la API key sin cifrar
APP_ID = "telemetria-titanic"            # Application ID en TTN (sin '@ttn')
API_KEY = os.environ.get("TTN_API_KEY")  # la clave se lee de una variable de entorno, no se escribe en el código

# En TTN (red comunitaria) el usuario y el topic llevan '@ttn' detrás del Application ID
USUARIO = f"{APP_ID}@ttn"
TOPIC_SUSCRIPCION = f"v3/{USUARIO}/devices/+/up"

# ---------------- Parámetros de la prueba (deben coincidir con el emisor) ----------------
INTERVALO_ENVIO_S = 15.0     # INTERVALO_ENVIO_S del emisor
TOTAL_ESPERADO = 100         # N_PAQUETES del emisor
K_CORTE = 3                  # paquetes perdidos seguidos que cuentan como "corte" del sistema
INACTIVIDAD_S = 5 * INTERVALO_ENVIO_S    # si no llega nada en este tiempo, la prueba se da por terminada
FICHERO_CSV = "resultados_lora.csv"

BYTES_APP = 22               # tamaño de los datos que envía el emisor
BYTES_CABECERA_LORAWAN = 13

registros = []               # una entrada por cada paquete recibido
vistos = set()               # números de secuencia ya recibidos
duplicados = 0
ultimo_rx = None             # hora (time.time) de la última recepción


def a_epoch(texto_iso):
    """Convierte la fecha de TTN ('2026-10-30T10:15:23.123456789Z') en segundos desde 1970."""
    texto = re.sub(r'(\.\d{1,6})\d*Z$', r'\1+00:00', texto_iso)   # TTN da hasta 9 decimales; Python admite 6
    texto = re.sub(r'Z$', '+00:00', texto)
    return datetime.fromisoformat(texto).timestamp()


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[ERROR] TTN rechazó la conexión: {reason_code}")
    else:
        client.subscribe(TOPIC_SUSCRIPCION)    # TTN solo admite QoS 0
        print(f"[MQTT TTN] Conectado. Suscrito a: {TOPIC_SUSCRIPCION}")


def on_message(client, userdata, msg):
    global ultimo_rx, duplicados
    t_pc = time.time()                          # hora de llegada al PC
    try:
        datos = json.loads(msg.payload.decode("utf-8"))
        up = datos.get("uplink_message", {})
        payload = base64.b64decode(up.get("frm_payload", ""))
        if len(payload) != BYTES_APP:
            print(f"[AVISO] Payload de {len(payload)} bytes (se esperaban {BYTES_APP}); se ignora")
            return

        seq, t_ms, altitud, ax, ay, az = struct.unpack('!HIffff', payload)
        if seq in vistos:
            duplicados += 1
            return
        vistos.add(seq)
        ultimo_rx = t_pc

        # Hora a la que TTN recibió el mensaje, y hora real de envío reconstruida a partir de los 32 bits bajos
        t_ttn = a_epoch(datos["received_at"])
        t_ttn_ms = int(t_ttn * 1000)
        t_envio = (t_ttn_ms - ((t_ttn_ms - t_ms) % 2 ** 32)) / 1000

        # Metadatos de la radio: se usa la pasarela que recibió con mejor RSSI
        pasarelas = up.get("rx_metadata") or [{}]
        gw = max(pasarelas, key=lambda g: g.get("rssi", -999))
        lora = up.get("settings", {}).get("data_rate", {}).get("lora", {})
        airtime = float(up.get("consumed_airtime", "0s").rstrip("s"))

        reg = {
            "seq": seq, "f_cnt": up.get("f_cnt"),
            "t_envio": t_envio, "t_ttn": t_ttn, "t_pc": t_pc,
            "lat_red_s": t_ttn - t_envio,        # emisor -> radio -> pasarela -> TTN
            "lat_nube_s": t_pc - t_ttn,          # TTN -> MQTT -> este PC
            "lat_total_s": t_pc - t_envio,
            "rssi": gw.get("rssi"), "snr": gw.get("snr"), "sf": lora.get("spreading_factor"),
            "airtime_s": airtime, "pasarelas": len(pasarelas),
            "altitud": altitud, "ax": ax, "ay": ay, "az": az,
        }
        registros.append(reg)
        print(f"[RX] paquete {seq}: latencia {reg['lat_total_s']:.2f} s | "
              f"RSSI {reg['rssi']} dBm, SNR {reg['snr']} dB, SF{reg['sf']} | altitud {altitud:.2f} m")
    except Exception as e:
        print(f"[ERROR] Procesando mensaje de TTN: {e}")


def paquetes_en_corte(total, k):
    """Cuenta los paquetes que pertenecen a rachas de k o más pérdidas seguidas."""
    en_corte, racha = 0, 0
    for seq in range(total):
        if seq in vistos:
            if racha >= k:
                en_corte += racha
            racha = 0
        else:
            racha += 1
    if racha >= k:
        en_corte += racha
    return en_corte


def mostrar_informe():
    if not registros:
        print("\n[INFORME] No se recibió ningún paquete.")
        return

    total = TOTAL_ESPERADO or (max(vistos) + 1)
    recibidos = len(registros)
    perdidos = total - recibidos
    duracion = total * INTERVALO_ENVIO_S                   # duración nominal de la prueba
    lat = [r["lat_total_s"] for r in registros]
    en_corte = paquetes_en_corte(total, K_CORTE)
    airtime_total = sum(r["airtime_s"] for r in registros)

    print("\n========== INFORME DE LA ESTACIÓN (LoRaWAN + MQTT) ==========")
    print(f"Paquetes recibidos        : {recibidos} de {total}")
    print(f"Paquetes perdidos         : {perdidos} ({100 * perdidos / total:.2f} %)")
    if duplicados:
        print(f"Paquetes duplicados       : {duplicados} (ignorados)")
    print(f"Régimen ofrecido (datos)  : {total * BYTES_APP * 8 / duracion:.1f} bit/s")
    print(f"Régimen entregado (datos) : {recibidos * BYTES_APP * 8 / duracion:.1f} bit/s "
          f"({recibidos * BYTES_APP * 8 / duracion / 1000:.3f} kbit/s)")
    print(f"Régimen con cabeceras LoRaWAN: {recibidos * (BYTES_APP + BYTES_CABECERA_LORAWAN) * 8 / duracion:.1f} bit/s")
    print(f"Latencia total media/mín/máx: {statistics.mean(lat):.2f} / {min(lat):.2f} / {max(lat):.2f} s")
    print(f"Latencia percentil 95     : {sorted(lat)[round(0.95 * (len(lat) - 1))]:.2f} s")
    if len(lat) > 1:
        print(f"Jitter (desv. típica)     : {statistics.pstdev(lat):.2f} s")
    print(f"  - tramo radio+pasarela+TTN media: {statistics.mean(r['lat_red_s'] for r in registros):.2f} s")
    print(f"  - tramo TTN -> PC (MQTT) media  : {statistics.mean(r['lat_nube_s'] for r in registros):.2f} s")
    if min(lat) < 0:
        print("[AVISO] Hay latencias negativas: los relojes de la Raspberry y del PC no están sincronizados.")
    rssis = [r["rssi"] for r in registros if r["rssi"] is not None]
    snrs = [r["snr"] for r in registros if r["snr"] is not None]
    if rssis:
        print(f"RSSI medio                : {statistics.mean(rssis):.1f} dBm")
    if snrs:
        print(f"SNR medio                 : {statistics.mean(snrs):.1f} dB")
    sfs = sorted({r["sf"] for r in registros if r["sf"] is not None})
    print(f"Factores de dispersión    : {', '.join('SF' + str(s) for s in sfs) or 'n/d'}")
    print(f"Tiempo en el aire total   : {airtime_total:.2f} s "
          f"(a este ritmo, {airtime_total / duracion * 86400:.0f} s al día; política TTN: 30 s)")
    print(f"Disponibilidad            : {100 * (1 - en_corte / total):.2f} % "
          f"(corte = {K_CORTE} o más paquetes perdidos seguidos)")
    print("=============================================================\n")

    with open(FICHERO_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(registros[0].keys()))
        w.writeheader()
        w.writerows(sorted(registros, key=lambda r: r["seq"]))
    print(f"[ESTACIÓN] Detalle por paquete guardado en '{FICHERO_CSV}'")


def iniciar_receptor_ttn():
    if not API_KEY:
        print("[ERROR] Falta la API key. Defínela antes de ejecutar, por ejemplo en PowerShell:")
        print('        $env:TTN_API_KEY="NNSXS.xxxx..."')
        return

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    cliente.username_pw_set(USUARIO, API_KEY)
    if BROKER_PORT == 8883:
        cliente.tls_set()                       # conexión cifrada con los certificados del sistema
    cliente.on_connect = on_connect
    cliente.on_message = on_message

    print("[MQTT TTN] Conectando a la nube de The Things Network...")
    try:
        cliente.connect(BROKER_TTN, BROKER_PORT, keepalive=60)
    except OSError as e:
        print(f"[ERROR] No se pudo conectar con {BROKER_TTN}:{BROKER_PORT}: {e}")
        return
    cliente.loop_start()

    try:
        while True:
            time.sleep(1)
            if ultimo_rx is not None:
                if time.time() - ultimo_rx > INACTIVIDAD_S:
                    print(f"[ESTACIÓN] {INACTIVIDAD_S:.0f} s sin recibir nada: fin de la prueba.")
                    break
                if TOTAL_ESPERADO and len(registros) >= TOTAL_ESPERADO:
                    print("[ESTACIÓN] Recibidos todos los paquetes esperados: fin de la prueba.")
                    break
    except KeyboardInterrupt:
        print("\n[ESTACIÓN] Prueba interrumpida.")
    finally:
        cliente.loop_stop()
        cliente.disconnect()
    mostrar_informe()


if __name__ == "__main__":
    iniciar_receptor_ttn()
