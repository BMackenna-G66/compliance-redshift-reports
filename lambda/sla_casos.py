# -*- coding: utf-8 -*-
"""El reloj de los casos nacidos de una alerta transaccional.

La regla es de compliance, no técnica: un caso de alerta se abre, a la mitad
del plazo hay que recontactar al cliente si todavía no contestó, y al final
del plazo el caso se cierra con lo que haya. Acá vive esa cuenta y nada más:
entra el caso, sale en qué punto del plazo está y qué toca hacer.

Es un módulo aparte y sin dependencias de AWS a propósito. La cuenta es la
parte que hay que poder probar con fechas inventadas, y mezclarla con las
lecturas de S3 obligaría a levantar medio `api_handler` para verificar que
36 horas dan amarillo.

**No cierra ni recontacta nada.** Sólo dice en qué estado está cada caso. Que
el cierre y el recontacto sigan siendo una decisión de una persona es
deliberado: el plazo es una guía para priorizar, y un cierre automático a las
72 horas cerraría también el caso del cliente que contestó a las 71.
"""
import datetime as dt

# El plazo, en horas. Tres días para resolver, recontacto a la mitad.
# En horas y no en días porque la cuenta arranca en la hora de creación del
# caso: uno abierto un viernes a las 18:00 vence el lunes a las 18:00, no el
# lunes a las 00:00.
HORAS_RECONTACTO = 36.0   # 1,5 días
HORAS_CIERRE = 72.0       # 3 días

# Los estados de caso que detienen el reloj.
CERRADOS = ("closed", "archived")

# Los estados del semáforo.
EN_PLAZO = "en_plazo"           # verde
POR_CONTACTAR = "por_contactar"  # amarillo, y nunca se le escribió
POR_RECONTACTAR = "por_recontactar"  # amarillo
VENCIDO = "vencido"             # rojo
CERRADO = "cerrado"             # gris
SIN_RELOJ = ""                  # el caso no es de alerta

ETIQUETAS = {
    EN_PLAZO: "En plazo",
    POR_CONTACTAR: "Sin contactar",
    POR_RECONTACTAR: "Recontactar",
    VENCIDO: "Vencido",
    CERRADO: "Cerrado",
    SIN_RELOJ: "Sin plazo",
}

FORMATO = "%Y-%m-%d %H:%M:%S"


def ahora():
    """La hora de referencia, en UTC, igual que `_now_str` de api_handler."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def a_fecha(texto):
    """La fecha de un campo del CRM, o None si viene vacía o rara.

    Devolver None en vez de reventar es a propósito: un caso viejo con la
    fecha en otro formato tiene que quedar sin reloj, no tumbar el listado
    entero de casos.
    """
    if not texto:
        return None
    t = str(texto).strip().replace("T", " ")
    if t.endswith("Z"):
        t = t[:-1]
    t = t.split(".")[0].split("+")[0]
    try:
        return dt.datetime.strptime(t, FORMATO)
    except ValueError:
        try:
            return dt.datetime.strptime(t[:10], "%Y-%m-%d")
        except ValueError:
            return None


def texto_de(fecha):
    return fecha.strftime(FORMATO) if fecha else ""


def es_de_alerta(caso):
    """Si el caso nació de una alerta transaccional.

    Se mira el origen que quedó guardado —el reporte que la disparó o la fila
    de la alerta— y no el título, que lo escribe una persona. Un caso abierto
    a mano por otro motivo no tiene este plazo.
    """
    if (caso.get("report_name") or "").strip():
        return True
    datos = caso.get("alert_data")
    return isinstance(datos, dict) and bool(datos)


def evaluar(caso, referencia=None, contactos=0, ultimo_contacto="", respondio=False):
    """En qué punto del plazo está el caso.

    `contactos` es cuántos correos se le mandaron al cliente por este caso y
    `ultimo_contacto` cuándo fue el último; `respondio`, si el cliente
    contestó alguna vez. Entran como parámetros y no se leen acá para que la
    cuenta sea probable sin tocar S3.

    Devuelve un dict con prefijo `sla_` listo para mezclar en la fila del
    caso que consume el front.
    """
    ref = referencia or ahora()
    vacio = {
        "sla_aplica": False,
        "sla_estado": SIN_RELOJ,
        "sla_etiqueta": ETIQUETAS[SIN_RELOJ],
        "sla_horas": None,
        "sla_dias": None,
        "sla_recontacto_at": "",
        "sla_cierre_at": "",
        "sla_horas_restantes": None,
        "sla_accion": "",
        "sla_contactos": int(contactos or 0),
        "sla_ultimo_contacto": ultimo_contacto or "",
        "sla_respondio": bool(respondio),
    }

    creado = a_fecha(caso.get("created_at"))
    if not es_de_alerta(caso) or creado is None:
        return vacio

    recontacto_at = creado + dt.timedelta(hours=HORAS_RECONTACTO)
    cierre_at = creado + dt.timedelta(hours=HORAS_CIERRE)
    salida = dict(vacio, **{
        "sla_aplica": True,
        "sla_recontacto_at": texto_de(recontacto_at),
        "sla_cierre_at": texto_de(cierre_at),
    })

    estado_caso = (caso.get("status") or "").strip()
    if estado_caso in CERRADOS:
        # Un caso cerrado no sigue corriendo: lo que interesa es cuánto tardó,
        # que es el dato con el que después se mide si el plazo se cumple.
        fin = a_fecha(caso.get("closed_at")) or a_fecha(caso.get("updated_at")) or ref
        horas = (fin - creado).total_seconds() / 3600
        return dict(salida, **{
            "sla_estado": CERRADO,
            "sla_etiqueta": ETIQUETAS[CERRADO],
            "sla_horas": round(horas, 1),
            "sla_dias": round(horas / 24, 2),
            "sla_horas_restantes": None,
            "sla_accion": "",
        })

    horas = (ref - creado).total_seconds() / 3600
    salida.update({
        "sla_horas": round(horas, 1),
        "sla_dias": round(horas / 24, 2),
        "sla_horas_restantes": round((cierre_at - ref).total_seconds() / 3600, 1),
    })

    if horas >= HORAS_CIERRE:
        return dict(salida, sla_estado=VENCIDO, sla_etiqueta=ETIQUETAS[VENCIDO],
                    sla_accion="cerrar")

    if horas >= HORAS_RECONTACTO:
        # Ya pasó la mitad del plazo. El amarillo es un pendiente, así que se
        # apaga cuando el pendiente está hecho: si el cliente contestó no hay
        # a quién insistirle, y si ya se le escribió después de la marca, el
        # recontacto ya ocurrió. Sin esto el semáforo pediría lo mismo una y
        # otra vez y el analista aprendería a ignorarlo.
        ultimo = a_fecha(ultimo_contacto)
        if respondio or (ultimo is not None and ultimo >= recontacto_at):
            return dict(salida, sla_estado=EN_PLAZO, sla_etiqueta=ETIQUETAS[EN_PLAZO])
        estado = POR_CONTACTAR if not contactos else POR_RECONTACTAR
        return dict(salida, sla_estado=estado, sla_etiqueta=ETIQUETAS[estado],
                    sla_accion="contactar" if estado == POR_CONTACTAR else "recontactar")

    return dict(salida, sla_estado=EN_PLAZO, sla_etiqueta=ETIQUETAS[EN_PLAZO])


def resumen(casos):
    """Cuántos casos hay en cada estado. Lo usa el encabezado de la vista."""
    conteo = {EN_PLAZO: 0, POR_CONTACTAR: 0, POR_RECONTACTAR: 0,
              VENCIDO: 0, CERRADO: 0, SIN_RELOJ: 0}
    for c in casos:
        conteo[c.get("sla_estado", SIN_RELOJ)] = conteo.get(c.get("sla_estado", SIN_RELOJ), 0) + 1
    return conteo
