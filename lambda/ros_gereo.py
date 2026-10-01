# -*- coding: utf-8 -*-
"""Del borrador de GEREO al ROS de WatchTower.

═══════════════════════════════════════════════════════════════════════════
LA DECISIÓN QUE ORDENA TODO ESTE ARCHIVO
═══════════════════════════════════════════════════════════════════════════

`ros.py` dice, sobre la narrativa: *«El sistema no la redacta ni la sugiere,
porque un texto generado que alguien firma sin leer es exactamente el
accidente que hay que evitar.»* GEREO devuelve narrativa generada.

Las dos cosas conviven con una sola regla, y es la que sostiene este módulo:
**el texto de GEREO nunca se escribe en `narrativa`.** Va a `borrador_gereo`,
que es un bloque aparte, marcado, que el analista lee y decide si usa. Copiar
ese texto al campo que firma el oficial de cumplimiento es un acto explícito
de una persona, un clic con nombre y hora, no una consecuencia de haber
apretado «generar».

El documento de GEREO coincide: el reporte sale incompleto a propósito, la
narrativa es un borrador, y *«si tu sistema automatiza algo sobre esto, que
sea preparar el trabajo del analista, nunca saltearlo»*.

═══════════════════════════════════════════════════════════════════════════
UN CAMPO AUSENTE SIGNIFICA «NO CORRESPONDE»
═══════════════════════════════════════════════════════════════════════════

GEREO no manda los campos cuya condición no se cumple: la referencia al
reporte anterior sólo si está vinculado a uno, los datos del cargo sólo si la
persona es PEP. No es un error ni un valor que haya que asumir.

Por eso acá no se rellena nada con `""` ni con `None`: lo que no vino, no se
inventa. La pantalla muestra lo que hay; lo que no está, no se dibuja —igual
que en la pantalla del analista de GEREO.
"""
from __future__ import annotations

import re

# Las secciones de cada país, con el número y el nombre del formulario del
# regulador. Salen del documento de integración; el orden es el del PDF.
#
# En Argentina las dos secciones `3_…` son EXCLUYENTES: viene la que
# corresponde al cliente y la otra no viaja. Por eso están las dos acá y el
# render se queda con la que exista.
SECCIONES = {
    "Chile": [
        ("1_antecedentes_operaciones_sospechosas", "Antecedentes de las operaciones sospechosas"),
        ("2_identificacion_reportados", "Identificación de los reportados"),
    ],
    "Colombia": [
        ("1_informacion_general_reporte", "Información general del reporte"),
        ("2_persona_juridica", "Persona jurídica"),
        ("3_persona_natural", "Persona natural"),
        ("4_detalle", "Detalle"),
    ],
    "Argentina": [
        ("1_datos_directos_ros", "Datos directos del ROS"),
        ("2_delito_precedente", "Delito precedente"),
        ("3_persona_fisica", "Persona física"),
        ("3_persona_fisica_extranjera", "Persona física extranjera"),
        ("4_operaciones_y_productos", "Operaciones y productos"),
    ],
}

# Los textos que GEREO redacta, por país. Se nombran para poder mostrarlos
# como lo que son —un borrador— y no mezclados con los datos duros.
#
# NO están en el mismo lugar en los tres países, y asumir que sí costó que en
# Argentina y Colombia no apareciera ninguno: cada formulario pide la narrativa
# donde su regulador la pide. En Chile es la sección de apertura; en los otros
# dos es la última, la de la operatoria. Por eso cada país trae su sección
# además de sus campos.
NARRATIVA = {
    "Chile": ("1_antecedentes_operaciones_sospechosas", (
        ("1_descripcion_hechos_orden_cronologico", "Descripción de los hechos"),
        ("2_que_se_considero_sospechoso", "Qué se consideró sospechoso"),
    )),
    "Argentina": ("4_operaciones_y_productos", (
        ("descripcion_operatoria", "Descripción de la operatoria"),
        ("descripcion_analisis", "Análisis de la operatoria"),
        # Viene vacío: GEREO lo deja al analista. Se lista igual para que el
        # día que lo redacte aparezca donde corresponde y no en los datos duros.
        ("conclusiones", "Conclusiones"),
    )),
    "Colombia": ("4_detalle", (
        ("descripcion", "Descripción de la operación"),
    )),
}

# El aviso de que el texto lo escribió una IA. GEREO lo manda en Chile y NO lo
# manda en Argentina ni en Colombia, aunque `meta.generado_con_ia` venga en
# `true` en los tres. Como es la advertencia que impide que alguien firme texto
# generado sin leerlo, no puede depender de que el proveedor se acuerde de
# emitirla: la derivamos nosotros del flag y la sumamos si no vino.
AVISO_IA = "Textos narrativos redactados con IA (borrador — validar)."


def _texto(v):
    return str(v or "").strip()


def secciones_de(ros_doc: dict, pais: str) -> list:
    """Las secciones del país, con su nombre de formulario, en orden.

    Sólo las que vinieron: una sección ausente no se dibuja vacía.
    """
    fuera = []
    for clave, titulo in SECCIONES.get(pais, []):
        contenido = ros_doc.get(clave)
        if contenido in (None, "", {}, []):
            continue
        fuera.append({"clave": clave, "titulo": titulo, "contenido": contenido})
    return fuera


def narrativa_borrador(ros_doc: dict, pais: str) -> list:
    """Los textos que redactó GEREO, separados y etiquetados.

    Devuelve una lista de `{titulo, texto}` y NO una cadena sola: son dos
    respuestas a dos preguntas distintas del formulario, y pegarlas invita a
    copiarlas juntas a un campo que pide una de las dos.
    """
    seccion, campos = NARRATIVA.get(pais, ("", ()))
    bloque = ros_doc.get(seccion)
    if not isinstance(bloque, dict):
        return []
    fuera = []
    for clave, titulo in campos:
        t = _texto(bloque.get(clave))
        if t:
            fuera.append({"titulo": titulo, "texto": t})
    return fuera


def advertencias_de(respuesta: dict) -> list:
    """Lo que GEREO advierte, más lo que advertimos nosotros.

    Ver `AVISO_IA`: el flag `generado_con_ia` viene en los tres países, el
    texto de advertencia sólo en uno. Se agrega si ninguna advertencia de
    GEREO ya habla de IA, para no decirlo dos veces en Chile.
    """
    fuera = [a for a in (respuesta.get("advertencias") or []) if _texto(a)]
    meta = (respuesta.get("ros_doc") or {}).get("meta") or {}
    if meta.get("generado_con_ia") and not any(
            re.search(r"\bIA\b", str(a)) for a in fuera):
        fuera.append(AVISO_IA)
    return fuera


def reglas_de(ros_doc: dict) -> dict:
    """Las señales evaluadas, separadas en gatilladas y no gatilladas.

    La diferencia entre «esto disparó» y «esto se miró y no disparó» es justo
    lo que se audita: un ROS que no dice qué se descartó no permite
    reconstruir el análisis.
    """
    todas = ros_doc.get("reglas") or []
    return {
        "gatilladas": [r for r in todas if r.get("gatillada")],
        "descartadas": [r for r in todas if not r.get("gatillada")],
        "total_evaluadas": len(todas),
    }


def armar_borrador(respuesta: dict, run_id: str = "") -> dict:
    """El borrador de GEREO, listo para guardar junto al ROS.

    `respuesta` es lo que devuelve `gereo.generar_ros()`.
    """
    doc = respuesta.get("ros_doc") or {}
    meta = doc.get("meta") or {}
    opciones = respuesta.get("opciones") or {}
    pais = _texto(opciones.get("pais"))

    return {
        # Con qué parámetros se emitió. Es el eco que devuelve GEREO, incluido
        # el mes de término que resuelve solo cuando no se manda.
        "opciones": opciones,
        "meta": meta,
        # Lo primero que tiene que leer el analista: qué quedó pendiente de
        # criterio humano y por qué.
        "advertencias": advertencias_de(respuesta),
        # Las gatilladas, que son las que sostienen el reporte.
        "senales": respuesta.get("senales") or [],
        "reglas": reglas_de(doc),
        "secciones": secciones_de(doc, pais),
        # El texto de GEREO, aparte y etiquetado. NO va a `narrativa`.
        "narrativa_borrador": narrativa_borrador(doc, pais),
        "generado_en": _texto(meta.get("generado_en")),
        "generado_con_ia": bool(meta.get("generado_con_ia")),
        "run_id": _texto(run_id),
    }


def identificador(respuesta: dict, run_id: str = "") -> str:
    """El `externo_id` del ROS: de dónde salió este borrador.

    `ros.py` lo dejó vacío esperando esto — «cuando se conecte, los que
    vengan de allá se distinguen de los de acá sin migrar nada».
    """
    meta = (respuesta.get("ros_doc") or {}).get("meta") or {}
    cliente = _texto(meta.get("customer_id")) or _texto(
        (respuesta.get("opciones") or {}).get("customer_id"))
    partes = [p for p in ("gereo", cliente, _texto(run_id)[:8]) if p]
    return ":".join(partes)


def listo_para_enviar(borrador: dict) -> list:
    """Qué falta antes de poder marcar el ROS como enviado.

    Es la traducción de las advertencias de GEREO a un control nuestro: la
    API avisa que el reporte sale incompleto a propósito, y sin esto ese
    aviso queda en un texto que nadie relee al momento de enviar.
    """
    faltan = []
    if not (borrador.get("senales") or []):
        faltan.append("No se gatilló ninguna señal automática: el analista "
                      "tiene que ingresar al menos una antes de enviar.")
    faltan += [a for a in (borrador.get("advertencias") or [])]
    return faltan
