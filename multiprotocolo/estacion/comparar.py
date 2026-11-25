"""Compara las pruebas de Wi-Fi HaLow, LoRa y BLE (hechas por turnos).

Lee los ficheros *_resumen.json que guarda estacion.py y genera:
  - una tabla en la consola,
  - comparativa.csv (para la memoria o una hoja de cálculo),
  - comparativa.png (gráficas de barras de las métricas comunes).

Uso:
    py comparar.py                       # el resumen más reciente de cada protocolo
    py comparar.py resultados\\halow_..._resumen.json resultados\\ble_..._resumen.json
"""

import argparse
import csv
import json
from pathlib import Path

from receptor.prestaciones import FILAS_COMUNES, FILAS_VIDEO, NOMBRES_PROTOCOLO, formatear

CARPETA = Path(__file__).resolve().parent / "resultados"
ORDEN = ("halow", "lora", "ble")
# Mismo color para el mismo protocolo en todas las gráficas (paleta validada).
COLORES = {"halow": "#2a78d6", "lora": "#eb6834", "ble": "#1baf7a"}

# Métricas que se dibujan: (sección, clave, título, unidad)
GRAFICAS = [
    ("comunes", "latencia_media_ms", "Latencia media", "ms"),
    ("comunes", "latencia_p95_ms", "Latencia percentil 95", "ms"),
    ("comunes", "jitter_ms", "Jitter", "ms"),
    ("comunes", "perdida_pct", "Tasa de pérdida", "%"),
    ("comunes", "disponibilidad_pct", "Disponibilidad", "%"),
    ("comunes", "tiempo_primer_dato_s", "Tiempo hasta el primer dato", "s"),
]


def cargar(ficheros):
    if not ficheros:
        # El más reciente de cada protocolo (el nombre lleva la fecha).
        ficheros = []
        for protocolo in ORDEN:
            candidatos = sorted(CARPETA.glob("{}_*_resumen.json".format(protocolo)))
            if candidatos:
                ficheros.append(candidatos[-1])
    resumenes = []
    for fichero in ficheros:
        with open(fichero, encoding="utf-8") as f:
            datos = json.load(f)
        datos["fichero"] = Path(fichero).name
        resumenes.append(datos)
    return resumenes


def tabla(resumenes):
    cabecera = ["Métrica"] + [NOMBRES_PROTOCOLO[r["protocolo"]] for r in resumenes]
    filas = []
    for seccion, definicion in (("comunes", FILAS_COMUNES), ("video", FILAS_VIDEO)):
        for clave, texto, formato in definicion:
            fila = [texto]
            for r in resumenes:
                datos = r.get(seccion) or {}
                fila.append(formatear(datos.get(clave), formato) if datos else "no aplica")
            filas.append(fila)
    filas.append(["Descripción de la prueba"] + [r.get("descripcion") or "—" for r in resumenes])
    filas.append(["Inicio de la prueba"] + [r.get("inicio", "—") for r in resumenes])
    return cabecera, filas


def dibujar(resumenes, destino):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figura, ejes = plt.subplots(2, 3, figsize=(12, 6.5), layout="constrained")
    nombres = [NOMBRES_PROTOCOLO[r["protocolo"]] for r in resumenes]
    for eje, (seccion, clave, titulo, unidad) in zip(ejes.flat, GRAFICAS):
        valores = [(r.get(seccion) or {}).get(clave) for r in resumenes]
        alturas = [0 if v is None else v for v in valores]
        barras = eje.bar(nombres, alturas, width=0.6,
                         color=[COLORES[r["protocolo"]] for r in resumenes],
                         edgecolor="white", linewidth=2)
        for barra, valor in zip(barras, valores):
            eje.annotate("—" if valor is None else "{:.1f}".format(valor),
                         (barra.get_x() + barra.get_width() / 2, barra.get_height()),
                         ha="center", va="bottom", fontsize=9, color="#3d3d3a",
                         xytext=(0, 3), textcoords="offset points")
        eje.set_title("{} ({})".format(titulo, unidad), fontsize=10)
        eje.grid(axis="y", color="#e4e4e0", lw=0.8)
        eje.set_axisbelow(True)
        for borde in ("top", "right"):
            eje.spines[borde].set_visible(False)
        eje.tick_params(labelsize=9, colors="#5f5e5a")
        eje.margins(y=0.15)
    figura.suptitle("Comparativa de protocolos — barco solar", fontsize=12)
    figura.savefig(destino, dpi=150)
    plt.close(figura)


def main():
    parser = argparse.ArgumentParser(description="Compara los resúmenes de las pruebas.")
    parser.add_argument("ficheros", nargs="*", help="Ficheros *_resumen.json (opcional).")
    args = parser.parse_args()

    resumenes = cargar(args.ficheros)
    if not resumenes:
        print("[ERROR] No hay resúmenes en '{}'. Haz antes alguna prueba con estacion.py.".format(CARPETA))
        return 1

    cabecera, filas = tabla(resumenes)
    anchos = [max(len(str(f[i])) for f in [cabecera] + filas) for i in range(len(cabecera))]
    for fila in [cabecera] + filas:
        print("  ".join(str(c).ljust(a) for c, a in zip(fila, anchos)))

    CARPETA.mkdir(exist_ok=True)
    with open(CARPETA / "comparativa.csv", "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f, delimiter=";").writerows([cabecera] + filas)
    dibujar(resumenes, CARPETA / "comparativa.png")
    print("\nFicheros usados: " + ", ".join(r["fichero"] for r in resumenes))
    print("Guardado: {} y {}".format(CARPETA / "comparativa.csv", CARPETA / "comparativa.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
