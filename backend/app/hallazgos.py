"""Hallazgos proactivos: detectores deterministas (SQL, sin LLM) que la app muestra
al abrir, al estilo de los agentes de monitoreo de Pricefx o Vendavo. Cada hallazgo
trae una pregunta sugerida para profundizar con el agente."""

from .agent import db
from .agent.herramientas import detectar_fugas


def _soles(x: float) -> str:
    return f"S/ {x:,.0f}".replace(",", ".")


def _pct(x: float, d: int = 1) -> str:
    return f"{x:.{d}f} %".replace(".", ",")


def fuga_no_autorizada() -> dict | None:
    """El cliente con mayor exceso de descuento sin excepción aprobada en el último año."""
    anio = db.consultar("SELECT EXTRACT(YEAR FROM MAX(fecha))::int AS a FROM mv_cascada_real")[0]["a"]
    r = detectar_fugas.invoke({"desde": str(anio), "top_n": 25})
    clientes = [c for c in r.get("clientes", []) if isinstance(c, dict) and c["exceso_no_autorizado_pen"] > 0]
    if not clientes:
        return None
    c = max(clientes, key=lambda x: x["exceso_no_autorizado_pen"])
    rechazo = c.get("excepcion_rechazada")
    detalle = (f"Dscto. {_pct(c['dscto_promedio_pct'])} vs tope {_pct(c['tope_politica_pct'], 0)}"
               + (f"; excepción rechazada ({rechazo['documento_id']})." if rechazo else "; sin excepción."))
    return {"tono": "peligro", "icono": "gpp_maybe", "etiqueta": "Fuga de pocket price",
            "metrica": f"−{_soles(c['exceso_no_autorizado_pen'])}", "metrica_sub": f"{c['cliente']} · {anio}",
            "detalle": detalle,
            "pregunta": f"¿Hay fugas de precio en el canal {c['canal']} en {anio}?"}


def rebate_por_escalar() -> dict | None:
    """El cliente más cerca de subir de tramo en su carta de rebate (último trimestre con datos)."""
    filas = db.consultar("""
        WITH t AS (SELECT MAX(trimestre) AS q FROM mv_cascada_real),
        v AS (SELECT cliente_id, cliente, SUM(cantidad) AS u, SUM(venta_factura) AS vf
              FROM mv_cascada_real, t WHERE trimestre = t.q GROUP BY 1, 2)
        SELECT v.*, c.objetivo_unidades AS obj, c.tramos, c.documento_id,
               to_char((SELECT q FROM t), 'YYYY-"Q"Q') AS trimestre,
               (SELECT SUM(venta_pocket_real) FROM mv_cascada_real m, t
                 WHERE m.cliente_id = v.cliente_id AND m.trimestre = t.q) AS pocket,
               (SELECT SUM(margen_real) FROM mv_cascada_real m, t
                 WHERE m.cliente_id = v.cliente_id AND m.trimestre = t.q) AS margen
        FROM v JOIN condiciones_extra_sap c ON c.tipo = 'rebate' AND c.cliente_id = v.cliente_id""")
    mejor = None
    for f in filas:
        cumpl = f["u"] / f["obj"]
        tramos = sorted(f["tramos"], key=lambda t: t["cumplimiento_min"])
        actual = max((t["pct"] for t in tramos if cumpl >= t["cumplimiento_min"]), default=0.0)
        siguiente = next((t for t in tramos if t["cumplimiento_min"] > cumpl), None)
        if not siguiente:
            continue
        faltan = siguiente["cumplimiento_min"] * f["obj"] - f["u"]
        brecha = faltan / f["obj"]
        if mejor is None or brecha < mejor["brecha"]:
            mejor = {**f, "cumpl": cumpl, "actual": actual, "siguiente": siguiente["pct"], "faltan": faltan,
                     "brecha": brecha, "costo_extra": (siguiente["pct"] - actual) * float(f["vf"])}
    if not mejor or mejor["brecha"] > 0.05:
        return None
    m = mejor
    pocket, margen, extra = float(m["pocket"]), float(m["margen"]), m["costo_extra"]
    caida_pp = 100 * ((margen - extra) / (pocket - extra) - margen / pocket)  # margen del cliente sobre pocket
    return {"tono": "alerta", "icono": "trending_up", "etiqueta": "Riesgo de margen por rebate",
            "metrica": f"{caida_pp:.1f} pp".replace(".", ",").replace("-", "−"),
            "metrica_sub": f"de margen · {m['cliente']}",
            "detalle": (f"A {f'{m['faltan']:,.0f}'.replace(',', '.')} unid. de pasar del {_pct(100 * m['actual'])} al "
                        f"{_pct(100 * m['siguiente'], 0)} de rebate (+{_soles(extra)}/trim.)."),
            "pregunta": f"¿Cuánto rebate le corresponde a {m['cliente']} en {m['trimestre'][:4]} y qué dice su carta?"}


def costo_sin_trasladar() -> dict | None:
    """Meses en que el costo estándar ya subió pero la lista de precios aún no (índice sin efecto mezcla)."""
    alza_costo = db.consultar("""
        SELECT AVG(n.costo_unitario / a.costo_unitario) - 1 AS alza, MAX(n.anio) AS anio
        FROM dim_costo n JOIN dim_costo a ON a.sku = n.sku AND a.anio = n.anio - 1""")[0]
    if not alza_costo["alza"] or alza_costo["alza"] <= 0:
        return None
    anio = alza_costo["anio"]
    meses = db.consultar("""
        WITH base AS (SELECT sku, AVG(precio_lista_unit) AS p0 FROM mv_cascada_real
                      WHERE fecha BETWEEN make_date(%(a)s - 1, 12, 1) AND make_date(%(a)s - 1, 12, 31) GROUP BY sku)
        SELECT date_trunc('month', v.fecha)::date AS mes,
               AVG(v.precio_lista_unit / b.p0) AS indice_lista,
               100 * SUM(v.margen_real) / SUM(v.venta_pocket_real) AS margen,
               SUM(v.venta_pocket_real) AS pocket
        FROM mv_cascada_real v JOIN base b USING (sku)
        WHERE v.fecha >= make_date(%(a)s - 1, 10, 1)
        GROUP BY 1 ORDER BY 1""", {"a": anio})
    previos = [m for m in meses if m["mes"].year < anio]
    sin_alza = [m for m in meses if m["mes"].year == anio and m["indice_lista"] < 1.005]
    con_alza = [m for m in meses if m["mes"].year == anio and m["indice_lista"] >= 1.005]
    if not (previos and sin_alza):
        return None
    prom = lambda xs: sum(float(x["margen"]) for x in xs) / len(xs)  # noqa: E731
    nombres = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    ventana = f"{nombres[sin_alza[0]['mes'].month - 1]}–{nombres[sin_alza[-1]['mes'].month - 1]} {anio}"
    caida_pp = prom(sin_alza) - prom(previos)
    perdido = -caida_pp / 100 * sum(float(m["pocket"]) for m in sin_alza)  # margen perdido vs. el nivel previo
    detalle = f"Costo +{_pct(100 * float(alza_costo['alza']), 0)} sin alza de lista ({ventana})"
    detalle += f"; volvió a {_pct(prom(con_alza))} con el alza." if con_alza else "."
    return {"tono": "alerta", "icono": "price_change", "etiqueta": "Margen erosionado por costo",
            "metrica": f"{caida_pp:.1f} pp".replace(".", ",").replace("-", "−"),
            "metrica_sub": f"de margen · −{_soles(perdido)}",
            "detalle": detalle,
            "pregunta": f"¿Por qué cambió el pocket price y el margen entre {anio - 1}-Q4 y {anio}-Q1?"}


def alza_capturada() -> dict | None:
    """Buena noticia: cuánto del último alza de lista llegó al pocket price (realización de precio).
    Compara cada producto consigo mismo, ponderado por el volumen posterior (sin efecto mezcla)."""
    anio = db.consultar("SELECT EXTRACT(YEAR FROM MAX(fecha))::int AS a FROM mv_cascada_real")[0]["a"]
    mes_alza = db.consultar("""
        WITH base AS (SELECT sku, AVG(precio_lista_unit) AS p0 FROM mv_cascada_real
                      WHERE fecha BETWEEN make_date(%(a)s - 1, 12, 1) AND make_date(%(a)s - 1, 12, 31) GROUP BY sku)
        SELECT MIN(date_trunc('month', v.fecha))::date AS mes FROM mv_cascada_real v JOIN base b USING (sku)
        WHERE v.fecha >= make_date(%(a)s, 1, 1) AND v.precio_lista_unit / b.p0 >= 1.005""", {"a": anio})[0]["mes"]
    if not mes_alza:
        return None
    r = db.consultar("""
        WITH a AS (SELECT sku, SUM(venta_lista) / SUM(cantidad) AS l0, SUM(venta_pocket_real) / SUM(cantidad) AS p0
                   FROM mv_cascada_real
                   WHERE fecha BETWEEN make_date(%(a)s - 1, 10, 1) AND make_date(%(a)s - 1, 12, 31) GROUP BY sku),
             b AS (SELECT sku, SUM(cantidad) AS u, SUM(venta_lista) / SUM(cantidad) AS l1,
                          SUM(venta_pocket_real) / SUM(cantidad) AS p1
                   FROM mv_cascada_real WHERE fecha >= %(m)s GROUP BY sku)
        SELECT SUM(b.u * b.l1) / SUM(b.u * a.l0) - 1 AS alza_lista,
               SUM(b.u * b.p1) / SUM(b.u * a.p0) - 1 AS alza_pocket,
               SUM(b.u * (b.p1 - a.p0)) AS ganancia,
               SUM(b.u * (b.p1 - a.p0)) / NULLIF(SUM(b.u * (b.l1 - a.l0)), 0) AS realizacion
        FROM a JOIN b USING (sku)""", {"a": anio, "m": mes_alza})[0]
    if not r["ganancia"] or float(r["ganancia"]) <= 0:
        return None
    nombres = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    ganancia = float(r["ganancia"])
    valor = f"+S/ {ganancia / 1e6:,.2f} MM".replace(".", ",") if ganancia >= 1e6 else f"+{_soles(ganancia)}"
    return {"tono": "positivo", "icono": "trending_up", "etiqueta": "Alza de precios capturada",
            "metrica": valor, "metrica_sub": f"de pocket desde {nombres[mes_alza.month - 1]} {anio}",
            "detalle": (f"Lista +{_pct(100 * float(r['alza_lista']))} → pocket +{_pct(100 * float(r['alza_pocket']))}: "
                        f"capturado el {_pct(100 * float(r['realizacion']), 0)} del alza."),
            "pregunta": f"¿Cuánto del alza de lista de {anio} llegó al pocket price y dónde se fugó el resto?"}


def calcular() -> list[dict]:
    hallazgos = []
    # Primero el logro y luego los riesgos: abrir con una buena noticia da contexto a las alertas.
    for detector in (alza_capturada, fuga_no_autorizada, rebate_por_escalar, costo_sin_trasladar):
        try:
            h = detector()
        except Exception:  # un detector que falla no debe tumbar la pantalla de inicio
            h = None
        if h:
            hallazgos.append(h)
    return hallazgos
