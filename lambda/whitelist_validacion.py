# -*- coding: utf-8 -*-
"""Qué puede entrar a la lista blanca, y por qué se valida dos veces.

═══════════════════════════════════════════════════════════════════════════
EL AGUJERO QUE ESTO CIERRA
═══════════════════════════════════════════════════════════════════════════

`inject_whitelist_exclusions` arma el SQL interpolando el valor y escapando
las comillas simples al doblarlas. Redshift **también acepta la barra
invertida** como escape, así que un valor como

    \\') AND (1=0) --

cierra el literal y lo que sigue entra como SQL. El reporte sale **vacío para
todos los clientes**, no sólo para el de la entrada. Probado en Redshift en
sólo lectura: una consulta que debía devolver una fila devolvió cero.

Y la API interna no autentica, así que cualquiera con la URL podía silenciar
todos los reportes con un POST. No es un «qué pasaría si»: es una línea.

═══════════════════════════════════════════════════════════════════════════
SE VALIDA AL ESCRIBIR Y AL APLICAR
═══════════════════════════════════════════════════════════════════════════

Al escribir, para que no entre. Al aplicar, porque lo que YA está guardado no
pasó por la validación nueva, y porque un camino que hoy no existe —la API
externa del PR B, un script, una carga a mano en S3— no tiene por qué
acordarse de validar.

Una entrada inválida al aplicar se DESCARTA, no rompe la corrida: un reporte
que no corre es peor que un reporte con una exclusión de menos, y el motivo
queda en el log. **Sin el valor**: si el valor es un intento de inyección,
copiarlo al log lo mete en CloudWatch.

═══════════════════════════════════════════════════════════════════════════
LISTA CERRADA, NO LISTA DE PROHIBIDOS
═══════════════════════════════════════════════════════════════════════════

Los campos y la forma de los valores se enumeran. Prohibir caracteres —la
comilla, la barra— es una carrera que se pierde: siempre queda una forma de
escapar que nadie pensó. Lo que entra es lo que se reconoce.
"""
from __future__ import annotations

import re

# Los campos por los que se puede excluir. Cualquier otro se rechaza.
#
# SALEN DE UN INVENTARIO DE TODO LO QUE PUEDE LLEGAR, no de lo que hay
# guardado. Las 49 entradas vigentes son todas `customer_id`, y quedarse con
# eso habría roto opciones que las pantallas ofrecen y nadie usó todavía:
#
#   v1 · formulario manual (dos pantallas)  customer_id, email,
#                                           beneficiary_id, customer_email
#   v1 · desde el caso                      customer_id, company_id
#   v2 · Caso.jsx                           customer_id, company_id
#   v2 · ListaBlanca (alta y masiva)        customer_id, company_id
#   backend · alta masiva por fila          customer_id, company_id,
#                                           beneficiary_id, email
#
# `customer_email` es el que casi se pierde: lo ofrecen los dos formularios de
# v1 y lo devuelven 23 de los 41 reportes. Agregar uno nuevo es una línea acá
# y una decisión consciente, que es el punto.
CAMPOS = ("customer_id", "company_id", "beneficiary_id",
          "email", "customer_email")

# Los que son correo y no id. El resto son ids numéricos.
CAMPOS_CORREO = ("email", "customer_email")

# Un id es sólo dígitos. No hay ninguno en producción que no lo sea.
RE_ID = re.compile(r"^\d{1,20}$")

# Un correo, con lo justo. No valida que exista: valida que no pueda romper un
# literal SQL. Sin comillas, sin barras, sin espacios, sin punto y coma.
RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,}$")

MAX_VALOR = 255


def motivo_de_rechazo(entity_field, entity_value) -> str:
    """Por qué NO se acepta esta entrada. Cadena vacía = se acepta.

    El motivo no incluye el valor: se devuelve al cliente y se escribe en el
    log, y si el valor es un intento de inyección no tiene por qué viajar a
    ninguno de los dos.
    """
    campo = str(entity_field or "").strip()
    valor = str(entity_value or "").strip()

    if not campo:
        return "falta el campo por el que excluir"
    if campo not in CAMPOS:
        # SIN REPETIR EL CAMPO. Lo controla quien llama igual que el valor, y
        # este texto va al cliente y al log: devolverlo es el mismo problema
        # que devolver el valor.
        return ("ese campo no está permitido; los válidos son "
                + ", ".join(CAMPOS))
    if not valor:
        return "falta el valor a excluir"
    if len(valor) > MAX_VALOR:
        return f"el valor supera los {MAX_VALOR} caracteres"

    if campo in CAMPOS_CORREO:
        if not RE_EMAIL.match(valor):
            return "el correo tiene una forma que no se reconoce"
        return ""
    if not RE_ID.match(valor):
        return "un id tiene que ser sólo dígitos"
    return ""


def es_valida(entity_field, entity_value) -> bool:
    return not motivo_de_rechazo(entity_field, entity_value)


def filtrar(entradas) -> tuple:
    """Separa lo aplicable de lo que hay que descartar.

    Devuelve `(buenas, descartadas)`, donde cada descartada es
    `(whitelist_id, motivo)` — sin el valor, a propósito.
    """
    buenas, descartadas = [], []
    for e in entradas or []:
        motivo = motivo_de_rechazo(e.get("entity_field"), e.get("entity_value"))
        if motivo:
            descartadas.append((str(e.get("whitelist_id") or "?"), motivo))
        else:
            buenas.append(e)
    return buenas, descartadas
