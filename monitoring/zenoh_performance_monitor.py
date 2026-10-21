#!/usr/bin/env python3
"""Benchmark de prestaciones de la comunicación entre el barco y la estación.

El benchmark se ejecuta en dos procesos: un emisor en el barco y un receptor
en la estación. El emisor publica sondas por Zenoh y el receptor devuelve un
acuse por otra expresión de clave. De esta forma se puede medir el RTT sin
suponer que los relojes de ambos equipos están sincronizados.

Emisor (barco)::

    python3 monitoring/zenoh_performance_monitor.py publisher

Receptor (estación)::

    python3 monitoring/zenoh_performance_monitor.py subscriber

Cada proceso guarda sus muestras periódicas en CSV y un resumen en JSON dentro
de ``monitoring/results``. Además de las métricas de Zenoh, se registran CPU,
RAM y tráfico de red del equipo que ejecuta el proceso.

La única dependencia adicional de este script es ``psutil``; Zenoh debe estar
instalado en el entorno que ejecute el benchmark.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import statistics
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - mensaje de instalación
    psutil = None  # type: ignore[assignment]

try:
    import zenoh
    # El repositorio también contiene una carpeta llamada ``zenoh``. Si el
    # paquete de Eclipse no está instalado, Python puede resolver esa carpeta
    # como un namespace package sin ``Config`` ni ``open``.
    if not hasattr(zenoh, "Config") or not hasattr(zenoh, "open"):
        raise ImportError("se ha encontrado la carpeta local zenoh, no eclipse-zenoh")
except ImportError:  # pragma: no cover - mensaje de instalación
    zenoh = None  # type: ignore[assignment]


ZENOH_PORT = 7447
DEFAULT_STATION_HOST = "10.42.0.1"
DEFAULT_LISTEN_ENDPOINT = f"udp/0.0.0.0:{ZENOH_PORT}"
DEFAULT_KEY_PREFIX = "barco/monitor/zenoh"
CSV_FIELDS = [
    "timestamp",
    "elapsed_s",
    "role",
    "sent_messages",
    "received_messages",
    "acknowledged_messages",
    "unacknowledged_messages",
    "lost_messages",
    "loss_percent",
    "gap_messages",
    "duplicate_messages",
    "sent_bytes",
    "received_bytes",
    "sent_messages_per_s",
    "received_messages_per_s",
    "sent_mbit_per_s",
    "received_mbit_per_s",
    "rtt_last_ms",
    "rtt_mean_ms",
    "rtt_p95_ms",
    "system_cpu_percent",
    "system_memory_percent",
    "process_cpu_percent",
    "process_rss_mb",
    "net_sent_mb",
    "net_recv_mb",
]


def _require_dependencies() -> None:
    missing: list[str] = []
    if psutil is None:
        missing.append(f"psutil ({sys.executable} -m pip install psutil)")
    if zenoh is None:
        missing.append(f"zenoh ({sys.executable} -m pip install eclipse-zenoh)")
    if missing:
        raise SystemExit("Faltan dependencias: " + ", ".join(missing))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
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


def _payload_bytes(sample: Any) -> bytes:
    """Convierte el payload de Zenoh a bytes en las versiones habituales."""
    payload = sample.payload
    to_bytes = getattr(payload, "to_bytes", None)
    if callable(to_bytes):
        return bytes(to_bytes())
    return payload.to_string().encode("utf-8")


def _configure_session(
    connect_endpoints: list[str], listen_endpoints: list[str]
) -> Any:
    config = zenoh.Config()  # type: ignore[union-attr]
    if connect_endpoints:
        config.insert_json5("connect/endpoints", json.dumps(connect_endpoints))
    if listen_endpoints:
        config.insert_json5("listen/endpoints", json.dumps(listen_endpoints))
    return zenoh.open(config)  # type: ignore[union-attr]


def _make_probe(run_id: str, sequence: int, payload_size: int) -> bytes:
    """Crea un mensaje JSON con un tamaño mínimo aproximado solicitado."""
    message = {
        "run_id": run_id,
        "seq": sequence,
        "created_ns": time.time_ns(),
        "padding": "",
    }
    encoded = json.dumps(message, separators=(",", ":")).encode("utf-8")
    # ``encoded`` ya contiene las dos comillas del campo vacío; al sustituirlo
    # por la cadena de relleno solo hay que compensar esas dos posiciones.
    padding_size = max(0, payload_size - len(encoded) + len(b'""'))
    message["padding"] = "x" * padding_size
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


def _parse_message(raw: bytes) -> dict[str, Any] | None:
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(message, dict):
        return None
    if not isinstance(message.get("run_id"), str) or not isinstance(message.get("seq"), int):
        return None
    return message


class RuntimeMetrics:
    """Métricas de recursos del proceso y del equipo local."""

    def __init__(self) -> None:
        self.process = psutil.Process()  # type: ignore[union-attr]
        self.process.cpu_percent(interval=None)
        self.network_start = psutil.net_io_counters()  # type: ignore[union-attr]

    def snapshot(self) -> dict[str, float | None]:
        memory = psutil.virtual_memory()  # type: ignore[union-attr]
        network = psutil.net_io_counters()  # type: ignore[union-attr]
        try:
            process_cpu = float(self.process.cpu_percent(interval=None))
            process_rss = self.process.memory_info().rss / (1024 * 1024)
        except (psutil.Error, OSError, PermissionError):  # type: ignore[union-attr]
            process_cpu = None
            process_rss = None
        return {
            "system_cpu_percent": float(psutil.cpu_percent(interval=None)),  # type: ignore[union-attr]
            "system_memory_percent": float(memory.percent),
            "process_cpu_percent": process_cpu,
            "process_rss_mb": round(process_rss, 2) if process_rss is not None else None,
            "net_sent_mb": round(
                (network.bytes_sent - self.network_start.bytes_sent) / (1024 * 1024), 3
            ),
            "net_recv_mb": round(
                (network.bytes_recv - self.network_start.bytes_recv) / (1024 * 1024), 3
            ),
        }


class PublisherStats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sent_messages = 0
        self.sent_bytes = 0
        self.acknowledged: set[int] = set()
        self.outstanding: dict[int, float] = {}
        self.rtts_ms: list[float] = []

    def sent(self, sequence: int, size: int, sent_at: float) -> None:
        with self.lock:
            self.sent_messages += 1
            self.sent_bytes += size
            self.outstanding[sequence] = sent_at

    def acknowledged_message(self, sequence: int, received_at: float) -> None:
        with self.lock:
            sent_at = self.outstanding.pop(sequence, None)
            if sent_at is None or sequence in self.acknowledged:
                return
            self.acknowledged.add(sequence)
            self.rtts_ms.append((received_at - sent_at) * 1000.0)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            rtts = list(self.rtts_ms)
            sent = self.sent_messages
            acked = len(self.acknowledged)
            sent_bytes = self.sent_bytes
            outstanding = len(self.outstanding)
        return {
            "sent_messages": sent,
            "received_messages": 0,
            "acknowledged_messages": acked,
            "unacknowledged_messages": outstanding,
            "lost_messages": max(0, sent - acked),
            "loss_percent": (max(0, sent - acked) / sent * 100.0) if sent else 0.0,
            "gap_messages": 0,
            "duplicate_messages": 0,
            "sent_bytes": sent_bytes,
            "received_bytes": 0,
            "rtt_last_ms": rtts[-1] if rtts else None,
            "rtt_mean_ms": statistics.fmean(rtts) if rtts else None,
            "rtt_p95_ms": _percentile(rtts, 95),
            "rtts_ms": rtts,
        }


class SubscriberStats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.received_messages = 0
        self.received_bytes = 0
        self.sent_messages = 0
        self.sent_bytes = 0
        self.gap_messages = 0
        self.duplicate_messages = 0
        self.last_sequence: dict[str, int] = {}

    def received(self, run_id: str, sequence: int, size: int) -> None:
        with self.lock:
            previous = self.last_sequence.get(run_id)
            if previous is not None:
                if sequence > previous + 1:
                    self.gap_messages += sequence - previous - 1
                elif sequence <= previous:
                    self.duplicate_messages += 1
            self.last_sequence[run_id] = max(sequence, previous or sequence)
            self.received_messages += 1
            self.received_bytes += size

    def ack_sent(self, size: int) -> None:
        with self.lock:
            self.sent_messages += 1
            self.sent_bytes += size

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "sent_messages": self.sent_messages,
                "received_messages": self.received_messages,
                "acknowledged_messages": 0,
                "unacknowledged_messages": 0,
                "lost_messages": self.gap_messages,
                "loss_percent": (
                    self.gap_messages / (self.received_messages + self.gap_messages) * 100.0
                    if self.received_messages + self.gap_messages
                    else 0.0
                ),
                "gap_messages": self.gap_messages,
                "duplicate_messages": self.duplicate_messages,
                "sent_bytes": self.sent_bytes,
                "received_bytes": self.received_bytes,
                "rtt_last_ms": None,
                "rtt_mean_ms": None,
                "rtt_p95_ms": None,
                "rtts_ms": [],
            }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mide RTT, pérdidas, caudal y recursos durante una comunicación Zenoh."
    )
    parser.add_argument("role", choices=("publisher", "subscriber"), help="Papel del proceso.")
    parser.add_argument(
        "--station-host",
        default=DEFAULT_STATION_HOST,
        help=f"IP de la estación para el emisor (por defecto: {DEFAULT_STATION_HOST}).",
    )
    parser.add_argument(
        "--key-prefix",
        default=DEFAULT_KEY_PREFIX,
        help=f"Prefijo de las claves (por defecto: {DEFAULT_KEY_PREFIX}).",
    )
    parser.add_argument("--duration", type=float, default=60.0, help="Duración en segundos (por defecto: 60).")
    parser.add_argument(
        "--interval",
        type=float,
        default=0.1,
        help="Tiempo entre sondas del emisor en segundos (por defecto: 0.1).",
    )
    parser.add_argument(
        "--payload-size",
        type=int,
        default=256,
        help="Tamaño mínimo aproximado de cada sonda en bytes (por defecto: 256).",
    )
    parser.add_argument(
        "--ack-timeout",
        type=float,
        default=2.0,
        help="Tiempo adicional para esperar acuses tras acabar el emisor (por defecto: 2).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV de salida; el resumen JSON se crea junto a él.",
    )
    return parser


def _default_output(role: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parent / "results" / f"zenoh_{role}_{stamp}.csv"


def _csv_value(value: Any) -> Any:
    return "" if value is None else value


def _write_record(writer: csv.DictWriter[str], record: dict[str, Any]) -> None:
    writer.writerow({field: _csv_value(record.get(field)) for field in CSV_FIELDS})


def _build_record(
    role: str,
    started: float,
    stats: dict[str, Any],
    resources: dict[str, Any],
) -> dict[str, Any]:
    elapsed = max(0.0, time.monotonic() - started)
    sent_messages = int(stats["sent_messages"])
    received_messages = int(stats["received_messages"])
    return {
        "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_s": round(elapsed, 3),
        "role": role,
        **{key: value for key, value in stats.items() if key != "rtts_ms"},
        "sent_messages_per_s": sent_messages / elapsed if elapsed else 0.0,
        "received_messages_per_s": received_messages / elapsed if elapsed else 0.0,
        "sent_mbit_per_s": stats["sent_bytes"] * 8 / elapsed / 1_000_000 if elapsed else 0.0,
        "received_mbit_per_s": stats["received_bytes"] * 8 / elapsed / 1_000_000 if elapsed else 0.0,
        **resources,
    }


def _run_publisher(args: argparse.Namespace, output: Path, summary_path: Path) -> None:
    connect_endpoints = [f"udp/{args.station_host}:{ZENOH_PORT}"]
    session = _configure_session(connect_endpoints, [])
    probe_key = f"{args.key_prefix.rstrip('/')}/probe"
    ack_key = f"{args.key_prefix.rstrip('/')}/ack"
    stats = PublisherStats()
    resources = RuntimeMetrics()
    run_id = uuid.uuid4().hex

    def on_ack(sample: Any) -> None:
        message = _parse_message(_payload_bytes(sample))
        if message is not None and message["run_id"] == run_id:
            stats.acknowledged_message(message["seq"], time.monotonic())

    subscriber = session.declare_subscriber(ack_key, on_ack)
    publisher = session.declare_publisher(probe_key)
    records: list[dict[str, Any]] = []
    started = time.monotonic()
    next_send = started
    sequence = 0
    print(f"[ZENOH] Emisor publicando en '{probe_key}' y esperando acuses en '{ack_key}'.")
    print(f"[INFO] run_id={run_id}; duración={args.duration:.1f}s; intervalo={args.interval:.3f}s")

    try:
        with output.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            while time.monotonic() - started < args.duration:
                now = time.monotonic()
                if now >= next_send:
                    payload = _make_probe(run_id, sequence, args.payload_size)
                    sent_at = time.monotonic()
                    publisher.put(payload)
                    stats.sent(sequence, len(payload), sent_at)
                    sequence += 1
                    next_send += args.interval

                record = _build_record("publisher", started, stats.snapshot(), resources.snapshot())
                _write_record(writer, record)
                csv_file.flush()
                records.append(record)
                time.sleep(min(0.05, max(0.001, next_send - time.monotonic())))

            deadline = time.monotonic() + args.ack_timeout
            while time.monotonic() < deadline and stats.snapshot()["unacknowledged_messages"]:
                record = _build_record("publisher", started, stats.snapshot(), resources.snapshot())
                _write_record(writer, record)
                csv_file.flush()
                records.append(record)
                time.sleep(0.05)
            final_record = _build_record("publisher", started, stats.snapshot(), resources.snapshot())
            _write_record(writer, final_record)
            records.append(final_record)
    finally:
        subscriber.undeclare()
        publisher.undeclare()
        session.close()

    final_stats = stats.snapshot()
    _write_summary(
        summary_path,
        role="publisher",
        args=args,
        run_id=run_id,
        records=records,
        final_stats=final_stats,
        output=output,
    )
    print(
        f"[RESULTADO] Enviados: {final_stats['sent_messages']} | "
        f"acuses: {final_stats['acknowledged_messages']} | "
        f"pérdidas/pendientes: {final_stats['lost_messages']} | "
        f"RTT p95: {final_stats['rtt_p95_ms'] if final_stats['rtt_p95_ms'] is not None else 'n/d'} ms"
    )


def _run_subscriber(args: argparse.Namespace, output: Path, summary_path: Path) -> None:
    listen_endpoints = [DEFAULT_LISTEN_ENDPOINT]
    session = _configure_session([], listen_endpoints)
    probe_key = f"{args.key_prefix.rstrip('/')}/probe"
    ack_key = f"{args.key_prefix.rstrip('/')}/ack"
    stats = SubscriberStats()
    resources = RuntimeMetrics()

    def on_probe(sample: Any) -> None:
        raw = _payload_bytes(sample)
        message = _parse_message(raw)
        if message is None:
            return
        stats.received(message["run_id"], message["seq"], len(raw))
        ack = json.dumps(
            {"run_id": message["run_id"], "seq": message["seq"]},
            separators=(",", ":"),
        ).encode("utf-8")
        ack_publisher.put(ack)
        stats.ack_sent(len(ack))

    ack_publisher = session.declare_publisher(ack_key)
    subscriber = session.declare_subscriber(probe_key, on_probe)
    records: list[dict[str, Any]] = []
    started = time.monotonic()
    print(f"[ZENOH] Receptor escuchando en '{probe_key}' y respondiendo en '{ack_key}'.")
    print(f"[INFO] duración={args.duration:.1f}s; endpoints={', '.join(listen_endpoints)}")

    try:
        with output.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            while time.monotonic() - started < args.duration:
                record = _build_record("subscriber", started, stats.snapshot(), resources.snapshot())
                _write_record(writer, record)
                csv_file.flush()
                records.append(record)
                time.sleep(min(args.interval, 0.5))
            final_record = _build_record("subscriber", started, stats.snapshot(), resources.snapshot())
            _write_record(writer, final_record)
            records.append(final_record)
    finally:
        subscriber.undeclare()
        ack_publisher.undeclare()
        session.close()

    final_stats = stats.snapshot()
    _write_summary(
        summary_path,
        role="subscriber",
        args=args,
        run_id=None,
        records=records,
        final_stats=final_stats,
        output=output,
    )
    print(
        f"[RESULTADO] Recibidos: {final_stats['received_messages']} | "
        f"huecos detectados: {final_stats['gap_messages']} | "
        f"duplicados: {final_stats['duplicate_messages']}"
    )


def _write_summary(
    summary_path: Path,
    role: str,
    args: argparse.Namespace,
    run_id: str | None,
    records: list[dict[str, Any]],
    final_stats: dict[str, Any],
    output: Path,
) -> None:
    def record_values(field: str) -> list[float]:
        return [float(record[field]) for record in records if record.get(field) is not None]

    summary = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "role": role,
        "run_id": run_id,
        "duration_s": round(records[-1]["elapsed_s"], 3) if records else 0.0,
        "samples": len(records),
        "interval_s": args.interval,
        "payload_size_requested": args.payload_size,
        "key_prefix": args.key_prefix,
        "connect_endpoints": (
            [f"udp/{args.station_host}:{ZENOH_PORT}"]
            if role == "publisher"
            else []
        ),
        "listen_endpoints": [DEFAULT_LISTEN_ENDPOINT],
        "totals": {
            key: value
            for key, value in final_stats.items()
            if key not in {"rtts_ms"}
        },
        "metrics": {
            "rtt_ms": _number_summary(final_stats.get("rtts_ms", [])),
            "sent_messages_per_s": _number_summary(record_values("sent_messages_per_s")),
            "received_messages_per_s": _number_summary(record_values("received_messages_per_s")),
            "sent_mbit_per_s": _number_summary(record_values("sent_mbit_per_s")),
            "received_mbit_per_s": _number_summary(record_values("received_mbit_per_s")),
            "system_cpu_percent": _number_summary(record_values("system_cpu_percent")),
            "system_memory_percent": _number_summary(record_values("system_memory_percent")),
            "process_cpu_percent": _number_summary(record_values("process_cpu_percent")),
            "process_rss_mb": _number_summary(record_values("process_rss_mb")),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path = output.with_name(f"{output.stem}_report.txt")

    def format_metric(label: str, values: dict[str, float | None], unit: str = "") -> str:
        def value(key: str) -> str:
            item = values.get(key)
            return "n/d" if item is None else f"{item:.2f}{unit}"

        return (
            f"{label}: media={value('mean')}, mínimo={value('min')}, "
            f"máximo={value('max')}, p95={value('p95')}"
        )

    report_lines = [
        "INFORME DE PRESTACIONES DE ZENOH",
        "=================================",
        f"Rol: {role}",
        f"Generado: {summary['generated_at']}",
        f"Duración: {summary['duration_s']} s",
        f"Muestras registradas: {summary['samples']}",
        f"Intervalo: {summary['interval_s']} s",
        f"Tamaño de payload solicitado: {summary['payload_size_requested']} bytes",
        "",
        "COMUNICACIÓN",
        "------------",
        format_metric("RTT", summary["metrics"]["rtt_ms"], " ms"),
        format_metric("Mensajes enviados por segundo", summary["metrics"]["sent_messages_per_s"]),
        format_metric("Mensajes recibidos por segundo", summary["metrics"]["received_messages_per_s"]),
        format_metric("Caudal enviado", summary["metrics"]["sent_mbit_per_s"], " Mbit/s"),
        format_metric("Caudal recibido", summary["metrics"]["received_mbit_per_s"], " Mbit/s"),
        f"Mensajes enviados: {final_stats['sent_messages']}",
        f"Mensajes recibidos: {final_stats['received_messages']}",
        f"Mensajes confirmados: {final_stats['acknowledged_messages']}",
        f"Mensajes perdidos: {final_stats['lost_messages']}",
        f"Pérdida estimada: {final_stats['loss_percent']:.2f}%",
        f"Duplicados: {final_stats['duplicate_messages']}",
        "",
        "RECURSOS DEL PROCESO Y SISTEMA",
        "------------------------------",
        format_metric("CPU del sistema", summary["metrics"]["system_cpu_percent"], "%"),
        format_metric("RAM del sistema", summary["metrics"]["system_memory_percent"], "%"),
        format_metric("CPU del proceso", summary["metrics"]["process_cpu_percent"], "%"),
        format_metric("RAM del proceso", summary["metrics"]["process_rss_mb"], " MB"),
        "",
        "ARCHIVOS DE DATOS",
        "-----------------",
        f"CSV: {output}",
        f"JSON: {summary_path}",
    ]
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"[INFO] Muestras guardadas en: {output}")
    print(f"[INFO] Resumen guardado en:    {summary_path}")
    print(f"[INFO] Informe de texto guardado en: {report_path}")


def main() -> int:
    args = _build_parser().parse_args()
    _require_dependencies()
    if args.duration <= 0:
        raise SystemExit("--duration debe ser mayor que cero.")
    if args.interval <= 0:
        raise SystemExit("--interval debe ser mayor que cero.")
    if args.payload_size < 1:
        raise SystemExit("--payload-size debe ser mayor que cero.")
    if args.ack_timeout < 0:
        raise SystemExit("--ack-timeout no puede ser negativo.")
    output = args.output or _default_output(args.role)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = output.with_name(f"{output.stem}_summary.json")

    if args.role == "publisher":
        _run_publisher(args, output, summary_path)
    else:
        _run_subscriber(args, output, summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
