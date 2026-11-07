"""Componentes visuales de la app (HTML + CSS en estilos.css)."""

import html
import json
import re
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

NARANJA, TINTA, GRIS_SAP, ROJO = "#E8730C", "#1B2333", "#A7B0BE", "#D32F2F"

LOGO_SVG = """<svg width="40" height="44" viewBox="0 0 40 44" aria-hidden="true">
<path d="M8 2 L36 2 L32 14 L4 14 Z" fill="#E8730C"/>
<path d="M6 17 L30 17 L26 29 L2 29 Z" fill="#F29A4A"/>
<path d="M4 32 L16 32 L12 44 L0 44 Z" fill="#E8730C"/></svg>"""

NOMBRES = {
    "1_precio_lista": "Precio de lista", "2_dscto_comercial": "Dscto. comercial",
    "3_dscto_volumen": "Dscto. volumen", "4_precio_factura": "Precio factura",
    "5_pronto_pago": "Pronto pago", "6_flete": "Flete", "7_costo_financiero": "Costo financiero",
    "8_POCKET_PRICE_SAP": "Pocket Price SAP", "9_grid_comercial_fuera_sap": "Grid comercial (fuera de SAP)",
    "10_campanas_fuera_sap": "Campañas (fuera de SAP)", "11_rebates_carta_fuera_sap": "Rebates por carta (fuera de SAP)",
    "12_POCKET_PRICE_REAL": "Pocket Price Real",
}
TOTALES = {"1_precio_lista", "4_precio_factura", "8_POCKET_PRICE_SAP", "12_POCKET_PRICE_REAL"}
CITA = re.compile(r"\[((?:POL|GRP|CMP|CP|CR|TF)-[A-Z0-9-]+|GLOSARIO)\]")


def cargar_estilos() -> None:
    css = (Path(__file__).parent / "estilos.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def ms(nombre: str, estilo: str = "") -> str:
    """Ícono Material Symbols en HTML."""
    return f'<span class="ms" style="{estilo}" aria-hidden="true">{nombre}</span>'


def html_(contenido: str) -> None:
    st.markdown(contenido, unsafe_allow_html=True)


def soles(x: float) -> str:
    return f"S/ {x:,.0f}".replace(",", ".")


# ---------------------------------------------------------------- cromo

def logo() -> None:
    html_(f'<div class="logo">{LOGO_SVG}<div><div class="nombre">Pocket Price AI</div>'
          f'<div class="sub">Agente de pricing</div></div></div>')


def barra_superior(conectado: bool, iniciales: str) -> None:
    # Estado en píldora blanca: el teal/rojo semánticos no contrastan directo sobre el naranja.
    clase, estado = ("ok", "Conectado") if conectado else ("error", "Sin conexión")
    html_(f'<div class="barra-superior"><div class="izq">{ms("apps", "font-size:22px")}Workspace comercial</div>'
          f'<div class="der"><span class="estado {clase}"><span class="punto"></span>{estado}</span>'
          f'<span class="sep"></span><span class="avatar">{iniciales}</span>{ms("expand_more")}</div></div>')


def usuario(nombre: str, rol: str, iniciales: str) -> None:
    html_(f'<div class="usuario"><span class="avatar">{iniciales}</span>'
          f'<div><div>{nombre}</div><div class="rol">{rol}</div></div></div>')


def migas(*partes: str) -> None:
    *previas, actual = partes
    texto = " &nbsp;/&nbsp; ".join(html.escape(p) for p in previas)
    html_(f'<div class="migas">{texto}{" &nbsp;/&nbsp; " if previas else ""}<b>{html.escape(actual)}</b></div>')


def hallazgo(h: dict, clave: str) -> bool:
    """Tarjeta de alerta proactiva. Devuelve True si el usuario pide analizarla."""
    positivo = h["tono"] == "positivo"
    pill = f'<span class="pill {"pos" if positivo else "neg"}">{ms("arrow_upward" if positivo else "arrow_downward")}'
    with st.container(key=f"hallazgo_{h['tono']}_{clave}"):
        html_(f'<div class="hz-etq">{ms(h["icono"])}{html.escape(h["etiqueta"])}</div>'
              f'<div class="hz-metrica">{pill}{html.escape(h["metrica"])}</span>'
              f'<span class="sub">{html.escape(h["metrica_sub"])}</span></div>'
              f'<div class="hz-detalle">{html.escape(h["detalle"])}</div>')
        return st.button("Analizar", icon=":material/arrow_forward:", key=f"hzb_{clave}")


# ---------------------------------------------------------------- cómo funciona

DOCUMENTOS = {
    # tipo: (nombre, ícono, qué se extrae o para qué se usa)
    "politica": ("Políticas de descuento", "policy", "Topes por canal y vigencia"),
    "grilla": ("Grids comerciales", "sell", "Descuento por grupo de productos y canal"),
    "campana": ("Campañas", "campaign", "Condición de compra y descuento"),
    "carta_rebate": ("Cartas de rebate", "receipt_long", "Objetivo trimestral y tramos"),
    "acta": ("Actas del Comité", "gavel", "Excepciones aprobadas o rechazadas"),
    "tarifario": ("Tarifario de flete", "local_shipping", "Tarifas por región (consulta)"),
    "glosario": ("Glosario de pricing", "menu_book", "Definiciones (consulta)"),
}
PASOS = [
    ("database", "1. Reúne las fuentes", "Ventas del ERP y documentos que el ERP no registra."),
    ("document_scanner", "2. Lee los documentos", "Extrae y valida los términos de cada acuerdo."),
    ("calculate", "3. Calcula", "Pocket price y margen con SQL: la IA no hace cuentas."),
    ("forum", "4. Responde con evidencia", "Explica el resultado y cita su documento."),
]
GARANTIAS = [
    ("calculate", "Cifras calculadas, no inventadas"), ("format_quote", "Cada afirmación con su fuente"),
    ("lock", "Acceso de solo lectura a los datos"), ("how_to_reg", "Confirmación antes de registrar algo"),
    ("visibility", "Cada paso queda trazado (LangSmith)"),
]


def como_funciona(f: dict) -> None:
    html_(f'<div class="tecnologia-sub">LangGraph + LangChain · LlamaIndex · Elasticsearch (búsqueda híbrida) · '
          f'PostgreSQL · Claude (respaldo OpenAI) · LangSmith · nube {f["proveedor_nube"].upper()} emulada con Floci</div>')
    pasos = "".join(f'<div class="paso"><div class="paso-t">{ms(i)}{t}</div><div class="paso-d">{d}</div></div>'
                    for i, t, d in PASOS)
    html_(f'<div class="pasos">{pasos}</div>')

    e = f["erp"]
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    periodo = (f'{meses[int(e["desde"][5:7]) - 1]} {e["desde"][:4]} a '
               f'{meses[int(e["hasta"][5:7]) - 1]} {e["hasta"][:4]}')
    filas = "".join(
        f'<tr><td>{ms(icono)}{nombre}</td><td class="num">{f["documentos"][tipo]["cantidad"]}</td>'
        f'<td><span class="fmt">{" · ".join(f["documentos"][tipo]["formatos"])}</span></td><td>{uso}</td></tr>'
        for tipo, (nombre, icono, uso) in DOCUMENTOS.items() if tipo in f["documentos"])
    total = sum(d["cantidad"] for d in f["documentos"].values())
    lineas = f'{e["lineas"]:,}'.replace(",", ".")
    chips = "".join(f'<div class="garantia">{ms(i)}{t}</div>' for i, t in GARANTIAS)
    html_(f'<div class="seccion-main">{ms("folder_open")}Fuentes de datos y garantías</div>'
          f'<div class="fuentes"><div class="col-izq">'
          f'<div class="fuente-erp"><div class="t">{ms("table_chart")}Ventas del ERP (SAP)</div>'
          f'<div class="v">{lineas} líneas de venta</div>'
          f'<div class="d">{periodo} · {e["clientes"]} clientes · {e["productos"]} productos</div>'
          f'<div class="d">Descuentos, flete, pronto pago y costos.</div></div>'
          f'<div class="fuente-erp"><div class="t">{ms("verified_user")}Garantías</div>'
          f'<div class="garantias">{chips}</div></div></div>'
          f'<div class="fuente-docs"><div class="t">{ms("description")}{total} documentos comerciales'
          f'<span class="nota">· lo que el ERP no registra</span></div>'
          f'<table class="tabla-docs"><tr><th>Documento</th><th class="num">Cant.</th><th>Formato</th>'
          f'<th>Qué obtiene el agente</th></tr>{filas}</table></div></div>')


# ---------------------------------------------------------------- conversación

def burbuja_usuario(texto: str, iniciales: str) -> None:
    html_(f'<div class="burbuja-usuario"><div class="texto">{html.escape(texto)}</div>'
          f'<span class="avatar">{iniciales}</span></div>')


def cabecera_respuesta(estado: str) -> None:
    html_(f'<div class="cabecera-resp"><span class="marca">{ms("auto_awesome")}Pocket Price AI</span>'
          f'<span class="sep"></span><span>{estado}</span></div>')


def kpis(tarjetas: list[tuple[str, str, str, str]]) -> None:
    """tarjetas: (tono peligro|neutro|ok, ícono, etiqueta, valor)."""
    celdas = "".join(f'<div class="kpi {tono}">{ms(icono)}<div><div class="etq">{etq}</div>'
                     f'<div class="val">{val}</div></div></div>' for tono, icono, etq, val in tarjetas)
    html_(f'<div class="kpis">{celdas}</div>')


def evidencia(texto: str) -> None:
    citas = list(dict.fromkeys(CITA.findall(texto or "")))
    if not citas:
        return
    chips = "".join(f'<span class="chip-doc">{ms("description")}{c}</span>' for c in citas)
    html_(f'<div class="evidencia-titulo">Evidencia</div><div class="chips">{chips}</div>')


def kpis_cascada(datos: dict) -> None:
    m = datos.get("margen_pct_sobre_pocket", {})
    pu = datos["pen_por_unidad"]
    real = m.get("con_pocket_price_real", 0) or 0
    caida = real - (m.get("con_pocket_price_sap", 0) or 0)
    kpis([
        ("peligro", "warning", "Acuerdos fuera de SAP", soles(datos["totales_pen"]["acuerdos_fuera_sap"])),
        ("neutro", "bar_chart", "Pocket Price SAP → Real (S/ por unidad)",
         f'{pu["8_POCKET_PRICE_SAP"]:.2f} → {pu["12_POCKET_PRICE_REAL"]:.2f}'.replace(".", ",")),
        ("peligro" if caida < 0 else "ok", "percent", "Margen con Pocket Price Real",
         f'{real:.1f} % ({caida:+.1f} pp vs SAP)'.replace(".", ",")),
    ])


def grafico_cascada(datos: dict) -> None:
    filas, nivel = [], 0.0
    for clave, nombre in NOMBRES.items():
        v = float(datos["pen_por_unidad"][clave] or 0)
        if clave in TOTALES:
            tipo, (ini, fin), nivel = "Total", (0.0, v), v
        else:
            tipo = "Fuera de SAP" if "fuera_sap" in clave else "Registrado en SAP"
            (ini, fin), nivel = (nivel, nivel - v), nivel - v
        filas.append({"concepto": nombre, "inicio": ini, "fin": fin, "valor": v if clave in TOTALES else -v,
                      "tipo": tipo, "orden": len(filas)})
    df = pd.DataFrame(filas)
    df["etiqueta"] = df["valor"].map(lambda v: f"{v:,.2f}".replace(".", ","))
    piso = max(0.0, min(df["fin"].min(), df["inicio"][df["tipo"] != "Total"].min()) * 0.9)
    techo = df["fin"].max() * 1.05
    escala = alt.Scale(domain=["Total", "Registrado en SAP", "Fuera de SAP"], range=[TINTA, GRIS_SAP, ROJO])
    eje_y = alt.Y("concepto:N", sort=alt.SortField("orden"), title=None,
                  axis=alt.Axis(labelLimit=240, labelFontSize=12.5, labelColor="#5B6475", ticks=False, domain=False,
                                labelOverlap=False, labelPadding=8))
    barras = alt.Chart(df).mark_bar(height=16, clip=True, cornerRadius=3).encode(
        y=eje_y,
        x=alt.X("inicio:Q", title="S/ por unidad", scale=alt.Scale(domain=[piso, techo], zero=False),
                axis=alt.Axis(grid=True, gridColor="#EEF0F3", labelColor="#8A93A3", titleColor="#8A93A3",
                              domain=False, ticks=False, tickCount=6, format=".0f")),
        x2="fin:Q",
        color=alt.Color("tipo:N", scale=escala, legend=alt.Legend(orient="top", title=None, labelColor="#5B6475",
                                                                    symbolType="square")),
        tooltip=["concepto", alt.Tooltip("valor:Q", format=".2f"), "tipo"],
    )
    etiquetas = alt.Chart(df).mark_text(align="left", dx=5, fontSize=12, color="#5B6475").encode(
        y=eje_y, x="derecha:Q", text="etiqueta:N",
    ).transform_calculate(derecha="max(datum.inicio, datum.fin)")
    grafico = ((barras + etiquetas).properties(height=400)
               .configure(font="Inter", background="#FFFFFF").configure_view(strokeWidth=0))
    st.altair_chart(grafico, use_container_width=True, theme=None)  # sin el tema gris de Streamlit


def pasos(r: dict) -> None:
    if not r.get("pasos"):
        return
    with st.expander(f"¿Cómo llegué a esto? · {len(r['pasos'])} consulta(s)", icon=":material/route:"):
        for p in r["pasos"]:
            st.markdown(f"**{p['herramienta']}** `{json.dumps(p['argumentos'], ensure_ascii=False)}`")
            if p.get("resultado"):
                st.code(p["resultado"][:800], language="json")


def respuesta(r: dict, clave: str) -> None:
    """Tarjeta de respuesta del agente."""
    with st.container(key=f"respuesta_{clave}"):
        cabecera_respuesta("Análisis completado" if r.get("ruta") != "error" else "No se pudo completar")
        if r.get("respuesta"):
            st.markdown(r["respuesta"])
        for datos in r.get("cascadas", [])[-1:]:
            kpis_cascada(datos)
            grafico_cascada(datos)
        evidencia(r.get("respuesta"))
        pasos(r)
