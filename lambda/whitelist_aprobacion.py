# -*- coding: utf-8 -*-
"""Quién aprueba que un cliente deje de alertar, y desde cuándo.

═══════════════════════════════════════════════════════════════════════════
QUÉ ESTABA PASANDO
═══════════════════════════════════════════════════════════════════════════

El botón de «pasar a whitelist» existía en las dos pantallas y en el caso. El
de aprobar, no. Una persona apretaba y el cliente dejaba de aparecer en los
reportes al instante, por hasta 90 días, sin que nadie más lo mirara.

Y la mayoría de las entradas vigentes ni siquiera decía de quién eran: el alta
masiva nunca guardó el autor. (El recuento concreto quedó fuera de acá a
propósito: este repositorio es público y la foto de cuántos clientes están
silenciados sin firma es información operativa.)

Dejar de alertar sobre un cliente es una decisión de compliance, y ésta se
tomaba sola.

═══════════════════════════════════════════════════════════════════════════
LAS DOS REGLAS
═══════════════════════════════════════════════════════════════════════════

**No aplica hasta que se apruebe.** Una entrada nace `pendiente` y no silencia
nada. La alternativa —silenciar ya y ratificar después— deja una ventana en la
que el cliente está tapado sin firma, y esa ventana es exactamente el agujero
que esto cierra.

**Aprueba el padrón de Oficiales, y no el que la pidió.** El mismo padrón que
firma los ROS: una sola lista para las dos decisiones de compliance. Que no
pueda aprobar quien la pidió no es desconfianza, es para qué sirve el control:
un segundo par de ojos que no son los mismos ojos.

═══════════════════════════════════════════════════════════════════════════
LAS 49 QUE YA ESTABAN
═══════════════════════════════════════════════════════════════════════════

Se respetan. Una entrada sin el campo `estado` es anterior a este control y
sigue aplicando hasta que venza — todas vencen dentro de los 90 días.

Ponerlas en `pendiente` habría sido lo riguroso y lo irresponsable: 46
clientes volviendo a alertar de golpe en la próxima corrida, encima de un
equipo que no pidió esa avalancha. Se marcan en la pantalla como «sin
aprobación» y el problema se termina solo.

═══════════════════════════════════════════════════════════════════════════
EL RELOJ ARRANCA AL APROBAR
═══════════════════════════════════════════════════════════════════════════

Los 30/60/90 días se cuentan desde la aprobación, no desde el pedido. Si se
contaran desde el pedido, una entrada aprobada cinco días después valdría 85,
y el que la pidió pagaría la demora del que la aprueba. Mientras está
pendiente no corre nada, porque no está silenciando nada.
"""
from __future__ import annotations

import datetime as dt

# El padrón es el MISMO de los ROS. Dos padrones para dos decisiones de
# compliance serían dos listas que se desincronizan, y la pregunta "¿quién
# puede firmar?" tendría dos respuestas.
from ros_aprobacion import CLAVE_PADRON, oficiales_de  # noqa: F401

PENDIENTE = "pendiente"
APROBADA = "aprobada"
RECHAZADA = "rechazada"

# Las que ya estaban cuando esto no existía. No es un estado que se pueda
# pedir: se deduce de que el campo no esté.
HEREDADA = "heredada"

ESTADOS = (PENDIENTE, APROBADA, RECHAZADA)

# Los únicos estados que silencian algo.
APLICAN = (APROBADA, HEREDADA)

DIAS_VALIDOS = (30, 60, 90)


def estado_de(entrada) -> str:
    """El estado de la entrada. Sin el campo, es anterior al control."""
    e = str((entrada or {}).get("estado") or "").strip().lower()
    return e if e in ESTADOS else HEREDADA


def vencida(entrada, ahora: int | None = None) -> bool:
    """Si ya pasó su fecha. Una pendiente no vence: todavía no empezó."""
    entrada = entrada or {}
    if estado_de(entrada) == PENDIENTE:
        return False
    try:
        exp = int(entrada.get("expires_at") or 0)
    except (TypeError, ValueError):
        return False
    if not exp:
        return False
    ahora = int(ahora if ahora is not None else dt.datetime.utcnow().timestamp())
    return exp <= ahora


def aplica(entrada, ahora: int | None = None) -> bool:
    """**La única respuesta a «¿esta entrada silencia algo?».**

    Vive acá y en un solo lugar a propósito: la pregunta se hace al correr el
    reporte, al listar la pantalla y al decidir si una nueva es redundante. Con
    tres copias de la condición, alcanza con que una se olvide del estado para
    que una entrada pendiente silencie igual, que es el bug que no se vería
    hasta que alguien revise por qué un cliente no aparece.
    """
    return estado_de(entrada) in APLICAN and not vencida(entrada, ahora)


def quien_pidio(entrada) -> str:
    """El correo de quien la pidió, normalizado."""
    entrada = entrada or {}
    crudo = (entrada.get("solicitado_por") or entrada.get("created_by") or "")
    return str(crudo).strip().lower()


def bloqueos_para_aprobar(entrada, quien: str, oficiales) -> list:
    """Por qué NO se puede aprobar. Lista vacía = se puede.

    Devuelve TODOS los motivos y no el primero: que alguien descubra de a uno
    por qué no puede firmar, apretando el botón cuatro veces, es una forma
    cara de leer una lista.
    """
    faltan = []
    entrada = entrada or {}
    quien = str(quien or "").strip().lower()
    oficiales = [str(o or "").strip().lower() for o in (oficiales or [])]

    if not quien:
        faltan.append("Falta quién aprueba.")

    estado = estado_de(entrada)
    if estado == APROBADA:
        faltan.append("Esta entrada ya está aprobada.")
    elif estado == RECHAZADA:
        faltan.append("Esta entrada fue rechazada: para retomarla hay que "
                      "pedirla de nuevo.")
    elif estado == HEREDADA:
        faltan.append("Esta entrada es anterior al control de aprobación: "
                      "sigue vigente hasta que venza y no se aprueba.")

    # EL PADRÓN FALLA CERRADO. Vacío no es "cualquiera puede": es "no sabemos
    # quién puede", y ante eso no se silencia a nadie.
    if not oficiales:
        faltan.append("No hay padrón de Oficiales de Cumplimiento cargado: "
                      "sin padrón no aprueba nadie.")
    elif quien and quien not in oficiales:
        faltan.append("Sólo un Oficial de Cumplimiento puede aprobar que un "
                      "cliente deje de alertar.")

    # CUATRO OJOS. Es el control entero: si el que pide puede firmar, el paso
    # de aprobación es una formalidad que se completa sola.
    if quien and quien == quien_pidio(entrada):
        faltan.append("No podés aprobar una entrada que pediste vos: tiene "
                      "que mirarla otra persona.")

    return faltan


def dias_de(entrada) -> int:
    """Los días pedidos, acotados a los válidos. 90 es el máximo, no el default
    cómodo: el default es el más corto."""
    try:
        d = int((entrada or {}).get("duration_days") or 0)
    except (TypeError, ValueError):
        d = 0
    return d if d in DIAS_VALIDOS else DIAS_VALIDOS[0]


def aprobar(entrada: dict, quien: str, momento: dt.datetime | None = None) -> dict:
    """Aprueba y **arranca el reloj**. NO muta la entrada que recibe.

    Acá es donde se calcula `expires_at`, y no al pedirla: los días valen
    desde que la entrada empieza a silenciar.
    """
    quien = str(quien or "").strip().lower()
    if not quien:
        raise ValueError("falta quién aprueba")
    momento = momento or dt.datetime.utcnow()
    dias = dias_de(entrada)
    vence = momento + dt.timedelta(days=dias)

    salida = dict(entrada or {})
    salida["estado"] = APROBADA
    salida["duration_days"] = dias
    salida["aprobacion"] = {"por": quien,
                            "en": momento.strftime("%Y-%m-%d %H:%M:%S")}
    salida["expires_at"] = int(vence.timestamp())
    salida["expires_at_str"] = vence.strftime("%Y-%m-%d %H:%M:%S")
    return salida


def rechazar(entrada: dict, quien: str, motivo: str = "",
             momento: dt.datetime | None = None) -> dict:
    """Rechaza, con el motivo. NO muta la entrada que recibe.

    Se rechaza en vez de borrar porque la decisión de NO silenciar a un
    cliente también es una decisión, y borrarla deja el expediente contando
    que nunca se pidió nada.
    """
    quien = str(quien or "").strip().lower()
    if not quien:
        raise ValueError("falta quién rechaza")
    momento = momento or dt.datetime.utcnow()
    salida = dict(entrada or {})
    salida["estado"] = RECHAZADA
    salida["rechazo"] = {"por": quien,
                         "en": momento.strftime("%Y-%m-%d %H:%M:%S"),
                         "motivo": str(motivo or "").strip()[:500]}
    # Una rechazada no vence: no hay nada que caduque.
    salida["expires_at"] = 0
    salida["expires_at_str"] = ""
    return salida


def resumen(entrada) -> dict:
    """Lo que la pantalla necesita para dibujar el estado de una entrada."""
    entrada = entrada or {}
    estado = estado_de(entrada)
    return {
        "estado": estado,
        "aplica": aplica(entrada),
        "solicitado_por": quien_pidio(entrada),
        "aprobada_por": str((entrada.get("aprobacion") or {}).get("por") or ""),
        "aprobada_en": str((entrada.get("aprobacion") or {}).get("en") or ""),
        "rechazada_por": str((entrada.get("rechazo") or {}).get("por") or ""),
        "motivo_rechazo": str((entrada.get("rechazo") or {}).get("motivo") or ""),
        # La pantalla lo usa para el cartel de «sin aprobación»: son las que
        # entraron antes de que esto existiera.
        "sin_aprobacion": estado == HEREDADA,
    }
