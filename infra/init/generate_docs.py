"""Genera el repositorio documental ficticio (PDF, DOCX, MD) a partir de
acuerdos.yaml, más un manifiesto con los metadatos de cada documento.

Estos documentos son la única vía por la que el agente conoce los acuerdos
fuera de SAP: grillas, campañas, cartas de rebate y actas del comité.
"""

import csv
import json
from datetime import date
from pathlib import Path

import yaml
from docx import Document
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ESTILOS = getSampleStyleSheet()
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}".rstrip("0").rstrip(".") + " %"


# ---------------------------------------------------------------- PDF

def _pdf(ruta: Path, empresa: dict, titulo: str, codigo: str, bloques: list) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(ruta), pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            title=titulo, author=empresa["razon_social"])
    flujo = [
        Paragraph(f"<b>{empresa['razon_social']}</b> — RUC {empresa['ruc']}", ESTILOS["Normal"]),
        Paragraph(f"Documento {codigo}", ESTILOS["Normal"]),
        Spacer(1, 0.5 * cm),
        Paragraph(titulo, ESTILOS["Title"]),
    ]
    for b in bloques:
        if isinstance(b, list):  # tabla
            t = Table(b, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]))
            flujo += [t, Spacer(1, 0.4 * cm)]
        elif b.startswith("## "):
            flujo.append(Paragraph(b[3:], ESTILOS["Heading2"]))
        else:
            flujo += [Paragraph(b, ESTILOS["BodyText"]), Spacer(1, 0.2 * cm)]
    doc.build(flujo)


def politicas(ac, empresa, base, manifiesto):
    for p in ac["politicas_descuento"]:
        filas = [["Canal", "Tope de descuento comercial en factura"]]
        filas += [[canal, _pct(t)] for canal, t in p["topes_comercial"].items()]
        bloques = [
            f"Fecha de emisión: {_fecha(p['fecha_emision'])}. Vigencia: del {_fecha(p['vigencia_desde'])} "
            f"al {_fecha(p['vigencia_hasta'])}.",
            "## 1. Objetivo",
            "Establecer los límites de descuento que el área comercial puede otorgar en la factura, "
            "con el fin de proteger el pocket price y el margen de la compañía.",
            "## 2. Descuento comercial por canal",
            "Ningún vendedor ni jefe de canal puede registrar en el sistema un descuento comercial "
            "superior al tope de su canal. Toda excepción requiere aprobación previa del Comité de Precios "
            "y debe constar en acta.",
            filas,
            "## 3. Descuento por volumen",
            f"Se permite un descuento adicional de hasta {_pct(p['descuento_volumen']['tope'])} en pedidos "
            f"(líneas) de {p['descuento_volumen']['cantidad_min']} unidades o más.",
            "## 4. Pronto pago",
            f"Se otorga {_pct(p['pronto_pago']['pct'])} de descuento por pronto pago cuando el cliente cancela "
            f"en un plazo de hasta {p['pronto_pago']['plazo_max_dias']} días.",
            "## 5. Descuentos fuera de factura",
            "Los rebates, grids comerciales y campañas se liquidan mediante nota de crédito y NO se "
            "registran en el sistema de facturación. Se rigen por sus propios documentos (cartas comerciales, "
            "grids comerciales y comunicados de campaña) y deben considerarse en el cálculo del pocket price.",
        ]
        ruta = base / "politicas" / f"{p['id']}.pdf"
        _pdf(ruta, empresa, p["titulo"], p["id"], bloques)
        manifiesto.append({"archivo": str(ruta.relative_to(base)), "documento_id": p["id"],
                           "tipo": "politica", "titulo": p["titulo"], "fecha": str(p["fecha_emision"]),
                           "vigencia_desde": str(p["vigencia_desde"]), "vigencia_hasta": str(p["vigencia_hasta"])})


def grillas(ac, empresa, base, manifiesto):
    for g in ac["grillas"]:
        filas = [["Código", "Grupo de productos", "Canal", "Descuento", "Desde", "Hasta"]]
        filas += [[f["id"], f["categoria"], f["canal"], _pct(f["pct"]), f["desde"].strftime("%d/%m/%Y"),
                   f["hasta"].strftime("%d/%m/%Y")] for f in g["filas"]]
        bloques = [
            f"Fecha de emisión: {_fecha(g['fecha_emision'])}.",
            "El presente grid comercial define los descuentos promocionales del periodo. El descuento se calcula "
            "sobre la venta neta en factura de las líneas que cumplan grupo de productos, canal y fecha, y se liquida "
            "mediante nota de crédito al cierre de cada mes. Este descuento no se registra en el sistema "
            "de facturación.",
            filas,
            "Las condiciones no son acumulables con otros grids comerciales del mismo periodo para el mismo grupo.",
        ]
        ruta = base / "grillas" / f"{g['id']}.pdf"
        _pdf(ruta, empresa, g["titulo"], g["id"], bloques)
        desde = min(f["desde"] for f in g["filas"])
        hasta = max(f["hasta"] for f in g["filas"])
        manifiesto.append({"archivo": str(ruta.relative_to(base)), "documento_id": g["id"], "tipo": "grilla",
                           "titulo": g["titulo"], "fecha": str(g["fecha_emision"]),
                           "vigencia_desde": str(desde), "vigencia_hasta": str(hasta),
                           "canales": sorted({f["canal"] for f in g["filas"]}),
                           "categorias": sorted({f["categoria"] for f in g["filas"]})})


def campanas(ac, empresa, base, manifiesto):
    for c in ac["campanas"]:
        condicion = (f"aplica a cada línea de pedido de {c['cantidad_min']} unidades o más"
                     if c["cantidad_min"] else "aplica a toda la venta del canal")
        bloques = [
            f"Comunicado de fecha {_fecha(c['fecha_emision'])}.",
            f"Se comunica a la fuerza de ventas el lanzamiento de la <b>{c['nombre']}</b>, dirigida al canal "
            f"<b>{c['canal']}</b>, vigente del {_fecha(c['desde'])} al {_fecha(c['hasta'])}.",
            f"Beneficio: descuento de <b>{_pct(c['pct'])}</b> sobre la venta neta en factura; {condicion}. "
            "Se liquida mediante nota de crédito trimestral y no se registra en el sistema de facturación.",
            f"Detalle: {c['detalle']}",
        ]
        ruta = base / "campanas" / f"{c['id']}.pdf"
        _pdf(ruta, empresa, c["nombre"], c["id"], bloques)
        manifiesto.append({"archivo": str(ruta.relative_to(base)), "documento_id": c["id"], "tipo": "campana",
                           "titulo": c["nombre"], "fecha": str(c["fecha_emision"]), "canales": [c["canal"]],
                           "vigencia_desde": str(c["desde"]), "vigencia_hasta": str(c["hasta"])})


def actas(ac, empresa, base, manifiesto):
    for a in ac["actas"]:
        bloques = [
            f"En Lima, el {_fecha(a['fecha'])}, se reunió el Comité de Precios con la participación de la "
            "Gerencia General, la Gerencia Comercial, la Gerencia de Finanzas y la Jefatura de Pricing.",
            "## Acuerdos",
        ]
        bloques += [f"{i}. {texto}" for i, texto in enumerate(a["acuerdos"], 1)]
        bloques.append("Sin otro particular, se levantó la sesión y firmaron los asistentes en señal de conformidad.")
        ruta = base / "actas" / f"{a['id']}.pdf"
        _pdf(ruta, empresa, f"Acta del Comité de Precios {a['id']}", a["id"], bloques)
        manifiesto.append({"archivo": str(ruta.relative_to(base)), "documento_id": a["id"], "tipo": "acta",
                           "titulo": f"Acta del Comité de Precios {a['id']}", "fecha": str(a["fecha"]),
                           "clientes": sorted({e["cliente_id"] for e in a["excepciones"]})})


# ---------------------------------------------------------------- DOCX

def cartas(ac, empresa, base, manifiesto, nombres):
    vig = ac["vigencia_cartas"]
    for c in ac["cartas_rebate"]:
        doc = Document()
        doc.styles["Normal"].font.size = Pt(11)
        doc.add_paragraph(f"Lima, {_fecha(c['fecha_emision'])}")
        doc.add_paragraph(f"Carta comercial N.° {c['id']}")
        doc.add_paragraph(f"Señores\n{nombres[c['cliente_id']]} (código de cliente {c['cliente_id']})\nPresente.-")
        doc.add_paragraph("Asunto: Programa de rebate por cumplimiento de objetivos 2026")
        doc.add_paragraph(
            f"De nuestra consideración: por medio de la presente, {empresa['razon_social']} le comunica las "
            f"condiciones del programa de rebate vigente del {_fecha(vig['desde'])} al {_fecha(vig['hasta'])}.")
        doc.add_paragraph(
            f"1. Objetivo: {c['objetivo_trimestral']:,} unidades por trimestre calendario, considerando todas "
            "las categorías de producto.".replace(",", "."))
        doc.add_paragraph("2. Escala de rebate según el cumplimiento del objetivo trimestral:")
        tabla = doc.add_table(rows=1, cols=2)
        tabla.style = "Table Grid"
        tabla.rows[0].cells[0].text = "Cumplimiento del objetivo"
        tabla.rows[0].cells[1].text = "Rebate sobre venta neta en factura"
        for t in c["tramos"]:
            fila = tabla.add_row().cells
            fila[0].text = f"Desde {_pct(t['cumplimiento_min'])}"
            fila[1].text = _pct(t["pct"])
        doc.add_paragraph(
            "3. Se aplica únicamente el tramo más alto alcanzado, sobre la venta neta en factura del trimestre. "
            "Por debajo del primer tramo no corresponde rebate.")
        doc.add_paragraph(
            "4. El rebate se liquida mediante nota de crédito dentro de los 30 días posteriores al cierre de "
            "cada trimestre y no se registra en el sistema de facturación.")
        doc.add_paragraph("Atentamente,\n\nGerencia Comercial\n" + empresa["razon_social"])
        ruta = base / "cartas" / f"{c['id']}.docx"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        doc.save(ruta)
        manifiesto.append({"archivo": str(ruta.relative_to(base)), "documento_id": c["id"],
                           "tipo": "carta_rebate", "titulo": f"Carta comercial {c['id']}",
                           "fecha": str(c["fecha_emision"]), "clientes": [c["cliente_id"]],
                           "vigencia_desde": str(vig["desde"]), "vigencia_hasta": str(vig["hasta"])})


def tarifario(ac, empresa, base, manifiesto):
    t = ac["tarifario_flete"]
    doc = Document()
    doc.add_heading(f"Tarifario de flete {t['id']}", level=1)
    doc.add_paragraph(f"{empresa['razon_social']}. Vigente desde el {_fecha(t['vigencia_desde'])}.")
    doc.add_paragraph(
        "El flete se calcula como unidades despachadas × peso equivalente del producto × tarifa de la región. "
        "Este costo sí se registra en el sistema de facturación como flete asumido por la compañía.")
    tabla = doc.add_table(rows=1, cols=2)
    tabla.style = "Table Grid"
    tabla.rows[0].cells[0].text = "Región"
    tabla.rows[0].cells[1].text = "Soles por unidad de peso equivalente"
    for region, s in t["soles_por_unidad_peso"].items():
        fila = tabla.add_row().cells
        fila[0].text = region
        fila[1].text = f"S/ {s:.2f}"
    doc.add_paragraph(
        "La región Oriente tiene la tarifa más alta por el transporte fluvial y los transbordos en Pucallpa "
        "e Iquitos.")
    ruta = base / "fletes" / f"{t['id']}.docx"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.save(ruta)
    manifiesto.append({"archivo": str(ruta.relative_to(base)), "documento_id": t["id"], "tipo": "tarifario",
                       "titulo": f"Tarifario de flete {t['id']}", "fecha": str(t["vigencia_desde"]),
                       "vigencia_desde": str(t["vigencia_desde"])})


GLOSARIO = """# Glosario de Pricing

## Precio de lista
Precio publicado en la lista oficial, antes de cualquier descuento.

## Precio factura (invoice price)
Precio de lista menos los descuentos registrados en la factura: descuento comercial y descuento por volumen.

## Pocket price
Lo que la empresa realmente "se lleva al bolsillo" por cada unidad: precio factura menos todos los costos y
descuentos fuera de factura (pronto pago, flete, costo financiero, rebates, grids comerciales y campañas).

## Pocket Price SAP vs. Pocket Price Real
El Pocket Price SAP solo descuenta lo que el sistema registra (descuentos en factura, pronto pago, flete y
costo financiero). El Pocket Price Real además descuenta los acuerdos que se liquidan con nota de crédito y solo existen en
documentos: rebates por carta comercial, grids comerciales y campañas.

## Grid comercial
Tabla de descuentos adicionales por grupo de productos, canal y periodo. Se liquida con nota de crédito,
por lo que no aparece en la factura.

## Cascada de precios (price waterfall)
Representación paso a paso desde el precio de lista hasta el pocket price, mostrando cuánto se pierde en cada
concepto. Permite identificar fugas de precio (price leakage).

## Margen pocket
Pocket price menos el costo unitario estándar del producto.

## Fuga de precio
Descuento o concesión que excede lo autorizado por la política comercial y no cuenta con una excepción
aprobada por el Comité de Precios.
"""


def glosario(base, manifiesto):
    ruta = base / "glosario" / "glosario_pricing.md"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(GLOSARIO, encoding="utf-8")
    manifiesto.append({"archivo": str(ruta.relative_to(base)), "documento_id": "GLOSARIO", "tipo": "glosario",
                       "titulo": "Glosario de Pricing", "fecha": "2025-01-01"})


def generar(acuerdos_yaml: Path, clientes_csv: Path, destino: Path) -> list[dict]:
    ac = yaml.safe_load(acuerdos_yaml.read_text(encoding="utf-8"))
    nombres = {r["cliente_id"]: r["nombre"] for r in csv.DictReader(open(clientes_csv, encoding="utf-8"))}
    empresa = ac["empresa"]
    manifiesto: list[dict] = []
    politicas(ac, empresa, destino, manifiesto)
    grillas(ac, empresa, destino, manifiesto)
    campanas(ac, empresa, destino, manifiesto)
    actas(ac, empresa, destino, manifiesto)
    cartas(ac, empresa, destino, manifiesto, nombres)
    tarifario(ac, empresa, destino, manifiesto)
    glosario(destino, manifiesto)
    for m in manifiesto:
        m["archivo"] = m["archivo"].replace("\\", "/")
    (destino / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifiesto


if __name__ == "__main__":
    aqui = Path(__file__).parent
    docs = generar(aqui / "acuerdos.yaml", Path("data/raw/dim_cliente.csv"), Path("data/docs"))
    print(f"{len(docs)} documentos generados")
