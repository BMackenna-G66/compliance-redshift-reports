"""Generacion masiva de oficios Word a partir de las plantillas judiciales."""
from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from docxtpl import DocxTemplate

from .normalize import fecha_larga_es, format_amount_cop


@dataclass
class ResultadoGeneracion:
    generados: List[Path]
    zip_clientes: Optional[Path] = None
    zip_no_clientes: Optional[Path] = None
    errores: List[str] = None

    def __post_init__(self):
        self.errores = self.errores or []


def slug(texto: str, largo: int = 40) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").upper()
    return t[:largo] or "SIN_NOMBRE"


def construir_contexto(persona: Dict, fecha: Optional[date] = None,
                       ciudad: str = "Bogotá D.C.") -> Dict:
    """Contexto Jinja para las plantillas.

    Nota de implementacion: la plantilla usa el placeholder
    ``{{numero_de_identificacion_C.C}}``. Jinja lo interpreta como el atributo
    ``C`` de la variable ``numero_de_identificacion_C``; por eso se entrega un
    diccionario anidado. Asi las plantillas originales funcionan SIN editarlas.
    """
    documento = str(persona.get("numero_documento", ""))
    nombre = persona.get("nombre_completo", "")
    oficio = persona.get("numero_oficio") or persona.get("numeros_oficio", "")
    return {
        "fecha_oficial": fecha_larga_es(fecha, ciudad),
        "numero_oficio": oficio,
        "demandado": nombre,
        "numero_de_identificacion_C": {"C": documento},   # -> {{numero_de_identificacion_C.C}}
        "numero_de_identificacion": documento,            # alias si se limpia la plantilla
        "tipo_documento": persona.get("tipo_documento", ""),
        "numero_proceso": persona.get("numero_proceso") or persona.get("numeros_proceso", ""),
        "valor_limite_embargo": format_amount_cop(persona.get("valor_total_a_embargar")
                                                  or persona.get("valor_limite_embargo")),
        "cantidad_procesos": persona.get("cantidad_procesos", 1),
    }


def nombre_archivo(persona: Dict, es_cliente: bool, indice: Optional[int] = None) -> str:
    partes = ["CLIENTE" if es_cliente else "NOCLIENTE",
              str(persona.get("numero_documento", "")),
              slug(persona.get("nombre_completo", ""))]
    oficio = slug(str(persona.get("numero_oficio", "")), 20)
    if oficio:
        partes.append(oficio)
    if indice is not None:
        partes.append(f"{indice:05d}")
    return "_".join(p for p in partes if p) + ".docx"


def generar_oficios(personas: Iterable[Dict],
                    plantilla_cliente: Path,
                    plantilla_no_cliente: Path,
                    destino: Path,
                    fecha: Optional[date] = None,
                    ciudad: str = "Bogotá D.C.",
                    empaquetar_zip: bool = True,
                    campo_cliente: str = "es_cliente") -> ResultadoGeneracion:
    """Renderiza un .docx por persona segun sea o no cliente y arma los ZIP."""
    destino = Path(destino)
    dir_cli = destino / "oficios_clientes"
    dir_no = destino / "oficios_no_clientes"
    dir_cli.mkdir(parents=True, exist_ok=True)
    dir_no.mkdir(parents=True, exist_ok=True)

    generados: List[Path] = []
    errores: List[str] = []
    usados: set = set()

    for i, persona in enumerate(personas, start=1):
        es_cliente = bool(persona.get(campo_cliente))
        plantilla = plantilla_cliente if es_cliente else plantilla_no_cliente
        carpeta = dir_cli if es_cliente else dir_no
        try:
            doc = DocxTemplate(str(plantilla))
            doc.render(construir_contexto(persona, fecha, ciudad))
            nombre = nombre_archivo(persona, es_cliente)
            if nombre in usados:                       # colision: agrega indice
                nombre = nombre_archivo(persona, es_cliente, i)
            usados.add(nombre)
            ruta = carpeta / nombre
            doc.save(str(ruta))
            generados.append(ruta)
        except Exception as exc:                        # una persona no tumba el lote
            errores.append(f"{persona.get('numero_documento')}: {exc}")

    res = ResultadoGeneracion(generados=generados, errores=errores)
    if empaquetar_zip:
        res.zip_clientes = _zipear(dir_cli, destino / "oficios_clientes.zip")
        res.zip_no_clientes = _zipear(dir_no, destino / "oficios_no_clientes.zip")
    return res


def _zipear(carpeta: Path, destino_zip: Path) -> Optional[Path]:
    archivos = sorted(carpeta.glob("*.docx"))
    if not archivos:
        return None
    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for a in archivos:
            zf.write(a, arcname=a.name)
    return destino_zip
