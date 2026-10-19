"""Limpieza del Excel de facturas de energía (Electricaribe, 2018) a un CSV unificado.

Cada hoja del Excel es un mes de facturación y su formato cambia a lo largo del año
(enero trae NIC y reparto IPS Universitaria/MiRed, abril pierde el NIC, agosto cambia
"intereses por mora" por "otros conceptos", etc.). En lugar de leer posiciones fijas,
el script busca las filas de encabezado ("SEDES", "Sede", "SEDES CERRADAS",
"ADICIONAL") y mapea cada columna por su nombre.

Uso:
    python limpieza.py                         # usa datos/CONSUMO DE ENERGIA 2018.xlsx
    python limpieza.py ruta.xlsx salida.csv
"""

from __future__ import annotations

import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

RAIZ = Path(__file__).parent
EXCEL_POR_DEFECTO = RAIZ / "datos" / "CONSUMO DE ENERGIA 2018.xlsx"
CSV_POR_DEFECTO = RAIZ / "datos" / "consumo_2018.csv"

MESES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

# Encabezados que abren una sección de la hoja y la sección que representan.
SECCIONES = {"SEDES": "habilitada", "SEDE": "habilitada", "SEDES CERRADAS": "cerrada", "ADICIONAL": "adicional"}

# Filas que marcan el final de la tabla (totales, observaciones, firmas).
FIN_DE_TABLA = ("TOTALES", "REVIS", "OBSERVACIONES", "ACLARACION")

# Nombres que cambian entre meses pero son la misma sede.
ALIAS = {
    "PASO Nuevo Esmeralda Lipaya": "PASO Esmeralda Lipaya",
}

COLUMNAS_CSV = [
    "mes", "mes_nombre", "seccion", "sede", "sitio", "tipo_sede", "direccion",
    "desde", "hasta", "dias", "kwh", "kwh_dia", "tarifa_factura", "tarifa_efectiva",
    "otros_cargos", "valor_cop", "tipo_lectura", "alertas",
]


def _normalizar_texto(valor) -> str:
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().upper()


def _numero(valor) -> float:
    """Convierte a número aceptando '353,75', '/', 'No emitida' y celdas vacías."""
    if valor is None or isinstance(valor, datetime):
        return np.nan
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace(" ", "")
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return np.nan


def _fecha(valor):
    if isinstance(valor, datetime):
        return pd.Timestamp(valor).normalize()
    if isinstance(valor, (int, float)) and 40000 < valor < 50000:  # serial de Excel
        return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(valor))
    if isinstance(valor, str):
        return pd.to_datetime(valor.strip(), dayfirst=True, errors="coerce")
    return pd.NaT


def normalizar_sede(nombre: str) -> str:
    texto = re.sub(r"\s+", " ", str(nombre)).strip()
    texto = re.sub(r"^(C\.A\.M\.I\.N\.O\.|Camino)\s+", "CAMINO ", texto, flags=re.IGNORECASE)
    texto = re.sub(r"^(P\.A\.S\.O\.|PASO)\s+", "PASO ", texto, flags=re.IGNORECASE)
    texto = texto.replace("Meissel", "Meisel")
    return ALIAS.get(texto, texto)


def tipo_de_sede(sede: str) -> str:
    if sede.startswith("Hospital"):
        return "Hospital"
    if sede.startswith("CAMINO"):
        return "CAMINO"
    if sede.startswith("PASO"):
        return "PASO"
    return "Otra"


def sitio_de_sede(sede: str) -> str:
    """Agrupa los medidores de un mismo sitio: 'Hospital Nazareth 3' -> 'Hospital Nazareth'.

    Solo quita un dígito final: 'PASO La 21' es el nombre de la sede, no un medidor.
    """
    return re.sub(r"\s+\d$", "", sede)


def _mapear_columnas(fila) -> dict[str, int]:
    columnas: dict[str, int] = {}
    for i, celda in enumerate(fila):
        if celda.value is None:
            continue
        etiqueta = _normalizar_texto(celda.value)
        if etiqueta.startswith("DIRECCION"):
            columnas["direccion"] = i
        elif etiqueta == "PERIODO":
            columnas["desde"], columnas["hasta"] = i, i + 1
        elif etiqueta == "CONSUMO":
            columnas["kwh"] = i
        elif etiqueta == "TARIFA":
            columnas["tarifa_factura"] = i
        elif etiqueta in ("INTERESES POR MORA", "OTROS CONCEPTOS"):
            columnas["otros_cargos"] = i
        elif etiqueta == "CALCULO":
            columnas["tipo_lectura"] = i
        elif etiqueta.startswith("VR. TOTAL"):
            columnas["valor_cop"] = i
        elif etiqueta.startswith("TOTAL DIAS FACTURADOS"):
            columnas["dias_factura"] = i
    return columnas


def _leer_hoja(hoja) -> list[dict]:
    nombre = _normalizar_texto(hoja.title)
    mes_num = next(n for m, n in MESES.items() if nombre.startswith(m))
    anio = int(re.search(r"(20\d\d)", nombre).group(1))
    mes_hoja = pd.Period(year=anio, month=mes_num, freq="M")

    registros, columnas, seccion = [], None, None
    for fila in hoja.iter_rows():
        a = fila[0].value
        if a is None:
            continue
        etiqueta = _normalizar_texto(a)
        if etiqueta in SECCIONES:
            columnas, seccion = _mapear_columnas(fila), SECCIONES[etiqueta]
            continue
        if columnas is None:
            continue
        if etiqueta.startswith(FIN_DE_TABLA):
            break

        def valor(campo):
            i = columnas.get(campo)
            return fila[i].value if i is not None and i < len(fila) else None

        desde, hasta = _fecha(valor("desde")), _fecha(valor("hasta"))
        lectura = valor("tipo_lectura")
        lectura = _normalizar_texto(lectura) if lectura is not None else ""
        lectura = {"MEDICION": "Medición", "REAL": "Medición", "ESTIMADO": "Estimado"}.get(lectura)

        # Las facturas atrasadas (sección ADICIONAL) se ubican en el mes que facturan.
        mes = mes_hoja
        if seccion == "adicional" and pd.notna(hasta):
            mes = hasta.to_period("M")

        registros.append({
            "mes": str(mes),
            "seccion": seccion,
            "sede": normalizar_sede(a),
            "direccion": re.sub(r"\s+", " ", str(valor("direccion") or "")).strip(),
            "desde": desde,
            "hasta": hasta,
            "dias_factura": _numero(valor("dias_factura")),
            "kwh": _numero(valor("kwh")),
            "tarifa_factura": _numero(valor("tarifa_factura")),
            "otros_cargos": _numero(valor("otros_cargos")),
            "valor_cop": _numero(valor("valor_cop")),
            "tipo_lectura": lectura,
        })
    return registros


def _alertas(fila) -> str:
    alertas = []
    if pd.isna(fila["kwh"]) and pd.isna(fila["valor_cop"]):
        alertas.append("sin factura")
    if pd.isna(fila["dias"]) or not 15 <= fila["dias"] <= 45:
        alertas.append("periodo inconsistente")
    if pd.notna(fila["tarifa_factura"]) and fila["tarifa_factura"] > 0 and not 200 <= fila["tarifa_factura"] <= 700:
        alertas.append("tarifa atípica")
    if fila["tipo_lectura"] == "Estimado":
        alertas.append("lectura estimada")
    return "; ".join(alertas)


def limpiar_excel(ruta: str | Path) -> pd.DataFrame:
    libro = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    registros = [r for hoja in libro.worksheets for r in _leer_hoja(hoja)]
    df = pd.DataFrame(registros)

    df["tipo_sede"] = df["sede"].map(tipo_de_sede)
    df["sitio"] = df["sede"].map(sitio_de_sede)
    df["mes_nombre"] = pd.PeriodIndex(df["mes"], freq="M").month.map(
        {n: m.capitalize() for m, n in MESES.items()}
    )

    dias_por_fechas = (df["hasta"] - df["desde"]).dt.days
    df["dias"] = df["dias_factura"].where(df["dias_factura"].notna(), dias_por_fechas)
    df.loc[df["dias"] <= 0, "dias"] = np.nan

    df["kwh_dia"] = (df["kwh"] / df["dias"]).round(2)
    df["tarifa_efectiva"] = (df["valor_cop"] / df["kwh"]).where(df["kwh"] > 0).round(2)
    df["alertas"] = df.apply(_alertas, axis=1)

    df["desde"] = df["desde"].dt.strftime("%Y-%m-%d")
    df["hasta"] = df["hasta"].dt.strftime("%Y-%m-%d")
    return df[COLUMNAS_CSV].sort_values(["mes", "tipo_sede", "sede"]).reset_index(drop=True)


def leer_csv(ruta: str | Path = CSV_POR_DEFECTO) -> pd.DataFrame:
    """Lee el CSV limpio con los mismos tipos que devuelve limpiar_excel."""
    df = pd.read_csv(ruta, encoding="utf-8-sig",
                     dtype={"mes": str, "desde": str, "hasta": str, "tipo_lectura": str})
    df[["direccion", "alertas"]] = df[["direccion", "alertas"]].fillna("")
    return df


def main() -> None:
    entrada = Path(sys.argv[1]) if len(sys.argv) > 1 else EXCEL_POR_DEFECTO
    salida = Path(sys.argv[2]) if len(sys.argv) > 2 else CSV_POR_DEFECTO
    df = limpiar_excel(entrada)
    df.to_csv(salida, index=False, encoding="utf-8-sig")
    print(f"{len(df)} registros, {df['sede'].nunique()} medidores, {df['sitio'].nunique()} sitios -> {salida}")
    print(df.groupby("seccion").size().to_string())
    con_alertas = df[df["alertas"] != ""]
    print(f"\nRegistros con alertas: {len(con_alertas)}")
    print(con_alertas["alertas"].str.split("; ").explode().value_counts().to_string())


if __name__ == "__main__":
    main()
