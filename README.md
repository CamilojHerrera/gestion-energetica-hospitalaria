# Sistema de apoyo a la gestión energética hospitalaria (prototipo)

Avance del aplicativo que simula el consumo energético de las sedes de MiRed Barranquilla IPS
usando la base de datos de facturas de Electricaribe (enero a noviembre de 2018).

Integrantes: Camilo Herrera, Richard Torres, Arnuy Juvinao.

## Cómo ejecutarlo

Requiere Python 3.10 o superior.

```bash
python -m venv .venv
.venv\Scripts\activate          # en macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

La app abre en `http://localhost:8501` y lee `datos/consumo_2018.csv`. El Excel original no se publica porque trae NIC y nombres de funcionarios; para regenerar el CSV, copien `CONSUMO DE ENERGIA 2018.xlsx` en `datos/` y ejecuten:

```bash
python limpieza.py
```

## Qué hace

| Pestaña | Contenido |
|---|---|
| **Consumo** | kWh y costo por mes y tipo de sede (Hospital, CAMINO, PASO), ranking de sitios, tarifa efectiva mensual y detalle por sitio. |
| **Simulador** | Para un sitio y un mes: demanda hora a hora, generación solar, batería y planta diésel ante un corte de red. Calcula la autonomía de la carga crítica, la energía sin atender, el diésel usado, una comparación de respaldos y el ahorro anual con la tarifa de 2026 ($890/kWh). |
| **Datos** | Facturas por sitio y mes, alertas de calidad (periodos inconsistentes, lecturas estimadas, tarifas atípicas) y descarga del CSV. |

## Archivos

- `limpieza.py`: convierte el Excel (11 hojas con formatos distintos) en `datos/consumo_2018.csv`.
- `simulador.py`: modelo horario de demanda, solar, batería, planta y cortes.
- `graficos.py`: gráficos Plotly.
- `app.py`: interfaz Streamlit.
- `datos/consumo_2018.csv`: base limpia que usa la app (sin NIC).

## Supuestos del modelo

- La base de datos solo trae consumo **mensual** por factura. La demanda horaria se obtiene repartiendo
  el consumo diario promedio con un perfil típico por tipo de sede. Es un supuesto, no una medición.
- La carga crítica es un porcentaje fijo de la demanda promedio. Durante el corte se desconecta el resto.
- Solar: kWp × horas sol pico × rendimiento, repartida entre las 6 h y las 18 h.
- La batería solo se descarga en cortes, tiene una eficiencia de ida y vuelta del 90 % y no baja de la reserva mínima.
- La planta consume 0,28 L de diésel por kWh y se asume que tiene combustible suficiente.
- El ahorro anual no descuenta inversión, mantenimiento ni degradación.

## Próximos pasos

- Reemplazar los perfiles típicos por mediciones horarias reales (submedición por área).
- Pronóstico de demanda y de generación solar (SARIMAX, Prophet, XGBoost).
- Detección de anomalías en el consumo.
- Evaluación económica de la inversión (VPN, periodo de retorno, opciones reales).

> Para compartir el proyecto, no incluyan la carpeta `.venv`: se vuelve a crear con los pasos de arriba.
