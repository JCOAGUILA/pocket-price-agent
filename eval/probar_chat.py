"""Prueba rápida del agente contra la API local.

Uso: python eval/probar_chat.py "pregunta 1" "pregunta 2" ...   (mismo hilo)
"""

import json
import sys
import urllib.request
import uuid

API = "http://localhost:8000"


def post(ruta: str, cuerpo: dict) -> dict:
    req = urllib.request.Request(f"{API}{ruta}", data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    hilo = f"prueba-{uuid.uuid4().hex[:8]}"
    for pregunta in sys.argv[1:]:
        print("=" * 100)
        print("USUARIO:", pregunta)
        if pregunta in ("/aprobar", "/rechazar"):
            r = post("/chat/aprobar", {"thread_id": hilo, "decision": pregunta[1:]})
        else:
            r = post("/chat", {"mensaje": pregunta, "thread_id": hilo})
        print(f"[ruta: {r['ruta']}]")
        for p in r["pasos"]:
            print(f"  -> {p['herramienta']}({json.dumps(p['argumentos'], ensure_ascii=False)})")
        if r.get("pendiente_aprobacion"):
            print("  PENDIENTE DE APROBACIÓN:", r["pendiente_aprobacion"])
        if r.get("detalle_error"):
            print("  ERROR:", r["detalle_error"])
        print("AGENTE:", r["respuesta"])
