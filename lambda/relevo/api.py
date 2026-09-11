"""Rutas del módulo: §10 de docs/MIGRACION_A_WATCHTOWER.md.

Vive acá y no dentro de `api_handler.py` a propósito. Ese archivo ya tiene más
de 6.000 líneas y la regla de oro de §1 es que el módulo no se mezcle con el
ciclo AML; `api_handler` sólo agrega el bloque de ruteo y llama acá.

Lo que NO está todavía, porque es el paso 6 y necesita el scope `gmail.send`:
`POST /relevo/casos/{id}/pedido` y `POST /relevo/pedidos/lote`.

Todo lee del snapshot de `vista.py`, salvo las acciones, que van en vivo.
"""
import json
import time

from . import casos, deposito, partner, pipeline
from . import reglas as R
from . import resolucion, vista

COLECCION_CONFIG = "config"

# Valores por defecto de §7: 3 días hábiles, 3 intentos.
CONFIG_POR_DEFECTO = {
    "politica_general": {"dias_habiles": 3, "intentos": 3},
    "interruptores": {"envio_general": False},
}


# ── configuración ────────────────────────────────────────────────────────
def leer_config():
    """Mantenedores e interruptores. Los interruptores arrancan APAGADOS (§8)."""
    fuera = json.loads(json.dumps(CONFIG_POR_DEFECTO))
    if not deposito.activo():
        return fuera
    for d in deposito.todos(COLECCION_CONFIG):
        clave = d.get("clave")
        if clave:
            fuera[clave] = d.get("valor")
    return fuera


def guardar_config(clave, valor, quien=""):
    deposito.poner(COLECCION_CONFIG, deposito.clave_segura(clave), {
        "clave": clave, "valor": valor, "quien": quien,
        "cuando": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    })
    return leer_config()


# ── casos ────────────────────────────────────────────────────────────────
def _resumen_caso(c):
    """Lo que la lista necesita. El detalle completo va en /relevo/casos/{id}."""
    cl = c.get("cliente") or {}
    datos = cl.get("cliente") if isinstance(cl.get("cliente"), dict) else cl
    datos = datos or {}
    seg = c.get("seguimiento") or {}
    return {
        "id": c.get("id"),
        "partner": c.get("partner"),
        "caso_partner": c.get("caso_partner"),
        "estado": c.get("estado"),
        "etapa": c.get("etapa"),
        "accionable": c.get("accionable"),
        "n_transacciones": c.get("n_transacciones"),
        "n_correos": c.get("n_correos"),
        # Los identificadores de las remesas (RMT…, IF-…, PY…). Viajan a la
        # lista porque son con lo que la gente busca: el partner los nombra en
        # su correo y el analista los tiene a mano. El `id` del caso los trae
        # sólo para dLocal y OZ; para Currencycloud y Nium lleva el número de
        # caso del partner, que es otra cosa.
        "transacciones": [str(t.get("valor") or "") for t in (c.get("transacciones") or [])
                          if t.get("valor")],
        "cliente_id": datos.get("cliente_id"),
        "cliente_nombre": datos.get("cliente_nombre"),
        "cliente_correo": datos.get("cliente_correo"),
        "cliente_estado": cl.get("estado"),
        "items": c.get("items") or [],
        "plazo": c.get("plazo"),
        "primera": c.get("primera"),
        "ultima": c.get("ultima"),
        "intentos": seg.get("intentos"),
        "vencido": seg.get("vencido"),
        "agotado": seg.get("agotado"),
        "proximo_contacto": seg.get("proximo_contacto"),
        "faltantes": seg.get("faltantes"),
    }


def listar_casos(q):
    d, meta = vista.completa()
    if d is None:
        return {"casos": [], "meta": meta}
    cs = d["casos"]
    if q.get("partner"):
        cs = [c for c in cs if str(c.get("partner", "")).lower() == q["partner"].lower()]
    if q.get("estado"):
        cs = [c for c in cs if c.get("estado") == q["estado"]]
    if q.get("cliente_id"):
        cs = [c for c in cs if str(_resumen_caso(c).get("cliente_id")) == str(q["cliente_id"])]
    if str(q.get("vencidos", "")).lower() in ("1", "true", "si", "sí"):
        cs = [c for c in cs if (c.get("seguimiento") or {}).get("vencido")]
    if str(q.get("accionables", "")).lower() in ("1", "true", "si", "sí"):
        cs = [c for c in cs if c.get("accionable")]
    return {"casos": [_resumen_caso(c) for c in cs], "total": len(cs), "meta": meta}


def detalle_caso(caso_id):
    d, meta = vista.completa()
    if d is None:
        return {"error": "sin snapshot", "meta": meta}
    c = next((x for x in d["casos"] if x.get("id") == caso_id), None)
    if c is None:
        return {"error": f"caso '{caso_id}' no encontrado"}
    return {"caso": c, "meta": meta}


def registrar_accion(caso_id, body):
    """Anota una acción. §10 exige registrar QUIÉN la ejecutó.

    El `quien` viene del cuerpo, como en el resto de este API. Debería salir
    del JWT —así lo pide §10— pero el API todavía no exige credenciales y
    `get_user_email()` no tiene claims que leer. Queda anotado: mientras eso
    no cambie, el autor de una acción es declarativo, no verificado.
    """
    accion = (body.get("accion") or "").strip()
    if accion not in casos.ACCIONES:
        return {"error": f"acción desconocida: {accion!r}",
                "validas": list(casos.ACCIONES)}
    quien = (body.get("quien") or body.get("actor_email") or "").strip()
    if not quien:
        return {"error": "quien es requerido: una acción sin autor no sirve de registro"}
    ev = casos.registrar(caso_id, accion, quien=quien, detalle=body.get("detalle") or {})
    # Se devuelve el estado recalculado con la acción ya incluida, para que la
    # pantalla no tenga que esperar el próximo snapshot.
    acciones = casos.leer_acciones()
    return {"accion": ev, "acciones_del_caso": acciones.get(caso_id, [])}


# ── clientes: el 360 de §7 ───────────────────────────────────────────────
def listar_clientes(q):
    d, meta = vista.completa()
    if d is None:
        return {"clientes": [], "meta": meta}
    cl = d["clientes"]
    items = list(cl.values()) if isinstance(cl, dict) else list(cl)
    if str(q.get("solo_pendientes", "")).lower() in ("1", "true", "si", "sí"):
        terminales = set(casos.TERMINALES)
        items = [c for c in items
                 if any((k.get("estado") if isinstance(k, dict) else k) not in terminales
                        for k in (c.get("casos") or []))]
    # Las remesas de todos sus casos, para que buscar un identificador
    # encuentre al cliente y no sólo al caso.
    for c in items:
        vals = []
        for k in (c.get("casos") or []):
            if isinstance(k, dict):
                vals += [str(t.get("valor") or "")
                         for t in (k.get("transacciones") or []) if t.get("valor")]
        c["transacciones_ids"] = sorted(set(vals))
    return {"clientes": items, "total": len(items), "meta": meta}


# ── bandeja de partners: §11.3, para depurar reglas ──────────────────────
def listar_mensajes(q):
    d, meta = vista.completa()
    if d is None:
        return {"mensajes": [], "meta": meta}
    ms = d["bandeja"]
    if q.get("partner"):
        ms = [m for m in ms if str(m.get("partner", "")).lower() == q["partner"].lower()]
    if q.get("tipo"):
        ms = [m for m in ms if m.get("tipo") == q["tipo"]]
    if str(q.get("solo_accionables", "")).lower() in ("1", "true", "si", "sí"):
        ms = [m for m in ms if m.get("accionable")]
    if q.get("buscar"):
        t = q["buscar"].lower()
        ms = [m for m in ms if t in str(m.get("asunto", "")).lower()]
    try:
        limite = min(int(q.get("limite") or 100), 300)
    except (TypeError, ValueError):
        limite = 100
    return {"mensajes": ms[:limite], "total": len(ms), "meta": meta}


# ── probador de reglas: §11.4 ────────────────────────────────────────────
def probar(body):
    """Corre el motor sobre un asunto y cuerpo pegados a mano. No guarda nada."""
    asunto = str(body.get("asunto") or "")
    cuerpo = str(body.get("cuerpo") or "")
    remitente = str(body.get("remitente") or body.get("x_original_sender") or "").strip()
    if not asunto and not cuerpo:
        return {"error": "asunto o cuerpo es requerido"}
    mensaje = {
        "id": "<prueba>",
        "asunto": asunto,
        "cuerpo": cuerpo,
        "headers": {"X-Original-Sender": remitente} if remitente else {},
    }
    rg = R.cargar_reglas()
    resultado = pipeline.procesar(mensaje, rg)
    # `procesar` ya reporta partner, tipo, accionable y —cuando algo no
    # matcheó— el motivo. Eso es lo que la pantalla necesita para depurar una
    # regla, así que no se re-encadenan los pasos a mano: cada módulo del
    # motor tiene su propia firma y replicarlas acá se rompe al primer cambio.
    p = partner.identificar(mensaje, rg)
    cfg = p[0] if isinstance(p, tuple) else p
    return {
        "resultado": resultado,
        "partner_detectado": {
            "id": resultado.get("partner_id"),
            "nombre": resultado.get("partner"),
            # El motor ya dice por qué vía identificó: remitente exacto,
            # dominio, o pista de asunto con su peso.
            "via": resultado.get("partner_via"),
            "config_encontrada": bool(cfg),
        },
    }


def leer_reglas():
    """reglas.json tal cual, para el probador. Es configuración, no datos.

    Se lee el archivo crudo y no `cargar_reglas()`: ésa compila los patrones a
    objetos `re.Pattern`, que no son serializables a JSON. La pantalla quiere
    ver el texto del patrón, que es justamente lo que tiene el archivo.
    """
    from pathlib import Path as _P
    return json.loads((_P(__file__).resolve().parent / "reglas.json")
                      .read_text(encoding="utf-8"))


# ── resolución a pedido ──────────────────────────────────────────────────
def resolver_ahora(body):
    return resolucion.correr(maximo=body.get("maximo"), forzar=bool(body.get("forzar")))
