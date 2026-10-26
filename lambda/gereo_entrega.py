# -*- coding: utf-8 -*-
"""El payload de la entrega del ROS aprobado a GEREO, y cómo leer su respuesta.

Esto es el paso 3 del flujo acordado con GEREO (propuesta del 23-10-2026):
WatchTower genera (paso 1), el analista revisa y aprueba (paso 2) y acá se
**entrega** el JSON aprobado. Desde ese momento el ROS queda bloqueado y la
comunicación termina: la autorización y la carga al regulador pasan en Slack
y no vuelven.

Lógica pura: ni red, ni S3, ni `resp()`. La llamada vive en `gereo.entregar()`
y el cableado en `api_handler`.

═══════════════════════════════════════════════════════════════════════════
EL HASH ES EL PUNTO FRÁGIL DE TODA LA INTEGRACIÓN
═══════════════════════════════════════════════════════════════════════════

GEREO valida que `hash_json` sea el SHA-256 de `ros_doc`. Pero el SHA-256 de
un objeto JSON no existe: existe el de **unos bytes**, y los bytes dependen de
cómo se serialice. Nuestro hash se calcula sobre `ros_versiones.canonico()`:

    json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    .encode("utf-8")

Si GEREO serializa distinto —un espacio después de la coma, `ensure_ascii`
prendido, otro orden de claves— el hash **nunca** va a coincidir y *todas* las
entregas van a ser 422. No es un riesgo que se descubra en una prueba: es
determinista y total. Tiene que estar acordado por escrito antes de habilitar
el endpoint.

Mientras tanto, lo que sí se puede controlar de este lado está controlado:
`desajuste_de_hash()` recalcula el hash sobre el documento que se va a mandar
y lo compara con el que se firmó al aprobar. Si difieren, lo que se leyó de S3
no es lo que se aprobó y no se entrega nada.

═══════════════════════════════════════════════════════════════════════════
EL 503 ACÁ SIGNIFICA LO CONTRARIO QUE EN LA GENERACIÓN
═══════════════════════════════════════════════════════════════════════════

En `gereo.generar_ros` un 503 es «la fuente de datos no responde» y mejora
insistiendo. En la entrega, 503 es «el endpoint todavía está deshabilitado»
(se publica apagado a propósito, para que WatchTower pueda dejar lista la
integración) y reintentar no cambia nada hasta la fecha que acuerden los dos
equipos. Al revés, los 5xx genéricos sí se reintentan y hoy `gereo._traducir`
no los marca reintentables.

Por eso la entrega tiene su propia tabla y no reusa la de la generación:
compartirla haría que el reintento se comporte exactamente al revés de lo que
corresponde, en los dos casos.
"""
from __future__ import annotations

import re

import ros_versiones

# Los tres países del acuerdo. Se valida de este lado antes de salir a la red
# por lo mismo que `gereo.validar`: GEREO lo rechazaría igual, con un viaje de
# por medio.
PAISES = ("Argentina", "Chile", "Colombia")

# ── el correo del cliente ────────────────────────────────────────────────
# GEREO arma la carpeta de Drive con `ID - NOMBRE - email`, así que el correo
# no es decorativo: sin él la carpeta del cliente queda mal nombrada.
#
# DÓNDE ESTÁ, MEDIDO SOBRE LOS 328 CASOS REALES:
#
#     alert_data.email            189
#     alert_data.customer_email    56
#     client_profile.email         18
#     en ninguno                   73   ← el 22%
#
# El orden de abajo es ese, de más frecuente a menos.
#
# `client_profile.compliance_agent` TAMBIÉN es un correo válido y aparece en
# un caso: es **nuestro analista**, no el cliente. Mandarlo como correo del
# cliente crearía una carpeta de Drive a nombre de un empleado. Por eso la
# búsqueda es por claves enumeradas y no «el primer campo que parezca correo»,
# que era la forma obvia de escribir esto y la forma de meter ese error.
CLAVES_CORREO = (
    ("alert_data", "email"),
    ("alert_data", "customer_email"),
    ("client_profile", "email"),
)

RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _texto(v) -> str:
    return str(v if v is not None else "").strip()


def correo_del_cliente(caso) -> tuple:
    """`(correo, de_dónde_salió)`. `("", "")` si el caso no lo tiene.

    Se devuelve el origen para que la pantalla pueda decir de dónde lo sacó:
    un correo que aparece sin explicación en un documento que va a un
    regulador es algo que alguien va a querer verificar.
    """
    caso = caso or {}
    for bloque, clave in CLAVES_CORREO:
        d = caso.get(bloque)
        if not isinstance(d, dict):
            continue
        v = _texto(d.get(clave))
        if v and RE_CORREO.match(v):
            return v, f"{bloque}.{clave}"
    return "", ""


def customer_id_de(reporte) -> str:
    """El id del cliente reportado, del eco de opciones que devolvió GEREO.

    Sale de `opciones` y no del caso a propósito: `opciones` es con qué
    parámetros se emitió **este** reporte, y es lo que GEREO va a cruzar
    contra `cliente.customer_id` en su validación (4.1).
    """
    borrador = (reporte or {}).get("borrador_gereo") or {}
    opciones = borrador.get("opciones") or {}
    return _texto(opciones.get("customer_id"))


def opciones_de(reporte) -> dict:
    borrador = (reporte or {}).get("borrador_gereo") or {}
    o = borrador.get("opciones")
    return dict(o) if isinstance(o, dict) else {}


def cliente_de(reporte, caso) -> dict:
    """El bloque `cliente` del payload."""
    correo, _ = correo_del_cliente(caso)
    return {
        "customer_id": customer_id_de(reporte),
        "nombre": _texto((caso or {}).get("entity_name")),
        "email": correo,
    }


def desajuste_de_hash(reporte, doc) -> str:
    """Por qué el documento leído NO es el que se aprobó. '' si coincide.

    Control propio, independiente del de GEREO: si lo que se leyó de S3 no
    hashea igual que lo que se firmó al aprobar, entregar sería mandar al
    regulador algo que nadie aprobó. Barato y determinista.
    """
    firmado = _texto(((reporte or {}).get("aprobacion") or {}).get("json_sha256"))
    if not firmado:
        return "la aprobación no guardó el hash de la versión"
    recalculado = ros_versiones.sha256_de(ros_versiones.canonico(doc))
    if recalculado != firmado:
        # Sin los hashes en el texto: va a la pantalla y no le dice nada a
        # nadie; el que importa ya está en el registro.
        return ("el documento guardado no coincide con el que se aprobó")
    return ""


def faltantes_para_entregar(reporte, caso) -> list:
    """Qué falta para poder entregar. Lista vacía = se puede.

    Son los controles que GEREO va a hacer igual (4.1) hechos de este lado:
    un 422 después de haber movido la etapa a «entregando» deja el reporte en
    error por algo que se sabía antes de salir.
    """
    faltan = []
    reporte = reporte or {}

    pais = ros_versiones.pais_largo(reporte)
    if pais not in PAISES:
        faltan.append("El reporte no tiene un país de los que GEREO recibe "
                      "(Argentina, Chile o Colombia).")

    aprobacion = reporte.get("aprobacion") or {}
    if not aprobacion.get("version"):
        faltan.append("El reporte no está aprobado: sólo se entrega una "
                      "versión aprobada.")
    elif int(aprobacion.get("version") or 0) != int(reporte.get("version_actual") or 0):
        # La aprobación quedó invalidada por una edición posterior. El registro
        # ya lo refleja; acá se dice con palabras antes de entregar la versión
        # equivocada.
        faltan.append("Se editó el reporte después de aprobarlo: hay que "
                      "aprobar la versión actual antes de entregarla.")

    if not customer_id_de(reporte):
        faltan.append("No sé el customer_id del cliente reportado: el "
                      "borrador de GEREO no trae `opciones`.")

    if not _texto((caso or {}).get("entity_name")):
        faltan.append("El caso no tiene el nombre del cliente, y GEREO arma "
                      "la carpeta del cliente con él.")

    # EL CORREO FRENA LA ENTREGA. 73 de los 328 casos no lo tienen, así que
    # esto va a aparecer seguido — y es a propósito: GEREO nombra la carpeta
    # de Drive `ID - NOMBRE - email`, y entregar sin correo deja una carpeta
    # mal nombrada en el expediente de un reporte regulatorio. Es más barato
    # completarlo antes que arreglar la carpeta después.
    if not correo_del_cliente(caso)[0]:
        faltan.append("No encuentro el correo del cliente en el caso, y GEREO "
                      "nombra su carpeta con él.")

    return faltan


def url_del_caso(base: str, case_id: str) -> str:
    """El enlace al caso que GEREO publica en Slack.

    Sin `case_id` se devuelve la base pelada en vez de una URL rota: un
    enlace que no abre nada es peor que un enlace a la bandeja.
    """
    base = _texto(base).rstrip("/")
    cid = _texto(case_id)
    if not base:
        return ""
    return f"{base}/#/cases/{cid}" if cid else base


def payload(reporte, caso, doc, *, url_base: str = "") -> dict:
    """Lo que se le manda a `POST /api/v1/ros/entregas` (3.2).

    NO lleva el PDF: GEREO lo regenera desde `ros_doc` con la plantilla del
    país (4.2), así el PDF siempre dice lo mismo que el JSON aprobado. El PDF
    de la generación original queda en WatchTower como lo que es, el borrador
    que miró el analista.
    """
    reporte = reporte or {}
    aprobacion = reporte.get("aprobacion") or {}
    return {
        "pais": ros_versiones.pais_largo(reporte),
        "watchtower": {
            "caso_id": _texto(reporte.get("case_id")),
            "ros_id": _texto(reporte.get("folio")),
            "version": int(aprobacion.get("version") or 0),
            "hash_json": _texto(aprobacion.get("json_sha256")),
            "aprobado_por": _texto(aprobacion.get("quien")),
            "aprobado_en": _texto(aprobacion.get("cuando")),
            "url": url_del_caso(url_base, reporte.get("case_id")),
        },
        "cliente": cliente_de(reporte, caso),
        "opciones": opciones_de(reporte),
        "ros_doc": doc if isinstance(doc, dict) else {},
    }


# ── la respuesta ─────────────────────────────────────────────────────────
# Qué significa cada código y qué hacer con él (3.3). `reintentable` es lo
# único que necesita quien llama para decidir.
#
#   202  RECIBIDO       se entregó. Etapa final, ROS bloqueado.
#   200  YA_ENTREGADO   reenvío de la MISMA versión. Mismo efecto que el 202:
#                       la entrega ya está hecha y el ROS se bloquea igual.
#   409  YA_ENTREGADO   otra versión de un ROS ya entregado. NO se reintenta:
#                       insistir manda lo mismo. No debería pasar, porque el
#                       ROS se bloquea al entregar.
#   422  INVALIDO       el JSON no pasó la validación. NO se reintenta: hay
#                       que corregir y volver a aprobar.
#   503  DESHABILITADO  el endpoint está publicado apagado. NO se reintenta:
#                       no cambia hasta la fecha acordada.
#   5xx  FALLA          problema de GEREO. SÍ se reintenta, con la MISMA
#                       versión: la idempotencia es por `ros_id + version`.

ENTREGADO = ("RECIBIDO", "YA_ENTREGADO")

_POR_CODIGO = {
    202: ("RECIBIDO", False),
    200: ("YA_ENTREGADO", False),
    409: ("YA_ENTREGADO", False),
    422: ("INVALIDO", False),
    503: ("DESHABILITADO", False),
}


def leer_respuesta(codigo, cuerpo) -> dict:
    """`{estado, entrega_id, mensaje, campo, codigo, entregado, reintentable}`.

    `entregado` es la pregunta que contesta el llamador: ¿bloqueo el ROS?
    Vale para 202 y para 200 —un reenvío de la misma versión significa que
    GEREO ya la tiene— y para nada más.
    """
    cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
    try:
        codigo = int(codigo)
    except (TypeError, ValueError):
        codigo = 0

    estado, reintentable = _POR_CODIGO.get(codigo, ("", None))
    if reintentable is None:
        # Todo lo que no está en la tabla: 5xx se reintenta, el resto no.
        # Un 401 (clave rotada) o un 404 no mejoran insistiendo.
        reintentable = 500 <= codigo < 600
        estado = "FALLA" if reintentable else "ERROR"

    # El estado que manda es el del cuerpo cuando viene: es lo que GEREO
    # afirma de sí mismo. El código es el respaldo cuando no viene.
    del_cuerpo = _texto(cuerpo.get("estado")).upper()
    return {
        "codigo": codigo,
        "estado": del_cuerpo or estado,
        "entrega_id": _texto(cuerpo.get("entrega_id")),
        "mensaje": _texto(cuerpo.get("mensaje") or cuerpo.get("error")),
        "campo": _texto(cuerpo.get("campo")),
        "entregado": codigo in (200, 202),
        "reintentable": bool(reintentable),
    }


def explicacion(lectura) -> str:
    """Qué decirle a la persona que apretó el botón.

    El mensaje de GEREO se usa cuando viene; cuando no, hay uno por código,
    porque «GEREO respondió 503» no le dice a nadie qué hacer después.
    """
    lectura = lectura or {}
    codigo = lectura.get("codigo")
    propio = lectura.get("mensaje")
    if codigo == 202:
        return "GEREO recibió el reporte. El ROS queda bloqueado."
    if codigo == 200:
        return ("GEREO ya tenía esta versión: la entrega estaba hecha. "
                "El ROS queda bloqueado.")
    if codigo == 409:
        return (propio or "GEREO ya recibió otra versión de este reporte. "
                "No se puede entregar una distinta.")
    if codigo == 422:
        campo = lectura.get("campo")
        base = propio or "GEREO rechazó el contenido del reporte."
        return f"{base} (campo: {campo})" if campo else base
    if codigo == 503:
        return (propio or "La entrega a GEREO todavía no está habilitada. "
                "Se habilita en la fecha que acuerden los dos equipos; "
                "mientras tanto el reporte sigue editable.")
    if lectura.get("reintentable"):
        return (propio or "GEREO no pudo procesar la entrega. "
                "Se puede reintentar con la misma versión.")
    return propio or f"GEREO respondió {codigo}."
