"""Inicialización única (servicio `init` del compose).

1. Genera los CSV sintéticos (ERP) y los documentos (PDF/DOCX/MD) si no existen.
2. Los sube al bucket (Cloud Storage o S3 según CLOUD_PROVIDER) bajo raw/ y docs/.
3. Guarda las claves de los LLM en el gestor de secretos.
4. Crea el esquema en Postgres y carga las tablas leyendo desde el bucket.

Es idempotente: se puede correr en cada `docker compose up`.
"""

import os
import time
from pathlib import Path

import psycopg
from psycopg import sql

import generate_data
import generate_docs
from common import cloud

RAW_DIR = Path("/data/raw")
DOCS_DIR = Path("/data/docs")
TABLAS = ["dim_producto", "dim_costo", "dim_cliente", "fact_venta"]  # orden de carga (FK)
# En la nube real el bucket y el secreto se crean aparte (mínimo privilegio):
# init no los crea ni escribe claves; solo sube archivos y carga Postgres.
NUBE_REAL = os.environ.get("NUBE_REAL", "false") == "true"


def esperar_emulador(intentos=30):
    if NUBE_REAL:
        return
    for i in range(intentos):
        try:
            cloud.asegurar_bucket()
            return
        except Exception as exc:  # el emulador aún no responde
            print(f"[init] esperando emulador ({i + 1}/{intentos}): {exc.__class__.__name__}")
            time.sleep(2)
    raise RuntimeError("El emulador de nube no respondió")


def subir_al_bucket():
    for tabla in TABLAS:
        cloud.subir(str(RAW_DIR / f"{tabla}.csv"), f"raw/{tabla}.csv")
        print(f"[init] {cloud.PROVEEDOR}://{cloud.BUCKET}/raw/{tabla}.csv")
    archivos = [p for p in DOCS_DIR.rglob("*") if p.is_file()]
    for ruta in archivos:
        cloud.subir(str(ruta), "docs/" + ruta.relative_to(DOCS_DIR).as_posix())
    print(f"[init] {len(archivos)} documentos en {cloud.PROVEEDOR}://{cloud.BUCKET}/docs/")


def guardar_secretos():
    if NUBE_REAL:
        print(f"[init] secretos: se usan los de {cloud.SECRET_NAME} (no se escriben)")
        return
    cloud.guardar_secretos({
        clave: os.environ.get(clave, "")
        for clave in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGSMITH_API_KEY")
    })
    print(f"[init] secreto guardado: {cloud.SECRET_NAME}")


def cargar_postgres():
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(schema)
        # schema.sql crea agente_ro con una clave de desarrollo; fuera de local se reemplaza
        # por la de AGENTE_RO_PASSWORD (inyectada desde Secret Manager).
        clave_ro = os.environ.get("AGENTE_RO_PASSWORD")
        if clave_ro:
            conn.execute(sql.SQL("ALTER ROLE agente_ro PASSWORD {}").format(sql.Literal(clave_ro)))
            print("[init] clave de agente_ro actualizada desde AGENTE_RO_PASSWORD")
        # Solo se recargan los datos del ERP; lo extraído de documentos lo gestiona la ingesta.
        conn.execute("TRUNCATE fact_venta, dim_cliente, dim_costo, dim_producto")
        for tabla in TABLAS:
            cuerpo = cloud.leer(f"raw/{tabla}.csv")
            with conn.cursor().copy(f"COPY {tabla} FROM STDIN WITH (FORMAT csv, HEADER true)") as cp:
                cp.write(cuerpo)
            n = conn.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
            print(f"[init] {tabla}: {n} filas")


def main():
    if not all((RAW_DIR / f"{t}.csv").exists() for t in TABLAS):
        print("[init] generando datos sintéticos del ERP...")
        generate_data.generar(RAW_DIR)
    if not (DOCS_DIR / "manifiesto.json").exists():
        print("[init] generando repositorio documental...")
        generate_docs.generar(Path(__file__).parent / "acuerdos.yaml", RAW_DIR / "dim_cliente.csv", DOCS_DIR)

    print(f"[init] proveedor de nube: {cloud.PROVEEDOR}")
    esperar_emulador()
    subir_al_bucket()
    guardar_secretos()
    cargar_postgres()
    print("[init] listo")


if __name__ == "__main__":
    main()
