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

import re

import ros
import ros_etapas
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


def aprobacion_vigente(reporte: dict) -> dict | None:
    """La aprobación SI sigue valiendo para la versión actual.

    NADIE LEE `aprobacion` A PELO. El campo puede haber quedado de una versión
    anterior —aunque al editar se limpia, un registro viejo o una escritura a
    medias pueden dejarlo—, y leerlo directo haría pasar por aprobado algo que
    no lo está. Se compara la versión Y el hash: si el contenido cambió, la
    firma no lo alcanza.
    """
    ap = reporte.get("aprobacion")
    if not isinstance(ap, dict):
        return None
    actual = reporte.get("version_actual") or 0
    if int(ap.get("version") or 0) != int(actual):
        return None
    ficha = ros_versiones.version_de(reporte, actual) or {}
    if ap.get("json_sha256") and ap["json_sha256"] != ficha.get("json_sha256"):
        return None
    return ap


def bloqueos_para_aprobar(reporte: dict, quien: str, oficiales,
                          acuse_ia: bool, narrativa_es_de_ia: bool,
                          acuse_gereo: bool) -> list:
    """Por qué no se puede aprobar. Lista vacía = se puede.

    El orden importa poco salvo en una cosa: se devuelven TODOS los motivos y
    no el primero. Alguien que arregla uno y vuelve a chocar con otro deja de
    confiar en lo que la pantalla le dice.

    `acuse_gereo` NO tiene default. Es la misma regla que ya costó una vez con
    `etapa` y `pendientes`: un control cuyo parámetro se puede omitir es un
    control que el próximo llamador saltea sin enterarse. Que cada uno diga
    explícitamente si hubo acuse.
    """
    faltan = []
    correo = str(quien or "").strip().lower()
    lista = [str(o).strip().lower() for o in (oficiales or [])]

    # DÓNDE TIENE QUE ESTAR EL REPORTE. Sin esto se podía aprobar un ROS en
    # «recibido» que nadie revisó —el oficial aprobando solo, sin segundo par
    # de ojos, que es justo lo que el cuatro ojos existe para impedir—, uno
    # descartado, o uno ya enviado.
    #
    # LA ETAPA Y LOS PENDIENTES SE CALCULAN ACÁ, no se reciben. Como
    # parámetros con default, un llamador que no los pasara saltearía el
    # control en silencio — y el próximo que use esta función sin ese kwarg
    # reabriría exactamente lo que cierra. Un control que depende de que lo
    # invoquen bien no es un control.
    etapa = ros_etapas.etapa_de(reporte)
    if etapa != "revisado":
        faltan.append("Para aprobar, el reporte tiene que estar marcado como "
                      f"revisado (hoy está en «{etapa}»).")
    estado = str(reporte.get("estado") or "").strip()
    if estado == "descartado":
        faltan.append("Este ROS está descartado: se decidió no reportarlo.")
    elif estado != "revision_legal":
        faltan.append("El reporte tiene que estar en revisión legal (hoy está "
                      f"en «{estado or 'sin estado'}»).")

    # LO QUE GEREO DEJÓ PENDIENTE SE ACUSA, NO BLOQUEA.
    #
    # Estaba como bloqueo seco y hacía que NINGÚN ROS de GEREO se pudiera
    # aprobar jamás. `ros.cambiar_estado` ya explicaba por qué, en el camino
    # viejo, es un acuse: «las advertencias vienen en TODAS las corridas —el
    # reporte sale incompleto a propósito y el texto siempre es generado—, así
    # que bloquear sin salida trabaría el módulo para siempre». El camino
    # nuevo copió el control y perdió esa parte.
    #
    # No se descubrió antes porque no hay ningún ROS en producción: el flujo
    # entero nunca corrió sobre un registro real. Lo encontró la prueba de
    # punta a punta de la entrega, que es la primera que recorre el camino
    # completo.
    #
    # Lo que falta no es que las advertencias desaparezcan: es que alguien se
    # haga cargo de haberlas leído, con nombre y hora. Eso es lo que queda en
    # `aprobacion.acuse_gereo`.
    pendientes = ros.pendientes_gereo(reporte)
    if pendientes and not acuse_gereo:
        faltan.append(
            "El borrador de GEREO deja puntos pendientes de tu criterio y hay "
            "que acusarlos para aprobar: " + "; ".join(str(p) for p in pendientes))

    # UNA VERSIÓN NO SE APRUEBA DOS VECES. La segunda pisaría la primera y la
    # firma original desaparecería del registro.
    if aprobacion_vigente(reporte):
        faltan.append("Esta versión ya está aprobada.")

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
            # AGREGADO: la ruta no existe en la v1, o sea que es un elemento
            # que sumó una persona. Quien firma tiene que distinguirlo de una
            # corrección: no es que GEREO se equivocó, es que alguien metió
            # un reportado que el modelo no encontró.
            "agregado": ruta not in a,
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


def _normalizar(t: str) -> str:
    """El texto sin lo que no cambia lo que dice.

    SE NORMALIZA ANTES DE COMPARAR porque, si no, el acuse de IA se esquiva
    con un espacio: agregar un punto al final o un salto de línea volvía el
    texto «distinto» y el control desaparecía. Nadie lo haría a propósito —y
    justamente por eso: pasaría sin que nadie lo note.

    Se ignoran espacios, PUNTUACIÓN y mayúsculas. Un cambio que es sólo un
    punto final o una letra capital no es autoría humana; es la misma evasión
    que el espacio con otra ropa. Qué hacer cuando el texto cambió de verdad
    pero poco —un umbral de parecido— es otra decisión, y es de negocio.
    """
    sin_puntuacion = re.sub(r"[^\w\s]", " ", str(t or ""), flags=re.UNICODE)
    return " ".join(sin_puntuacion.casefold().split())


def hay_narrativa(version: dict, pais: str) -> bool:
    return bool(ros_gereo.narrativa_borrador(version, pais))


def narrativa_sin_tocar(v1: dict, version: dict, pais: str) -> bool:
    """Si el texto que se va a reportar es el de GEREO, palabra por palabra.

    Se compara sólo la narrativa y no el documento entero: corregir un monto
    no cambia que el TEXTO lo escribió una IA, que es lo que hay que acusar.
    """
    de_ahora = ros_gereo.narrativa_borrador(version, pais)
    if not de_ahora:
        # Sin narrativa no hay texto de IA que acusar. Que no se pueda
        # aprobar un reporte sin narrativa es otro control, aparte.
        return False
    de_gereo = ros_gereo.narrativa_borrador(v1, pais)
    return [(n["titulo"], _normalizar(n["texto"])) for n in de_gereo] == \
           [(n["titulo"], _normalizar(n["texto"])) for n in de_ahora]


def narrativa_para_el_registro(version: dict, pais: str) -> str:
    """El texto que efectivamente se reporta, para guardarlo en el ROS.

    SALE DE LA VERSIÓN APROBADA y no de un campo aparte. Si `narrativa` fuera
    independiente, el registro podría decir una cosa y el regulador recibir
    otra — y eso es peor que un campo vacío, porque nadie lo notaría.
    """
    bloques = ros_gereo.narrativa_borrador(version, pais)
    return "\n\n".join(f"{b['titulo']}\n{b['texto']}" for b in bloques).strip()
