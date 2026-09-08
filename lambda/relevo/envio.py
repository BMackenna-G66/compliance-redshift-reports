"""Envío del pedido al cliente: las salvaguardas de §8, todas obligatorias.

1. **Previsualización.** Se puede leer el correo completo antes de que exista
   la posibilidad de mandarlo: `previsualizar()` no toca la red.
2. **Bloqueo de doble envío.** Un caso ya pedido no se vuelve a pedir por
   accidente. El bloqueo mira `relevo_solicitudes` Y las acciones del caso.
3. **Interruptor general y por partner**, en `relevo_config`, **apagados por
   defecto**, igual que el disparo automático de WatchTower.
4. **Tope por lote y confirmación explícita.** Nada sale sin que alguien lo
   mire: el lote exige `confirmado: true` en el cuerpo.
5. **Registro en `relevo_solicitudes` salga o no** el correo. Si falla, queda
   el intento con su error; si sale, queda el threadId.

El threadId se guarda porque es lo que correlaciona la respuesta del cliente
por hilo, que sobrevive a que edite el asunto (§9). El token del asunto es el
segundo camino.
"""
import os
import time
import uuid

from . import casos, correo, deposito, ingesta, vista

COLECCION = "solicitudes"
# Tope por lote. Bajo a propósito: es un flujo que le escribe a clientes
# reales, así que la primera vez que alguien se equivoca tiene que equivocarse
# en pocos.
MAX_LOTE = int(os.environ.get("RELEVO_MAX_LOTE", "20"))
REMITENTE = os.environ.get("RELEVO_FROM_ADDR", correo.REMITENTE_POR_DEFECTO)


# ── registro ─────────────────────────────────────────────────────────────
def solicitudes_de(caso_id):
    """Solicitudes ya registradas para un caso, salieran o no."""
    if not deposito.activo():
        return []
    todas = deposito.todos(COLECCION)
    return sorted((s for s in todas if s.get("caso_id") == caso_id),
                  key=lambda s: s.get("cuando", ""))


def _registrar(caso_id, compuesto, enviado, error="", thread_id="", quien=""):
    """Deja rastro del intento. Se llama SIEMPRE, salga o no el correo."""
    rid = uuid.uuid4().hex
    reg = {
        "request_id": rid,
        "caso_id": caso_id,
        "correo": compuesto.get("para"),
        "nombre": compuesto.get("nombre"),
        "asunto": compuesto.get("asunto"),
        "ref": compuesto.get("token"),
        "documentos": compuesto.get("items_catalogo") or [],
        "documentos_crudo": compuesto.get("items_crudo") or [],
        "thread_id": thread_id,
        "enviado": bool(enviado),
        "error": str(error or "")[:400],
        "quien": quien,
        "cuando": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    }
    try:
        deposito.poner(COLECCION, rid, reg)
        # Índice por token, para que el poller de respuestas encuentre el caso
        # sin recorrer todas las solicitudes.
        if compuesto.get("token"):
            deposito.poner("refs", deposito.clave_segura(compuesto["token"]),
                           {"ref": compuesto["token"], "caso_id": caso_id,
                            "request_id": rid, "thread_id": thread_id})
    except Exception as e:
        print(f"[relevo] no pude registrar la solicitud de {caso_id}: {e}")
    return reg


# ── interruptores ────────────────────────────────────────────────────────
def interruptores():
    from . import api as rapi
    cfg = rapi.leer_config()
    return cfg.get("interruptores") or {}


def puede_enviar(partner=""):
    """(permitido, motivo). Apagado por defecto, y por partner si se declara."""
    sw = interruptores()
    if not sw.get("envio_general"):
        return False, ("el interruptor general de envío está apagado "
                       "(Admin → Relevo → Configuración)")
    if partner:
        clave = f"envio_{str(partner).lower().replace(' ', '_')}"
        if clave in sw and not sw[clave]:
            return False, f"el interruptor de {partner} está apagado ({clave})"
    return True, ""


# ── el caso ──────────────────────────────────────────────────────────────
def _buscar_caso(caso_id):
    d, meta = vista.completa()
    if d is None:
        return None, meta
    return next((c for c in d["casos"] if c.get("id") == caso_id), None), meta


def ya_pedido(caso_id):
    """(sí, motivo). Mira el registro Y las acciones: cualquiera de los dos
    basta, porque un pedido puede haberse marcado a mano sin pasar por acá."""
    for s in solicitudes_de(caso_id):
        if s.get("enviado"):
            return True, f"ya se envió el {s.get('cuando')} a {s.get('correo')}"
    acc = casos.leer_acciones().get(caso_id) or []
    if any(a.get("accion") in ("pedido_enviado", "recontactado") for a in acc):
        return True, "el caso ya tiene registrada una acción de contacto"
    return False, ""


# ── previsualizar: no toca la red ────────────────────────────────────────
def previsualizar(caso_id, nota=""):
    caso, meta = _buscar_caso(caso_id)
    if caso is None:
        return {"error": f"caso '{caso_id}' no encontrado", "meta": meta}
    c = correo.componer(caso, nota=nota)
    pedido, motivo_pedido = ya_pedido(caso_id)
    permitido, motivo_sw = puede_enviar(caso.get("partner"))
    return {
        "caso_id": caso_id,
        "partner": caso.get("partner"),
        "estado": caso.get("estado"),
        "asunto": c["asunto"],
        "para": c["para"],
        "html": c["html"],
        "texto": c["texto"],
        "items_catalogo": c["items_catalogo"],
        "items_crudo": c["items_crudo"],
        "datos": c["datos"],
        "plazo": c["plazo"],
        "avisos": c["avisos"],
        "puede_enviar": bool(permitido and c["para"] and not pedido),
        "bloqueos": [x for x in (
            motivo_sw,
            motivo_pedido and f"doble envío: {motivo_pedido}",
            "" if c["para"] else "el caso no tiene correo de cliente",
        ) if x],
        # El adjunto no existe a propósito: esto no es una solicitud KYC (§8).
        "adjuntos": [],
    }


# ── enviar de a uno ──────────────────────────────────────────────────────
def enviar(caso_id, quien="", nota="", saltar_bloqueo_doble=False):
    """Manda el pedido. Registra el intento salga o no, y anota la acción."""
    if not str(quien or "").strip():
        return {"enviado": False, "error": "quien es requerido: no se le escribe a un cliente sin autor"}

    caso, meta = _buscar_caso(caso_id)
    if caso is None:
        return {"enviado": False, "error": f"caso '{caso_id}' no encontrado"}

    permitido, motivo = puede_enviar(caso.get("partner"))
    if not permitido:
        return {"enviado": False, "error": motivo, "bloqueado": True}

    pedido, motivo_pedido = ya_pedido(caso_id)
    if pedido and not saltar_bloqueo_doble:
        return {"enviado": False, "error": f"doble envío bloqueado: {motivo_pedido}",
                "bloqueado": True}

    c = correo.componer(caso, nota=nota)
    if not c["para"]:
        return {"enviado": False, "error": "el caso no tiene correo de cliente resuelto"}

    try:
        g = ingesta.cliente()
        r = g.enviar(correo.a_mime(c, REMITENTE))
        thread_id = str(r.get("threadId") or "")
    except Exception as e:
        # Se registra el intento fallido: que no salga no significa que no pasó.
        reg = _registrar(caso_id, c, False, error=str(e), quien=quien)
        return {"enviado": False, "error": str(e)[:400], "request_id": reg["request_id"]}

    reg = _registrar(caso_id, c, True, thread_id=thread_id, quien=quien)
    # La acción se anota después del envío: si el correo no salió, el caso no
    # puede quedar como "pedido enviado".
    try:
        casos.registrar(caso_id, "pedido_enviado", quien=quien,
                        detalle={"ref": c["token"], "thread_id": thread_id,
                                 "correo": c["para"],
                                 "documentos": c["items_catalogo"]})
    except Exception as e:
        print(f"[relevo] correo enviado pero no pude anotar la acción de {caso_id}: {e}")

    return {"enviado": True, "para": c["para"], "asunto": c["asunto"],
            "ref": c["token"], "thread_id": thread_id,
            "request_id": reg["request_id"]}


# ── lote ─────────────────────────────────────────────────────────────────
def enviar_lote(caso_ids, quien="", confirmado=False):
    """Nada sale sin confirmación explícita y sin tope (§8)."""
    ids = [str(x).strip() for x in (caso_ids or []) if str(x).strip()]
    if not ids:
        return {"error": "caso_ids es requerido"}
    if not confirmado:
        return {"error": "confirmado: true es requerido — el lote le escribe a clientes reales",
                "a_enviar": len(ids)}
    if len(ids) > MAX_LOTE:
        return {"error": f"máximo {MAX_LOTE} casos por lote (llegaron {len(ids)})"}
    if not str(quien or "").strip():
        return {"error": "quien es requerido"}

    resultados = []
    for cid in ids:
        r = enviar(cid, quien=quien)
        resultados.append({"caso_id": cid, **r})
    enviados = sum(1 for r in resultados if r.get("enviado"))
    return {"enviados": enviados, "fallidos": len(resultados) - enviados,
            "resultados": resultados}
