"""Genera los datos sintéticos de "Andina Materiales de Construcción S.A.C."
(empresa ficticia): extracto de ventas del ERP (SAP) con su cascada de precio
y costos estándar. Determinista (semilla fija).

Solo incluye lo que SAP registra. Las grillas promocionales, campañas y
rebates por carta comercial NO están aquí: viven en documentos (ver
acuerdos.yaml y generate_docs.py) y se incorporan al pocket price real
mediante la ingesta.

Historias sembradas:
- Alza de lista de 6 % en marzo 2026.
- Flete alto en Oriente.
- Dos ferreterías del Sur (CLI-FER-003 y CLI-FER-011) con descuentos de
  nivel distribuidor; solo una tiene excepción aprobada por el comité.
"""

import csv
import random
from datetime import date
from pathlib import Path

SEED = 42

PRODUCTOS = [
    # sku, nombre, grupo (columna categoria), unidad, precio_lista_2025, peso_flete
    # El orden y la cantidad no cambian: el generador consume el azar igual y las cifras se mantienen.
    ("PY-125-ST", "Plancha Kanto estándar 12,5 mm", "Planchas de yeso", "plancha", 32.90, 1.0),
    ("PY-125-RH", "Plancha Kanto humedad 12,5 mm", "Planchas de yeso", "plancha", 44.50, 1.0),
    ("PY-159-RF", "Plancha Kanto cortafuego 15,9 mm", "Planchas de yeso", "plancha", 58.20, 1.3),
    ("PY-095-ST", "Plancha Kanto estándar 9,5 mm", "Planchas de yeso", "plancha", 27.40, 0.8),
    ("FC-06-LIS", "Placa Cempla 6 mm", "Placas cementicias", "plancha", 52.80, 1.6),
    ("FC-08-LIS", "Placa Cempla 8 mm", "Placas cementicias", "plancha", 68.90, 2.0),
    ("FC-10-LIS", "Placa Cempla 10 mm", "Placas cementicias", "plancha", 84.60, 2.4),
    ("FC-08-SID", "Siding Cempla 8 mm", "Placas cementicias", "pieza", 24.30, 0.7),
    ("PM-PAR-89", "Parante galvanizado 89 mm x 3 m", "Perfilería", "pieza", 15.60, 0.4),
    ("PM-PAR-64", "Parante galvanizado 64 mm x 3 m", "Perfilería", "pieza", 12.80, 0.35),
    ("PM-RIE-89", "Riel galvanizado 89 mm x 3 m", "Perfilería", "pieza", 13.40, 0.35),
    ("PM-RIE-64", "Riel galvanizado 64 mm x 3 m", "Perfilería", "pieza", 10.90, 0.3),
    ("PM-OMG-01", "Omega galvanizado x 3 m", "Perfilería", "pieza", 8.70, 0.25),
    ("CU-ON-122", "Teja Ondamax 1,22 m", "Tejas onduladas", "plancha", 38.70, 1.5),
    ("CU-ON-183", "Teja Ondamax 1,83 m", "Tejas onduladas", "plancha", 55.90, 2.2),
    ("CU-ON-244", "Teja Ondamax 2,44 m", "Tejas onduladas", "plancha", 72.40, 2.9),
    ("CU-CUM-01", "Cumbrera Ondamax", "Tejas onduladas", "pieza", 21.50, 0.6),
    ("AC-MAS-28", "Pasta para juntas 28 kg", "Complementos", "balde", 79.90, 1.1),
    ("AC-CIN-90", "Cinta para juntas 90 m", "Complementos", "rollo", 9.80, 0.05),
    ("AC-TOR-01", "Tornillo autorroscante caja x1000", "Complementos", "caja", 46.50, 0.2),
    ("AC-ESQ-30", "Esquinero galvanizado 3 m", "Complementos", "pieza", 6.40, 0.1),
    ("TE-BAL-61", "Baldosa acústica 61x61 cm caja x10", "Cielos rasos", "caja", 92.30, 0.9),
    ("TE-PER-12", "Perfil T principal 3,66 m", "Cielos rasos", "pieza", 11.20, 0.3),
    ("TE-PER-06", "Perfil T secundario 0,61 m", "Cielos rasos", "pieza", 3.10, 0.05),
]

# División nueva (albañilería): sus ventas se generan aparte, con otro generador, para no
# alterar las líneas existentes ni las historias de la demo.
PRODUCTOS_ALBANILERIA = [
    # sku, nombre, grupo, unidad, precio_lista_2025, peso_flete, rango de cantidad
    ("LA-KK-18", "Ladrillo King Kong 18 huecos (millar)", "Ladrillos", "millar", 1150.00, 20.0, (2, 25)),
    ("LA-PAN-01", "Ladrillo pandereta (millar)", "Ladrillos", "millar", 980.00, 16.0, (2, 25)),
    ("CE-TI-425", "Cemento Portland tipo I bolsa 42,5 kg", "Cemento", "bolsa", 32.50, 1.0, (50, 600)),
    ("CE-IP-425", "Cemento tipo IP bolsa 42,5 kg", "Cemento", "bolsa", 29.90, 1.0, (50, 600)),
]
LINEAS_ALBANILERIA_POR_MES = 150

DIVISION = {
    "Planchas de yeso": "Sistemas Livianos", "Perfilería": "Sistemas Livianos", "Complementos": "Sistemas Livianos",
    "Placas cementicias": "Placas Cementicias",
    "Tejas onduladas": "Coberturas", "Cielos rasos": "Coberturas",
    "Ladrillos": "Albañilería", "Cemento": "Albañilería",
}

# Costo estándar como fracción del precio de lista 2025; en 2026 sube 4 %.
COSTO_SOBRE_LISTA = {
    "Planchas de yeso": 0.58, "Placas cementicias": 0.55, "Perfilería": 0.62,
    "Tejas onduladas": 0.54, "Complementos": 0.50, "Cielos rasos": 0.57,
    "Ladrillos": 0.62, "Cemento": 0.78,
}

# Organización comercial y geografía (se asignan con un generador aparte).
DEPARTAMENTOS = {
    "Lima": ["Lima", "Callao"], "Norte": ["La Libertad", "Piura", "Lambayeque", "Cajamarca"],
    "Sur": ["Arequipa", "Cusco", "Puno", "Tacna"], "Centro": ["Junín", "Ica", "Huánuco", "Ayacucho"],
    "Oriente": ["Loreto", "Ucayali", "San Martín"],
}
EJECUTIVOS = {
    "Gerencia Lima": ["Carla Quispe", "Diego Salazar", "Lucía Paredes"],
    "Gerencia Provincias": ["Jorge Huamán", "Rosa Mendoza", "Martín Flores"],
    "Gerencia Proyectos": ["Ana Torres", "Luis Rojas"],
}
INFLACION_COSTO_2026 = 1.04

REGIONES = ["Lima", "Norte", "Sur", "Centro", "Oriente"]
FLETE_POR_REGION = {"Lima": 0.35, "Norte": 0.90, "Sur": 1.00, "Centro": 1.20, "Oriente": 2.40}

CANALES = {
    # canal: (n_clientes, rango dscto_comercial %, rango cantidad, plazos posibles)
    "Distribuidor": (12, (0.12, 0.17), (80, 600), [30, 45, 60]),
    "Ferretería": (26, (0.03, 0.07), (5, 80), [0, 15, 30]),
    "Constructora": (14, (0.08, 0.14), (40, 400), [30, 60, 90]),
    "Retail moderno": (8, (0.05, 0.10), (30, 250), [45, 60, 90]),
}

NOMBRES_BASE = [
    "Andina", "Pacífico", "Los Andes", "Inca", "Del Sur", "Norteña", "Amazonas",
    "Central", "San Martín", "Santa Rosa", "El Constructor", "Mistral", "Huascarán",
    "Misti", "Chavín", "Paracas", "Titicaca", "Kuelap", "Caral", "Moche",
]

TASA_FIN_ANUAL = 0.12
FUGAS = {"CLI-FER-003", "CLI-FER-011"}  # ferreterías con descuento de distribuidor


def _clientes(rnd):
    clientes = []
    prefijos = {"Distribuidor": "DIS", "Ferretería": "FER", "Constructora": "CON", "Retail moderno": "RET"}
    etiquetas = {"Distribuidor": "Distribuidora", "Ferretería": "Ferretería",
                 "Constructora": "Constructora", "Retail moderno": "Retail"}
    for canal, (n, *_rest) in CANALES.items():
        for i in range(1, n + 1):
            cid = f"CLI-{prefijos[canal]}-{i:03d}"
            region = "Sur" if cid in FUGAS else rnd.choice(REGIONES)
            segmento = rnd.choices(["A", "B", "C"], weights=[2, 3, 5])[0]
            nombre = f"{etiquetas[canal]} {rnd.choice(NOMBRES_BASE)} {i}"
            clientes.append((cid, nombre, canal, region, segmento))
    return clientes


def _meses():
    y, m = 2025, 1
    while (y, m) <= (2026, 9):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _jerarquia_comercial(clientes, rnd):
    """Tipo de venta, gerencia, ejecutivo y departamento de cada cliente (generador aparte)."""
    extra = {}
    for cid, _n, canal, region, _s in clientes:
        if canal == "Constructora":
            tipo, gerencia = "Venta Proyectos", "Gerencia Proyectos"
        else:
            tipo, gerencia = "Venta Comercial", "Gerencia Lima" if region == "Lima" else "Gerencia Provincias"
        extra[cid] = (tipo, gerencia, rnd.choice(EJECUTIVOS[gerencia]), rnd.choice(DEPARTAMENTOS[region]))
    return extra


def _clientes_con_historia() -> set[str]:
    """Clientes de las historias de la demo (fugas, excepciones, cartas de rebate): la división
    nueva no les vende, para que sus cifras no cambien."""
    import yaml

    ac = yaml.safe_load((Path(__file__).parent / "acuerdos.yaml").read_text(encoding="utf-8"))
    ids = set(FUGAS)
    ids |= {c["cliente_id"] for c in ac.get("cartas_rebate", [])}
    ids |= {e["cliente_id"] for a in ac.get("actas", []) for e in a.get("excepciones", [])}
    return ids


def generar(destino: Path, lineas_por_mes: int = 1500) -> None:
    rnd = random.Random(SEED)
    destino.mkdir(parents=True, exist_ok=True)
    clientes = _clientes(rnd)
    jerarquia = _jerarquia_comercial(clientes, random.Random(SEED + 1))

    with open(destino / "dim_producto.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sku", "nombre", "categoria", "unidad", "division"])
        for sku, nombre, grupo, unidad, *_ in PRODUCTOS + PRODUCTOS_ALBANILERIA:
            w.writerow([sku, nombre, grupo, unidad, DIVISION[grupo]])

    with open(destino / "dim_costo.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sku", "anio", "costo_unitario"])
        for sku, _n, grupo, _u, precio, *_ in PRODUCTOS + PRODUCTOS_ALBANILERIA:
            costo = precio * COSTO_SOBRE_LISTA[grupo]
            w.writerow([sku, 2025, f"{costo:.2f}"])
            w.writerow([sku, 2026, f"{costo * INFLACION_COSTO_2026:.2f}"])

    with open(destino / "dim_cliente.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["cliente_id", "nombre", "canal", "region", "segmento",
                    "tipo_venta", "gerencia", "ejecutivo", "departamento"])
        w.writerows(c + jerarquia[c[0]] for c in clientes)

    with open(destino / "fact_venta.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "linea_id", "fecha", "cliente_id", "sku", "cantidad", "plazo_pago_dias",
            "precio_lista_unit", "dscto_comercial", "dscto_volumen",
            "dscto_pronto_pago", "flete", "costo_financiero",
        ])
        linea_id = 0
        for y, m in _meses():
            alza = 1.06 if (y, m) >= (2026, 3) else 1.0
            for _ in range(lineas_por_mes):
                linea_id += 1
                cid, _n, canal, region, _segmento = rnd.choice(clientes)
                sku, _nom, _cat, _u, precio_base, peso = rnd.choice(PRODUCTOS)
                _nc, rango_dc, rango_q, plazos = CANALES[canal]

                cantidad = rnd.randint(*rango_q)
                plazo = rnd.choice(plazos)
                precio = round(precio_base * alza, 2)
                bruto = precio * cantidad

                pct_com = rnd.uniform(*rango_dc)
                if cid in FUGAS:
                    pct_com = rnd.uniform(*CANALES["Distribuidor"][1])
                dscto_com = bruto * pct_com
                dscto_vol = bruto * rnd.uniform(0.02, 0.06) if cantidad >= 200 else 0.0
                factura = bruto - dscto_com - dscto_vol

                pronto_pago = factura * 0.02 if plazo <= 15 and rnd.random() < 0.7 else 0.0
                flete = cantidad * peso * FLETE_POR_REGION[region] * rnd.uniform(0.85, 1.25)
                costo_fin = factura * TASA_FIN_ANUAL * plazo / 360

                dia = rnd.randint(1, 28)
                w.writerow([
                    linea_id, date(y, m, dia).isoformat(), cid, sku, cantidad, plazo, f"{precio:.2f}",
                    *(f"{v:.2f}" for v in (dscto_com, dscto_vol, pronto_pago, flete, costo_fin)),
                ])

        # Albañilería: líneas adicionales con su propio generador, dentro de la política de
        # descuentos y sin tocar a los clientes de las historias de la demo.
        rnd_alb = random.Random(SEED + 2)
        excluidos = _clientes_con_historia()
        elegibles = [c for c in clientes if c[0] not in excluidos]
        for y, m in _meses():
            alza = 1.06 if (y, m) >= (2026, 3) else 1.0
            for _ in range(LINEAS_ALBANILERIA_POR_MES):
                linea_id += 1
                cid, _n, canal, region, _segmento = rnd_alb.choice(elegibles)
                sku, _nom, _g, _u, precio_base, peso, rango_q = rnd_alb.choice(PRODUCTOS_ALBANILERIA)
                _nc, rango_dc, _rq, plazos = CANALES[canal]

                cantidad = rnd_alb.randint(*rango_q)
                plazo = rnd_alb.choice(plazos)
                precio = round(precio_base * alza, 2)
                bruto = precio * cantidad
                dscto_com = bruto * rnd_alb.uniform(*rango_dc)
                dscto_vol = bruto * rnd_alb.uniform(0.02, 0.06) if cantidad >= 200 else 0.0
                factura = bruto - dscto_com - dscto_vol
                pronto_pago = factura * 0.02 if plazo <= 15 and rnd_alb.random() < 0.7 else 0.0
                flete = cantidad * peso * FLETE_POR_REGION[region] * rnd_alb.uniform(0.85, 1.25)
                costo_fin = factura * TASA_FIN_ANUAL * plazo / 360

                w.writerow([
                    linea_id, date(y, m, rnd_alb.randint(1, 28)).isoformat(), cid, sku, cantidad, plazo,
                    f"{precio:.2f}", *(f"{v:.2f}" for v in (dscto_com, dscto_vol, pronto_pago, flete, costo_fin)),
                ])


if __name__ == "__main__":
    generar(Path("data/raw"))
