# -*- coding: utf-8 -*-
"""Los controles del alta de whitelist por API externa (`/v1/whitelist`).

Acá vive la lógica pura —sin S3, sin `resp()`, sin `event`— para que cada
control se pueda probar solo. Las rutas están en `api_handler.py` y el alta
real la escribe `add_to_whitelist`, la MISMA función que usan las pantallas:
un segundo escritor de whitelist se separa del primero en el tercer cambio.

═══════════════════════════════════════════════════════════════════════════
POR QUÉ WATCHTOWER CONTROLA Y NO CONFÍA EN EL QUE LLAMA
═══════════════════════════════════════════════════════════════════════════

Una entrada de whitelist deja de alertar sobre un cliente. El sistema que
pide el alta (hoy Octopus) ya hizo sus propios controles, pero los suyos son
sobre SU modelo: que el caso exista acá, que el cliente sea el del caso y que
quien lo pide sea alguien de este equipo son hechos de WatchTower, y sólo
WatchTower los puede afirmar.

Lo que NO hace la whitelist: no libera la cuenta ni toca Admin. Sólo silencia
las alertas. Conviene que lo sepa quien la pide.

═══════════════════════════════════════════════════════════════════════════
EL ALCANCE `report` SIN REPORTE NO EXCLUYE NADA
═══════════════════════════════════════════════════════════════════════════

El Report Runner aplica una entrada si `scope == "global"` o si
`report_name` coincide con el reporte que está corriendo. Una entrada con
alcance `report` y `report_name` vacío no coincide con ninguno: queda
guardada, se ve en la pantalla, vence a los 30 días y **no silencia nada**.

El alcance por defecto de esta API es el reporte del caso, así que un caso
sin `report_name` no tiene alcance posible. 10 de los 328 casos están en esa
situación. Se responde 409 en vez de crear la entrada inútil, y en vez de
caer a `global`, que sería excluir de TODOS los reportes algo que se pidió
para uno.
"""
from __future__ import annotations

import time

import whitelist_validacion

# Los permisos (`whitelist:leer` / `whitelist:escribir`) viven en
# `api_externa.py`, con los otros tres: `PERMISOS_VALIDOS` filtra lo que no
# conoce, así que un permiso definido en otro lado se descarta en silencio al
# leer el secreto.

# El tipo de cliente del caso, al campo por el que excluye la whitelist.
#
# `customer_id` y `company_id` están como alias porque el dato real los tiene:
# 327 casos dicen `customer` y uno dice `customer_id`. Ese caso existe y
# rechazarlo por un tipeo viejo sería un 409 que nadie puede explicar.
CAMPO_POR_TIPO = {
    "customer": "customer_id",
    "customer_id": "customer_id",
    "company": "company_id",
    "company_id": "company_id",
}

# Alcance y duración por defecto (definición de Benjamín, 23-10-2026).
#
# El alcance NO es configurable desde la API: `global` saca al cliente de
# todos los reportes, incluido `high_risk_countries`, y eso es una decisión
# más grande que la que esta integración viene a automatizar. Se pide desde la
# pantalla. La duración sí se puede elegir entre las tres de siempre: mueve
# cuánto dura, no a cuánto alcanza.
ALCANCE = "report"
DIAS_POR_DEFECTO = 30
DIAS_VALIDOS = (30, 60, 90)

MAX_MOTIVO = 500


def normalizar_correo(v) -> str:
    return str(v or "").strip().lower()


def campo_de_tipo(tipo) -> str:
    """El `entity_field` de la whitelist para un tipo de cliente. '' si no."""
    return CAMPO_POR_TIPO.get(str(tipo or "").strip().lower(), "")


def usuario_habilitado(usuarios, correo) -> bool:
    """¿`correo` es un usuario registrado y activo de WatchTower?

    El `is_active` se lee con default **False**: un registro sin el campo no
    autoriza. Hoy los 12 usuarios lo traen, así que no cambia nada; el default
    seguro es el que corresponde a un control de acceso, no el permisivo que
    usa la proyección de la pantalla.
    """
    buscado = normalizar_correo(correo)
    if not buscado:
        return False
    for u in usuarios or []:
        if normalizar_correo(u.get("email")) != buscado:
            continue
        return bool(u.get("is_active", False))
    return False


def motivo_de_rechazo_alta(cuerpo) -> str:
    """Los 400 de forma del cuerpo. Cadena vacía = la forma está bien.

    No incluye el valor del cliente en el texto, por lo mismo que
    `whitelist_validacion.motivo_de_rechazo`: el motivo va al cliente y al log.
    """
    cuerpo = cuerpo or {}
    cliente = cuerpo.get("cliente") or {}

    if not str(cuerpo.get("caso_id") or "").strip():
        return "caso_id es requerido"

    campo = campo_de_tipo(cliente.get("tipo"))
    if not campo:
        return ("cliente.tipo tiene que ser 'customer' o 'company'")

    malo = whitelist_validacion.motivo_de_rechazo(campo, cliente.get("id"))
    if malo:
        return f"cliente.id: {malo}"

    motivo = str(cuerpo.get("motivo") or "").strip()
    if not motivo:
        return ("motivo es requerido — queda como justificación de por qué se "
                "silencian las alertas de este cliente")
    if len(motivo) > MAX_MOTIVO:
        return f"motivo supera los {MAX_MOTIVO} caracteres"

    if not normalizar_correo(cuerpo.get("solicitado_por")):
        return "solicitado_por es requerido"

    if "alcance" in cuerpo and str(cuerpo.get("alcance") or "").strip() != ALCANCE:
        return ("el alcance por API es siempre el reporte del caso; "
                "el alcance global se pide desde la pantalla")

    if "dias" in cuerpo and dias_de(cuerpo) is None:
        return "dias tiene que ser 30, 60 o 90"

    return ""


def dias_de(cuerpo) -> int | None:
    """Los días pedidos, o None si el valor no es uno de los tres válidos."""
    crudo = (cuerpo or {}).get("dias")
    if crudo is None or str(crudo).strip() == "":
        return DIAS_POR_DEFECTO
    try:
        n = int(crudo)
    except (TypeError, ValueError):
        return None
    return n if n in DIAS_VALIDOS else None


def desajuste_con_el_caso(caso, cliente) -> str:
    """Por qué este cliente NO es el del caso. '' si coincide.

    Es el control que no se le puede delegar al que llama: el cuerpo trae el
    cliente que Octopus cree que corresponde, y si se equivoca de caso se
    silencia a alguien que nadie revisó.
    """
    caso = caso or {}
    cliente = cliente or {}
    campo_pedido = campo_de_tipo(cliente.get("tipo"))
    campo_caso = campo_de_tipo(caso.get("entity_type"))
    if not campo_caso:
        return "el caso no identifica el tipo de cliente"
    if campo_caso != campo_pedido:
        return "el tipo de cliente no es el del caso"
    if str(caso.get("entity_id") or "").strip() != str(cliente.get("id") or "").strip():
        return "el cliente no es el del caso"
    return ""


def reporte_del_caso(caso) -> str:
    return str((caso or {}).get("report_name") or "").strip()


def entrada_que_ya_cubre(entradas, campo, valor, reporte, ahora=None):
    """La entrada vigente que YA silencia a este cliente en ese reporte, o None.

    Idempotencia: Octopus puede reintentar y no tiene que crear una segunda
    entrada ni correrle el vencimiento a la que está. Se devuelve la existente
    tal cual.

    Una entrada `global` vigente también cubre el reporte del caso —así la
    aplica el Report Runner—, así que cuenta: crear una segunda, más angosta,
    no cambiaría en nada qué se excluye y sólo ensucia la pantalla.
    """
    ahora = int(ahora if ahora is not None else time.time())
    valor = str(valor or "").strip()
    for e in entradas or []:
        if str(e.get("entity_field") or "").strip() != campo:
            continue
        if str(e.get("entity_value") or "").strip() != valor:
            continue
        vence = int(e.get("expires_at") or 0)
        if vence and vence <= ahora:
            continue
        alcance = str(e.get("scope") or "global").strip()
        if alcance == "global" or str(e.get("report_name") or "").strip() == reporte:
            return e
    return None


def nota_de_alta(solicitado_por, origen, reporte, dias, motivo) -> str:
    """La nota que queda en el caso. Las pantallas dejan una igual: una
    whitelist sin rastro de por qué es lo primero que pregunta una auditoría.
    """
    return (f"Cliente pasado a whitelist por {origen} "
            f"a pedido de {solicitado_por} "
            f"({dias} días, sólo {reporte}). Motivo: {motivo}")


def entrada_publica(e) -> dict:
    """Una entrada, como la ve el consumidor externo. Explícita a propósito:
    el contrato es la proyección, igual que en `api_externa.caso_publico`."""
    e = e or {}
    return {
        "whitelist_id": e.get("whitelist_id", ""),
        "cliente": {
            "tipo": "company" if e.get("entity_field") == "company_id" else "customer",
            "id": e.get("entity_value", ""),
        },
        "alcance": e.get("scope", "global"),
        "reporte": e.get("report_name", ""),
        "caso_id": e.get("case_id", ""),
        "motivo": e.get("reason", ""),
        "solicitado_por": e.get("solicitado_por", "") or e.get("created_by", ""),
        "origen": e.get("origen", ""),
        "desde": e.get("created_at", ""),
        "hasta": e.get("expires_at_str", ""),
        "dias": int(e.get("duration_days") or 0),
        # EL ESTADO VA EN EL CONTRATO. Una entrada pendiente existe pero no
        # silencia nada, y sin este campo Octopus leería `whitelist_id` más
        # un `hasta` vacío y tendría que adivinar qué significa. Peor: podría
        # leer «ya existe» como «ya está silenciado» y cerrar el caso.
        "estado": _estado(e),
        "silencia": _estado(e) in ("aprobada", "heredada"),
    }


def _estado(e) -> str:
    """El estado de la entrada, sin importar `whitelist_aprobacion`.

    Este módulo es puro y no importa nada del paquete: duplicar la lectura
    del campo es más barato que arrastrar la dependencia, y el test de
    contrato en `test_whitelist_api.py` lo mantiene en línea.
    """
    v = str((e or {}).get("estado") or "").strip().lower()
    return v if v in ("pendiente", "aprobada", "rechazada") else "heredada"


def vigentes_de(entradas, campo, valor, ahora=None) -> list:
    """Las entradas vigentes de ese cliente, de la más nueva a la más vieja."""
    ahora = int(ahora if ahora is not None else time.time())
    valor = str(valor or "").strip()
    fuera = []
    for e in entradas or []:
        if str(e.get("entity_field") or "").strip() != campo:
            continue
        if str(e.get("entity_value") or "").strip() != valor:
            continue
        vence = int(e.get("expires_at") or 0)
        if vence and vence <= ahora:
            continue
        fuera.append(e)
    fuera.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return fuera
