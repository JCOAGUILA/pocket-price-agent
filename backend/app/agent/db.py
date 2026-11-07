"""Acceso a Postgres para las herramientas del agente.

Las consultas usan el usuario `agente_ro` (solo SELECT) en una sesión de
solo lectura y con tiempo máximo: es la barrera real contra escrituras
(OWASP LLM06), independiente de lo que diga el prompt.
"""

import os
import re
from datetime import date
from functools import lru_cache

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_OPCIONES_RO = "-c default_transaction_read_only=on -c statement_timeout=15000"


@lru_cache
def pool_ro() -> ConnectionPool:
    return ConnectionPool(
        os.environ["AGENT_DATABASE_URL"], min_size=1, max_size=5, open=True,
        kwargs={"row_factory": dict_row, "autocommit": True, "options": _OPCIONES_RO},
    )


@lru_cache
def pool_escritura() -> ConnectionPool:
    """Solo para el checkpointer de LangGraph y la herramienta de alertas."""
    return ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=5, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0})


def consultar(sql: str, params: dict | tuple = ()) -> list[dict]:
    with pool_ro().connection() as conn:
        return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------- periodos

class PeriodoInvalido(ValueError):
    pass


def _inicio(p: str) -> date:
    if m := re.fullmatch(r"(\d{4})", p):
        return date(int(m[1]), 1, 1)
    if m := re.fullmatch(r"(\d{4})-Q([1-4])", p, re.I):
        return date(int(m[1]), 3 * int(m[2]) - 2, 1)
    if m := re.fullmatch(r"(\d{4})-(\d{2})", p):
        return date(int(m[1]), int(m[2]), 1)
    raise PeriodoInvalido(
        f"Periodo '{p}' no válido. Usa AAAA (2026), AAAA-Qn (2026-Q1) o AAAA-MM (2026-03).")


def _fin(p: str) -> date:
    ini = _inicio(p)
    if re.fullmatch(r"\d{4}", p):
        return date(ini.year, 12, 31)
    meses = 3 if "Q" in p.upper() else 1
    mes_sig = ini.month + meses
    sig = date(ini.year + (mes_sig - 1) // 12, (mes_sig - 1) % 12 + 1, 1)
    return date.fromordinal(sig.toordinal() - 1)


def rango(desde: str, hasta: str | None = None) -> tuple[date, date]:
    """'2026-Q1' -> (2026-01-01, 2026-03-31); desde/hasta pueden mezclar formatos."""
    a, b = _inicio(desde.strip()), _fin((hasta or desde).strip())
    if b < a:
        raise PeriodoInvalido("El periodo 'hasta' es anterior a 'desde'.")
    if a > date(2026, 9, 30) or b < date(2025, 1, 1):
        raise PeriodoInvalido("Solo hay datos entre 2025-01 y 2026-09.")
    return a, b


# ---------------------------------------------------------------- catálogo

@lru_cache
def catalogo() -> dict[str, list]:
    valores = {
        "canal": [r["v"] for r in consultar("SELECT DISTINCT canal v FROM dim_cliente ORDER BY 1")],
        "region": [r["v"] for r in consultar("SELECT DISTINCT region v FROM dim_cliente ORDER BY 1")],
        "categoria": [r["v"] for r in consultar("SELECT DISTINCT categoria v FROM dim_producto ORDER BY 1")],
        "division": [r["v"] for r in consultar("SELECT DISTINCT division v FROM dim_producto ORDER BY 1")],
        "gerencia": [r["v"] for r in consultar("SELECT DISTINCT gerencia v FROM dim_cliente ORDER BY 1")],
        "ejecutivo": [r["v"] for r in consultar("SELECT DISTINCT ejecutivo v FROM dim_cliente ORDER BY 1")],
        "departamento": [r["v"] for r in consultar("SELECT DISTINCT departamento v FROM dim_cliente ORDER BY 1")],
    }
    valores["cliente_id"] = [r["v"] for r in consultar("SELECT cliente_id v FROM dim_cliente ORDER BY 1")]
    valores["sku"] = [r["v"] for r in consultar("SELECT sku v FROM dim_producto ORDER BY 1")]
    return valores


def validar_filtros(**filtros) -> dict:
    """Valida filtros contra el catálogo y devuelve solo los informados."""
    cat = catalogo()
    limpios = {}
    for clave, valor in filtros.items():
        if valor in (None, ""):
            continue
        if valor not in cat[clave]:
            opciones = cat[clave] if len(cat[clave]) <= 10 else cat[clave][:10] + ["..."]
            raise ValueError(f"{clave}='{valor}' no existe. Valores válidos: {opciones}. "
                             "Usa la herramienta 'catalogo' para buscar.")
        limpios[clave] = valor
    return limpios


def where(filtros: dict, desde: date, hasta: date, alias: str = "") -> tuple[str, dict]:
    p = f"{alias}." if alias else ""
    cond = [f"{p}fecha BETWEEN %(desde)s AND %(hasta)s"]
    cond += [f"{p}{k} = %({k})s" for k in filtros]
    return " AND ".join(cond), {"desde": desde, "hasta": hasta, **filtros}
