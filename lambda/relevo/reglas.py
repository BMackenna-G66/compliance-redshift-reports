"""Carga y compila reglas.json. Es la unica fuente de verdad de la extraccion."""
import json
import re
from pathlib import Path

RUTA_POR_DEFECTO = Path(__file__).resolve().parent / "reglas.json"


def _flags(s):
    f = 0
    if "i" in (s or ""):
        f |= re.IGNORECASE
    if "m" in (s or ""):
        f |= re.MULTILINE
    if "s" in (s or ""):
        f |= re.DOTALL
    return f


def cargar_reglas(ruta=None):
    """Devuelve el dict de reglas con los patrones ya compilados."""
    ruta = Path(ruta) if ruta else RUTA_POR_DEFECTO
    reglas = json.loads(ruta.read_text(encoding="utf-8"))

    for p in reglas["partners"]:
        for pista in p.get("pistas_asunto", []):
            pista["_re"] = re.compile(pista["patron"], re.IGNORECASE)
        for c in p["clasificacion"]:
            c["_re"] = re.compile(c["patron"], _flags(c.get("flags", "")) | re.IGNORECASE)
        for e in p["extraccion"]:
            e["_re"] = re.compile(e["patron"], _flags(e.get("flags", "")))
            e["_re_ancla"] = re.compile(e["ancla"], _flags(e.get("flags", ""))) if e.get("ancla") else None

    for k, f in reglas.get("formatos", {}).items():
        f["_re"] = re.compile(f["patron_aceptado"])

    for a in reglas.get("no_corresponsal", {}).get("asunto", []):
        a["_re"] = re.compile(a["patron"], re.IGNORECASE)

    req = reglas.get("requerimiento") or {}
    req["_re_arranques"] = [re.compile(x) for x in req.get("arranques", [])]
    for c in req.get("catalogo", []):
        c["_re"] = [re.compile(x, re.IGNORECASE) for x in c["patrones"]]
    for pl in req.get("plazo", []):
        pl["_re"] = re.compile(pl["patron"], re.IGNORECASE)

    for c in (reglas.get("datos") or {}).get("campos", []):
        alt = "|".join(c["etiquetas"])
        # «Etiqueta<tab>valor» de una tabla, o «Etiqueta: valor» de texto plano.
        # El valor corta en el tab siguiente: una fila de tabla trae varias
        # columnas en el mismo renglón («Country\tPA\tAmount\tUSD 7572») y sin
        # ese corte el primer campo se comía a los demás.
        c["_re"] = re.compile(rf"(?:^|\t)\s*(?:{alt})\s*(?:\t|:)\s*([^\t\n]+?)\s*(?=\t|$)",
                              re.IGNORECASE | re.MULTILINE)

    reglas["_por_id"] = {p["id"]: p for p in reglas["partners"]}
    reglas["_por_nombre"] = {p["nombre"].lower(): p for p in reglas["partners"]}
    reglas["_ruta"] = str(ruta)
    return reglas


def partner_por_id(reglas, pid):
    return reglas["_por_id"].get(pid)


def partner_por_nombre(reglas, nombre):
    return reglas["_por_nombre"].get((nombre or "").strip().lower())
