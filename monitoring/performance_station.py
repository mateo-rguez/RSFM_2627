#!/usr/bin/env python3
"""Receptor de métricas de prestaciones para la estación.

Escucha muestras JSON enviadas por datagramas UDP desde
``performance_monitor.py``. Puede recibir datos de uno o varios
monitores y los conserva en CSV y JSONL.

Ejemplo:

    python3 monitoring/performance_station.py
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import socketserver
import threading
from pathlib import Path
from typing import Any


MONITORING_PORT = 8765


FIELDS = [
    "received_at",
    "client_ip",
    "timestamp",
    "elapsed_s",
    "system_cpu_percent",
    "system_memory_percent",
    "system_memory_used_mb",
    "load_1m",
    "temperature_max_c",
    "net_sent_mb",
    "net_recv_mb",
    "disk_read_mb",
    "disk_write_mb",
    "sensor_cpu_percent",
    "sensor_rss_mb",
    "sensor_processes",
    "sensor_pids",
    "camera_cpu_percent",
    "camera_rss_mb",
    "camera_processes",
    "camera_pids",
]


class RecordWriter:
    """Escribe muestras recibidas de forma segura desde varios clientes."""

    def __init__(self, csv_path: Path, jsonl_path: Path) -> None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self.csv_file = csv_path.open("a", newline="", encoding="utf-8")
        self.jsonl_file = jsonl_path.open("a", encoding="utf-8")
        self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=FIELDS)
        if csv_path.stat().st_size == 0:
            self.csv_writer.writeheader()
            self.csv_file.flush()
        self.lock = threading.Lock()
        self.count = 0

    def write(self, record: dict[str, Any], client_ip: str) -> None:
        received_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        stored = dict(record)
        stored["received_at"] = received_at
        stored["client_ip"] = client_ip
        with self.lock:
            self.csv_writer.writerow({field: stored.get(field, "") for field in FIELDS})
            self.csv_file.flush()
            self.jsonl_file.write(json.dumps(stored, ensure_ascii=False) + "\n")
            self.jsonl_file.flush()
            self.count += 1

    def close(self) -> None:
        self.csv_file.close()
        self.jsonl_file.close()


class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    allow_reuse_address = True
    daemon_threads = True


class PerformanceHandler(socketserver.DatagramRequestHandler):
    def handle(self) -> None:
        writer: RecordWriter = self.server.writer  # type: ignore[attr-defined]
        client_ip = self.client_address[0]
        raw_data = self.rfile.read()
        try:
            record = json.loads(raw_data.decode("utf-8"))
            if not isinstance(record, dict):
                raise ValueError("la muestra no es un objeto JSON")
            writer.write(record, client_ip)
            print(
                f"[RECIBIDO] {client_ip} | "
                f"CPU {record.get('system_cpu_percent', '')}% | "
                f"RAM {record.get('system_memory_percent', '')}% | "
                f"muestras almacenadas: {writer.count}"
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            print(f"[AVISO] Muestra ignorada desde {client_ip}: {error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recibe y almacena las métricas de performance_monitor.py."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Interfaz de escucha (por defecto: 0.0.0.0).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV de salida; por defecto se guarda en monitoring/results/.",
    )
    parser.add_argument(
        "--jsonl-output",
        type=Path,
        default=None,
        help="Archivo JSONL de salida; se deriva del CSV si se omite.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.output or Path(__file__).resolve().parent / "results" / f"station_performance_{stamp}.csv"
    jsonl_path = args.jsonl_output or csv_path.with_suffix(".jsonl")
    writer = RecordWriter(csv_path, jsonl_path)
    server = ThreadedUDPServer((args.host, MONITORING_PORT), PerformanceHandler)
    server.writer = writer  # type: ignore[attr-defined]

    print(f"[INFO] Estación escuchando por UDP en {args.host}:{MONITORING_PORT}")
    print(f"[INFO] CSV:   {csv_path}")
    print(f"[INFO] JSONL: {jsonl_path}")
    print("[INFO] Ctrl+C para detener la recepción.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Recepción detenida por el usuario.")
    finally:
        server.server_close()
        writer.close()
        print(f"[INFO] Total de muestras almacenadas: {writer.count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
