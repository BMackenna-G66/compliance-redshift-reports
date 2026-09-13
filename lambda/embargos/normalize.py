"""Normalizacion de texto, documentos de identidad, nombres y montos.

Todas las funciones son puras y no dependen del formato de origen: se aplican
igual a una fila de Excel, a una celda de PDF o a un CSV.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Optional, Tuple

try:
    from ftfy import fix_text as _ftfy_fix
except ImportError:  # degradacion elegante: el pipeline sigue funcionando
    _ftfy_fix = None

# Caracteres que delatan una corrupcion IRRECUPERABLE de encoding.
# Ej: "MUÂ¿OZ" (Ñ ya perdida en un transcode anterior), "GÂ¿MEZ" (Ó perdida).
LOSSY_MARKERS = ("�", "Â¿", "¿")

# Mojibake reversible frecuente en exportes latin1/utf-8 de la Rama Judicial.
MOJIBAKE_MAP = {
    "Ã¡": "á", "Ã©": "é", "Ã­": "í", "Ã³": "ó", "Ãº": "ú",
    "Ã": "Á", "Ã‰": "É", "Ã": "Í", "Ã“": "Ó", "Ãš": "Ú",
    "Ã±": "ñ", "Ã‘": "Ñ", "Ã¼": "ü", "Â°": "°", "Âº": "º", "Â´": "´",
    "Â ": " ",
}

DOC_TYPE_MAP = {
    "CEDULA DE CIUDADANIA": "CC",
    "CEDULA CIUDADANIA": "CC",
    "CEDULA": "CC",
    "C.C.": "CC",
    "CC": "CC",
    "TARJETA DE IDENTIDAD": "TI",
    "TARJETA IDENTIDAD": "TI",
    "TI": "TI",
    "CEDULA DE EXTRANJERIA": "CE",
    "CEDULA EXTRANJERIA": "CE",
    "CEDULA DE EXTRANJERO": "CE",
    "CE": "CE",
    "PASAPORTE": "PA",
    "PA": "PA",
    "NIT": "NIT",
    "PPT": "PPT",
    "PERMISO POR PROTECCION TEMPORAL": "PPT",
    "PERMISO PROTECCION TEMPORAL": "PPT",
    "PERMISO ESPECIAL DE PERMANENCIA": "PEP",
    "PEP": "PEP",
    "CEDULA VENEZOLANA": "CV",
    "REGISTRO CIVIL": "RC",
}

# Sinónimos agregados a partir de los tipos que aparecen en los cuatro oficios
# reales y que el mapa no reconocía. Se descubrieron al exigir que el tipo de
# documento coincida en el cruce: sin mapear, `Cédula Extranjeria` salía como
# el literal "CEDULA EXT" y nunca iba a coincidir con el "CE" de la base, así
# que 47 personas habrían pasado a "no es cliente" por un problema de formato.
# Conteos medidos: CEDULA VEN 1.043 · TARJETA ID 253 · CEDULA EXT 47 ·
# PERMISO PR 21.

# Rango valido de longitud por tipo de documento en Colombia.
DOC_LENGTH_RULES = {
    "CC": (5, 10),
    "TI": (8, 11),
    "CE": (5, 10),
    "PA": (5, 15),
    "NIT": (6, 10),
    "PPT": (7, 10),
    "RC": (8, 11),
}

MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fix_mojibake(value: str) -> Tuple[str, bool]:
    """Repara mojibake reversible. Devuelve (texto, hay_perdida_irrecuperable)."""
    if not value:
        return "", False
    text = value
    for bad, good in MOJIBAKE_MAP.items():
        if bad in text:
            text = text.replace(bad, good)
    if _ftfy_fix is not None:
        text = _ftfy_fix(text)
    lossy = any(marker in text for marker in LOSSY_MARKERS)
    return text, lossy


def clean_text(value) -> str:
    """Limpieza base: string, sin apostrofe de Excel, sin espacios colapsados."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith("'"):          # Excel fuerza texto con apostrofe inicial
        text = text[1:]
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\s ]+", " ", text)
    return text.strip()


def normalize_doc_type(value) -> str:
    """Mapea la descripcion libre del tipo de documento a un codigo canonico."""
    text = clean_text(value)
    if not text:
        return ""
    text, _ = fix_mojibake(text)
    key = strip_accents(text).upper().strip().rstrip(".")
    key = re.sub(r"\s+", " ", key)
    return DOC_TYPE_MAP.get(key, key[:10])


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def normalize_doc_id(value) -> str:
    """Deja solo digitos. Para NIT descarta el digito de verificacion (800165941-6)."""
    text = clean_text(value)
    if not text:
        return ""
    text = text.split(".")[0] if re.fullmatch(r"\d+\.0+", text) else text
    if re.fullmatch(r"\d{9,10}-\d", text):     # NIT con DV
        text = text.split("-")[0]
    digits = re.sub(r"\D", "", text)
    return digits.lstrip("0") or digits


def validate_doc_id(doc_id: str, doc_type: str) -> Optional[str]:
    """Devuelve un motivo de invalidez, o None si el documento pasa las reglas."""
    if not doc_id:
        return "documento_vacio"
    if not doc_id.isdigit():
        return "documento_no_numerico"
    low, high = DOC_LENGTH_RULES.get(doc_type, (3, 15))
    if not (low <= len(doc_id) <= high):
        return f"longitud_fuera_de_rango ({len(doc_id)} digitos para {doc_type or 'tipo desconocido'})"
    if len(set(doc_id)) == 1:
        return "documento_repetitivo"
    return None


def normalize_name(value) -> Tuple[str, bool]:
    """Nombre en mayusculas, sin dobles espacios. Devuelve (nombre, mojibake_perdido)."""
    text = clean_text(value)
    if not text:
        return "", False
    text, lossy = fix_mojibake(text)
    text = re.sub(r"\s*\n\s*", " ", text)          # celdas PDF multilinea
    text = re.sub(r"[\s,;]+$", "", text)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text, lossy


def parse_amount(value) -> Optional[float]:
    """Monto tolerante a '$117,467,889.79', '10921096.1269' y numeros nativos."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = clean_text(value).replace("$", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") \
            else text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", "") if re.search(r",\d{3}\b", text) else text.replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def format_amount_cop(amount: Optional[float]) -> str:
    if amount is None:
        return ""
    return "$" + f"{amount:,.2f}"


def fecha_larga_es(value: Optional[date] = None, ciudad: str = "Bogotá D.C.") -> str:
    """'Bogotá D.C., 12 de septiembre de 2026' para el placeholder fecha_oficial."""
    d = value or date.today()
    return f"{ciudad}, {d.day} de {MESES_ES[d.month - 1]} de {d.year}"
