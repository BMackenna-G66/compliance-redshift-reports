"""Snapshot de la vista: separa lo caro de lo que cambia.

**Por qué existe.** Armar la vista completa exige leer todos los correos del
depósito y pasarlos por el motor. Medido en la Lambda del API: **8,3 s sólo
para leer los 580 mensajes**, y crece lineal con la casilla — a 3.000 correos
se pasa del timeout de 60 s. Servir eso en cada carga de pantalla no funciona.

La solución no es cachear la vista entera, porque entonces una acción del
analista tardaría minutos en verse. Se parte en dos:

- **Caro y estable** → snapshot. Los correos pasados por el motor y agrupados
  en transacciones. Sólo cambia cuando entra correo nuevo, así que lo
  reconstruye un job después de la ingesta.
- **Barato y mutable** → en vivo. Las acciones y el caché de clientes. Son
  pocos objetos y son justo lo que el analista acaba de tocar: tienen que
  reflejarse al instante.

Así una acción registrada se ve en la siguiente carga sin esperar el job, y
la pantalla abre rápido.
"""
import os
import time

from . import almacen, casos, cliente, deposito, pipeline, reglas as R, transacciones as TX

CLAVE = "actual"
COLECCION = "vista"
# Cuántos correos se guardan para la bandeja de partners. Es una vista de
# depuración de reglas (§11.3): no hace falta la casilla completa, y el cuerpo
# de cada correo es lo que más pesa.
MAX_BANDEJA = int(os.environ.get("RELEVO_VISTA_BANDEJA", "300"))


def construir():
    """Arma la parte cara: correos → motor → transacciones, más la bandeja."""
    arranque = time.time()
    rg = R.cargar_reglas()
    mensajes = almacen.leer()
    registros = [pipeline.procesar(m, rg) for m in mensajes]
    por_id = {m["id"]: m for m in mensajes}
    txs = TX.construir(registros, por_id, rg)

    # El caché de clientes entra al snapshot. Medido: leerlo en vivo son 132
    # GET a S3 y ~4,5 s por carga de pantalla. Cambia cada 15 min con la
    # resolución, así que 5 min de desfase —lo que tarda el job en volver a
    # correr— es aceptable; la latencia de la pantalla no lo era.
    cache = cliente.leer_cache()
    cliente.adjuntar(txs, cache)

    # Bandeja: lo que el motor extrajo de cada correo, para depurar reglas. Se
    # guarda sin el cuerpo — pesa mucho y la pantalla no lo muestra en la lista.
    bandeja = []
    for reg in registros:
        m = por_id.get(reg.get("id")) or {}
        bandeja.append({
            "id": reg.get("id"),
            "asunto": reg.get("asunto") or m.get("asunto"),
            "partner": reg.get("partner"),
            "partner_id": reg.get("partner_id"),
            # partner_via dice CÓMO se identificó (remitente exacto, dominio,
            # pista de asunto). Es el dato que hace útil esta pantalla para
            # depurar una regla que no matchea.
            "partner_via": reg.get("partner_via"),
            "tipo": reg.get("tipo"),
            "accionable": reg.get("accionable"),
            "estado": reg.get("estado"),
            "alertas": reg.get("alertas") or [],
            "ids": reg.get("ids") or [],
            "llave_consulta": reg.get("llave_consulta"),
            "valor_consulta": reg.get("valor_consulta"),
            "caso_partner": reg.get("caso_partner"),
            "tiene_cuerpo": bool(reg.get("tiene_cuerpo") or m.get("cuerpo")),
        })
    bandeja.sort(key=lambda x: str(x.get("id")), reverse=True)

    return {
        "generado_en": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "segundos": round(time.time() - arranque, 1),
        "n_mensajes": len(mensajes),
        "transacciones": txs,
        "cache": cache,
        "bandeja": bandeja[:MAX_BANDEJA],
    }


def guardar(v=None):
    v = v or construir()
    deposito.poner(COLECCION, CLAVE, v)
    return v


def leer():
    """El snapshot, o None si todavía no se generó ninguno."""
    return deposito.obtener(COLECCION, CLAVE) if deposito.activo() else None


def completa():
    """Vista lista para servir: snapshot + acciones y clientes en vivo.

    Devuelve (datos, meta). `meta` dice de cuándo es el snapshot, para poder
    mostrarlo en pantalla y no confundir "no hay casos" con "el job no corrió".
    """
    snap = leer()
    if not snap:
        return None, {"snapshot": False,
                      "nota": "todavía no se generó el snapshot; corré relevo_vista"}

    txs = snap.get("transacciones") or []
    cache = snap.get("cache") or {}
    # Sólo las acciones se leen en vivo: son pocas y son lo que el analista
    # acaba de registrar, así que tienen que verse sin esperar el job.
    acciones = casos.leer_acciones()
    cs = casos.construir(txs, acciones)

    return {
        "casos": cs,
        "clientes": casos.por_cliente(cs),
        "bandeja": snap.get("bandeja") or [],
        "cache": cache,
    }, {
        "snapshot": True,
        "generado_en": snap.get("generado_en"),
        "n_mensajes": snap.get("n_mensajes"),
        "n_transacciones": len(txs),
        "n_acciones": sum(len(v) for v in acciones.values()),
    }
