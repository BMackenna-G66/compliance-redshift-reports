"""Depósito de documentos del módulo: un objeto de S3 por registro.

Reemplaza el fondo en disco de `almacen`, `cliente` y `casos`. El filesystem
de Lambda es de sólo lectura salvo /tmp, y /tmp no sobrevive entre
invocaciones, así que sin esto el módulo no puede guardar nada en producción.

**Por qué S3 y no DynamoDB, que es lo que pide §4 de la especificación.**
El rol con el que se opera esta cuenta tiene `dynamodb:CreateTable` en
implicitDeny — con cualquier nombre de tabla, verificado con
`simulate-principal-policy` — y sus permisos de datos alcanzan sólo a las
cuatro tablas que ya existen. No hay forma de crear las siete tablas que
describe la especificación sin pedir permisos nuevos.

S3, en cambio, ya está disponible: el bucket existe y el rol de la Lambda
tiene GetObject/PutObject/DeleteObject/ListBucket sobre él. Y es el mismo
patrón con el que WatchTower ya persiste su CRM (`crm/{tipo}/{id}.json`).

Los dos argumentos con los que §4 eligió Dynamo se sostienen igual acá:

- *El almacén sólo agrega y el estado se deriva.* Un objeto por registro es
  append-only de verdad: no hay lectura-modificación-escritura, así que dos
  invocaciones concurrentes no se pisan. Es más fuerte que reescribir un
  JSONL completo, que era lo que hacía el fondo en disco.
- *Sobrevive al cluster pausado.* S3 no tiene nada que ver con Redshift.

Y las escrituras condicionales de S3 (`IfNoneMatch`) dan la deduplicación por
clave que en Dynamo daba la PK.

Lo que se pierde frente a Dynamo, dicho explícitamente: no hay consulta por
clave de ordenamiento. Se compensa con la jerarquía de la clave —las acciones
de un caso viven bajo su propio prefijo— que para el volumen del ciclo RFI
(cientos de registros, no millones) resuelve igual. Si más adelante se
consiguen los permisos, migrar es reescribir sólo este archivo.

Si `RELEVO_BUCKET` no está seteada, el módulo no usa S3 y cada función cae al
fondo en disco de siempre. Eso mantiene el desarrollo local y los 104 tests
funcionando sin cambios.
"""
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

BUCKET = os.environ.get("RELEVO_BUCKET", "").strip()
PREFIJO = os.environ.get("RELEVO_PREFIJO", "relevo").strip().strip("/")
# Lecturas en paralelo: traer 478 mensajes de a uno tarda demasiado para una
# invocación. El tope es bajo a propósito, para no competir con las consultas
# a Redshift que corren en la misma Lambda.
_HILOS = int(os.environ.get("RELEVO_HILOS", "8"))

_CLIENTE = None
_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")


def activo() -> bool:
    """True si hay que persistir en S3. Si no, cada función usa disco."""
    return bool(BUCKET)


def _s3():
    global _CLIENTE
    if _CLIENTE is None:
        import boto3
        _CLIENTE = boto3.client("s3")
    return _CLIENTE


def clave_segura(valor) -> str:
    """Convierte un identificador cualquiera en un segmento de clave S3.

    Los Message-ID vienen como `<CA+xyz@mail.gmail.com>` y los ids de caso
    como `nium:caso:1088170`: hay que limpiarlos. Se conserva un prefijo
    legible para poder mirar el bucket y entender qué hay, y se le pega un
    hash del valor original para que dos ids distintos nunca colapsen en la
    misma clave por efecto de la limpieza.
    """
    bruto = str(valor or "")
    legible = _SEGURO.sub("_", bruto).strip("_")[:60] or "x"
    firma = hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]
    return f"{legible}-{firma}"


def _ruta(coleccion: str, clave: str) -> str:
    return f"{PREFIJO}/{coleccion.strip('/')}/{clave}.json"


def poner(coleccion: str, clave: str, dato: dict, solo_si_falta: bool = False) -> bool:
    """Escribe un registro. Con solo_si_falta=True no sobreescribe.

    Devuelve True si escribió, False si ya existía y no se pisó.
    """
    kw = {"IfNoneMatch": "*"} if solo_si_falta else {}
    try:
        _s3().put_object(
            Bucket=BUCKET, Key=_ruta(coleccion, clave),
            Body=json.dumps(dato, ensure_ascii=False, default=str).encode("utf-8"),
            ContentType="application/json", **kw,
        )
        return True
    except Exception as e:
        # PreconditionFailed = ya existía. Cualquier otro error sí es un error.
        if solo_si_falta and "PreconditionFailed" in str(e):
            return False
        raise


def obtener(coleccion: str, clave: str):
    try:
        obj = _s3().get_object(Bucket=BUCKET, Key=_ruta(coleccion, clave))
        return json.loads(obj["Body"].read())
    except Exception as e:
        if "NoSuchKey" in str(e) or "404" in str(e):
            return None
        raise


def claves(coleccion: str, sub: str = "") -> list:
    """Lista las claves de una colección, opcionalmente bajo un subprefijo."""
    pref = f"{PREFIJO}/{coleccion.strip('/')}/"
    if sub:
        pref += f"{sub.strip('/')}/"
    fuera, token = [], None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": pref, "MaxKeys": 1000}
        if token:
            kw["ContinuationToken"] = token
        r = _s3().list_objects_v2(**kw)
        fuera.extend(o["Key"] for o in r.get("Contents", []) if o["Key"].endswith(".json"))
        token = r.get("NextContinuationToken")
        if not token:
            break
    return fuera


def todos(coleccion: str, sub: str = "") -> list:
    """Todos los registros de una colección. Lee en paralelo."""
    ks = claves(coleccion, sub)
    if not ks:
        return []

    def _leer(k):
        try:
            return json.loads(_s3().get_object(Bucket=BUCKET, Key=k)["Body"].read())
        except Exception:
            return None  # un objeto ilegible no puede tumbar la lista completa

    with ThreadPoolExecutor(max_workers=min(_HILOS, len(ks))) as ex:
        return [d for d in ex.map(_leer, ks) if isinstance(d, dict)]


def borrar(coleccion: str, clave: str) -> None:
    _s3().delete_object(Bucket=BUCKET, Key=_ruta(coleccion, clave))
