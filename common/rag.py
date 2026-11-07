"""Configuración compartida del RAG: Elasticsearch como vector store y
embeddings de OpenAI. La usan la ingesta (escribe) y el backend (lee)."""

import os

from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.elasticsearch import AsyncDenseVectorStrategy, ElasticsearchStore

ES_URL = os.environ.get("ES_URL", "http://elasticsearch:9200")
INDICE = os.environ.get("ES_INDEX", "documentos_pricing")
MODELO_EMBEDDINGS = "text-embedding-3-small"

# Metadatos que se usan para filtrar, pero que no deben "ensuciar" el texto
# que se vectoriza.
METADATOS_SOLO_FILTRO = [
    "archivo", "documento_id", "fecha", "vigencia_desde", "vigencia_hasta",
    "clientes", "canales", "categorias", "file_path", "file_name", "file_type",
    "file_size", "creation_date", "last_modified_date", "page_label",
]


def embeddings() -> OpenAIEmbedding:
    return OpenAIEmbedding(model=MODELO_EMBEDDINGS)


def vector_store() -> ElasticsearchStore:
    # Solo denso: el RRF nativo de Elasticsearch requiere licencia de pago, así
    # que la fusión híbrida (BM25 + semántica) se hace en la aplicación
    # (ver backend/app/agent/documentos.py).
    return ElasticsearchStore(
        index_name=INDICE,
        es_url=ES_URL,
        retrieval_strategy=AsyncDenseVectorStrategy(hybrid=False),
    )
