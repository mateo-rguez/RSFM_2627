import zenoh
import json
import time

KEY_EXPRESSION = "barco/telemetria"
FICHERO_DATOS = "datos_simulados.txt"

def enviar_telemetria():
    conf = zenoh.Config()
    # Usamos insert_json5 en lugar de insert_json
    conf.insert_json5("connect/endpoints", '["tcp/10.42.0.1:7447"]')
    
    print("[ZENOH] Abriendo sesión y conectando al receptor...")
    session = zenoh.open(conf)
    
    try:
        with open(FICHERO_DATOS, "r", encoding="utf-8") as f:
            for linea in f:
                linea_limpia = linea.strip()
                if not linea_limpia:
                    continue
                
                try:
                    paquete = json.loads(linea_limpia)
                except json.JSONDecodeError:
                    continue

                data_str = json.dumps(paquete)
                session.put(KEY_EXPRESSION, data_str)
                print(f"[EMISOR] Publicado en '{KEY_EXPRESSION}': {data_str}")
                
                time.sleep(1)
                
    except FileNotFoundError:
        print(f"[ERROR] No se encontró el fichero '{FICHERO_DATOS}'")
    finally:
        session.close()
        print("[ZENOH] Sesión cerrada.")

if __name__ == "__main__":
    enviar_telemetria()
