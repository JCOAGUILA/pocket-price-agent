import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

import ui

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")
USUARIO = ("Analista de pricing", "Andina Materiales", "AP")  # demo: la app no tiene login

st.set_page_config(page_title="Pocket Price AI", page_icon=str(Path(__file__).parent / "favicon.png"), layout="wide",
                   initial_sidebar_state="expanded")
ui.cargar_estilos()

# Un solo agente responde todo: la barra lateral solo separa la conversación de la vista técnica.
VISTAS = {
    "analisis": ("Análisis", ":material/bar_chart:"),
    "infra": ("Cómo funciona", ":material/info:"),
}
# Sugerencias de la bienvenida, agrupadas por tema.
SUGERENCIAS = {
    "Pocket price": [
        (":material/trending_down:", "¿Pocket price real vs SAP de Tejas onduladas en 2026-Q2?"),
        (":material/leaderboard:", "¿Qué clientes tienen mayor brecha SAP vs. pocket real en 2026?"),
        (":material/compare_arrows:", "¿Por qué cambió el pocket price entre 2025-Q4 y 2026-Q2?"),
        (":material/map:", "¿Qué región tiene el menor margen real en 2026?"),
    ],
    "Fugas": [
        (":material/warning:", "¿Hay fugas de precio en el canal Ferretería en 2026?"),
        (":material/gavel:", "¿Qué excepciones de descuento aprobó o rechazó el Comité?"),
        (":material/construction:", "¿Las Constructoras respetan el nuevo tope de descuento de 2026?"),
        (":material/location_on:", "¿En qué región hay más descuentos sobre la política?"),
    ],
    "Rebates": [
        (":material/receipt_long:", "¿Cuánto rebate le corresponde a Distribuidora San Martín 1 en 2026?"),
        (":material/flag:", "¿Qué clientes no alcanzaron su objetivo de rebate en 2026-Q2?"),
        (":material/request_quote:", "¿Cuánto restan los rebates por carta al margen en 2026?"),
        (":material/description:", "¿Qué dice la carta comercial de Distribuidora Kuelap 6?"),
    ],
    "Políticas": [
        (":material/policy:", "¿Cuál es el tope de descuento de Constructoras en 2026?"),
        (":material/history:", "¿Qué cambió entre la política de descuentos 2025 y la 2026?"),
        (":material/local_shipping:", "¿Por qué el flete de la región Oriente es más caro?"),
        (":material/menu_book:", "¿Qué es el pocket price y en qué se diferencia del precio factura?"),
    ],
}


# ---------------------------------------------------------------- estado

def nueva_conversacion() -> str:
    hilo = f"web-{uuid.uuid4().hex[:10]}"
    st.session_state.conversaciones[hilo] = {"titulo": None, "hora": datetime.now(), "historial": [],
                                             "pendiente": None}
    st.session_state.hilo = hilo
    return hilo


if "conversaciones" not in st.session_state:
    st.session_state.conversaciones = {}
    st.session_state.vista = "analisis"
    nueva_conversacion()

conv = st.session_state.conversaciones[st.session_state.hilo]


@st.cache_data(ttl=30, show_spinner=False)
def backend_conectado() -> bool:
    try:
        return requests.get(f"{BACKEND}/health", timeout=5).ok
    except requests.RequestException:
        return False


@st.cache_data(ttl=60, show_spinner=False)
def obtener_hallazgos() -> list[dict]:
    try:
        return requests.get(f"{BACKEND}/api/hallazgos", timeout=15).json()
    except (requests.RequestException, ValueError):
        return []


# ---------------------------------------------------------------- llamadas al agente

SIN_CONEXION = "No se pudo contactar al agente. Intenta de nuevo en unos segundos."

def llamar_en_vivo(cuerpo: dict) -> dict:
    """Consume /chat/stream: muestra el avance y devuelve la respuesta final."""
    estado = st.status("Analizando…", expanded=True)
    texto, caja = "", st.empty()
    try:
        with requests.post(f"{BACKEND}/chat/stream", json=cuerpo, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            for linea in resp.iter_lines(decode_unicode=True):
                if not linea:
                    continue
                evento = json.loads(linea)
                if evento["tipo"] == "estado":
                    estado.write(evento["texto"])
                elif evento["tipo"] == "token":
                    texto += evento["texto"]
                    caja.markdown(texto + "▌")
                elif evento["tipo"] == "final":
                    estado.update(label="Listo", state="complete", expanded=False)
                    return evento["datos"]
    except requests.RequestException as exc:
        print(f"[frontend] error llamando al agente: {exc}", flush=True)  # detalle solo en el log
        estado.update(label="Sin conexión con el agente", state="error")
        return {"respuesta": SIN_CONEXION, "ruta": "error", "pasos": [], "cascadas": []}
    return {"respuesta": texto or "La respuesta se interrumpió.", "ruta": "error", "pasos": [], "cascadas": []}


def llamar(ruta: str, cuerpo: dict) -> dict:
    try:
        resp = requests.post(f"{BACKEND}{ruta}", json=cuerpo, timeout=300)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        print(f"[frontend] error llamando al agente: {exc}", flush=True)  # detalle solo en el log
        return {"respuesta": SIN_CONEXION, "ruta": "error", "pasos": [], "cascadas": []}


# ---------------------------------------------------------------- barra lateral

with st.sidebar:
    ui.logo()
    if st.button("Nuevo análisis", icon=":material/add:", key="nuevo", use_container_width=True):
        nueva_conversacion()
        st.session_state.vista = "analisis"
        st.rerun()
    st.write("")
    for clave, (nombre, icono) in VISTAS.items():
        if st.button(nombre, icon=icono, key=f"nav_{clave}", use_container_width=True):
            st.session_state.vista = clave
            st.rerun()
    activa = st.session_state.vista
    ui.html_(f"<style>.st-key-nav_{activa} button{{background:var(--naranja-suave)!important;"
             f"color:var(--naranja-texto)!important;font-weight:500}}"
             f".st-key-nav_{activa} button [data-testid='stIconMaterial']{{color:var(--naranja)!important}}</style>")

    recientes = [(h, c) for h, c in st.session_state.conversaciones.items() if c["titulo"]]
    if recientes:
        ui.html_('<div class="divisor"></div><div class="seccion">Recientes</div>')
        for h, c in sorted(recientes, key=lambda x: x[1]["hora"], reverse=True)[:6]:
            titulo = c["titulo"] if len(c["titulo"]) <= 30 else c["titulo"][:29] + "…"
            if st.button(f"{titulo}  \n{c['hora']:%H:%M}", icon=":material/description:", key=f"rec_{h}",
                         use_container_width=True):
                st.session_state.hilo = h
                st.session_state.vista = "analisis"
                st.rerun()
    nombre, rol, iniciales = USUARIO
    ui.usuario(nombre, rol, iniciales)

ui.barra_superior(backend_conectado(), USUARIO[2])

# ---------------------------------------------------------------- infraestructura

if st.session_state.vista == "infra":
    # Sin caja de chat en esta vista: no hace falta reservarle espacio abajo.
    ui.html_("<style>.block-container{padding-bottom:0.5rem!important}</style>")
    ui.migas("Workspace", "Cómo funciona")
    ui.html_('<div class="titulo-pagina">Cómo funciona Pocket Price AI</div>')
    try:
        ui.como_funciona(requests.get(f"{BACKEND}/api/fuentes", timeout=15).json())
    except (requests.RequestException, ValueError, KeyError) as exc:
        st.error(f"No se pudo consultar el backend: {exc}")
    st.stop()

# ---------------------------------------------------------------- análisis

titulo = conv["titulo"] or "Nueva consulta"
ui.migas("Análisis", titulo if len(titulo) <= 45 else titulo[:44] + "…")

if not conv["historial"]:
    hallazgos = obtener_hallazgos()
    if hallazgos:
        ui.html_(f'<div class="seccion-main">{ui.ms("notifications_active")}Hallazgos de hoy'
                 f'<span class="nota">· riesgos y logros detectados automáticamente en tus datos y acuerdos</span></div>')
        for col, (i, h) in zip(st.columns(len(hallazgos)), enumerate(hallazgos)):
            with col:
                if ui.hallazgo(h, str(i)):
                    st.session_state.pregunta_ejemplo = h["pregunta"]
    # Título y chips de tema en una sola fila.
    c_titulo, c_temas = st.columns([1, 3], vertical_alignment="center")
    with c_titulo:
        ui.html_(f'<div class="seccion-main">{ui.ms("lightbulb")}Preguntas sugeridas</div>')
    with c_temas:
        tema = st.segmented_control("Tema", list(SUGERENCIAS), default="Pocket price", key="tema",
                                    label_visibility="collapsed") or "Pocket price"
    columnas = st.columns(2)
    for i, (icono, texto) in enumerate(SUGERENCIAS[tema]):
        if columnas[i % 2].button(texto, icon=icono, key=f"sug_{i}", use_container_width=True):
            st.session_state.pregunta_ejemplo = texto

for i, turno in enumerate(conv["historial"]):
    if turno["rol"] == "user":
        ui.burbuja_usuario(turno["texto"], USUARIO[2])
    else:
        ui.respuesta(turno["respuesta"], f"{st.session_state.hilo}_{i}")

pend = conv["pendiente"]
if pend:
    with st.container(key="aprobacion"):
        ui.cabecera_respuesta("Requiere tu confirmación")
        st.markdown("Esta acción **registra datos** en el sistema. Revisa el detalle antes de aprobar:")
        for a in pend["acciones"]:
            st.json({"herramienta": a["herramienta"], **(a["argumentos"] or {})})
        c1, c2, _ = st.columns([1, 1, 3])
        decision = None
        if c1.button("Aprobar", icon=":material/check:", key="aprobar", use_container_width=True):
            decision = "aprobar"
        if c2.button("Rechazar", icon=":material/close:", key="rechazar", use_container_width=True):
            decision = "rechazar"
        if decision:
            with st.spinner("Ejecutando…"):
                r = llamar("/chat/aprobar", {"thread_id": st.session_state.hilo, "decision": decision})
            conv["historial"].append({"rol": "assistant", "respuesta": r})
            conv["pendiente"] = r.get("pendiente_aprobacion")
            st.rerun()

pregunta = st.chat_input("Pregunta sobre pricing…")
pregunta = pregunta or st.session_state.pop("pregunta_ejemplo", None)
if pregunta:
    conv["titulo"] = conv["titulo"] or pregunta
    conv["historial"].append({"rol": "user", "texto": pregunta})
    ui.burbuja_usuario(pregunta, USUARIO[2])
    with st.container(key=f"respuesta_{st.session_state.hilo}_vivo"):
        ui.cabecera_respuesta("Analizando…")
        r = llamar_en_vivo({"mensaje": pregunta, "thread_id": st.session_state.hilo})
    conv["historial"].append({"rol": "assistant", "respuesta": r})
    conv["pendiente"] = r.get("pendiente_aprobacion")
    st.rerun()
