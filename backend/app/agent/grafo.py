"""Grafo del asistente (arquitectura híbrida):

    START -> guardia_entrada --(bloqueado)--> END
                  |
              clasificar --(fuera_de_dominio)--> fuera_de_dominio -> END
                  |------(concepto)-----------> concepto (workflow RAG) -> END
                  '------(analisis)-----------> agente (create_agent ReAct + herramientas) -> END

La memoria de corto plazo es un checkpointer en Postgres (en GCP: Cloud SQL),
por hilo de conversación (thread_id).
"""

import os
from functools import lru_cache
from typing import Literal

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware, ModelCallLimitMiddleware, ModelFallbackMiddleware, PIIMiddleware,
    SummarizationMiddleware, ToolCallLimitMiddleware, ToolRetryMiddleware,
)
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from . import documentos, prompts
from .guardrails import VerificarRespaldo, validar_entrada
from .herramientas import HERRAMIENTAS

MODELO_AGENTE = os.environ.get("MODELO_AGENTE", "claude-sonnet-5-5")
MODELO_RAPIDO = os.environ.get("MODELO_RAPIDO", "claude-haiku-5-5")
MODELO_RESPALDO = os.environ.get("MODELO_RESPALDO", "openai:gpt-5-mini")


class Estado(MessagesState):
    ruta: str


class Clasificacion(BaseModel):
    categoria: Literal["analisis", "concepto", "fuera_de_dominio"]


def _ultima_pregunta(state: Estado) -> str:
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):
            return m.text if isinstance(m.text, str) else str(m.content)
    return ""


# ---------------------------------------------------------------- nodos

def guardia_entrada(state: Estado) -> dict:
    rechazo = validar_entrada(_ultima_pregunta(state))
    if rechazo:
        return {"ruta": "bloqueado", "messages": [AIMessage(content=rechazo)]}
    return {"ruta": ""}


def clasificar(state: Estado) -> dict:
    # Solo texto: el clasificador no necesita (ni debe recibir) llamadas a herramientas.
    previos = [m for m in state["messages"][:-1] if isinstance(m, (HumanMessage, AIMessage)) and m.text][-4:]
    contexto = "\n".join(f"{'Usuario' if isinstance(m, HumanMessage) else 'Asistente'}: {m.text[:300]}"
                         for m in previos)
    llm = ChatAnthropic(model=MODELO_RAPIDO, max_retries=2).with_structured_output(
        Clasificacion, method="json_schema")
    try:
        c = llm.invoke([("system", prompts.SISTEMA_CLASIFICADOR),
                        ("human", f"<contexto>\n{contexto or '(sin mensajes previos)'}\n</contexto>\n"
                                  f"<mensaje>{_ultima_pregunta(state)}</mensaje>")])
        return {"ruta": c.categoria}
    except Exception:
        return {"ruta": "analisis"}  # ante la duda, el agente (que también filtra el dominio) decide


def fuera_de_dominio(state: Estado) -> dict:
    return {"messages": [AIMessage(content=prompts.FUERA_DE_DOMINIO)]}


def concepto(state: Estado) -> dict:
    """Workflow simple de RAG: recuperar -> responder con citas. Sin herramientas ni bucles."""
    pregunta = _ultima_pregunta(state)
    try:
        fragmentos = documentos.buscar(pregunta, top_k=4)
    except Exception:
        fragmentos = []
    if not fragmentos:
        return {"messages": [AIMessage(content="No encontré documentos que respondan esa pregunta. "
                                               "¿Puedes reformularla o indicar el tipo de documento?")]}
    contexto = "\n\n".join(f"<fragmento documento_id='{f['documento_id']}'>\n{f['texto']}\n</fragmento>"
                           for f in fragmentos)
    llm = ChatAnthropic(model=MODELO_RAPIDO, max_retries=2)
    respuesta = llm.invoke([("system", prompts.SISTEMA_CONCEPTO),
                            ("human", f"{contexto}\n\nPregunta: {pregunta}")])
    return {"messages": [AIMessage(content=respuesta.text)]}


def _middlewares() -> list:
    capas = [
        PIIMiddleware("email", strategy="redact", apply_to_input=True),       # LLM02
        ModelCallLimitMiddleware(run_limit=12, exit_behavior="end"),          # LLM10
        ToolCallLimitMiddleware(run_limit=15),                                # LLM10
        ToolRetryMiddleware(max_retries=1),                                   # errores transitorios
        HumanInTheLoopMiddleware(interrupt_on={"registrar_alerta_fuga": True}),  # LLM06
        SummarizationMiddleware(model=ChatAnthropic(model=MODELO_RAPIDO), trigger=("tokens", 60000)),
        VerificarRespaldo(),                                                  # LLM09
    ]
    # Caché de prompt: el prompt de sistema y los esquemas de las 8 herramientas se
    # reutilizan entre llamadas (menos latencia y costo). Si responde el modelo de
    # respaldo (OpenAI), se ignora.
    capas.insert(0, AnthropicPromptCachingMiddleware(ttl="5m", unsupported_model_behavior="ignore"))
    if os.environ.get("OPENAI_API_KEY"):
        capas.insert(0, ModelFallbackMiddleware(MODELO_RESPALDO))             # resiliencia multi-LLM
    return capas


def construir_agente():
    return create_agent(
        model=ChatAnthropic(model=MODELO_AGENTE, max_retries=2),
        tools=HERRAMIENTAS,
        system_prompt=prompts.SISTEMA_AGENTE,
        middleware=_middlewares(),
        name="agente_pricing",
    )


def _enrutar(state: Estado) -> str:
    return {"bloqueado": END, "fuera_de_dominio": "fuera_de_dominio",
            "concepto": "concepto"}.get(state["ruta"], "agente")


@lru_cache
def checkpointer() -> PostgresSaver:
    pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=5, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    saver = PostgresSaver(pool)
    saver.setup()
    return saver


@lru_cache
def grafo():
    g = StateGraph(Estado)
    g.add_node("guardia_entrada", guardia_entrada)
    g.add_node("clasificar", clasificar)
    g.add_node("fuera_de_dominio", fuera_de_dominio)
    g.add_node("concepto", concepto)
    g.add_node("agente", construir_agente())
    g.add_edge(START, "guardia_entrada")
    g.add_conditional_edges("guardia_entrada", lambda s: END if s["ruta"] == "bloqueado" else "clasificar")
    g.add_conditional_edges("clasificar", _enrutar, ["fuera_de_dominio", "concepto", "agente", END])
    for nodo in ("fuera_de_dominio", "concepto", "agente"):
        g.add_edge(nodo, END)
    return g.compile(checkpointer=checkpointer(), name="pocket_price_agent")
