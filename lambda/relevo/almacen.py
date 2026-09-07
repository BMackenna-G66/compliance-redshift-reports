"""Almacén local de mensajes en JSONL. Una línea por correo, en la forma que
consume el pipeline.

Vive en disco, en la máquina donde corre el backend. Los datos de cliente no
salen de ahí: el front remoto sólo recibe lo que la API le devuelve, y la API
corre acá.
"""
import json
import os
from pathlib import Path

from . import deposito

# En contenedor esto apunta a un volumen montado. Por eso es configurable:
# RELEVO_DATOS=/datos  ->  /datos/mensajes.jsonl
_DIR = Path(os.environ.get("RELEVO_DATOS") or Path(__file__).resolve().parent.parent / "datos")
POR_DEFECTO = _DIR / "mensajes.jsonl"


def guardar(mensajes, ruta=None, agregar=True):
    """Escribe mensajes deduplicando por id. Devuelve cuántos son nuevos.

    Sin `ruta` y con el depósito activo va a S3, un objeto por mensaje: la
    deduplicación la da la clave, igual que la PK de `relevo_mensajes` en la
    especificación. Con `ruta` explícita mantiene el fondo en disco, que es
    lo que usan los tests.
    """
    if ruta is None and deposito.activo():
        nuevos = 0
        for m in mensajes:
            clave = deposito.clave_segura(m["id"])
            if agregar:
                # solo_si_falta hace la deduplicación en el servidor: dos
                # invocaciones concurrentes no se pisan ni cuentan doble.
                if deposito.poner("mensajes", clave, m, solo_si_falta=True):
                    nuevos += 1
            else:
                existia = deposito.obtener("mensajes", clave) is not None
                deposito.poner("mensajes", clave, m)
                if not existia:
                    nuevos += 1
        return nuevos

    ruta = Path(ruta or POR_DEFECTO)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    existentes = {m["id"]: m for m in leer(ruta)} if (agregar and ruta.exists()) else {}
    nuevos = 0
    for m in mensajes:
        if m["id"] not in existentes:
            nuevos += 1
        existentes[m["id"]] = m
    with ruta.open("w", encoding="utf-8") as fh:
        for m in existentes.values():
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    return nuevos


def _normalizar(m):
    """Los defaults que el pipeline espera encontrar siempre."""
    m.setdefault("cuerpo", "")
    m.setdefault("headers", {})
    m.setdefault("texto_adjuntos", [])
    m.setdefault("esperado", None)
    return m


def leer(ruta=None):
    if ruta is None and deposito.activo():
        return [_normalizar(m) for m in deposito.todos("mensajes")]

    ruta = Path(ruta or POR_DEFECTO)
    if not ruta.exists():
        return []
    fuera = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        fuera.append(_normalizar(json.loads(linea)))
    return fuera
