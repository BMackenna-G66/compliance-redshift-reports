# -*- coding: utf-8 -*-
"""Revisar y aprobar un ROS: quién puede, sobre qué versión y con qué acuse.

═══════════════════════════════════════════════════════════════════════════
SE APRUEBA UNA VERSIÓN, NO «EL ROS»
═══════════════════════════════════════════════════════════════════════════

La aprobación queda atada a un `json_sha256`: el del objeto exacto que se
revisó. Si después alguien edita, eso crea otra versión y la aprobación no la
alcanza — por eso editar devuelve el reporte a «recibido».

Sin esto, «lo aprobó Fulana» no se podría probar: el documento aprobado y el
documento que se manda serían dos cosas distintas y nadie notaría la
diferencia.

═══════════════════════════════════════════════════════════════════════════
CUATRO OJOS: QUIÉN NO PUEDE APROBAR
═══════════════════════════════════════════════════════════════════════════

Ni quien revisó, ni quien editó. Y «editó» es cualquiera que creó una versión
de edición desde la v1, no sólo el de la última: si A edita la v2 y B la v3,
el contenido de la v3 sigue siendo en parte de A, así que A no aprueba.

La v1 NO cuenta. La creó GEREO a pedido de alguien, y pedir un reporte no es
escribirlo: si contara, quien lo pidió quedaría inhabilitado para aprobarlo
sin haber tocado una letra.

═══════════════════════════════════════════════════════════════════════════
EL ACUSE DE IA ES EXPLÍCITO CUANDO EL TEXTO NO SE TOCÓ
═══════════════════════════════════════════════════════════════════════════

Si la narrativa de la versión a aprobar es idéntica a la que redactó GEREO,
quien firma tiene que decirlo con todas las letras. No es un tecnicismo: es
la pregunta que va a hacer una auditoría —«¿esto lo escribió una persona?»— y
hoy nadie la podría contestar.
"""
from __future__ import annotations

import ros_gereo
import ros_versiones


# ── El padrón ──────────────────────────────────────────────────────────────
#
# DÓNDE NO VIVE, y por qué. En el repo no: es público y serían correos de
# personas con un rol de cumplimiento. En una variable de entorno tampoco:
# `update-function-configuration` reemplaza el mapa entero y ahí es donde se
# pisan secretos sin querer.
#
# Vive en S3, se lee en CADA aprobación y no se cachea: una baja tiene que
# tener efecto ahora, no cuando Lambda recicle el contenedor.
CLAVE_PADRON = "crm/config/oficiales_cumplimiento.json"


def oficiales_de(documento) -> list:
    """Los correos del padrón, normalizados. Vacío si no hay nada.

    FALLA CERRADO: si el objeto no existe, está vacío o viene con otra forma,
    la lista es vacía y no aprueba nadie. Es lo correcto — un padrón que no se
    puede leer no es «todos pueden», es «no sabemos quién puede».
    """
    if isinstance(documento, dict):
        crudos = documento.get("oficiales") or documento.get("emails") or []
    elif isinstance(documento, list):
        crudos = documento
    else:
        crudos = []
    fuera = []
    for c in crudos:
        correo = str(c or "").strip().lower()
        if correo and correo not in fuera:
            fuera.append(correo)
    return fuera


# ── Quién tocó qué ─────────────────────────────────────────────────────────

def editores_de(reporte: dict) -> set:
    """Quiénes escribieron contenido en este ROS.

    Sólo las versiones de edición: la v1 la generó GEREO y pedirla no es
    escribirla.
    """
    return {
        str(v.get("creada_por") or "").strip().lower()
        for v in ros_versiones.versiones_de(reporte)
        if v.get("origen") == "edicion" and str(v.get("creada_por") or "").strip()
    }


def revisores_de(reporte: dict) -> set:
    """Quiénes marcaron «revisado», en toda la historia del reporte.

    Van todos y no sólo el último: si A revisó, se editó, y B revisó de nuevo,
    los dos miraron ese contenido y ninguno es el par de ojos independiente.
    """
    return {
        str(h.get("quien") or "").strip().lower()
        for h in (reporte.get("historial_gereo") or [])
        if h.get("etapa") == "revisado" and str(h.get("quien") or "").strip()
    }


# ── Los controles ──────────────────────────────────────────────────────────

def bloqueos_para_revisar(reporte: dict) -> list:
    """Por qué no se puede marcar como revisado."""
    faltan = []
    if not ros_versiones.versiones_de(reporte):
        faltan.append("Este reporte no tiene ninguna versión guardada: no hay "
                      "nada que revisar.")
    return faltan


def bloqueos_para_aprobar(reporte: dict, quien: str, oficiales,
                          acuse_ia: bool, narrativa_es_de_ia: bool) -> list:
    """Por qué no se puede aprobar. Lista vacía = se puede.

    El orden importa poco salvo en una cosa: se devuelven TODOS los motivos y
    no el primero. Alguien que arregla uno y vuelve a chocar con otro deja de
    confiar en lo que la pantalla le dice.
    """
    faltan = []
    correo = str(quien or "").strip().lower()
    lista = [str(o).strip().lower() for o in (oficiales or [])]

    if not lista:
        faltan.append("Todavía no hay ningún Oficial de Cumplimiento "
                      "designado, así que nadie puede aprobar un ROS. Lo "
                      "carga un administrador.")
    elif correo not in lista:
        faltan.append("Aprobar el envío de un ROS está reservado al Oficial "
                      "de Cumplimiento.")

    # CUATRO OJOS. Sin excepciones y sin forma de relevarlo desde la pantalla.
    if correo and correo in revisores_de(reporte):
        faltan.append("Vos marcaste este reporte como revisado: tiene que "
                      "aprobarlo otra persona.")
    if correo and correo in editores_de(reporte):
        faltan.append("Vos editaste el contenido de este reporte: tiene que "
                      "aprobarlo otra persona.")

    if narrativa_es_de_ia and not acuse_ia:
        faltan.append("El texto del reporte es el que redactó la IA, sin "
                      "modificar. Hay que decirlo expresamente para aprobarlo.")

    return faltan


# ── Qué cambió respecto de lo que generó GEREO ────────────────────────────

def _texto(v) -> str:
    return "" if v is None else str(v)


def _vacio(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def diferencias_contra_v1(v1: dict, version: dict) -> list:
    """Qué tocó una persona desde que GEREO lo generó.

    Devuelve `{ruta, antes, despues, vaciado}`. `vaciado` marca los campos que
    GEREO había llenado y quedaron en blanco: es la única forma de BORRAR un
    dato que el modelo sí trajo —un RUT, un monto— y quien firma tiene que
    verlo, porque el documento va a salir sin él.
    """
    a = _valores(v1)
    b = _valores(version)
    fuera = []
    for ruta in sorted(set(a) | set(b)):
        antes, despues = a.get(ruta), b.get(ruta)
        if antes == despues:
            continue
        fuera.append({
            "ruta": ruta,
            "antes": _texto(antes),
            "despues": _texto(despues),
            "vaciado": bool(not _vacio(antes) and _vacio(despues)),
        })
    return fuera


def _valores(obj, prefijo: str = "") -> dict:
    """Cada hoja con su valor. Espeja `ros_versiones.rutas_de`, que da tipos."""
    fuera = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            fuera.update(_valores(v, f"{prefijo}.{k}" if prefijo else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            fuera.update(_valores(v, f"{prefijo}[{i}]"))
        if not obj:
            fuera[prefijo] = None
    else:
        fuera[prefijo] = obj
    return fuera


def narrativa_sin_tocar(v1: dict, version: dict, pais: str) -> bool:
    """Si el texto que se va a reportar es el de GEREO, palabra por palabra.

    Se compara sólo la narrativa y no el documento entero: corregir un monto
    no cambia que el TEXTO lo escribió una IA, que es lo que hay que acusar.
    """
    de_gereo = ros_gereo.narrativa_borrador(v1, pais)
    de_ahora = ros_gereo.narrativa_borrador(version, pais)
    if not de_ahora:
        return False
    return [(n["titulo"], n["texto"]) for n in de_gereo] == \
           [(n["titulo"], n["texto"]) for n in de_ahora]


def narrativa_para_el_registro(version: dict, pais: str) -> str:
    """El texto que efectivamente se reporta, para guardarlo en el ROS.

    SALE DE LA VERSIÓN APROBADA y no de un campo aparte. Si `narrativa` fuera
    independiente, el registro podría decir una cosa y el regulador recibir
    otra — y eso es peor que un campo vacío, porque nadie lo notaría.
    """
    bloques = ros_gereo.narrativa_borrador(version, pais)
    return "\n\n".join(f"{b['titulo']}\n{b['texto']}" for b in bloques).strip()
