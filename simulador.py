"""Simulación horaria de una sede: demanda, generación solar, batería, planta y cortes de red.

La base de datos solo trae el consumo mensual facturado, así que la demanda horaria se
construye repartiendo el consumo diario promedio con un perfil típico según el tipo de
sede. Es un supuesto del modelo, no una medición.

Regla de despacho (hora a hora):
- Con red: la solar atiende primero la demanda y su excedente carga la batería; la red
  cubre el resto y, si se permite, también completa la carga de la batería. La batería
  se reserva para los cortes (no se descarga con red disponible).
- En corte: se desconecta la carga no crítica. La carga crítica se atiende con solar,
  después con la batería, después con la planta de emergencia; lo que falte es energía
  no servida.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

# Perfiles horarios relativos (0 h a 23 h). Se normalizan para que su promedio sea 1.
PERFILES = {
    # Hospital: operación 24 h con carga base alta (UCI, hospitalización, climatización).
    "Hospital": [0.80, 0.78, 0.77, 0.77, 0.78, 0.82, 0.90, 1.00, 1.12, 1.20, 1.25, 1.28,
                 1.28, 1.27, 1.25, 1.20, 1.12, 1.05, 1.00, 0.97, 0.93, 0.89, 0.85, 0.82],
    # CAMINO: urgencias 24 h más consulta diurna.
    "CAMINO": [0.70, 0.68, 0.67, 0.67, 0.68, 0.74, 0.88, 1.05, 1.22, 1.32, 1.35, 1.35,
               1.33, 1.32, 1.30, 1.25, 1.15, 1.05, 0.98, 0.92, 0.86, 0.80, 0.75, 0.72],
    # PASO: atención ambulatoria diurna; de noche solo refrigeración y seguridad.
    "PASO": [0.35, 0.35, 0.35, 0.35, 0.35, 0.40, 0.80, 1.50, 1.85, 1.95, 2.00, 2.00,
             1.90, 1.95, 1.95, 1.90, 1.70, 1.20, 0.70, 0.45, 0.40, 0.38, 0.36, 0.35],
}

LITROS_DIESEL_POR_KWH = 0.28  # consumo típico de una planta diésel a carga media
DIAS_SIMULADOS = 4
DIA_DEL_CORTE = 1  # el corte empieza el segundo día, para que la batería llegue cargada


def perfil_demanda(tipo_sede: str) -> np.ndarray:
    perfil = np.array(PERFILES.get(tipo_sede, PERFILES["Hospital"]), dtype=float)
    return perfil / perfil.mean()


def perfil_solar() -> np.ndarray:
    """Fracción de la energía solar diaria producida en cada hora (sol de 6 h a 18 h)."""
    centro_hora = np.arange(24) + 0.5
    forma = np.clip(np.sin(np.pi * (centro_hora - 6) / 12), 0, None)
    forma[(centro_hora < 6) | (centro_hora > 18)] = 0
    return forma / forma.sum()


@dataclass(frozen=True)
class Escenario:
    kwh_dia: float                 # consumo diario promedio de la sede
    tipo_sede: str = "Hospital"
    pct_critica: float = 0.40      # fracción de la demanda promedio que es crítica
    kwp: float = 0.0               # potencia solar instalada
    hsp: float = 5.5               # horas sol pico (Barranquilla ~5,0-5,8 kWh/m²/día)
    pr: float = 0.80               # rendimiento global del sistema solar
    factor_clima: float = 1.0      # 1 = día despejado; menor = nubosidad
    bateria_kwh: float = 0.0
    bateria_kw: float = 0.0
    soc_min: float = 0.20          # reserva mínima que no se descarga
    soc_inicial: float = 1.0
    eficiencia: float = 0.90       # eficiencia de ida y vuelta de la batería
    cargar_desde_red: bool = True
    planta_kw: float = 0.0
    corte_hora: int = 18           # hora del día en que empieza el corte
    corte_duracion: int = 8        # horas
    dias: int = DIAS_SIMULADOS


def simular(e: Escenario) -> pd.DataFrame:
    horas = e.dias * 24
    hora_dia = np.arange(horas) % 24
    demanda = e.kwh_dia / 24 * perfil_demanda(e.tipo_sede)[hora_dia]
    critica = np.minimum(e.pct_critica * e.kwh_dia / 24, demanda)
    solar = e.kwp * e.hsp * e.pr * e.factor_clima * perfil_solar()[hora_dia]

    inicio = DIA_DEL_CORTE * 24 + e.corte_hora
    red_ok = np.ones(horas, dtype=bool)
    red_ok[inicio:inicio + e.corte_duracion] = False

    eta = np.sqrt(e.eficiencia)  # misma eficiencia al cargar y al descargar
    soc_min = e.bateria_kwh * e.soc_min
    soc = e.bateria_kwh * e.soc_inicial

    columnas = ["solar_a_carga", "solar_a_bateria", "solar_excedente", "red_a_carga",
                "red_a_bateria", "bateria_a_carga", "planta", "no_servida", "soc_kwh"]
    r = {c: np.zeros(horas) for c in columnas}

    for t in range(horas):
        objetivo = demanda[t] if red_ok[t] else critica[t]
        a_carga = min(solar[t], objetivo)
        excedente = solar[t] - a_carga
        faltante = objetivo - a_carga

        espacio = max(0.0, (e.bateria_kwh - soc) / eta)
        carga_solar = min(excedente, e.bateria_kw, espacio)
        soc += carga_solar * eta

        if red_ok[t]:
            r["red_a_carga"][t] = faltante
            if e.cargar_desde_red:
                espacio = max(0.0, (e.bateria_kwh - soc) / eta)
                carga_red = min(e.bateria_kw - carga_solar, espacio)
                soc += carga_red * eta
                r["red_a_bateria"][t] = carga_red
        else:
            descarga = min(faltante, e.bateria_kw, max(0.0, (soc - soc_min) * eta))
            soc -= descarga / eta
            faltante -= descarga
            planta = min(faltante, e.planta_kw)
            r["bateria_a_carga"][t] = descarga
            r["planta"][t] = planta
            r["no_servida"][t] = faltante - planta

        r["solar_a_carga"][t] = a_carga
        r["solar_a_bateria"][t] = carga_solar
        r["solar_excedente"][t] = excedente - carga_solar
        r["soc_kwh"][t] = soc

    df = pd.DataFrame(r)
    df.insert(0, "hora", np.arange(horas))
    df.insert(1, "dia", np.arange(horas) // 24 + 1)
    df.insert(2, "hora_dia", hora_dia)
    df.insert(3, "red_disponible", red_ok)
    df.insert(4, "demanda", demanda)
    df.insert(5, "critica", critica)
    df.insert(6, "solar", solar)
    df["soc_pct"] = np.where(e.bateria_kwh > 0, df["soc_kwh"] / max(e.bateria_kwh, 1e-9) * 100, np.nan)
    return df


def resumir(e: Escenario, df: pd.DataFrame) -> dict:
    corte = df[~df["red_disponible"]]
    sin_cubrir = corte["no_servida"] > 1e-6
    autonomia = int(np.argmax(sin_cubrir.to_numpy())) if sin_cubrir.any() else len(corte)
    critica_corte = corte["critica"].sum()
    return {
        "horas_corte": len(corte),
        "horas_cubiertas": int((~sin_cubrir).sum()),
        "autonomia_h": autonomia,
        "corte_cubierto": not sin_cubrir.any(),
        "critica_kwh": critica_corte,
        "no_servida_kwh": corte["no_servida"].sum(),
        "cobertura_pct": 100 * (1 - corte["no_servida"].sum() / critica_corte) if critica_corte else 100.0,
        "solar_kwh": corte["solar_a_carga"].sum(),
        "bateria_kwh": corte["bateria_a_carga"].sum(),
        "planta_kwh": corte["planta"].sum(),
        "diesel_l": corte["planta"].sum() * LITROS_DIESEL_POR_KWH,
    }


def autonomia_teorica_bateria(e: Escenario) -> float:
    """Horas que la batería sola sostiene la carga crítica promedio, sin sol."""
    critica_kw = e.pct_critica * e.kwh_dia / 24
    if critica_kw <= 0:
        return 0.0
    utilizable = e.bateria_kwh * (e.soc_inicial - e.soc_min) * np.sqrt(e.eficiencia)
    return max(0.0, utilizable) / min(critica_kw, e.bateria_kw or critica_kw)


def impacto_anual(e: Escenario, tarifa_cop_kwh: float) -> dict:
    """Energía solar aprovechada en un año normal (sin cortes) y su ahorro a la tarifa dada."""
    normal = simular(replace(e, corte_duracion=0, factor_clima=1.0, dias=2))
    dia = normal[normal["dia"] == 2]  # segundo día: la batería ya está llena
    generada = dia["solar"].sum()
    aprovechada = dia["solar_a_carga"].sum() + dia["solar_a_bateria"].sum()
    fraccion = aprovechada / generada if generada else 0.0
    solar_anual = e.kwp * e.hsp * e.pr * 365
    aprovechada_anual = solar_anual * fraccion
    consumo_anual = e.kwh_dia * 365
    return {
        "solar_anual_kwh": solar_anual,
        "aprovechada_anual_kwh": aprovechada_anual,
        "cobertura_consumo_pct": 100 * aprovechada_anual / consumo_anual if consumo_anual else 0.0,
        "ahorro_anual_cop": aprovechada_anual * tarifa_cop_kwh,
    }


def comparar_respaldos(e: Escenario) -> pd.DataFrame:
    """Mismo corte con distintas combinaciones de respaldo."""
    variantes = [("Sin respaldo", replace(e, kwp=0, bateria_kwh=0, bateria_kw=0, planta_kw=0))]
    if e.planta_kw > 0:
        variantes.append(("Solo planta", replace(e, kwp=0, bateria_kwh=0, bateria_kw=0)))
    if e.kwp > 0:
        variantes.append(("Solar", replace(e, bateria_kwh=0, bateria_kw=0, planta_kw=0)))
    if e.bateria_kwh > 0:
        variantes.append(("Batería", replace(e, kwp=0, planta_kw=0)))
    if e.kwp > 0 and e.bateria_kwh > 0:
        variantes.append(("Solar + batería", replace(e, planta_kw=0)))
    if e.planta_kw > 0 and (e.kwp > 0 or e.bateria_kwh > 0):
        partes = [n for n, activo in (("Solar", e.kwp > 0), ("batería", e.bateria_kwh > 0)) if activo]
        variantes.append((" + ".join(partes + ["planta"]).capitalize(), e))

    filas = []
    for nombre, variante in variantes:
        s = resumir(variante, simular(variante))
        filas.append({
            "Respaldo": nombre,
            "Horas cubiertas": f"{s['horas_cubiertas']} de {s['horas_corte']}",
            "Cobertura (%)": round(s["cobertura_pct"], 1),
            "Sin atender (kWh)": round(s["no_servida_kwh"]),
            "Diésel (L)": round(s["diesel_l"]),
        })
    return pd.DataFrame(filas)
