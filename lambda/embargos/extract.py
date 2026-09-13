"""Orquestador: archivo de entrada -> registros canonicos + reporte de calidad."""
from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .normalize import (clean_text, normalize_doc_id, normalize_doc_type,
                        normalize_name, parse_amount, validate_doc_id)
from .readers import detect_format, read_any
from .schema import CANONICAL_COLUMNS, RegistroEmbargo


@dataclass
class ReporteExtraccion:
    archivo: str = ""
    formato: str = ""
    hojas: List[str] = field(default_factory=list)
    hojas_omitidas: List[str] = field(default_factory=list)
    filas_leidas: int = 0
    registros_validos: int = 0
    registros_descartados: int = 0
    personas_unicas: int = 0
    metadatos_documento: Dict[str, str] = field(default_factory=dict)
    conteo_flags: Dict[str, int] = field(default_factory=dict)
    motivos_descarte: Dict[str, int] = field(default_factory=dict)

    def resumen(self) -> str:
        lineas = [
            f"Archivo           : {self.archivo}",
            f"Formato           : {self.formato}",
            f"Hojas / secciones : {', '.join(self.hojas) or '-'}",
            f"Filas leidas      : {self.filas_leidas:,}",
            f"Registros validos : {self.registros_validos:,}",
            f"Descartados       : {self.registros_descartados:,}",
            f"Personas unicas   : {self.personas_unicas:,}",
        ]
        if self.metadatos_documento:
            lineas.append(f"Metadatos oficio  : {self.metadatos_documento}")
        if self.motivos_descarte:
            lineas.append(f"Motivos descarte  : {dict(self.motivos_descarte)}")
        if self.conteo_flags:
            lineas.append(f"Alertas calidad   : {dict(self.conteo_flags)}")
        return "\n".join(lineas)


@dataclass
class ResultadoExtraccion:
    registros: List[RegistroEmbargo] = field(default_factory=list)
    descartados: List[RegistroEmbargo] = field(default_factory=list)
    reporte: ReporteExtraccion = field(default_factory=ReporteExtraccion)


def _construir_registro(raw: Dict, archivo: str, formato: str) -> RegistroEmbargo:
    doc_raw = clean_text(raw.get("numero_documento"))
    tipo_raw = clean_text(raw.get("tipo_documento"))
    nombre, nombre_lossy = normalize_name(raw.get("nombre_completo"))
    tipo = normalize_doc_type(tipo_raw) or ("CC" if doc_raw.isdigit() else "")
    doc = normalize_doc_id(doc_raw)

    reg = RegistroEmbargo(
        numero_documento=doc,
        numero_documento_raw=doc_raw,
        tipo_documento=tipo,
        tipo_documento_raw=tipo_raw,
        nombre_completo=nombre,
        valor_limite_embargo=parse_amount(raw.get("valor_limite_embargo")),
        numero_proceso=clean_text(raw.get("numero_proceso")),
        numero_oficio=clean_text(raw.get("numero_oficio")),
        numero_resolucion=clean_text(raw.get("numero_resolucion")),
        cuenta_judicial=clean_text(raw.get("cuenta_judicial")),
        demandante=clean_text(raw.get("demandante")),
        nit_demandante=clean_text(raw.get("nit_demandante")),
        fecha_proceso=clean_text(raw.get("fecha_proceso")),
        archivo_origen=archivo,
        hoja_origen=raw.get("__sheet__", ""),
        fila_origen=raw.get("__row__"),
        formato_origen=formato,
    )

    # Metadatos del oficio (PDF) rellenan solo lo que la fila no traiga.
    meta = raw.get("__page_meta__") or {}
    for campo in ("numero_oficio", "numero_resolucion", "cuenta_judicial"):
        if not getattr(reg, campo) and meta.get(campo):
            setattr(reg, campo, meta[campo])

    # ---- reglas de calidad ----
    motivo = validate_doc_id(reg.numero_documento, reg.tipo_documento)
    if motivo:
        reg.flags.append(f"ERROR:{motivo}")
    if not reg.nombre_completo:
        reg.flags.append("ERROR:nombre_vacio")
    elif len(reg.nombre_completo.split()) < 2:
        reg.flags.append("AVISO:nombre_de_una_sola_palabra")
    if nombre_lossy:
        reg.flags.append("AVISO:nombre_con_caracteres_perdidos")
    if doc_raw.lstrip("'").lstrip().startswith("0"):
        reg.flags.append("AVISO:documento_con_ceros_a_la_izquierda")
    if reg.valor_limite_embargo is None:
        reg.flags.append("AVISO:sin_valor_limite")
    if len(reg.nombre_completo) > 60:
        reg.flags.append("AVISO:nombre_anomalo_muy_largo")
    return reg


def extraer(path, archivo_alias: Optional[str] = None) -> ResultadoExtraccion:
    """Extrae registros canonicos desde xlsx / csv / pdf."""
    path = Path(path)
    formato = detect_format(path)
    nombre_archivo = archivo_alias or path.name
    res = ResultadoExtraccion()
    res.reporte.archivo = nombre_archivo
    res.reporte.formato = formato

    hojas: "OrderedDict[str, None]" = OrderedDict()
    flags = Counter()
    motivos = Counter()

    for raw in read_any(path):
        if "__meta__" in raw:
            res.reporte.metadatos_documento = {
                k: v for k, v in raw["__meta__"].items() if not k.startswith("__")}
            if "__declarado__" in raw["__meta__"]:
                res.reporte.metadatos_documento["registros_declarados_en_texto"] = \
                    raw["__meta__"]["__declarado__"]
            continue
        if "__skip_sheet__" in raw:
            res.reporte.hojas_omitidas.append(
                f"{raw['__skip_sheet__']} ({raw['__reason__']})")
            continue

        res.reporte.filas_leidas += 1
        hojas[raw.get("__sheet__", "")] = None
        reg = _construir_registro(raw, nombre_archivo, formato)
        for f in reg.flags:
            flags[f] += 1
        if reg.es_valido:
            res.registros.append(reg)
        else:
            res.descartados.append(reg)
            for f in reg.flags:
                if f.startswith("ERROR:"):
                    motivos[f[6:]] += 1

    res.reporte.hojas = [h for h in hojas if h]
    res.reporte.registros_validos = len(res.registros)
    res.reporte.registros_descartados = len(res.descartados)
    res.reporte.personas_unicas = len({r.clave_persona for r in res.registros})
    res.reporte.conteo_flags = dict(flags)
    res.reporte.motivos_descarte = dict(motivos)
    return res


def consolidar_por_persona(registros: List[RegistroEmbargo]) -> List[Dict]:
    """Agrupa por documento. Suma valores y concatena procesos/oficios."""
    grupos: "OrderedDict[str, List[RegistroEmbargo]]" = OrderedDict()
    for r in registros:
        grupos.setdefault(r.clave_persona, []).append(r)

    consolidado = []
    for clave, items in grupos.items():
        base = items[0]
        nombre = max((i.nombre_completo for i in items), key=len)  # el menos truncado
        valores = [i.valor_limite_embargo for i in items if i.valor_limite_embargo is not None]
        procesos = sorted({i.numero_proceso for i in items if i.numero_proceso})
        oficios = sorted({i.numero_oficio for i in items if i.numero_oficio})
        consolidado.append({
            "clave_persona": clave,
            "tipo_documento": base.tipo_documento,
            "numero_documento": base.numero_documento,
            "numero_documento_raw": base.numero_documento_raw,
            "nombre_completo": nombre,
            "cantidad_procesos": len(items),
            "valor_total_a_embargar": round(sum(valores), 2) if valores else None,
            "numeros_proceso": " | ".join(procesos),
            "numeros_oficio": " | ".join(oficios),
            "numero_oficio": oficios[0] if oficios else "",
            "numero_resolucion": base.numero_resolucion,
            "cuenta_judicial": base.cuenta_judicial,
            "demandante": base.demandante,
            "archivo_origen": base.archivo_origen,
            "hojas_origen": " | ".join(sorted({i.hoja_origen for i in items if i.hoja_origen})),
            "flags": "; ".join(sorted({f for i in items for f in i.flags})),
        })
    return consolidado


def a_dataframe(registros: List[RegistroEmbargo]):
    import pandas as pd
    df = pd.DataFrame([r.to_dict() for r in registros])
    if df.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return df[[c for c in CANONICAL_COLUMNS if c in df.columns]]
