"""Ingesta documental (servicio `ingesta` del compose; en GCP, un Cloud Run Job).

1. Descarga los documentos del bucket (docs/) junto con su manifiesto de metadatos.
2. LlamaIndex: lectura (PDF, DOCX, MD) -> fragmentación por oraciones ->
   embeddings de OpenAI -> Elasticsearch, con metadatos para filtrar.
3. Extracción estructurada con LLM de los acuerdos fuera de SAP -> Postgres.
"""

import json
import os
import tempfile
import time
from pathlib import Path

import psycopg
from elasticsearch import Elasticsearch
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter

from common import cloud, rag
from extraccion import extraer_documentos


def descargar_documentos(destino: Path) -> list[dict]:
    claves = cloud.listar("docs/")
    for clave in claves:
        ruta = destino / clave.removeprefix("docs/")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(cloud.leer(clave))
    print(f"[ingesta] {len(claves)} archivos descargados del bucket")
    return json.loads((destino / "manifiesto.json").read_text(encoding="utf-8"))


def cargar(destino: Path, manifiesto: list[dict]):
    por_archivo = {str((destino / m["archivo"]).resolve()): m for m in manifiesto}
    lector = SimpleDirectoryReader(
        input_files=list(por_archivo),
        file_metadata=lambda ruta: dict(por_archivo[str(Path(ruta).resolve())]),
    )
    documentos = lector.load_data()
    for d in documentos:
        d.excluded_embed_metadata_keys = rag.METADATOS_SOLO_FILTRO
        d.excluded_llm_metadata_keys = [k for k in rag.METADATOS_SOLO_FILTRO if k != "documento_id"]
    print(f"[ingesta] {len(documentos)} documentos leídos (PDF por página, DOCX y MD completos)")
    return documentos


def esperar_elasticsearch(intentos=60):
    es = Elasticsearch(rag.ES_URL)
    for i in range(intentos):
        try:
            if es.cluster.health(wait_for_status="yellow", timeout="5s")["status"] in ("yellow", "green"):
                return es
        except Exception as exc:
            print(f"[ingesta] esperando Elasticsearch ({i + 1}/{intentos}): {exc.__class__.__name__}")
        time.sleep(3)
    raise RuntimeError("Elasticsearch no respondió")


def indexar(documentos) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("[ingesta] AVISO: sin OPENAI_API_KEY no se generan embeddings; se omite la indexación")
        return
    es = esperar_elasticsearch()
    if es.indices.exists(index=rag.INDICE):
        if os.environ.get("REINDEXAR", "false") != "true":
            n = es.count(index=rag.INDICE)["count"]
            print(f"[ingesta] índice '{rag.INDICE}' ya existe con {n} fragmentos; se omite (REINDEXAR=true para rehacer)")
            return
        es.indices.delete(index=rag.INDICE)
    pipeline = IngestionPipeline(transformations=[
        SentenceSplitter(chunk_size=400, chunk_overlap=60),
        rag.embeddings(),
    ])
    nodos = pipeline.run(documents=documentos, show_progress=False)
    contexto = StorageContext.from_defaults(vector_store=rag.vector_store())
    VectorStoreIndex(nodos, storage_context=contexto, embed_model=rag.embeddings())
    print(f"[ingesta] {len(nodos)} fragmentos indexados en Elasticsearch ('{rag.INDICE}')")


def main():
    cloud.cargar_secretos_en_entorno()
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp)
        manifiesto = descargar_documentos(destino)
        documentos = cargar(destino, manifiesto)
        indexar(documentos)

        textos: dict[str, str] = {}
        for d in documentos:
            doc_id = d.metadata["documento_id"]
            textos[doc_id] = (textos.get(doc_id, "") + "\n" + d.text).strip()
        rutas = {m["documento_id"]: str(destino / m["archivo"]) for m in manifiesto}
        if os.environ.get("ANTHROPIC_API_KEY"):
            extraer_documentos(manifiesto, textos, rutas)
        else:
            print("[ingesta] AVISO: sin ANTHROPIC_API_KEY no se extraen los acuerdos")
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("REFRESH MATERIALIZED VIEW mv_cascada_real")
    print("[ingesta] cascada real materializada; listo")


if __name__ == "__main__":
    main()
