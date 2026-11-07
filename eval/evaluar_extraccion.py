"""Evalúa la extracción con LLM comparando lo cargado en Postgres contra la
fuente de verdad (infra/init/acuerdos.yaml), campo por campo.

Uso (con el stack levantado):
    python eval/evaluar_extraccion.py                 # reporte local
    docker compose run --rm --no-deps -v ./eval:/eval:ro -v ./infra/init:/init:ro \
        -e ACUERDOS=/init/acuerdos.yaml -e EVAL_DSN=postgresql://pp:pp@postgres:5432/pocketprice \
        backend python /eval/evaluar_extraccion.py --langsmith   # experimento en LangSmith
"""

import json
import os
import sys
from pathlib import Path

import psycopg
import yaml

RAIZ = Path(__file__).resolve().parents[1]
DSN = os.environ.get("EVAL_DSN", "postgresql://pp:pp@localhost:5433/pocketprice")
ACUERDOS = Path(os.environ.get("ACUERDOS", RAIZ / "infra/init/acuerdos.yaml"))
DATASET = "pocket-price · extracción de acuerdos"


def esperado() -> dict[tuple, dict]:
    ac = yaml.safe_load(ACUERDOS.read_text(encoding="utf-8"))
    e: dict[tuple, dict] = {}
    for p in ac["politicas_descuento"]:
        for canal, tope in p["topes_comercial"].items():
            e[("tope", p["id"], canal)] = {"tope_pct": tope, "desde": p["vigencia_desde"], "hasta": p["vigencia_hasta"]}
    for g in ac["grillas"]:
        for f in g["filas"]:
            e[("grilla", f["id"])] = {"categoria": f["categoria"], "canal": f["canal"], "pct": f["pct"],
                                      "desde": f["desde"], "hasta": f["hasta"]}
    for c in ac["campanas"]:
        e[("campana", c["id"])] = {"canal": c["canal"], "cantidad_min": c["cantidad_min"], "pct": c["pct"],
                                   "desde": c["desde"], "hasta": c["hasta"]}
    vig = ac["vigencia_cartas"]
    for c in ac["cartas_rebate"]:
        e[("rebate", c["id"])] = {"cliente_id": c["cliente_id"], "objetivo": c["objetivo_trimestral"],
                                  "tramos": [(t["cumplimiento_min"], t["pct"]) for t in c["tramos"]],
                                  "desde": vig["desde"], "hasta": vig["hasta"]}
    for a in ac["actas"]:
        for x in a["excepciones"]:
            e[("excepcion", a["id"], x["cliente_id"])] = {"estado": x["estado"], "tope_pct": x["tope"],
                                                          "desde": x["desde"], "hasta": x["hasta"]}
    return e


def extraido(conn) -> dict[tuple, dict]:
    r: dict[tuple, dict] = {}
    for doc, canal, tope, d, h in conn.execute("SELECT documento_id, canal, tope_pct, vigencia_desde, vigencia_hasta FROM topes_politica"):
        r[("tope", doc, canal)] = {"tope_pct": float(tope), "desde": d, "hasta": h}
    filas = conn.execute("""SELECT id, tipo, cliente_id, canal, categoria, cantidad_min, pct, objetivo_unidades,
                                   tramos, vigencia_desde, vigencia_hasta FROM condiciones_extra_sap""")
    for id_, tipo, cli, canal, cat, cmin, pct, obj, tramos, d, h in filas:
        if tipo == "grilla":
            r[("grilla", id_)] = {"categoria": cat, "canal": canal, "pct": float(pct), "desde": d, "hasta": h}
        elif tipo == "campana":
            r[("campana", id_)] = {"canal": canal, "cantidad_min": cmin, "pct": float(pct), "desde": d, "hasta": h}
        else:
            r[("rebate", id_)] = {"cliente_id": cli, "objetivo": obj,
                                  "tramos": [(t["cumplimiento_min"], t["pct"]) for t in tramos],
                                  "desde": d, "hasta": h}
    for doc, cli, est, tope, d, h in conn.execute(
            "SELECT documento_id, cliente_id, estado, tope_pct, vigencia_desde, vigencia_hasta FROM excepciones_comite"):
        r[("excepcion", doc, cli)] = {"estado": est, "tope_pct": float(tope) if tope is not None else None,
                                      "desde": d, "hasta": h}
    return r


def _igual(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-6
    if isinstance(a, list):
        return (isinstance(b, list) and len(a) == len(b)
                and all(_igual(x[0], y[0]) and _igual(x[1], y[1]) for x, y in zip(a, b)))
    return a == b


def evaluar() -> dict:
    with psycopg.connect(DSN) as conn:
        esp, ext = esperado(), extraido(conn)
    campos_ok = campos_total = 0
    errores = []
    for clave, valores in esp.items():
        obtenido = ext.get(clave)
        if obtenido is None:
            errores.append(f"FALTA   {clave}")
            campos_total += len(valores)
            continue
        for campo, v in valores.items():
            campos_total += 1
            if _igual(v, obtenido.get(campo)):
                campos_ok += 1
            else:
                errores.append(f"DIFIERE {clave}.{campo}: esperado={v} obtenido={obtenido.get(campo)}")
    sobrantes = [k for k in ext if k not in esp]
    errores += [f"SOBRA   {k}" for k in sobrantes]
    return {
        "registros_esperados": len(esp),
        "registros_encontrados": len(esp) - sum(e.startswith("FALTA") for e in errores),
        "registros_sobrantes": len(sobrantes),
        "precision_campos": campos_ok / campos_total if campos_total else 0.0,
        "errores": errores,
    }


def _serializable(d: dict | None) -> dict | None:
    return None if d is None else json.loads(json.dumps(d, default=str))


def evaluar_en_langsmith() -> None:
    """Un ejemplo por registro esperado; la 'salida' es lo que la ingesta dejó en Postgres."""
    from langsmith import Client

    from common import cloud
    cloud.cargar_secretos_en_entorno()
    client = Client()
    esp = esperado()
    if not client.has_dataset(dataset_name=DATASET):
        ds = client.create_dataset(DATASET, description="Acuerdos fuera de SAP: valor esperado por registro "
                                                         "(fuente: acuerdos.yaml).")
        client.create_examples(dataset_id=ds.id,
                               inputs=[{"clave": "|".join(k)} for k in esp],
                               outputs=[{"esperado": _serializable(v)} for v in esp.values()])

    with psycopg.connect(DSN) as conn:
        ext = {"|".join(k): _serializable(v) for k, v in extraido(conn).items()}

    def objetivo(inputs: dict) -> dict:
        return {"extraido": ext.get(inputs["clave"])}

    def registro_encontrado(outputs: dict, reference_outputs: dict) -> bool:
        return outputs["extraido"] is not None

    def precision_campos(outputs: dict, reference_outputs: dict) -> float:
        esp_, obt = reference_outputs["esperado"], outputs["extraido"] or {}
        return sum(_igual(v, obt.get(c)) for c, v in esp_.items()) / len(esp_)

    r = client.evaluate(objetivo, data=DATASET, evaluators=[registro_encontrado, precision_campos],
                        experiment_prefix="extraccion-claude-sonnet-5-5",
                        metadata={"modelo_extraccion": "claude-sonnet-5-5"})
    print("Experimento:", r.experiment_name)


if __name__ == "__main__":
    if "--langsmith" in sys.argv:
        evaluar_en_langsmith()
    res = evaluar()
    print(json.dumps({k: v for k, v in res.items() if k != "errores"}, indent=2, default=str))
    for e in res["errores"]:
        print(" ", e)
    sys.exit(0 if not res["errores"] else 1)
