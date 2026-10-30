import paho.mqtt.client as mqtt
import json
import base64
import struct

# Configuración del Broker MQTT de The Things Network (TTN)
# (Clúster de Europa por defecto: eu1.cloud.thethings.network)
BROKER_TTN = "eu1.cloud.thethings.network"
BROKER_PORT = 1883

# Credenciales proporcionadas por tu consola de TTN
APP_ID = "telemetria-titanic"       # Tu Application ID en TTN
API_KEY = "NNSXS.5QGTW4EOCEQWANKZT743OPLPWLEWNIPIGQAS2XI.VPNYHOL7NDVQFILTGQF3MLYUHJSEKIAPKCZ5EP5M3RZLKYW6AWWA" # Tu API Key con permisos de lectura (Link)

# Tópico estándar de TTN para escuchar los uplink (mensajes del dispositivo) de toda la aplicación
TOPIC_SUSCRIPCION = f"v3/{APP_ID}/devices/+/up"

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT TTN] Conectado exitosamente al broker de TTN ({BROKER_TTN})")
        client.subscribe(TOPIC_SUSCRIPCION)
        print(f"[MQTT TTN] Suscrito al tópico: {TOPIC_SUSCRIPCION}")
    else:
        print(f"[ERROR] Fallo de conexión con TTN, código de error: {rc}")

def on_message(client, userdata, msg):
    try:
        # TTN envía un JSON grande con metadatos y el payload en base64
        payload_raw = msg.payload.decode('utf-8')
        datos_ttn = json.loads(payload_raw)
        
        # Extraer información útil del paquete de TTN
        device_id = datos_ttn.get("end_device_ids", {}).get("device_id", "desconocido")
        gateway_info = datos_ttn.get("uplink_message", {}).get("rx_metadata", [{}])[0]
        rssi = gateway_info.get("rssi", "N/A")
        
        # El payload real que mandó el barco suele venir en 'uplink_message.frm_payload' codificado en Base64
        frm_payload_b64 = datos_ttn.get("uplink_message", {}).get("frm_payload")
        
        if frm_payload_b64:
            # Decodificar de Base64 a bytes binarios
            bytes_recibidos = base64.b64decode(frm_payload_b64)
            
            # Desempaquetar los 4 floats (!ffff -> altitud, acel_x, acel_y, acel_z)
            if len(bytes_recibidos) == 16:
                altitud, ax, ay, az = struct.unpack('!ffff', bytes_recibidos)
                print(f"\n[DATOS RECIBIDOS DE {device_id}] (RSSI: {rssi} dBm)")
                print(f" -> Altitud: {altitud:.2f} m")
                print(f" -> Aceleraciones (X, Y, Z): ({ax:.2f}, {ay:.2f}, {az:.2f})")
                
                # AQUÍ PUEDES CONECTAR TU LÓGICA DE GRÁFICAS (matplotlib) O GUARDAR EN FICHERO
            else:
                print(f"[AVISO] El payload no tiene el tamaño esperado: {len(bytes_recibidos)} bytes")
                
    except Exception as e:
        print(f"[ERROR] Procesando mensaje MQTT de TTN: {e}")

def iniciar_receptor_ttn():
    # Inicializar cliente MQTT con compatibilidad para Callback API v2
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    
    # Autenticación requerida por TTN
    cliente.username_pw_set(APP_ID, API_KEY)
    
    # Asignar callbacks
    cliente.on_connect = on_connect
    cliente.on_message = on_message
    
    print("[MQTT TTN] Conectando a la nube de The Things Network...")
    cliente.connect(BROKER_TTN, BROKER_PORT, keepalive=60)
    
    # Mantener el bucle escuchando indefinidamente
    try:
        cliente.loop_forever()
    except KeyboardInterrupt:
        print("\n[MQTT TTN] Desconectando receptor...")
        cliente.disconnect()

if __name__ == "__main__":
    iniciar_receptor_ttn()
