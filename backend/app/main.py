"""API del agente de pocket price (en GCP: servicio de Cloud Run).

- POST /chat            turno de conversación (memoria por thread_id)
- POST /chat/stream     igual, transmitiendo herramientas y texto a medida que se generan
- POST /chat/aprobar    aprueba o rechaza una acción pendiente (human-in-the-loop)
- GET  /agent           msg + idagente, compatible con el frontend del curso
- GET  /api/hallazgos   alertas proactivas (SQL, sin LLM)
- GET  /health, /api/cascada  estado de la infraestructura
"""

import ast
import json
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from common import cloud

cloud.cargar_secretos_en_entorno()  # Anthropic, OpenAI y LangSmith desde Secret Manager

from .agent import db  # noqa: E402
from .agent.grafo import grafo  # noqa: E402
from .agent.prompts import FALLBACK  # noqa: E402

app = FastAPI(title="Pocket Price Agent")


class Turno(BaseModel):
    mensaje: str = Field(max_length=4000)
    thread_id: str = Field(min_length=1, max_length=100)


class Decision(BaseModel):
    thread_id: str
    decision: Literal["aprobar", "rechazar"]
    comentario: str | None = None


def _resumen(contenido) -> str:
    texto = contenido if isinstance(contenido, str) else json.dumps(contenido, ensure_ascii=False)
    return texto[:4000]  # completo para la evaluación de fidelidad; la UI muestra un extracto


def _como_dict(contenido):
    if isinstance(contenido, dict):
        return contenido
    try:
        return json.loads(contenido)
    except (TypeError, ValueError):
        try:
            return ast.literal_eval(contenido)
        except (ValueError, SyntaxError):
            return None


def _respuesta(estado: dict) -> dict:
    mensajes = estado.get("messages", [])
    ultimo_humano = max((i for i, m in enumerate(mensajes) if isinstance(m, HumanMessage)), default=-1)
    turno = mensajes[ultimo_humano + 1:]
    pasos, resultados = [], {m.tool_call_id: m for m in turno if isinstance(m, ToolMessage)}
    graficos = []
    for m in turno:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                r = resultados.get(tc["id"])
                pasos.append({"herramienta": tc["name"], "argumentos": tc["args"],
                              "resultado": _resumen(r.content) if r else None})
                if r and tc["name"] == "cascada_precio":
                    datos = _como_dict(r.content)
                    if datos and "pen_por_unidad" in datos:
                        graficos.append(datos)
    finales = [m for m in turno if isinstance(m, AIMessage) and m.text]
    pendiente = None
    if estado.get("__interrupt__"):
        valor = estado["__interrupt__"][0].value
        acciones = valor.get("action_requests", []) if isinstance(valor, dict) else []
        pendiente = {"acciones": [{"herramienta": a.get("name"), "argumentos": a.get("args")} for a in acciones]}
    return {
        "respuesta": finales[-1].text if finales else (None if pendiente else FALLBACK),
        "ruta": estado.get("ruta") or "agente",
        "pasos": pasos,
        "cascadas": graficos,
        "pendiente_aprobacion": pendiente,
    }


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "run_name": "pocket_price_agent",
            "metadata": {"thread_id": thread_id}}


def _descartar_pendiente(cfg: dict) -> None:
    """Si había una acción esperando aprobación y el usuario cambió de tema, se descarta:
    una acción sensible nunca se ejecuta sin un "sí" explícito."""
    if grafo().get_state(cfg).interrupts:
        grafo().invoke(Command(resume={"decisions": [{
            "type": "reject", "message": "El usuario no confirmó la acción y envió otro mensaje."}]}), cfg)


def _estado_final(cfg: dict) -> dict:
    snap = grafo().get_state(cfg)
    return {**snap.values, "__interrupt__": snap.interrupts}


# Nodos cuyo texto se transmite al usuario (no el clasificador ni el resumen de memoria).
_NODOS_VISIBLES = {"model", "concepto"}


@app.post("/chat/stream")
def chat_stream(t: Turno):
    """Igual que /chat, pero transmite el avance en NDJSON:
    {"tipo": "estado"|"token"|"final", ...}. El evento final trae la respuesta completa."""
    cfg = _config(t.thread_id)

    def eventos():
        def linea(d: dict) -> str:
            return json.dumps(d, ensure_ascii=False, default=str) + "\n"

        try:
            _descartar_pendiente(cfg)
            avisadas = set()
            for _ns, modo, datos in grafo().stream(
                    {"messages": [HumanMessage(content=t.mensaje)]}, cfg,
                    stream_mode=["messages", "updates"], subgraphs=True):
                if modo == "updates":
                    if "clasificar" in datos:
                        yield linea({"tipo": "estado", "texto": f"Ruta: {datos['clasificar'].get('ruta')}"})
                    continue
                chunk, meta = datos
                if meta.get("langgraph_node") not in _NODOS_VISIBLES:
                    continue
                for tc in getattr(chunk, "tool_call_chunks", None) or []:
                    if tc.get("name") and tc.get("id") not in avisadas:
                        avisadas.add(tc.get("id"))
                        yield linea({"tipo": "estado", "texto": f"Consultando {tc['name']}…"})
                texto = chunk.text if isinstance(chunk.text, str) else ""
                if texto:
                    yield linea({"tipo": "token", "texto": texto})
            yield linea({"tipo": "final", "datos": _respuesta(_estado_final(cfg))})
        except Exception as exc:
            yield linea({"tipo": "final", "datos": {
                "respuesta": FALLBACK, "ruta": "error", "pasos": [], "cascadas": [],
                "pendiente_aprobacion": None, "detalle_error": exc.__class__.__name__}})

    return StreamingResponse(eventos(), media_type="application/x-ndjson")


@app.post("/chat")
def chat(t: Turno):
    cfg = _config(t.thread_id)
    try:
        _descartar_pendiente(cfg)
        estado = grafo().invoke({"messages": [HumanMessage(content=t.mensaje)]}, cfg)
    except Exception as exc:  # fallback ante errores del proveedor o de infraestructura
        return {"respuesta": FALLBACK, "ruta": "error", "pasos": [], "cascadas": [],
                "pendiente_aprobacion": None, "detalle_error": exc.__class__.__name__}
    return _respuesta(estado)


@app.post("/chat/aprobar")
def aprobar(d: Decision):
    if d.decision == "aprobar":
        decision = {"type": "approve"}
    else:
        decision = {"type": "reject", "message": d.comentario or "El usuario rechazó la acción."}
    estado = grafo().invoke(Command(resume={"decisions": [decision]}), _config(d.thread_id))
    return _respuesta(estado)


@app.get("/agent", response_class=PlainTextResponse)
def agent(msg: str, idagente: str):
    """Firma compatible con el frontend Next.js del curso (agentui)."""
    r = chat(Turno(mensaje=msg, thread_id=idagente))
    if r["pendiente_aprobacion"]:
        return "La acción solicitada requiere aprobación; confírmala desde la consola del agente."
    return r["respuesta"]


@app.get("/health")
def health():
    return {
        "postgres_filas_venta": db.consultar("SELECT count(*) AS n FROM fact_venta")[0]["n"],
        "acuerdos_extraidos": db.consultar("SELECT count(*) AS n FROM condiciones_extra_sap")[0]["n"],
        "proveedor_nube": cloud.PROVEEDOR,
        "bucket_objetos": len(cloud.listar("")),
        "secretos_configurados": {k: bool(v) for k, v in cloud.secretos().items()},
    }


@app.get("/api/fuentes")
def fuentes():
    """Qué datos usa el agente: extracto del ERP y repositorio documental (para la página 'Cómo funciona')."""
    erp = db.consultar("""SELECT COUNT(*) AS lineas, MIN(fecha) AS desde, MAX(fecha) AS hasta,
                                 COUNT(DISTINCT cliente_id) AS clientes, COUNT(DISTINCT sku) AS productos
                          FROM fact_venta""")[0]
    manifiesto = json.loads(cloud.leer("docs/manifiesto.json"))
    documentos: dict[str, dict] = {}
    for d in manifiesto:
        t = documentos.setdefault(d["tipo"], {"cantidad": 0, "formatos": set()})
        t["cantidad"] += 1
        t["formatos"].add(d["archivo"].rsplit(".", 1)[-1].upper())
    extraidos = db.consultar("""SELECT tipo, COUNT(*) AS n FROM condiciones_extra_sap GROUP BY tipo
                                UNION ALL SELECT 'tope', COUNT(*) FROM topes_politica
                                UNION ALL SELECT 'excepcion', COUNT(*) FROM excepciones_comite""")
    return {
        "erp": erp,
        "documentos": {k: {"cantidad": v["cantidad"], "formatos": sorted(v["formatos"])} for k, v in documentos.items()},
        "extraidos": {r["tipo"]: r["n"] for r in extraidos},
        "proveedor_nube": cloud.PROVEEDOR,
    }


@app.get("/api/hallazgos")
def hallazgos():
    """Alertas proactivas calculadas con SQL (sin LLM) para la pantalla de inicio."""
    from . import hallazgos as h
    return h.calcular()


@app.get("/api/cascada")
def cascada(desde: str = "2025", hasta: str = "2026"):
    from .agent.herramientas import cascada_precio
    return cascada_precio.invoke({"desde": desde, "hasta": hasta})
