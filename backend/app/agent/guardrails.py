"""Guardrails propios (además de los middleware incluidos en LangChain).

- validar_entrada: determinista y barato; corre antes de gastar en el LLM.
- VerificarRespaldo: after_agent; si la respuesta trae cifras pero el agente no
  consultó ninguna herramienta en este turno, se marca como no verificada.
"""

import re

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

LONGITUD_MAXIMA = 1500

# Patrones típicos de inyección directa de prompt (OWASP LLM01) y de
# filtración del prompt de sistema (LLM07).
_INYECCION = re.compile(
    r"ignor(a|e|ar)\s+(todas\s+)?(las\s+|tus\s+)?(instrucciones|reglas)|"
    r"(muestra|revela|imprime|repite)\s+(tu|tus|el)\s+(prompt|instrucciones|system)|"
    r"system\s*prompt|jailbreak|modo\s+desarrollador|act[uú]a\s+como\s+si\s+no\s+tuvieras|"
    r"olvida\s+(todo|tus\s+instrucciones)|ignore\s+(all\s+)?previous",
    re.IGNORECASE,
)
_CIFRA = re.compile(r"S/\s?\d|\d+[.,]?\d*\s?%")


def validar_entrada(texto: str) -> str | None:
    """Devuelve un mensaje de rechazo, o None si la entrada es válida."""
    t = (texto or "").strip()
    if not t:
        return "No recibí ninguna pregunta. ¿Qué te gustaría analizar?"
    if len(t) > LONGITUD_MAXIMA:
        return f"La pregunta es muy larga ({len(t)} caracteres). Resúmela en menos de {LONGITUD_MAXIMA}."
    if _INYECCION.search(t):
        return ("No puedo modificar mis instrucciones ni revelarlas. Puedo ayudarte con análisis de "
                "pricing: pocket price, márgenes, descuentos, rebates o fugas de precio.")
    return None


class VerificarRespaldo(AgentMiddleware):
    """Marca respuestas con cifras que no se apoyan en ninguna herramienta (OWASP LLM09)."""

    def after_agent(self, state: AgentState, runtime) -> dict | None:
        mensajes = state["messages"]
        ultimo_humano = max((i for i, m in enumerate(mensajes) if isinstance(m, HumanMessage)), default=-1)
        turno = mensajes[ultimo_humano + 1:]
        final = turno[-1] if turno else None
        if not isinstance(final, AIMessage):
            return None
        texto = final.text if isinstance(final.text, str) else str(final.content)
        if not texto.strip():
            return {"messages": [AIMessage(content="No pude generar una respuesta. Intenta reformular la pregunta.")]}
        uso_herramientas = any(isinstance(m, ToolMessage) for m in turno)
        if _CIFRA.search(texto) and not uso_herramientas:
            aviso = ("\n\n_⚠️ Cifras no verificadas con las herramientas de datos en este turno; "
                     "pide el análisis explícitamente para confirmarlas._")
            return {"messages": [AIMessage(content=texto + aviso, id=final.id)]}
        return None
