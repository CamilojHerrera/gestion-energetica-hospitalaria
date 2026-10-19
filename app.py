"""Prototipo: sistema de apoyo a la gestión energética hospitalaria (MiRed Barranquilla IPS).

Ejecutar con:  streamlit run app.py
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import streamlit as st

import graficos as g
from limpieza import leer_csv, limpiar_excel
from simulador import Escenario, comparar_respaldos, impacto_anual, resumir, simular

TARIFA_2026 = 890  # COP/kWh, julio de 2026 (planteamiento del problema)
SIN_BARRA = {"displayModeBar": False}

st.set_page_config(page_title="Gestión energética hospitalaria", page_icon="⚡", layout="wide")

st.html("""
<style>
[data-testid="stMainBlockContainer"] { padding-top: 2.5rem; padding-bottom: 2rem; max-width: 1240px; }
[data-testid="stHeader"] { background: transparent; }
[class*="st-key-card_"], [data-testid="stMetric"] { background: #ffffff; }
[data-testid="stMetricLabel"] p { color: #6b6a65; font-weight: 500; }
button[data-baseweb="tab"] p { font-size: 0.95rem; font-weight: 500; }
.antetitulo { color: #2a78d6; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em;
              text-transform: uppercase; margin-bottom: 0.3rem; }
.titulo-app { font-size: 2rem; font-weight: 700; line-height: 1.15; color: #141413; }
.bajada { color: #67665f; font-size: 0.95rem; margin: 0.35rem 0 0.4rem; }
.titulo { font-size: 0.98rem; font-weight: 600; color: #1b1b1a; }
.detalle { color: #7a7973; font-size: 0.82rem; margin: 0.1rem 0 0.35rem; }
.sede { font-size: 1.3rem; font-weight: 700; color: #141413; line-height: 1.2; }
.insignia { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0.8rem 0.3rem 0.35rem;
            border-radius: 999px; font-size: 0.85rem; font-weight: 500; margin: 0.6rem 0 0.2rem; }
.insignia b { display: inline-grid; place-items: center; width: 1.2rem; height: 1.2rem; border-radius: 50%;
              color: #fff; font-size: 0.72rem; }
.insignia.ok { background: #e8f5e8; color: #135c13; }
.insignia.ok b { background: #0ca30c; }
.insignia.alerta { background: #fbeaea; color: #962626; }
.insignia.alerta b { background: #d03b3b; }
</style>
""")


def num(valor: float, decimales: int = 0) -> str:
    """Formato colombiano: 1.234.567,8"""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def pesos(valor: float) -> str:
    return f"${num(valor / 1e6, 1 if abs(valor) < 1e9 else 0)} M" if abs(valor) >= 1e6 else f"${num(valor)}"


def titulo(texto: str, detalle: str | None = None) -> None:
    html = f'<div class="titulo">{texto}</div>'
    if detalle:
        html += f'<div class="detalle">{detalle}</div>'
    st.markdown(html, unsafe_allow_html=True)


def tarjeta(clave: str):
    return st.container(border=True, key=f"card_{clave}")


def grafico(fig) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, config=SIN_BARRA)


@st.cache_data(show_spinner="Cargando las facturas…")
def cargar_datos(contenido: bytes | None) -> pd.DataFrame:
    """Por defecto lee el CSV limpio; si se sube un Excel, lo limpia en el momento."""
    return limpiar_excel(io.BytesIO(contenido)) if contenido else leer_csv()


def kwh_dia_estimado(df: pd.DataFrame) -> pd.Series:
    """kWh/día por factura; si el periodo es inconsistente se asume un mes de 30 días."""
    valido = df["dias"].between(15, 45)
    return df["kwh_dia"].where(valido, df["kwh"] / 30)


def indicadores_por_sitio(df: pd.DataFrame) -> pd.DataFrame:
    datos = df.assign(kwh_dia_est=kwh_dia_estimado(df))
    por_mes = datos.groupby(["sitio", "mes"]).agg(kwh=("kwh", "sum"), kwh_dia=("kwh_dia_est", "sum"))
    ind = datos.groupby("sitio").agg(
        tipo_sede=("tipo_sede", "first"),
        medidores=("sede", "nunique"),
        kwh_total=("kwh", "sum"),
        costo_total=("valor_cop", "sum"),
    )
    ind["kwh_dia_prom"] = por_mes.groupby("sitio")["kwh_dia"].mean()
    ind["tarifa_efectiva"] = ind["costo_total"] / ind["kwh_total"].replace(0, np.nan)
    return ind.reset_index().sort_values("kwh_total", ascending=False)


# El cargador de Excel vive en la pestaña Datos; su valor ya está en session_state al recargar.
archivo = st.session_state.get("excel")
datos = cargar_datos(archivo.getvalue() if archivo else None)
activos = datos[datos["seccion"] != "cerrada"]

st.markdown("""
<div class="antetitulo">Prototipo · MiRed Barranquilla IPS</div>
<div class="titulo-app">Gestión energética hospitalaria</div>
<div class="bajada">Consumo facturado en 2018 y simulación de cortes de red con solar, batería y planta de emergencia.</div>
""", unsafe_allow_html=True)

tab_consumo, tab_simulador, tab_datos = st.tabs(["Consumo", "Simulador", "Datos"])

# ---------------------------------------------------------------- consumo
with tab_consumo:
    meses_disponibles = sorted(datos["mes"].unique())
    f1, f2, f3 = st.columns([2.2, 2, 1], vertical_alignment="bottom")
    tipos = f1.multiselect("Tipo de sede", ["Hospital", "CAMINO", "PASO"], default=["Hospital", "CAMINO", "PASO"])
    desde, hasta = f2.select_slider("Meses", options=meses_disponibles,
                                    value=(meses_disponibles[0], meses_disponibles[-1]),
                                    format_func=g.mes_corto)
    con_cerradas = f3.toggle("Sedes cerradas", value=False)

    base = datos if con_cerradas else activos
    filtro = base[base["tipo_sede"].isin(tipos) & base["mes"].between(desde, hasta)]

    if filtro.empty:
        st.info("No hay registros con esos filtros.")
    else:
        ind = indicadores_por_sitio(filtro)
        con_valor = filtro[filtro["kwh"] > 0]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Consumo", f"{num(filtro['kwh'].sum() / 1e6, 2)} GWh", border=True)
        m2.metric("Costo", pesos(filtro["valor_cop"].sum()), border=True)
        m3.metric("Tarifa efectiva", f"${num(con_valor['valor_cop'].sum() / con_valor['kwh'].sum())}/kWh",
                  border=True)
        m4.metric("Sitios", num((ind["kwh_total"] > 0).sum()), border=True)

        with tarjeta("mensual"):
            titulo("Consumo mensual por tipo de sede", "MWh facturados")
            grafico(g.consumo_mensual_por_tipo(filtro))

        c1, c2 = st.columns([3, 2])
        with c1, tarjeta("ranking"):
            titulo("Sitios que más consumen", "MWh en el periodo")
            grafico(g.ranking_sitios(ind))
        with c2, tarjeta("tarifa"):
            titulo("Tarifa efectiva", "Pesos por kWh facturado")
            grafico(g.tarifa_mensual(filtro))

        with tarjeta("detalle"):
            titulo("Detalle por sitio")
            st.dataframe(
                ind[["sitio", "tipo_sede", "kwh_total", "costo_total", "kwh_dia_prom", "tarifa_efectiva"]],
                hide_index=True, width="stretch", height=320,
                column_config={
                    "sitio": "Sitio",
                    "tipo_sede": "Tipo",
                    "kwh_total": st.column_config.NumberColumn("kWh", format="localized"),
                    "costo_total": st.column_config.NumberColumn("Costo (COP)", format="localized"),
                    "kwh_dia_prom": st.column_config.NumberColumn("kWh/día", format="%.0f"),
                    "tarifa_efectiva": st.column_config.NumberColumn("$/kWh", format="%.0f"),
                },
            )

# ---------------------------------------------------------------- simulador
with tab_simulador:
    ind_activos = indicadores_por_sitio(activos)
    sitios = ind_activos[ind_activos["kwh_total"] > 0]["sitio"].tolist()
    defecto = sitios.index("Hospital General de Barranquilla") if "Hospital General de Barranquilla" in sitios else 0

    entradas, resultados = st.columns([1, 2.4], gap="large")

    with entradas, tarjeta("controles"):
        sitio = st.selectbox("Sitio", sitios, index=defecto)
        tipo = ind_activos.set_index("sitio").loc[sitio, "tipo_sede"]
        por_mes = (activos[activos["sitio"] == sitio].assign(kwh_dia_est=kwh_dia_estimado)
                   .groupby("mes")["kwh_dia_est"].sum())
        mes = st.selectbox("Mes", ["Promedio 2018"] + list(por_mes.index),
                           format_func=lambda m: m if m == "Promedio 2018" else f"{g.mes_corto(m)} 2018")
        kwh_dia = float(por_mes.mean() if mes == "Promedio 2018" else por_mes[mes])
        carga_media = kwh_dia / 24
        st.markdown(f'<div class="detalle">{tipo} · {num(kwh_dia)} kWh/día · {num(carga_media)} kW promedio</div>',
                    unsafe_allow_html=True)
        pct_critica = st.slider("Carga crítica (%)", 10, 80, 40 if tipo != "PASO" else 25, step=5,
                                key=f"critica_{sitio}",
                                help="Parte de la demanda que no se puede apagar: UCI, quirófanos, cadena de frío.") / 100
        critica_kw = carga_media * pct_critica

        st.space("small")
        titulo("Corte de red")
        c1, c2 = st.columns(2)
        corte_hora = c1.number_input("Inicio (h)", 0, 23, 14)
        corte_dur = c2.number_input("Duración (h)", 1, 48, 8)
        clima = st.select_slider("Clima", options=[0.35, 0.6, 0.8, 1.0], value=1.0,
                                 format_func={0.35: "Nublado", 0.6: "Parcial", 0.8: "Algo de nubes",
                                              1.0: "Despejado"}.get)

        st.space("small")
        titulo("Respaldo")
        kwp = st.number_input("Solar (kWp)", 0.0, 5000.0, float(max(10, round(carga_media / 10) * 10)),
                              step=10.0, key=f"kwp_{sitio}")
        bat_kwh = st.number_input("Batería (kWh)", 0.0, 20000.0, float(round(critica_kw * 4 / 10) * 10),
                                  step=10.0, key=f"bkwh_{sitio}")
        planta_kw = st.number_input("Planta diésel (kW)", 0.0, 5000.0, 0.0, step=10.0, key=f"planta_{sitio}")

        with st.expander("Más parámetros"):
            bat_kw = st.number_input("Potencia de la batería (kW)", 0.0, 5000.0,
                                     float(max(10, round(critica_kw * 1.2 / 10) * 10)), step=10.0,
                                     key=f"bkw_{sitio}")
            p1, p2 = st.columns(2)
            soc_min = p1.number_input("Reserva (%)", 0, 50, 20, step=5) / 100
            soc_ini = p2.number_input("Carga inicial (%)", 20, 100, 100, step=10) / 100
            hsp = p1.number_input("Horas sol pico", 3.0, 7.0, 5.5, step=0.1)
            pr = p2.number_input("Rendimiento", 0.5, 0.95, 0.80, step=0.05)
            cargar_red = st.checkbox("Cargar la batería desde la red", value=True)
            tarifa = st.number_input("Tarifa (COP/kWh)", 100, 2000, TARIFA_2026, step=10)

    escenario = Escenario(
        kwh_dia=kwh_dia, tipo_sede=tipo, pct_critica=pct_critica,
        kwp=kwp, hsp=hsp, pr=pr, factor_clima=clima,
        bateria_kwh=bat_kwh, bateria_kw=bat_kw, soc_min=soc_min, soc_inicial=soc_ini,
        cargar_desde_red=cargar_red, planta_kw=planta_kw,
        corte_hora=int(corte_hora), corte_duracion=int(corte_dur),
    )
    sim = simular(escenario)
    res = resumir(escenario, sim)
    anual = impacto_anual(escenario, tarifa)

    with resultados:
        st.markdown(f'<div class="sede">{sitio}</div>'
                    f'<div class="detalle">Corte de {res["horas_corte"]} h desde las {int(corte_hora):02d}:00</div>',
                    unsafe_allow_html=True)
        if res["corte_cubierto"]:
            insignia = '<div class="insignia ok"><b>✓</b>La carga crítica queda cubierta todo el corte</div>'
        else:
            insignia = (f'<div class="insignia alerta"><b>!</b>La carga crítica queda sin respaldo '
                        f'a las {res["autonomia_h"]} h del corte</div>')
        st.markdown(insignia, unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Autonomía", f"{res['autonomia_h']} h", border=True,
                  help="Horas seguidas con la carga crítica cubierta desde que empieza el corte.")
        k2.metric("Cobertura", f"{num(res['cobertura_pct'], 1)} %", border=True)
        k3.metric("Sin atender", f"{num(res['no_servida_kwh'])} kWh", border=True)
        k4.metric("Diésel", f"{num(res['diesel_l'])} L", border=True)

        with tarjeta("operacion"):
            titulo("Operación hora a hora", "En el corte solo se atiende la carga crítica")
            grafico(g.simulacion(sim, soc_min * 100))

        with tarjeta("comparacion"):
            titulo("Comparación de respaldos", "Mismo corte con distintas combinaciones")
            st.dataframe(comparar_respaldos(escenario), hide_index=True, width="stretch")

        a1, a2, a3 = st.columns(3)
        a1.metric("Solar al año", f"{num(anual['solar_anual_kwh'] / 1000)} MWh", border=True)
        a2.metric("Consumo cubierto", f"{num(anual['cobertura_consumo_pct'], 1)} %", border=True)
        a3.metric("Ahorro al año", pesos(anual["ahorro_anual_cop"]), border=True,
                  help=f"Energía solar aprovechada × ${num(tarifa)}/kWh, sin descontar la inversión.")

        with st.expander("Supuestos del modelo"):
            st.markdown(f"""
- La base solo trae consumo mensual. Los {num(kwh_dia)} kWh/día se reparten con un perfil típico de **{tipo}**.
- La carga crítica es el {int(pct_critica * 100)} % de la demanda promedio; en el corte se apaga el resto.
- Solar: {num(kwp)} kWp × {num(hsp, 1)} horas sol pico × rendimiento {num(pr, 2)}, entre las 6 h y las 18 h.
- La batería rinde 90 % ida y vuelta, respeta la reserva mínima y solo se descarga en cortes.
- La planta gasta 0,28 L de diésel por kWh y tiene combustible suficiente.
- El ahorro no descuenta inversión, mantenimiento ni degradación.
""")

# ---------------------------------------------------------------- datos
with tab_datos:
    con_alertas = datos[datos["alertas"] != ""]
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Facturas", num(len(datos)), border=True)
    d2.metric("Medidores", num(datos["sede"].nunique()), border=True)
    d3.metric("Sitios", num(datos["sitio"].nunique()), border=True)
    d4.metric("Con alertas", num(len(con_alertas)), border=True)

    with tarjeta("facturas"):
        titulo("Facturas por sitio y mes", "MWh facturados · celda vacía: mes sin factura")
        grafico(g.mapa_calor(activos, indicadores_por_sitio(activos)["sitio"].tolist()))

    c1, c2 = st.columns([1, 2.2])
    with c1, tarjeta("alertas"):
        titulo("Alertas")
        resumen = (con_alertas["alertas"].str.split("; ").explode().value_counts()
                   .rename_axis("Alerta").reset_index(name="Registros"))
        st.dataframe(resumen, hide_index=True, width="stretch")
    with c2, tarjeta("alertas_detalle"):
        titulo("Registros con alertas")
        st.dataframe(con_alertas[["mes", "sede", "desde", "hasta", "dias", "kwh", "alertas"]],
                     hide_index=True, width="stretch", height=250)

    with tarjeta("base"):
        titulo("Base de datos limpia", f"{num(len(datos))} registros · {datos['mes'].min()} a {datos['mes'].max()}")
        b1, b2 = st.columns([1, 2], vertical_alignment="center")
        b1.download_button("Descargar CSV", datos.to_csv(index=False).encode("utf-8-sig"),
                           file_name="consumo_2018.csv", mime="text/csv", icon=":material/download:")
        b2.file_uploader("Usar otro Excel", type=["xlsx"], key="excel")
        st.dataframe(datos, hide_index=True, width="stretch", height=360)

    with st.expander("Cómo se limpió el Excel"):
        st.markdown("""
- Se leen las 11 hojas mensuales aunque cambien de columnas entre meses.
- Se unifican nombres (`C.A.M.I.N.O.` → `CAMINO`, `P.A.S.O.` → `PASO`, `Meissel` → `Meisel`).
- Se separan sedes habilitadas, cerradas y facturas atrasadas; se descartan totales, notas y firmas.
- Se agrupan medidores por sitio y se calculan días, kWh/día y tarifa efectiva.
- No se publican el NIC ni los nombres de quienes firman las hojas del Excel.
""")
