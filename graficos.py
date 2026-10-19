"""Gráficos de la app (Plotly) con una sola paleta y estilo compartido."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

FUENTE = 'Inter, system-ui, -apple-system, "Segoe UI", sans-serif'
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
TENUE = "#898781"
REJILLA = "#e1e0d9"
EJE = "#c3c2b7"
SUPERFICIE = "#ffffff"  # las gráficas van sobre tarjetas blancas
CRITICO = "#d03b3b"

# Paleta categórica validada (orden fijo). El color sigue a la entidad, no a su posición.
SERIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
COLOR_TIPO = {"Hospital": SERIE[0], "CAMINO": SERIE[1], "PASO": SERIE[2], "Otra": SERIE[3]}
COLOR_FUENTE = {"Red": SERIE[0], "Planta": SERIE[1], "Batería": SERIE[2], "Solar": SERIE[3]}
SECUENCIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def mes_corto(mes: str) -> str:
    return MESES_CORTOS[int(mes[5:7]) - 1]


def _estilo(fig: go.Figure, alto: int = 340, leyenda: bool = True) -> go.Figure:
    fig.update_layout(
        height=alto,
        margin=dict(l=8, r=8, t=8 if not leyenda else 36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FUENTE, size=12, color=TINTA_2),
        separators=",.",
        showlegend=leyenda,
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom", title_text="",
                    font=dict(color=TINTA_2), traceorder="normal"),
        hoverlabel=dict(bgcolor="white", bordercolor=EJE, font=dict(color=TINTA)),
        barcornerradius=4,
    )
    fig.update_xaxes(showgrid=False, linecolor=EJE, ticks="", tickfont=dict(color=TENUE), zeroline=False,
                     automargin=True)
    fig.update_yaxes(gridcolor=REJILLA, gridwidth=1, linecolor=EJE, ticks="", tickfont=dict(color=TENUE),
                     zeroline=False, automargin=True)
    return fig


def consumo_mensual_por_tipo(df: pd.DataFrame) -> go.Figure:
    tabla = df.groupby(["mes", "tipo_sede"])["kwh"].sum().unstack(fill_value=0)
    meses = [mes_corto(m) for m in tabla.index]
    fig = go.Figure()
    for tipo in [t for t in COLOR_TIPO if t in tabla.columns]:
        fig.add_bar(
            x=meses, y=tabla[tipo] / 1000, name=tipo,
            marker=dict(color=COLOR_TIPO[tipo], line=dict(color=SUPERFICIE, width=1)),
            hovertemplate=f"<b>{tipo}</b> · %{{x}}<br>%{{y:,.1f}} MWh<extra></extra>",
        )
    fig.update_layout(barmode="stack", bargap=0.55)
    return _estilo(fig, alto=300)


def ranking_sitios(indicadores: pd.DataFrame, n: int = 10) -> go.Figure:
    top = indicadores.nlargest(n, "kwh_total").iloc[::-1]
    fig = go.Figure(go.Bar(
        x=top["kwh_total"] / 1000, y=top["sitio"], orientation="h",
        marker=dict(color=SERIE[0]),
        text=[f"{v / 1000:,.0f}".replace(",", ".") for v in top["kwh_total"]],
        textposition="outside", textfont=dict(color=TINTA_2),
        cliponaxis=False,
        customdata=top[["tipo_sede", "costo_total"]].to_numpy(),
        hovertemplate="<b>%{y}</b> (%{customdata[0]})<br>%{x:,.1f} MWh<br>$%{customdata[1]:,.0f}<extra></extra>",
    ))
    fig.update_layout(bargap=0.4)
    fig.update_xaxes(showticklabels=False, showgrid=False, showline=False,
                     range=[0, top["kwh_total"].max() / 1000 * 1.15])  # espacio para la etiqueta
    fig.update_yaxes(showgrid=False, showline=False, tickfont=dict(color=TINTA_2))
    return _estilo(fig, alto=300, leyenda=False)


def tarifa_mensual(df: pd.DataFrame) -> go.Figure:
    validos = df[(df["kwh"] > 0) & df["valor_cop"].notna()]
    tabla = validos.groupby("mes")[["valor_cop", "kwh"]].sum()
    tarifa = tabla["valor_cop"] / tabla["kwh"]
    meses = [mes_corto(m) for m in tarifa.index]
    fig = go.Figure(go.Scatter(
        x=meses, y=tarifa, mode="lines+markers",
        line=dict(color=SERIE[0], width=2), marker=dict(size=8, line=dict(color=SUPERFICIE, width=2)),
        hovertemplate="%{x}<br>$%{y:,.0f} por kWh<extra></extra>",
    ))
    fig.add_annotation(x=meses[-1], y=tarifa.iloc[-1], text=f"${tarifa.iloc[-1]:,.0f}".replace(",", "."),
                       showarrow=False, xanchor="left", xshift=8, font=dict(color=TINTA_2))
    fig.update_xaxes(dtick=2, tickangle=0)
    # Rango con aire alrededor: sin forzar el cero, pero sin exagerar variaciones pequeñas.
    fig.update_yaxes(tickprefix="$", range=[(tarifa.min() * 0.85) // 50 * 50, (tarifa.max() * 1.05) // 50 * 50 + 50])
    return _estilo(fig, alto=300, leyenda=False)


def mapa_calor(df: pd.DataFrame, orden_sitios: list[str]) -> go.Figure:
    tabla = df.groupby(["sitio", "mes"])["kwh"].sum(min_count=1).unstack()
    tabla = tabla.reindex(orden_sitios)
    meses = [mes_corto(m) for m in tabla.columns]
    escala = [[i / (len(SECUENCIAL) - 1), c] for i, c in enumerate(SECUENCIAL)]
    fig = go.Figure(go.Heatmap(
        z=tabla.to_numpy() / 1000, x=meses, y=tabla.index, colorscale=escala, xgap=2, ygap=2,
        colorbar=dict(title=dict(text="MWh", font=dict(color=TENUE)), tickfont=dict(color=TENUE),
                      thickness=10, outlinewidth=0),
        hovertemplate="<b>%{y}</b> · %{x}<br>%{z:,.1f} MWh<extra></extra>",
        hoverongaps=False,
    ))
    fig.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(color=TINTA_2))
    fig.update_xaxes(side="top")
    return _estilo(fig, alto=max(360, 19 * len(tabla)), leyenda=False)


def _etiqueta_hora(df: pd.DataFrame) -> list[str]:
    return [f"Día {d} · {h:02d}:00" for d, h in zip(df["dia"], df["hora_dia"])]


def simulacion(sim: pd.DataFrame, soc_min_pct: float) -> go.Figure:
    """Fuentes que atienden la demanda (arriba) y carga de la batería (abajo), con el corte sombreado."""
    con_bateria = bool(sim["soc_pct"].notna().any())
    fig = make_subplots(rows=2 if con_bateria else 1, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                        row_heights=[0.72, 0.28] if con_bateria else [1.0])
    etiquetas = _etiqueta_hora(sim)

    fuentes = [("Solar", sim["solar_a_carga"]), ("Batería", sim["bateria_a_carga"]),
               ("Planta", sim["planta"]), ("Red", sim["red_a_carga"])]
    for nombre, serie in fuentes:
        if serie.sum() > 0:
            fig.add_bar(
                x=sim["hora"], y=serie, name=nombre, customdata=etiquetas, row=1, col=1,
                marker=dict(color=COLOR_FUENTE[nombre], line=dict(color="white", width=1)),
                hovertemplate=f"<b>{nombre}</b> · %{{customdata}}<br>%{{y:,.1f}} kW<extra></extra>",
            )
    if sim["no_servida"].sum() > 0:
        fig.add_bar(
            x=sim["hora"], y=sim["no_servida"], name="Sin atender", customdata=etiquetas, row=1, col=1,
            marker=dict(color=CRITICO, line=dict(color="white", width=1)),
            hovertemplate="<b>Carga crítica sin atender</b> · %{customdata}<br>%{y:,.1f} kW<extra></extra>",
        )
    for nombre, serie, trazo in [("Demanda", sim["demanda"], dict(color=TINTA, width=2)),
                                 ("Carga crítica", sim["critica"], dict(color=TINTA_2, width=2, dash="dot"))]:
        fig.add_scatter(
            x=sim["hora"], y=serie, name=nombre, mode="lines", customdata=etiquetas, row=1, col=1,
            line=dict(shape="hvh", **trazo),
            hovertemplate=f"<b>{nombre}</b> · %{{customdata}}<br>%{{y:,.1f}} kW<extra></extra>",
        )
    fig.update_yaxes(title_text="kW", title_font=dict(color=TENUE), row=1, col=1)

    if con_bateria:
        fig.add_scatter(
            x=sim["hora"], y=sim["soc_pct"], mode="lines", showlegend=False, customdata=etiquetas,
            line=dict(color=COLOR_FUENTE["Batería"], width=2), fill="tozeroy",
            fillcolor="rgba(27,175,122,0.10)", row=2, col=1,
            hovertemplate="<b>Batería</b> · %{customdata}<br>%{y:.0f} % de carga<extra></extra>",
        )
        fig.add_hline(y=soc_min_pct, line=dict(color=TENUE, width=1), row=2, col=1)
        fig.update_yaxes(range=[0, 105], tickvals=[0, 50, 100], ticksuffix=" %", title_text="Batería",
                         title_font=dict(color=TENUE), row=2, col=1)

    corte = sim.loc[~sim["red_disponible"], "hora"]
    if not corte.empty:
        fig.add_vrect(x0=corte.min() - 0.5, x1=corte.max() + 0.5, fillcolor=CRITICO, opacity=0.07,
                      line_width=0, row="all", col=1)
        fig.add_annotation(x=(corte.min() + corte.max()) / 2, xref="x", y=0.99, yref="y domain",
                           yanchor="top", text="Corte", showarrow=False, font=dict(color=TINTA_2, size=11))

    marcas = sim[sim["hora_dia"] % 6 == 0]
    fig.update_xaxes(tickvals=marcas["hora"], tickangle=0,
                     ticktext=[f"Día {d}" if h == 0 else f"{h:02d}h" for d, h in zip(marcas["dia"], marcas["hora_dia"])])
    fig.update_layout(barmode="stack", bargap=0.12)
    return _estilo(fig, alto=460 if con_bateria else 340)
