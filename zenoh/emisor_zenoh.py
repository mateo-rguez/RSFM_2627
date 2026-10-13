import zenoh
import json
import time

KEY_EXPRESSION = "barco/telemetria"
FICHERO_DATOS = "datos_simulados.txt"

def enviar_telemetria():
    # Configuración e inicio de sesión en Zenoh
    conf = zenoh.Config()
    print("[ZENOH] Abriendo sesión...")
    session = zenoh.open(conf)
    
    try:
        with open(FICHERO_DATOS, "r", encoding="utf-8") as f:
            for linea in f:
                linea_limpia = linea.strip()
                if not linea_limpia:
                    continue
                
                # Validar que es un JSON correcto
                try:
                    paquete = json.loads(linea_limpia)
                except json.JSONDecodeError:
                    continue

                # Publicar el mensaje en Zenoh
                data_str = json.dumps(paquete)
                session.put(KEY_EXPRESSION, data_str)
                print(f"[EMISOR] Publicado en '{KEY_EXPRESSION}': {data_str}")
                
                # Simular intervalo de envío entre muestras (ej. 1 segundo)
                time.sleep(1)
                
    except FileNotFoundError:
        print(f"[ERROR] No se encontró el fichero '{FICHERO_DATOS}'")
    finally:
        session.close()
        print("[ZENOH] Sesión cerrada.")

if __name__ == "__main__":
    enviar_telemetria()
