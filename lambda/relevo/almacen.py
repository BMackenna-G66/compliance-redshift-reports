"""Almacén local de mensajes en JSONL. Una línea por correo, en la forma que
consume el pipeline.

Vive en disco, en la máquina donde corre el backend. Los datos de cliente no
salen de ahí: el front remoto sólo recibe lo que la API le devuelve, y la API
corre acá.
"""
import json
import os
from pathlib import Path

# En contenedor esto apunta a un volumen montado. Por eso es configurable:
# RELEVO_DATOS=/datos  ->  /datos/mensajes.jsonl
_DIR = Path(os.environ.get("RELEVO_DATOS") or Path(__file__).resolve().parent.parent / "datos")
POR_DEFECTO = _DIR / "mensajes.jsonl"


def guardar(mensajes, ruta=None, agregar=True):
    """Escribe mensajes deduplicando por id. Devuelve cuántos son nuevos."""
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


def leer(ruta=None):
    ruta = Path(ruta or POR_DEFECTO)
    if not ruta.exists():
        return []
    fuera = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        m = json.loads(linea)
        m.setdefault("cuerpo", "")
        m.setdefault("headers", {})
        m.setdefault("texto_adjuntos", [])
        m.setdefault("esperado", None)
        fuera.append(m)
    return fuera
