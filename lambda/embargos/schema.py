"""Esquema canonico: el unico contrato de datos que sale del extractor."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional

# --------------------------------------------------------------------------
# Sinonimos de encabezado. La clave es el campo canonico; los valores son
# fragmentos en MAYUSCULAS SIN TILDES que deben aparecer en el encabezado.
# Se evalua por orden: gana el primer patron que haga match.
# --------------------------------------------------------------------------
COLUMN_SYNONYMS = {
    "numero_documento": [
        "NUMERO ID DEMANDADO", "NUMERO DOCUMENTO", "NUMERO DE DOCUMENTO",
        "IDENTIFICACION INFRACTOR", "IDENTIFICACION DEMANDADO", "NUMERO IDENTIFICACION",
        "NRO DOCUMENTO", "NO DOCUMENTO", "CEDULA", "DOCUMENTO", "IDENTIFICACION",
        "NUMERO ID", "NIT DEMANDADO", "DNI",
    ],
    "nombre_completo": [
        "NOMBRE Y APELLIDO DEL DEMANDADO", "NOMBRE Y APELLIDO", "NOMBRE INFRACTOR",
        "NOMBRE DEMANDADO", "NOMBRE DEL DEMANDADO", "NOMBRE Y NUMERO CEDULA DEUDOR",
        "NOMBRE Y NUMERO CEDULA", "NOMBRE COMPLETO", "NOMBRE SANCIONADO",
        "NOMBRES Y APELLIDOS", "TITULAR", "NOMBRE",
    ],
    "tipo_documento": [
        "TIPO DE DOCUMENTO", "TIPO DOCUMENTO", "CLASE DOCUMENTO", "TIPO ID", "TIPO",
    ],
    "valor_limite_embargo": [
        "VALOR LIMITE A EMBARGAR", "VALOR ACTUALIZADO A EMBARGAR", "LIMITE DEL EMBARGO",
        "LIMITE DE EMBARGO", "VALOR A EMBARGAR", "VALOR EMBARGO", "MONTO",
        "VALOR LIMITE", "CUANTIA",
    ],
    "numero_proceso": [
        "NUMERO DE PROCESO", "RAD PROCESO COACTIVO", "RADICADO PROCESO",
        "NRO COACTIVO", "NUMERO PROCESO", "PROCESO COACTIVO", "RADICADO",
        "NRO COMPARENDO", "NUMERO COMPARENDO", "EXPEDIENTE",
    ],
    "numero_oficio": [
        "NUMERO OFICIO", "NUMERO DE OFICIO", "NO DE OFICIO", "NO OFICIO", "OFICIO",
    ],
    "numero_resolucion": ["NUMERO RESOLUCION", "NUMERO DE RESOLUCION", "RESOLUCION"],
    "cuenta_judicial": ["NUMERO CUENTA JUDICIAL", "CUENTA JUDICIAL", "NUMERO DE CUENTA"],
    "demandante": ["DEMANDANTE", "ENTIDAD DEMANDANTE", "ACREEDOR"],
    "nit_demandante": ["NIT DEMANDANTE"],
    "fecha_proceso": ["FECHA COACTIVO", "FECHA COMPARENDO", "FECHA PROCESO", "FECHA"],
}

# Campos minimos sin los cuales una fila no es explotable.
REQUIRED_FIELDS = ("numero_documento", "nombre_completo")


@dataclass
class RegistroEmbargo:
    """Una persona requerida en un oficio de embargo."""
    # --- identidad (lo que alimenta la validacion en Redshift) ---
    numero_documento: str = ""            # normalizado: solo digitos, sin ceros a la izquierda
    numero_documento_raw: str = ""        # tal como venia en el archivo
    tipo_documento: str = ""              # codigo canonico: CC / CE / NIT / PA ...
    tipo_documento_raw: str = ""
    nombre_completo: str = ""

    # --- contexto judicial (alimenta los placeholders del Word) ---
    valor_limite_embargo: Optional[float] = None
    numero_proceso: str = ""
    numero_oficio: str = ""
    numero_resolucion: str = ""
    cuenta_judicial: str = ""
    demandante: str = ""
    nit_demandante: str = ""
    fecha_proceso: str = ""

    # --- trazabilidad ---
    archivo_origen: str = ""
    hoja_origen: str = ""
    fila_origen: Optional[int] = None
    formato_origen: str = ""              # xlsx | pdf | csv

    # --- calidad ---
    flags: List[str] = field(default_factory=list)

    @property
    def es_valido(self) -> bool:
        return not any(f.startswith("ERROR:") for f in self.flags)

    @property
    def clave_persona(self) -> str:
        return f"{self.tipo_documento or 'NA'}:{self.numero_documento}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["flags"] = "; ".join(self.flags)
        return d


CANONICAL_COLUMNS = [
    "numero_documento", "numero_documento_raw", "tipo_documento", "tipo_documento_raw",
    "nombre_completo", "valor_limite_embargo", "numero_proceso", "numero_oficio",
    "numero_resolucion", "cuenta_judicial", "demandante", "nit_demandante",
    "fecha_proceso", "archivo_origen", "hoja_origen", "fila_origen",
    "formato_origen", "flags",
]
