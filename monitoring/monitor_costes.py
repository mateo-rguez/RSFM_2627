#!/usr/bin/env python3
"""Monitor de indicadores operativos RSFM. No mide potencia eléctrica."""
import argparse
import csv
import datetime as dt
import json
import shutil
import subprocess
import time
from pathlib import Path

import psutil


def temperatura():
    try:
        r = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True,
                           text=True, timeout=2, check=True)
        return float(r.stdout.split('=')[1].split("'")[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        temps = psutil.sensors_temperatures()
        for group in temps.values():
            if group:
                return group[0].current
        return None


def main():
    p = argparse.ArgumentParser(description='Monitor RSFM: CPU, RAM, temperatura, red y disco')
    p.add_argument('escenario', choices=['E0', 'E1', 'E2', 'E3'])
    p.add_argument('--duracion', type=int, default=300, help='Duración en segundos')
    p.add_argument('--intervalo', type=float, default=1, help='Intervalo en segundos')
    p.add_argument('--salida', default='resultados_costes')
    args = p.parse_args()
    if args.duracion <= 0 or args.intervalo <= 0:
        p.error('Duración e intervalo deben ser positivos')
    carpeta = Path(args.salida)
    carpeta.mkdir(parents=True, exist_ok=True)
    etiqueta = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    prefijo = carpeta / f'{args.escenario}_{etiqueta}'
    filas = []
    net0 = psutil.net_io_counters()
    disk0 = psutil.disk_io_counters()
    prev_t = time.monotonic()
    psutil.cpu_percent(interval=None)
    inicio = time.monotonic()
    print(f'Midiendo {args.escenario} durante {args.duracion} s...')
    try:
        while time.monotonic() - inicio < args.duracion:
            time.sleep(args.intervalo)
            ahora = time.monotonic()
            net1 = psutil.net_io_counters()
            disk1 = psutil.disk_io_counters()
            delta = max(ahora - prev_t, 1e-9)
            filas.append({
                'segundo': round(ahora - inicio, 2),
                'cpu_pct': psutil.cpu_percent(interval=None),
                'ram_pct': psutil.virtual_memory().percent,
                'temperatura_c': temperatura(),
                'red_tx_bytes_s': round((net1.bytes_sent - net0.bytes_sent) / delta, 2),
                'red_rx_bytes_s': round((net1.bytes_recv - net0.bytes_recv) / delta, 2),
                'disco_escritura_bytes_s': round((disk1.write_bytes - disk0.write_bytes) / delta, 2) if disk0 and disk1 else None,
            })
            prev_t, net0, disk0 = ahora, net1, disk1
    except KeyboardInterrupt:
        print('Prueba interrumpida; guardando muestras disponibles.')
    if not filas:
        print('No se registraron muestras.')
        return
    with open(f'{prefijo}.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=filas[0].keys())
        writer.writeheader()
        writer.writerows(filas)
    estadisticas = {}
    for clave in filas[0]:
        if clave == 'segundo':
            continue
        datos = [x[clave] for x in filas if x[clave] is not None]
        estadisticas[clave] = {'media': round(sum(datos)/len(datos), 3), 'maximo': round(max(datos), 3)} if datos else None
    resumen = {'escenario': args.escenario, 'duracion_real_s': filas[-1]['segundo'],
               'muestras': len(filas), 'indicadores': estadisticas,
               'nota': 'No incluye medicion de potencia electrica ni costes de mantenimiento.'}
    with open(f'{prefijo}_resumen.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    print(f'Archivos: {prefijo}.csv y {prefijo}_resumen.json')


if __name__ == '__main__':
    main()
