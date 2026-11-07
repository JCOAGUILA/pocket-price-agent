"""Recuperación sobre el repositorio documental (Elasticsearch).

Búsqueda híbrida: una consulta semántica (kNN sobre embeddings) y otra léxica
(BM25, encuentra códigos exactos como "CLI-FER-003" o "CP-02-2026"), ambas con
los mismos filtros, fusionadas con Reciprocal Rank Fusion en la aplicación
(el RRF nativo de Elasticsearch requiere licencia de pago).

Filtros de metadatos:
- tipo, cliente_id, canal: igualdad sobre campos keyword.
- fecha_referencia: documentos vigentes a esa fecha. Los documentos sin
  vigencia (actas, glosario) no se excluyen.
"""

import os
from datetime import date
from functools import lru_cache

from elasticsearch import Elasticsearch

from common import rag

TIPOS = ("politica", "grid_comercial", "campana", "carta_rebate", "acta", "tarifario", "glosario")
# El índice guarda los grids comerciales con el tipo interno "grilla"; hacia el agente se expone
# solo "grid_comercial", que es el término de uso comercial.
_TIPO_INTERNO = {"grid_comercial": "grilla"}
_TIPO_PUBLICO = {v: k for k, v in _TIPO_INTERNO.items()}
RRF_K = 60
# Similitud semántica mínima (coseno normalizado de Elasticsearch, 0-1). Calibrado con
# consultas relevantes (0,725-0,83) e irrelevantes (0,58-0,67); ver README, sección 3.4.
UMBRAL_RELEVANCIA = float(os.environ.get("RAG_UMBRAL", "0.70"))


@lru_cache
def _es():
    return Elasticsearch(rag.ES_URL)


@lru_cache
def _embed():
    return rag.embeddings()


def _termino(campo: str, valor: str) -> dict:
    return {"term": {f"metadata.{campo}.keyword": valor}}


def _vigente(fecha: date) -> dict:
    f = fecha.isoformat()
    return {"bool": {"should": [
        {"bool": {"must_not": {"exists": {"field": "metadata.vigencia_desde"}}}},
        {"bool": {"must": [
            {"range": {"metadata.vigencia_desde": {"lte": f}}},
            {"bool": {"should": [
                {"bool": {"must_not": {"exists": {"field": "metadata.vigencia_hasta"}}}},
                {"range": {"metadata.vigencia_hasta": {"gte": f}}},
            ]}},
        ]}},
    ]}}


def _semantica(consulta: str, filtros: list, n: int) -> list[tuple[str, str, dict, float]]:
    # kNN con el cliente síncrono: el wrapper síncrono del store de LlamaIndex usa
    # asyncio por dentro y falla en los hilos donde LangGraph ejecuta las herramientas.
    knn = {"field": "embedding", "query_vector": _embed().get_query_embedding(consulta),
           "k": n, "num_candidates": max(50, n * 10)}
    if filtros:
        knn["filter"] = filtros
    r = _es().search(index=rag.INDICE, size=n, knn=knn, source_excludes=["embedding"])
    return [(h["_id"], h["_source"]["content"], h["_source"]["metadata"], h["_score"])
            for h in r["hits"]["hits"]]


def _lexica(consulta: str, filtros: list, n: int) -> list[tuple[str, str, dict]]:
    r = _es().search(index=rag.INDICE, size=n, source_excludes=["embedding"], query={"bool": {
        "must": {"match": {"content": consulta}}, "filter": filtros}})
    return [(h["_id"], h["_source"]["content"], h["_source"]["metadata"]) for h in r["hits"]["hits"]]


def buscar(consulta: str, tipo: str | None = None, cliente_id: str | None = None,
           canal: str | None = None, fecha_referencia: date | None = None, top_k: int = 4) -> list[dict]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("El índice documental no está disponible (falta la clave de embeddings).")
    filtros = []
    if tipo:
        filtros.append(_termino("tipo", _TIPO_INTERNO.get(tipo, tipo)))
    if cliente_id:
        filtros.append(_termino("clientes", cliente_id))
    if canal:
        filtros.append(_termino("canales", canal))
    if fecha_referencia:
        filtros.append(_vigente(fecha_referencia))

    semantica = _semantica(consulta, filtros, top_k * 3)
    similitud = {id_: s for id_, _t, _m, s in semantica}

    # Reciprocal Rank Fusion: puntaje = sum(1 / (k + posición)) en cada lista.
    puntajes: dict[str, float] = {}
    nodos: dict[str, tuple[str, dict]] = {}
    listas = ([(i, t, m) for i, t, m, _s in semantica], _lexica(consulta, filtros, top_k * 3))
    for lista in listas:
        for pos, (id_, texto, meta) in enumerate(lista, 1):
            puntajes[id_] = puntajes.get(id_, 0.0) + 1.0 / (RRF_K + pos)
            nodos[id_] = (texto, meta)

    # Umbral de relevancia: un fragmento entra solo si es semánticamente cercano.
    # Evita "rellenar" con documentos que no responden (y que el LLM podría citar).
    relevantes = [i for i in puntajes if similitud.get(i, 0.0) >= UMBRAL_RELEVANCIA]

    salida = []
    for id_ in sorted(relevantes, key=puntajes.get, reverse=True)[:top_k]:
        texto, m = nodos[id_]
        salida.append({
            "documento_id": m.get("documento_id"),
            "titulo": m.get("titulo"),
            "tipo": _TIPO_PUBLICO.get(m.get("tipo"), m.get("tipo")),
            "fecha": m.get("fecha"),
            "vigencia": f"{m.get('vigencia_desde', '-')} a {m.get('vigencia_hasta', '-')}",
            "pagina": m.get("page_label"),
            "similitud": round(similitud[id_], 3),
            "relevancia_rrf": round(puntajes[id_], 4),
            "texto": texto.strip()[:1200],
        })
    return salida
