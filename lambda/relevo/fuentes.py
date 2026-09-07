"""Adaptadores de entrada. Todos devuelven la misma forma de mensaje:

    {"id", "asunto", "cuerpo", "headers": {...}, "texto_adjuntos": [...], "esperado": {...}|None}

`esperado` solo lo trae el consolidado: es el golden set contra el que se mide.
"""
import email
import email.policy
import json
import mailbox
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_T = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
_ROW = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"


# --------------------------------------------------------------- xlsx (stdlib)
def _col(ref):
    letras = re.match(r"([A-Z]+)", ref).group(1)
    n = 0
    for ch in letras:
        n = n * 26 + ord(ch) - 64
    return n - 1


def leer_xlsx(ruta, hoja):
    """Lee una hoja de un .xlsx sin dependencias. Devuelve lista de dicts por encabezado."""
    z = zipfile.ZipFile(ruta)
    compartidas = []
    try:
        raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in raiz.findall("m:si", NS):
            compartidas.append("".join(t.text or "" for t in si.iter(_T)))
    except KeyError:
        pass

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    destino = {x.get("Id"): x.get("Target") for x in rels}
    rid = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    objetivo = None
    for s in wb.find("m:sheets", NS):
        if s.get("name") == hoja:
            objetivo = destino[s.get(rid)]
    if objetivo is None:
        raise KeyError(f"no existe la hoja {hoja!r} en {ruta}")

    sh = ET.fromstring(z.read("xl/" + objetivo.lstrip("/").replace("xl/", "")))
    filas = []
    for fila in sh.iter(_ROW):
        celdas = {}
        for c in fila.findall("m:c", NS):
            v, t = c.find("m:v", NS), c.get("t")
            if t == "inlineStr":
                bloque = c.find("m:is", NS)
                val = "".join(x.text or "" for x in bloque.iter(_T)) if bloque is not None else ""
            elif v is None:
                val = ""
            elif t == "s":
                val = compartidas[int(v.text)]
            else:
                val = v.text
            celdas[_col(c.get("r"))] = val
        if celdas:
            filas.append([celdas.get(i, "") for i in range(max(celdas) + 1)])

    if not filas:
        return []
    ancho = max(len(f) for f in filas)
    enc = (filas[0] + [""] * ancho)[:ancho]
    return [dict(zip(enc, (f + [""] * ancho)[:ancho])) for f in filas[1:]]


def _fecha_excel(v):
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


LLAVE_POR_TIPO = {
    "RMT · External ID":      "rmt",
    "PY · Transaction ID":    "nium_payout_id",
    "ID de envío Global66":   "transfer_no",
    "Ticket Zendesk":         "cc_ticket",
}


def desde_consolidado(ruta, hoja="IDs unificados"):
    """El consolidado de 963 registros como golden set.

    Ojo con el alcance de lo que esto puede medir: el Excel tiene el ASUNTO de
    cada registro, no el cuerpo ni los headers. Sirve para medir la extraccion
    por asunto y la identificacion de partner por pista de asunto. La
    identificacion por X-Original-Sender y la extraccion de cuerpo necesitan
    correos reales (--eml / --mbox).
    """
    mensajes = []
    for i, f in enumerate(leer_xlsx(ruta, hoja), start=1):
        asunto = (f.get("Asunto") or "").strip()
        if not asunto:
            continue
        tipo_id = (f.get("Tipo de ID") or "").strip()
        donde = (f.get("Dónde vive") or "").strip()
        mensajes.append({
            "id": f"cons-{i:04d}",
            "asunto": asunto,
            "cuerpo": "",
            "headers": {"From": "compliance@global66.com"},  # como llegan de verdad: el From reescrito
            "texto_adjuntos": [],
            "esperado": {
                "partner": (f.get("Corresponsal") or "").strip(),
                "llave": LLAVE_POR_TIPO.get(tipo_id, ""),
                "tipo_id": tipo_id,
                "valor": (f.get("ID") or "").strip(),
                "valor_secundario": (f.get("ID secundario") or "").strip(),
                "caso_partner": (f.get("Caso del partner") or "").strip(),
                "query_key": (f.get("query_key") or "").strip(),
                "donde_vive": donde,
                "en_asunto": "asunto" in donde.lower(),
                "mensajes": (f.get("Mensajes") or "").strip(),
                "primera": _fecha_excel(f.get("Primera")),
            },
        })
    return mensajes


# ------------------------------------------------------------------ correos
def _texto_de_parte(msg):
    partes = []
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_maintype() == "multipart":
                continue
            if p.get_filename():
                continue
            ct = p.get_content_type()
            if ct in ("text/plain", "text/html"):
                try:
                    t = p.get_content()
                except Exception:
                    t = p.get_payload(decode=True) or b""
                    t = t.decode(p.get_content_charset() or "utf-8", "replace")
                if ct == "text/html":
                    from .html import a_texto
                    t = a_texto(t)
                partes.append(t)
    else:
        try:
            partes.append(msg.get_content())
        except Exception:
            b = msg.get_payload(decode=True) or b""
            partes.append(b.decode(msg.get_content_charset() or "utf-8", "replace"))
    # el texto citado NO se recorta: 25 de los 71 PY de Nium viven ahi
    return "\n".join(partes)


def _adjuntos_texto(msg):
    fuera = []
    for p in msg.walk() if msg.is_multipart() else []:
        nombre = p.get_filename()
        if not nombre:
            continue
        if Path(nombre).suffix.lower() in (".txt", ".csv", ".eml", ".json", ".md"):
            b = p.get_payload(decode=True) or b""
            fuera.append(b.decode("utf-8", "replace"))
        else:
            fuera.append(f"[adjunto no leido: {nombre}]")
    return fuera


def _de_mensaje_email(msg, ident):
    return {
        "id": ident,
        "asunto": str(msg.get("Subject") or ""),
        "cuerpo": _texto_de_parte(msg),
        "headers": {k: str(v) for k, v in msg.items()},
        "texto_adjuntos": _adjuntos_texto(msg),
        "esperado": None,
    }


def desde_eml(ruta):
    """Un .eml o un directorio de .eml. Es la fuente que ejercita los headers."""
    ruta = Path(ruta)
    archivos = sorted(ruta.rglob("*.eml")) if ruta.is_dir() else [ruta]
    fuera = []
    for a in archivos:
        with a.open("rb") as fh:
            msg = email.message_from_binary_file(fh, policy=email.policy.default)
        fuera.append(_de_mensaje_email(msg, a.name))
    return fuera


def desde_mbox(ruta):
    return [_de_mensaje_email(m, f"mbox-{i:05d}") for i, m in enumerate(mailbox.mbox(str(ruta)), 1)]


def desde_json(ruta):
    """Lista de mensajes ya con la forma esperada. Para exportaciones de Gmail API."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if isinstance(datos, dict):
        datos = datos.get("mensajes") or datos.get("messages") or []
    for i, m in enumerate(datos, 1):
        m.setdefault("id", f"json-{i:05d}")
        m.setdefault("headers", {})
        m.setdefault("cuerpo", m.pop("body", ""))
        m.setdefault("asunto", m.pop("subject", ""))
        m.setdefault("texto_adjuntos", [])
        m.setdefault("esperado", None)
    return datos
