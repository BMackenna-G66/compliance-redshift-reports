"""Lectores por formato. Todos devuelven filas crudas ya mapeadas al esquema canonico."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .normalize import clean_text, fix_mojibake, strip_accents
from .schema import COLUMN_SYNONYMS, REQUIRED_FIELDS

HEADER_SCAN_ROWS = 15          # cuantas filas se inspeccionan buscando el encabezado
MIN_HEADER_SCORE = 2           # minimo de campos canonicos para aceptar una fila como encabezado
PDF_X_TOLERANCE = 2            # calibrado: separa palabras sin pegar "Cedulade"


# --------------------------------------------------------------------- headers
def _canon_header(text) -> str:
    t = clean_text(text)
    t, _ = fix_mojibake(t)
    t = strip_accents(t).upper()
    t = re.sub(r"[\.\-_/()]+", " ", t)
    t = re.sub(r"[^A-Z0-9ÑÜ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _score(header: str, synonym: str) -> int:
    """Puntaje de afinidad entre un encabezado real y un sinonimo conocido."""
    if not header:
        return 0
    if header == synonym:
        return 1000 + len(synonym)
    if synonym in header:
        return 500 + len(synonym) - (len(header) - len(synonym))
    if len(header) >= 6 and header in synonym:   # encabezado truncado por el exportador
        return 300 + len(header)
    return 0


def map_columns(headers: List) -> Dict[str, int]:
    """Mapea encabezados reales -> indices de columna del esquema canonico."""
    canon = [_canon_header(h) for h in headers]
    used: set = set()
    mapping: Dict[str, int] = {}
    for field, synonyms in COLUMN_SYNONYMS.items():
        best_idx, best_score = None, 0
        for idx, header in enumerate(canon):
            if idx in used or not header:
                continue
            for syn in synonyms:
                s = _score(header, syn)
                if s > best_score:
                    best_idx, best_score = idx, s
        if best_idx is not None and best_score >= 300:
            mapping[field] = best_idx
            used.add(best_idx)
    return mapping


def _header_score(mapping: Dict[str, int]) -> int:
    return sum(1 for f in REQUIRED_FIELDS if f in mapping) * 10 + len(mapping)


def find_header_row(rows: List[List]) -> Tuple[Optional[int], Dict[str, int]]:
    """Devuelve (indice_fila_encabezado, mapeo). Tolera titulos y filas en blanco."""
    best = (None, {}, 0)
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        mapping = map_columns(row)
        score = _header_score(mapping)
        if sum(1 for f in REQUIRED_FIELDS if f in mapping) >= MIN_HEADER_SCORE and score > best[2]:
            best = (i, mapping, score)
    return best[0], best[1]


def _row_to_raw(row, mapping: Dict[str, int]) -> Dict[str, object]:
    out = {}
    for field, idx in mapping.items():
        out[field] = row[idx] if idx < len(row) else None
    return out


# ----------------------------------------------------------------------- xlsx
def read_xlsx(path: Path) -> Iterator[Dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            head_rows = []
            it = ws.iter_rows(values_only=True)
            for _ in range(HEADER_SCAN_ROWS):
                try:
                    head_rows.append(list(next(it)))
                except StopIteration:
                    break
            hidx, mapping = find_header_row(head_rows)
            if hidx is None:
                yield {"__skip_sheet__": ws.title, "__reason__": "sin encabezado reconocible"}
                continue
            # filas ya leidas por debajo del encabezado
            for offset, row in enumerate(head_rows[hidx + 1:], start=hidx + 2):
                raw = _row_to_raw(list(row), mapping)
                if any(v not in (None, "") for v in raw.values()):
                    yield {**raw, "__sheet__": ws.title, "__row__": offset}
            for offset, row in enumerate(it, start=len(head_rows) + 1):
                raw = _row_to_raw(list(row), mapping)
                if any(v not in (None, "") for v in raw.values()):
                    yield {**raw, "__sheet__": ws.title, "__row__": offset}
    finally:
        wb.close()


# ------------------------------------------------------------------------ csv
def read_csv(path: Path) -> Iterator[Dict]:
    import csv as _csv
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with open(path, newline="", encoding=encoding) as fh:
                sample = fh.read(8192)
                fh.seek(0)
                try:
                    dialect = _csv.Sniffer().sniff(sample, delimiters=",;|\t")
                except _csv.Error:
                    dialect = _csv.excel
                rows = list(_csv.reader(fh, dialect))
            break
        except UnicodeDecodeError:
            continue
    else:
        return
    hidx, mapping = find_header_row(rows)
    if hidx is None:
        return
    for offset, row in enumerate(rows[hidx + 1:], start=hidx + 2):
        raw = _row_to_raw(row, mapping)
        if any(v not in (None, "") for v in raw.values()):
            yield {**raw, "__sheet__": path.stem, "__row__": offset}


# ------------------------------------------------------------------------ pdf
OFICIO_PATTERNS = {
    "numero_oficio": r"\b((?:DEAJ|DESAJ)[A-Z]{0,6}\d{2}-\d{3,6})\b",
    "numero_resolucion": r"Resoluci[oó]n\s+No\.?\s*([A-Z0-9\-]{6,30})",
    "cuenta_judicial": r"CUENTA\s+No\.?\s*(\d{8,20})",
}
DECLARED_COUNT = r"terminando\s+en\s+el\s+nombre\s+n[uú]mero\s+[A-ZÁÉÍÓÚÑ\s]+\((\d+)\)"


def extract_pdf_metadata(text: str) -> Dict[str, str]:
    flat = re.sub(r"\s+", " ", text)
    meta: Dict[str, str] = {}
    for field, pattern in OFICIO_PATTERNS.items():
        m = re.search(pattern, flat, re.IGNORECASE)
        if m:
            meta[field] = m.group(1).strip()
    m = re.search(DECLARED_COUNT, flat, re.IGNORECASE)
    if m:
        meta["__declarado__"] = m.group(1)
    return meta


class PdfSinTabla(Exception):
    """El PDF no entregó la tabla de demandados. Lleva el porqué adentro."""


# Un oficio real ronda los 3.300 caracteres por pagina; un escaneo devuelve 0.
# El umbral esta lejos de los dos para que un PDF con una portada en imagen y
# el resto en texto no se confunda con un escaneo.
MIN_CHARS_POR_PAGINA = 50


def read_pdf(path: Path) -> Iterator[Dict]:
    import pdfplumber
    settings = {"text_x_tolerance": PDF_X_TOLERANCE}
    with pdfplumber.open(path) as pdf:
        full_text = "\n".join((p.extract_text(x_tolerance=PDF_X_TOLERANCE) or "")
                              for p in pdf.pages)
        paginas = max(1, len(pdf.pages))

        # Un PDF escaneado devuelve cero filas SIN error, y "0 personas" en la
        # pantalla se lee como "no hay a quien embargar" cuando en realidad el
        # archivo no se leyo. En un oficio judicial esa confusion es cara: se
        # archiva como procesado y las personas nunca se cruzaron. Por eso
        # falla fuerte y dice que hacer.
        if len(full_text.strip()) < MIN_CHARS_POR_PAGINA * paginas:
            raise PdfSinTabla(
                "El PDF no tiene texto: parece un escaneo o una imagen. "
                "No se leyo ninguna persona. Pedi el oficio en Excel, o el "
                "PDF original del juzgado (no la copia escaneada).")

        meta = extract_pdf_metadata(full_text)
        yield {"__meta__": meta}

        filas = 0
        mapping: Dict[str, int] = {}
        for pno, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables(settings) or []:
                if not table:
                    continue
                hidx, new_map = find_header_row(table)
                start = 0
                if hidx is not None:
                    mapping = new_map            # el encabezado se repite en cada pagina
                    start = hidx + 1
                if not mapping:
                    continue
                for offset, row in enumerate(table[start:], start=start + 1):
                    raw = _row_to_raw(row, mapping)
                    doc = clean_text(raw.get("numero_documento"))
                    if not re.search(r"\d{4,}", doc):   # descarta filas de instrucciones
                        continue
                    filas += 1
                    yield {**raw, "__sheet__": f"pagina {pno}", "__row__": offset,
                           "__page_meta__": meta}

        # Tiene texto pero no salio ninguna fila. Es otro problema —la tabla no
        # se reconocio, o el oficio no trae tabla— y se dice distinto, porque
        # el remedio es distinto: aca el archivo sirve y hay que mirar el
        # formato, no pedirlo de nuevo.
        if not filas:
            raise PdfSinTabla(
                "Se leyo el texto del PDF pero no se reconocio la tabla de "
                "demandados, asi que no se extrajo ninguna persona. Revisa que "
                "el oficio traiga la tabla con las columnas de tipo y numero de "
                "documento; si la trae, mandalo para ajustar la lectura.")


# --------------------------------------------------------------------- router
READERS = {".xlsx": read_xlsx, ".xlsm": read_xlsx, ".xls": read_xlsx,
           ".csv": read_csv, ".txt": read_csv, ".pdf": read_pdf}


def detect_format(path: Path) -> str:
    ext = path.suffix.lower()
    if ext not in READERS:
        raise ValueError(f"Formato no soportado: {ext}")
    return {".xlsm": "xlsx", ".xls": "xlsx", ".txt": "csv"}.get(ext, ext.lstrip("."))


def read_any(path: Path) -> Iterator[Dict]:
    return READERS[path.suffix.lower()](path)
