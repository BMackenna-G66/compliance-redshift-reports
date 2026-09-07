"""Estado del módulo entre invocaciones: el equivalente de `relevo_estado` de §4.

Guarda las marcas que la ingesta y el poller necesitan recordar de una corrida
a la siguiente. Hoy la única que importa es `gmail_history_id`.

Va sobre el mismo depósito que el resto (ver `deposito.py` para por qué S3 y no
DynamoDB). Con `RELEVO_BUCKET` sin definir se cae a disco, así el desarrollo
local sigue funcionando.
"""
import json
import os
from pathlib import Path

from . import deposito

_ARCHIVO = Path(os.environ.get("RELEVO_DATOS") or
                Path(__file__).resolve().parent.parent / "datos") / "estado.json"


def leer(clave, por_defecto=None):
    if deposito.activo():
        d = deposito.obtener("estado", deposito.clave_segura(clave))
        return d.get("valor", por_defecto) if d else por_defecto
    if not _ARCHIVO.exists():
        return por_defecto
    try:
        return json.loads(_ARCHIVO.read_text(encoding="utf-8")).get(clave, por_defecto)
    except (json.JSONDecodeError, OSError):
        return por_defecto


def guardar(clave, valor):
    if deposito.activo():
        deposito.poner("estado", deposito.clave_segura(clave),
                       {"clave": clave, "valor": valor})
        return valor
    _ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    try:
        todo = json.loads(_ARCHIVO.read_text(encoding="utf-8")) if _ARCHIVO.exists() else {}
    except (json.JSONDecodeError, OSError):
        todo = {}
    todo[clave] = valor
    _ARCHIVO.write_text(json.dumps(todo, ensure_ascii=False, indent=2), encoding="utf-8")
    return valor
