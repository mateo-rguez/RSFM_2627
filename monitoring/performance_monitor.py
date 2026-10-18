#!/usr/bin/env python3
"""Monitor de prestaciones durante la ejecución simultánea de sensores y cámara.

El monitor no abre el puerto serie ni la cámara: observa los procesos que ya
están ejecutando esas tareas. Así no introduce lecturas adicionales ni consume
el flujo UDP de vídeo.

Ejemplos desde la raíz del proyecto:

    # La forma más precisa: indicar los PID de los procesos en ejecución.
    python3 monitoring/performance_monitor.py \
        --sensor-pid 1234 --camera-pid 1235 --duration 120

    # Alternativa: localizar procesos por parte de su línea de comandos.
    python3 monitoring/performance_monitor.py \
        --sensor-pattern collector.py --camera-pattern video_sender.py

Las muestras se guardan en CSV y el resumen estadístico en JSON. Con
``--station-host`` también se envía cada muestra por TCP a la estación. La
única dependencia externa es ``psutil`` (``python3 -m pip install psutil``).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import socket
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable

try:
    import psutil
except ImportError:  # pragma: no cover - mensaje de instalación
    psutil = None  # type: ignore[assignment]


DEFAULT_SENSOR_PATTERNS = (
    "collector.py",
    "dds_barco_main.py",
    "emisor_mqtt",
    "emisor_sensores_zenoh",
    "barco/datos_reales/main.py",
)
DEFAULT_CAMERA_PATTERNS = ("video_sender.py", "video_receiver.py")


class StationClient:
    """Envía muestras a la estación y se reconecta si el receptor reaparece."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.connection: socket.socket | None = None
        self.next_retry = 0.0

    def _connect(self) -> bool:
        if time.monotonic() < self.next_retry:
            return False
        try:
            self.connection = socket.create_connection((self.host, self.port), timeout=3)
            self.next_retry = 0.0
            return True
        except OSError as error:
            self.connection = None
            self.next_retry = time.monotonic() + 5.0
            print(f"[AVISO] No se puede conectar con la estación {self.host}:{self.port}: {error}")
            return False

    def send(self, record: dict[str, Any]) -> None:
        payload = (
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        for attempt in range(2):
            if self.connection is None and not self._connect():
                return
            try:
                assert self.connection is not None
                self.connection.sendall(payload)
                return
            except OSError as error:
                print(f"[AVISO] Conexión con la estación perdida: {error}")
                self.close()
                if attempt == 0:
                    continue
                return

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            except OSError:
                pass
            self.connection = None


def _require_psutil() -> None:
    if psutil is None:
        raise SystemExit(
            "Falta la dependencia 'psutil'. Instálala con: "
            f"{sys.executable} -m pip install psutil"
        )


def _command_line(info: dict[str, Any]) -> str:
    """Devuelve una línea comparable aunque cmdline no esté disponible."""
    command = info.get("cmdline") or []
    if isinstance(command, (list, tuple)):
        return " ".join(str(part) for part in command)
    return str(command)


def _matches(command: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, command, re.IGNORECASE) for pattern in patterns)


def find_processes(
    pids: Iterable[int], patterns: Iterable[str]
) -> dict[int, Any]:
    """Busca procesos por PID o por expresión regular en su línea de comandos."""
    requested_pids = {int(pid) for pid in pids}
    patterns = tuple(patterns)
    matches: dict[int, Any] = {}
    excluded_pids = {os.getpid()}
    try:
        excluded_pids.update(parent.pid for parent in psutil.Process().parents())
    except (psutil.Error, OSError, PermissionError):
        pass

    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            # Un patrón explícito puede aparecer en los argumentos del monitor
            # o de su shell lanzador; ninguno debe incluirse en los resultados.
            if process.pid in excluded_pids:
                continue
            info = process.info
            command = _command_line(info)
            selected_by_pid = process.pid in requested_pids
            selected_by_pattern = bool(patterns) and _matches(command, patterns)
            if selected_by_pid or selected_by_pattern:
                matches[process.pid] = process
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return matches


def _safe_call(function: Any, default: Any = None) -> Any:
    try:
        return function()
    except (psutil.Error, OSError, PermissionError):
        return default


def _temperature_max() -> float | None:
    """Obtiene la temperatura máxima disponible, si el sistema la expone."""
    temperatures = _safe_call(psutil.sensors_temperatures, {}) or {}
    values: list[float] = []
    for entries in temperatures.values():
        for entry in entries:
            current = getattr(entry, "current", None)
            if current is not None and math.isfinite(float(current)):
                values.append(float(current))
    return max(values) if values else None


def _process_metrics(processes: dict[int, Any]) -> tuple[float, float, int, str]:
    """Agrega CPU y memoria RSS de los procesos seleccionados."""
    cpu = 0.0
    rss = 0.0
    alive = 0
    names: list[str] = []

    for pid, process in list(processes.items()):
        try:
            cpu_value = process.cpu_percent(interval=None)
            memory = process.memory_info().rss
            cpu += float(cpu_value)
            rss += memory / (1024 * 1024)
            alive += 1
            names.append(f"{pid}:{process.name()}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            processes.pop(pid, None)

    return cpu, rss, alive, ";".join(names)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _number_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "min": None, "max": None, "p95": None}
    return {
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
        "p95": _percentile(values, 95),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Registra CPU, RAM, temperatura, red y disco del sistema, "
            "además de los procesos de sensores y cámara."
        )
    )
    parser.add_argument(
        "--sensor-pid",
        type=int,
        action="append",
        default=[],
        help="PID del proceso de sensores; se puede repetir.",
    )
    parser.add_argument(
        "--camera-pid",
        type=int,
        action="append",
        default=[],
        help="PID del proceso de cámara; se puede repetir.",
    )
    parser.add_argument(
        "--sensor-pattern",
        action="append",
        default=None,
        help="Expresión regular para localizar sensores por línea de comandos.",
    )
    parser.add_argument(
        "--camera-pattern",
        action="append",
        default=None,
        help="Expresión regular para localizar la cámara por línea de comandos.",
    )
    parser.add_argument(
        "--no-auto-discover",
        action="store_true",
        help="No usar los patrones predeterminados de sensores y cámara.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Duración en segundos; si se omite, el monitor funciona indefinidamente.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Intervalo entre muestras en segundos (por defecto: 1).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "CSV de salida. El resumen se crea junto a él con sufijo "
            "_summary.json."
        ),
    )
    parser.add_argument(
        "--station-host",
        help="IP o nombre de host de la estación que recibirá las muestras.",
    )
    parser.add_argument(
        "--station-port",
        type=int,
        default=8765,
        help="Puerto TCP de la estación (por defecto: 8765).",
    )
    return parser


def _default_output() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parent / "results" / f"performance_{stamp}.csv"


def _csv_value(value: Any) -> Any:
    return "" if value is None else value


def monitor(args: argparse.Namespace) -> tuple[Path, Path]:
    _require_psutil()

    if args.duration is not None and args.duration <= 0:
        raise SystemExit("--duration debe ser mayor que cero.")
    if args.interval <= 0:
        raise SystemExit("--interval debe ser mayor que cero.")
    if not 1 <= args.station_port <= 65535:
        raise SystemExit("--station-port debe estar entre 1 y 65535.")

    sensor_patterns = [] if args.no_auto_discover else list(DEFAULT_SENSOR_PATTERNS)
    camera_patterns = [] if args.no_auto_discover else list(DEFAULT_CAMERA_PATTERNS)
    if args.sensor_pattern is not None:
        sensor_patterns = args.sensor_pattern
    if args.camera_pattern is not None:
        camera_patterns = args.camera_pattern

    output = args.output or _default_output()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = output.with_name(f"{output.stem}_summary.json")

    sensors = find_processes(args.sensor_pid, sensor_patterns)
    cameras = find_processes(args.camera_pid, camera_patterns)
    if not sensors:
        print(
            "[AVISO] No se encontraron procesos de sensores al iniciar. "
            "Se seguirán buscando en cada muestra."
        )
    if not cameras:
        print(
            "[AVISO] No se encontraron procesos de cámara al iniciar. "
            "Se seguirán buscando en cada muestra."
        )

    # Primera llamada para que cpu_percent() devuelva el porcentaje del periodo
    # siguiente y no el tiempo acumulado desde el arranque del proceso.
    psutil.cpu_percent(interval=None)
    for process in {**sensors, **cameras}.values():
        _safe_call(lambda process=process: process.cpu_percent(interval=None))

    fields = [
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
    records: list[dict[str, Any]] = []
    station_client = (
        StationClient(args.station_host, args.station_port)
        if args.station_host
        else None
    )
    started = time.monotonic()
    network_start = psutil.net_io_counters()
    disk_start = psutil.disk_io_counters()

    duration_text = (
        "indefinidamente"
        if args.duration is None
        else f"durante {args.duration:.1f} s"
    )
    print(
        f"[INFO] Monitorizando {duration_text} "
        f"(muestras cada {args.interval:.2f} s). Ctrl+C para finalizar."
    )
    if station_client:
        print(f"[INFO] Envío de muestras a {args.station_host}:{args.station_port}")

    try:
        with output.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fields)
            writer.writeheader()

            while True:
                elapsed = time.monotonic() - started
                if args.duration is not None and elapsed >= args.duration and records:
                    break

                # Permite que las aplicaciones arranquen después del monitor y
                # también elimina procesos que hayan terminado.
                sensors = find_processes(args.sensor_pid, sensor_patterns)
                cameras = find_processes(args.camera_pid, camera_patterns)
                sensor_cpu, sensor_rss, sensor_count, sensor_names = _process_metrics(sensors)
                camera_cpu, camera_rss, camera_count, camera_names = _process_metrics(cameras)

                memory = psutil.virtual_memory()
                network = psutil.net_io_counters()
                disk = psutil.disk_io_counters()
                load = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
                record = {
                    "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "elapsed_s": round(elapsed, 3),
                    "system_cpu_percent": psutil.cpu_percent(interval=None),
                    "system_memory_percent": memory.percent,
                    "system_memory_used_mb": round(memory.used / (1024 * 1024), 2),
                    "load_1m": round(load, 3) if load is not None else None,
                    "temperature_max_c": _temperature_max(),
                    "net_sent_mb": round((network.bytes_sent - network_start.bytes_sent) / (1024 * 1024), 3),
                    "net_recv_mb": round((network.bytes_recv - network_start.bytes_recv) / (1024 * 1024), 3),
                    "disk_read_mb": round((disk.read_bytes - disk_start.read_bytes) / (1024 * 1024), 3) if disk and disk_start else None,
                    "disk_write_mb": round((disk.write_bytes - disk_start.write_bytes) / (1024 * 1024), 3) if disk and disk_start else None,
                    "sensor_cpu_percent": round(sensor_cpu, 2),
                    "sensor_rss_mb": round(sensor_rss, 2),
                    "sensor_processes": sensor_count,
                    "sensor_pids": sensor_names,
                    "camera_cpu_percent": round(camera_cpu, 2),
                    "camera_rss_mb": round(camera_rss, 2),
                    "camera_processes": camera_count,
                    "camera_pids": camera_names,
                }
                writer.writerow({field: _csv_value(record[field]) for field in fields})
                csv_file.flush()
                records.append(record)
                if station_client:
                    station_client.send(record)

                print(
                    f"[{record['elapsed_s']:6.1f}s] "
                    f"CPU {record['system_cpu_percent']:5.1f}% | "
                    f"RAM {record['system_memory_percent']:5.1f}% | "
                    f"sensores {sensor_count} ({sensor_cpu:5.1f}%) | "
                    f"cámara {camera_count} ({camera_cpu:5.1f}%)"
                )
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[INFO] Monitor detenido por el usuario; generando resumen parcial.")
    finally:
        if station_client:
            station_client.close()

    def values(field: str) -> list[float]:
        return [float(record[field]) for record in records if record[field] is not None]

    summary = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "duration_s": round(records[-1]["elapsed_s"], 3) if records else 0.0,
        "samples": len(records),
        "interval_s": args.interval,
        "sensor_pids": args.sensor_pid,
        "camera_pids": args.camera_pid,
        "sensor_patterns": sensor_patterns,
        "camera_patterns": camera_patterns,
        "metrics": {
            "system_cpu_percent": _number_summary(values("system_cpu_percent")),
            "system_memory_percent": _number_summary(values("system_memory_percent")),
            "system_memory_used_mb": _number_summary(values("system_memory_used_mb")),
            "temperature_max_c": _number_summary(values("temperature_max_c")),
            "sensor_cpu_percent": _number_summary(values("sensor_cpu_percent")),
            "sensor_rss_mb": _number_summary(values("sensor_rss_mb")),
            "camera_cpu_percent": _number_summary(values("camera_cpu_percent")),
            "camera_rss_mb": _number_summary(values("camera_rss_mb")),
        },
        "last_detected_processes": {
            "sensors": records[-1]["sensor_pids"] if records else "",
            "camera": records[-1]["camera_pids"] if records else "",
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[INFO] Muestras guardadas en: {output}")
    print(f"[INFO] Resumen guardado en:    {summary_path}")
    return output, summary_path


def main() -> int:
    args = build_parser().parse_args()
    monitor(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
