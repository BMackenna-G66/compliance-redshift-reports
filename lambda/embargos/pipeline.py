"""Pipeline end-to-end: archivo -> extraccion -> validacion -> Excel + oficios Word."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from .docgen import generar_oficios
from .excel_out import escribir_excel
from .extract import ResultadoExtraccion, consolidar_por_persona, extraer
from .schema import RegistroEmbargo
from .validation import ValidadorClientes, marcar_clientes

MODO_PERSONA = "persona"     # un oficio por documento de identidad (consolidado)
MODO_PROCESO = "proceso"     # un oficio por fila/proceso del archivo origen


@dataclass
class ResultadoPipeline:
    extraccion: ResultadoExtraccion
    personas: List[Dict] = field(default_factory=list)
    excel: Optional[Path] = None
    zip_clientes: Optional[Path] = None
    zip_no_clientes: Optional[Path] = None
    resumen: List[Dict] = field(default_factory=list)


def _registro_a_dict(r: RegistroEmbargo) -> Dict:
    d = r.to_dict()
    d["clave_persona"] = r.clave_persona
    return d


def procesar(archivo: Path,
             plantilla_cliente: Path,
             plantilla_no_cliente: Path,
             destino: Path,
             validador: ValidadorClientes,
             modo: str = MODO_PERSONA,
             generar_word: bool = True,
             fecha: Optional[date] = None,
             ciudad: str = "Bogotá D.C.",
             alias: Optional[str] = None) -> ResultadoPipeline:
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    extraccion = extraer(archivo, alias)

    if modo == MODO_PERSONA:
        personas = consolidar_por_persona(extraccion.registros)
    elif modo == MODO_PROCESO:
        personas = [_registro_a_dict(r) for r in extraccion.registros]
    else:
        raise ValueError(f"Modo no soportado: {modo}")

    personas = marcar_clientes(personas, validador)
    clientes = [p for p in personas if p["es_cliente"]]
    no_clientes = [p for p in personas if not p["es_cliente"]]
    descartados = [_registro_a_dict(r) for r in extraccion.descartados]

    rep = extraccion.reporte
    resumen = [
        {"indicador": "Archivo procesado", "valor": rep.archivo},
        {"indicador": "Formato detectado", "valor": rep.formato},
        {"indicador": "Hojas / secciones leidas", "valor": ", ".join(rep.hojas) or "-"},
        {"indicador": "Modo de generacion", "valor": modo},
        {"indicador": "Filas leidas", "valor": rep.filas_leidas},
        {"indicador": "Registros validos", "valor": rep.registros_validos},
        {"indicador": "Registros descartados", "valor": rep.registros_descartados},
        {"indicador": "Personas unicas", "valor": rep.personas_unicas},
        {"indicador": "Unidades a oficiar", "valor": len(personas)},
        {"indicador": "Clientes Global66", "valor": len(clientes)},
        {"indicador": "No clientes", "valor": len(no_clientes)},
        {"indicador": "Metadatos del oficio", "valor": str(rep.metadatos_documento or "-")},
        {"indicador": "Motivos de descarte", "valor": str(rep.motivos_descarte or "-")},
        {"indicador": "Alertas de calidad", "valor": str(rep.conteo_flags or "-")},
        {"indicador": "Fecha de ejecucion", "valor": str(fecha or date.today())},
    ]

    res = ResultadoPipeline(extraccion=extraccion, personas=personas, resumen=resumen)
    res.excel = escribir_excel(destino / "resultado_validacion.xlsx",
                               clientes, no_clientes, descartados, resumen)

    if generar_word:
        gen = generar_oficios(personas, plantilla_cliente, plantilla_no_cliente,
                              destino, fecha=fecha, ciudad=ciudad)
        res.zip_clientes, res.zip_no_clientes = gen.zip_clientes, gen.zip_no_clientes
        if gen.errores:
            resumen.append({"indicador": "Errores al generar Word",
                            "valor": "; ".join(gen.errores[:10])})
    return res
