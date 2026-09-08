"""Checklist tri-estado de documentos pedidos: §9.

    pendiente  ← lo pone el sistema al enviar el pedido
    recibido   ← lo pone el sistema al detectar la respuesta
    entregado  ← SIEMPRE una persona, después de revisar el contenido

El sistema nunca pone `entregado`. Eso no es una formalidad: el sistema puede
saber que llegó un archivo, no que ese archivo satisface lo que se pidió.

**Sobre por qué `recibido` va a nivel de pedido y no de ítem.** Cuando llega un
adjunto no hay forma automática de atribuirlo a un ítem: el cliente manda
"foto.jpg" sin decir si es el documento de identidad o el comprobante de
domicilio. Marcar un ítem específico sería inventar. Así que la respuesta mueve
a `recibido` todo lo que estaba `pendiente` —que es la verdad: llegó algo para
este pedido— y la atribución fina la hace la persona al marcar `entregado`.
"""
import time

from . import deposito

COLECCION = "checklist"
PENDIENTE, RECIBIDO, ENTREGADO = "pendiente", "recibido", "entregado"
ESTADOS = (PENDIENTE, RECIBIDO, ENTREGADO)


def _ahora():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def leer(caso_id):
    if not deposito.activo():
        return {}
    return deposito.obtener(COLECCION, deposito.clave_segura(caso_id)) or {}


def _guardar(caso_id, doc):
    deposito.poner(COLECCION, deposito.clave_segura(caso_id), doc)
    return doc


def crear(caso_id, items, ref="", quien=""):
    """Arma el checklist al enviar el pedido. Todo arranca en `pendiente`.

    Si ya existía —un recontacto— no se pisa: se agregan los ítems nuevos y
    se conserva el estado de los que ya tenían uno. Perder un `entregado` que
    una persona confirmó sería el peor resultado posible acá.
    """
    previo = leer(caso_id)
    docs = dict(previo.get("documentos") or {})
    for it in (items or []):
        clave = it if isinstance(it, str) else str(
            (it or {}).get("item") or (it or {}).get("es") or "")
        etiqueta = it if isinstance(it, str) else str(
            (it or {}).get("es") or (it or {}).get("item") or "")
        if not clave:
            continue
        if clave not in docs:
            docs[clave] = {"etiqueta": etiqueta, "estado": PENDIENTE,
                           "cuando": _ahora(), "quien": quien}
    return _guardar(caso_id, {
        "caso_id": caso_id,
        "ref": ref or previo.get("ref", ""),
        "documentos": docs,
        "actualizado": _ahora(),
    })


def marcar_recibido(caso_id, quien="sistema", detalle=""):
    """Mueve a `recibido` lo que estaba `pendiente`. Nunca toca `entregado`."""
    doc = leer(caso_id)
    docs = dict(doc.get("documentos") or {})
    movidos = []
    for clave, d in docs.items():
        if d.get("estado") == PENDIENTE:
            d = dict(d)
            d.update(estado=RECIBIDO, cuando=_ahora(), quien=quien, detalle=detalle)
            docs[clave] = d
            movidos.append(clave)
    if not docs:
        return {"movidos": [], "nota": "el caso no tiene checklist: ¿se pidió desde acá?"}
    doc["documentos"] = docs
    doc["actualizado"] = _ahora()
    _guardar(caso_id, doc)
    return {"movidos": movidos, "documentos": docs}


def marcar(caso_id, clave, estado, quien=""):
    """Cambio manual. `entregado` sólo puede venir por acá, con un autor."""
    if estado not in ESTADOS:
        return {"error": f"estado inválido: {estado!r}. Válidos: {', '.join(ESTADOS)}"}
    if estado == ENTREGADO and not str(quien or "").strip():
        return {"error": "entregado exige un autor: lo confirma una persona, no el sistema"}
    doc = leer(caso_id)
    docs = dict(doc.get("documentos") or {})
    if clave not in docs:
        return {"error": f"el checklist del caso no tiene '{clave}'"}
    d = dict(docs[clave])
    d.update(estado=estado, cuando=_ahora(), quien=quien or "sistema")
    docs[clave] = d
    doc["documentos"] = docs
    doc["actualizado"] = _ahora()
    _guardar(caso_id, doc)
    return {"documentos": docs}


def resumen(caso_id):
    """{pendiente: n, recibido: n, entregado: n, total: n, faltantes: [...]}"""
    docs = (leer(caso_id).get("documentos") or {})
    r = {e: 0 for e in ESTADOS}
    faltantes = []
    for clave, d in docs.items():
        e = d.get("estado") or PENDIENTE
        r[e] = r.get(e, 0) + 1
        if e == PENDIENTE:
            faltantes.append(d.get("etiqueta") or clave)
    r["total"] = len(docs)
    r["faltantes"] = faltantes
    return r
