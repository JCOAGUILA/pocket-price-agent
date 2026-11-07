"""Acceso a la nube: almacenamiento de objetos y secretos.

CLOUD_PROVIDER elige la implementación:
- gcp: Cloud Storage + Secret Manager (local: Floci GCP)
- aws: S3 + Secrets Manager (local: Floci AWS)

En local, las variables *_EMULATOR_HOST / AWS_ENDPOINT_URL apuntan al
emulador; en la nube real basta con quitarlas.
"""

import json
import os
from functools import lru_cache

PROVEEDOR = os.environ.get("CLOUD_PROVIDER", "gcp")
BUCKET = os.environ["BUCKET"]
SECRET_NAME = os.environ["SECRET_NAME"]


# ---------------------------------------------------------------- GCP

@lru_cache
def _gcs():
    from google.cloud import storage

    proyecto = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if os.environ.get("STORAGE_EMULATOR_HOST"):
        from google.auth.credentials import AnonymousCredentials

        return storage.Client(project=proyecto, credentials=AnonymousCredentials())
    return storage.Client(project=proyecto)


@lru_cache
def _gsm():
    from google.cloud import secretmanager

    emulador = os.environ.get("SECRET_MANAGER_EMULATOR_HOST")
    if emulador:
        # El cliente Python ignora SECRET_MANAGER_EMULATOR_HOST: canal explícito.
        import grpc
        from google.cloud.secretmanager_v1.services.secret_manager_service.transports import (
            SecretManagerServiceGrpcTransport,
        )

        canal = grpc.insecure_channel(emulador)
        return secretmanager.SecretManagerServiceClient(
            transport=SecretManagerServiceGrpcTransport(channel=canal)
        )
    return secretmanager.SecretManagerServiceClient()


def _gcp_secreto_ruta() -> str:
    return f"projects/{os.environ['GOOGLE_CLOUD_PROJECT']}/secrets/{SECRET_NAME}"


# ---------------------------------------------------------------- AWS

@lru_cache
def _s3():
    import boto3
    from botocore.config import Config

    return boto3.client("s3", config=Config(s3={"addressing_style": "path"}))


@lru_cache
def _asm():
    import boto3

    return boto3.client("secretsmanager")


# ---------------------------------------------------------------- API común

def asegurar_bucket() -> None:
    if PROVEEDOR == "gcp":
        if not _gcs().bucket(BUCKET).exists():
            _gcs().create_bucket(BUCKET)
    else:
        from botocore.exceptions import ClientError

        try:
            _s3().create_bucket(Bucket=BUCKET)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise


def subir(ruta_local: str, clave: str) -> None:
    if PROVEEDOR == "gcp":
        _gcs().bucket(BUCKET).blob(clave).upload_from_filename(ruta_local)
    else:
        _s3().upload_file(ruta_local, BUCKET, clave)


def leer(clave: str) -> bytes:
    if PROVEEDOR == "gcp":
        return _gcs().bucket(BUCKET).blob(clave).download_as_bytes()
    return _s3().get_object(Bucket=BUCKET, Key=clave)["Body"].read()


def listar(prefijo: str = "") -> list[str]:
    if PROVEEDOR == "gcp":
        return [b.name for b in _gcs().list_blobs(BUCKET, prefix=prefijo)]
    respuesta = _s3().list_objects_v2(Bucket=BUCKET, Prefix=prefijo)
    return [o["Key"] for o in respuesta.get("Contents", [])]


def guardar_secretos(valores: dict) -> None:
    carga = json.dumps(valores)
    if PROVEEDOR == "gcp":
        from google.api_core.exceptions import AlreadyExists

        padre = f"projects/{os.environ['GOOGLE_CLOUD_PROJECT']}"
        try:
            _gsm().create_secret(parent=padre, secret_id=SECRET_NAME,
                                 secret={"replication": {"automatic": {}}})
        except AlreadyExists:
            pass
        _gsm().add_secret_version(parent=_gcp_secreto_ruta(), payload={"data": carga.encode()})
    else:
        from botocore.exceptions import ClientError

        try:
            _asm().create_secret(Name=SECRET_NAME, SecretString=carga)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceExistsException":
                raise
            _asm().put_secret_value(SecretId=SECRET_NAME, SecretString=carga)


@lru_cache
def secretos() -> dict:
    if PROVEEDOR == "gcp":
        version = _gsm().access_secret_version(name=f"{_gcp_secreto_ruta()}/versions/latest")
        return json.loads(version.payload.data.decode())
    return json.loads(_asm().get_secret_value(SecretId=SECRET_NAME)["SecretString"])


def cargar_secretos_en_entorno() -> None:
    """Expone las claves del gestor de secretos como variables de entorno,
    que es donde las buscan los SDK de Anthropic, OpenAI y LangSmith."""
    for clave, valor in secretos().items():
        if valor:
            os.environ[clave] = valor
