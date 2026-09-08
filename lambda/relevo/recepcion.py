"""Recepción de la respuesta del cliente: §9.

Poller propio, con las lecciones de WatchTower incorporadas y **sin tocar su
código**. Corre en Lambda cada 10 minutos.

**Correlación, en este orden:**

1. Por **`thread_id`**: la respuesta del cliente cae en el hilo que abrimos.
   Es lo robusto — sobrevive a que el cliente edite el asunto.
2. Por el token **`[rfi: xxxxxxxx]`** del asunto, como respaldo.
3. Si no matchea nada, **no se toca el mensaje**.

**Deduplicación por ledger de Message-ID, NO por el flag `\\Seen`.** Es la
lección explícita de WatchTower, y le costó caro: si se depende de `\\Seen`,
una respuesta que alguien abrió a mano antes del poller no se procesa nunca y
el documento no llega al caso.

**No hace una segunda sincronización con Gmail.** Los candidatos salen del
propio depósito: la ingesta ya baja todo correo nuevo cada 5 minutos, y la
respuesta del cliente llega a la misma casilla. Sólo se va a Gmail a buscar
los adjuntos del mensaje que sí correlacionó, que es cuando vale la pena.

**Nunca crea un caso nuevo desde una respuesta**: siempre actualiza el que
originó la solicitud.
"""
import os
import re
import time

from . import almacen, casos, checklist, correo, deposito, ingesta

COL_PROCESADOS = "procesados"
# Tope por corrida. Recorrer toda la casilla en una invocación la cuelga (§9);
# lo que sobra queda para la corrida siguiente, que llega en 10 minutos.
MAX_POR_CORRIDA = int(os.environ.get("RELEVO_RECEPCION_MAX", "25"))
SEGUNDOS_LIMITE = int(os.environ.get("RELEVO_RECEPCION_SEGUNDOS", "600"))
PREFIJO_S3 = os.environ.get("RELEVO_PREFIJO_ADJUNTOS", "adjuntos")


def _ahora():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


# ── ledger de deduplicación ──────────────────────────────────────────────
def ya_procesado(message_id):
    if not deposito.activo() or not message_id:
        return False
    return deposito.obtener(COL_PROCESADOS, deposito.clave_segura(message_id)) is not None


def marcar_procesado(message_id, caso_id, resultado):
    try:
        deposito.poner(COL_PROCESADOS, deposito.clave_segura(message_id),
                       {"message_id": message_id, "caso_id": caso_id,
                        "resultado": resultado, "cuando": _ahora()})
    except Exception as e:
        print(f"[relevo] no pude marcar procesado {message_id}: {e}")


# ── correlación ──────────────────────────────────────────────────────────
def _indice_solicitudes():
    """(por_hilo, por_token). Sólo de solicitudes que efectivamente salieron:
    un intento fallido no abrió ningún hilo al que responder."""
    por_hilo, por_token = {}, {}
    if not deposito.activo():
        return por_hilo, por_token
    for s in deposito.todos("solicitudes"):
        if not s.get("enviado"):
            continue
        if s.get("thread_id"):
            por_hilo[str(s["thread_id"])] = s
        if s.get("ref"):
            por_token[str(s["ref"]).lower()] = s
    return por_hilo, por_token


def correlacionar(mensaje, por_hilo=None, por_token=None):
    """(caso_id, via) o (None, "") si no matchea. En ese caso NO se toca."""
    if por_hilo is None or por_token is None:
        por_hilo, por_token = _indice_solicitudes()
    hilo = str(mensaje.get("thread_id") or "")
    if hilo and hilo in por_hilo:
        return por_hilo[hilo].get("caso_id"), "thread_id"
    tok = correo.token_de_asunto(mensaje.get("asunto"))
    if tok and tok in por_token:
        return por_token[tok].get("caso_id"), "token"
    return None, ""


def _es_del_cliente(mensaje, solicitud=None):
    """Filtra nuestro propio correo saliente, que también cae en el hilo."""
    h = {str(k).lower(): str(v) for k, v in (mensaje.get("headers") or {}).items()}
    de = (h.get("from") or "") + " " + (h.get("x-original-sender") or "")
    return "compliance@global66.com" not in de and "compliance.masivo@global66.com" not in de


# ── adjuntos ─────────────────────────────────────────────────────────────
_SEGURO_ARCHIVO = re.compile(r"[^A-Za-z0-9._-]+")


def _nombre_archivo(nombre, i=0):
    """Sanea el nombre CONSERVANDO la extensión.

    No se usa `clave_segura` acá: ésa le pega un hash al final, y eso deja
    "cedula.pdf-42c524f6" — un archivo que el analista descarga y no abre.
    Lo que importa en una clave de identificador (que no colisione) no es lo
    que importa en un nombre de archivo (que se pueda abrir). El prefijo con
    el message_id ya garantiza que dos adjuntos no se pisen.
    """
    base = str(nombre or "").strip() or f"adjunto-{i}"
    if "." in base:
        cuerpo, _, ext = base.rpartition(".")
        ext = _SEGURO_ARCHIVO.sub("", ext)[:8]
    else:
        cuerpo, ext = base, ""
    cuerpo = _SEGURO_ARCHIVO.sub("_", cuerpo).strip("_")[:80] or f"adjunto-{i}"
    return f"{cuerpo}.{ext}" if ext else cuerpo


def _guardar_adjuntos(caso_id, message_id, adjuntos):
    """Sube a S3 bajo relevo/adjuntos/<caso>/<mensaje>/. Devuelve la metadata."""
    fuera = []
    s3 = deposito._s3()
    for i, a in enumerate(adjuntos):
        nombre = _nombre_archivo(a.get("nombre"), i)
        clave = (f"{deposito.PREFIJO}/{PREFIJO_S3}/{deposito.clave_segura(caso_id)}/"
                 f"{deposito.clave_segura(message_id)}/{nombre}")
        try:
            s3.put_object(Bucket=deposito.BUCKET, Key=clave, Body=a["bytes"],
                          ContentType=a.get("tipo") or "application/octet-stream")
            fuera.append({"nombre": a.get("nombre"), "tipo": a.get("tipo"),
                          "tamano": a.get("tamano"), "s3_key": clave})
        except Exception as e:
            print(f"[relevo] no pude subir {a.get('nombre')} de {caso_id}: {e}")
    return fuera


# ── procesar una respuesta ───────────────────────────────────────────────
def procesar(mensaje, caso_id, via, g=None, quien="sistema"):
    """Una respuesta ya correlacionada. Devuelve el resumen de lo que hizo."""
    mid = mensaje.get("id")
    r = {"message_id": mid, "caso_id": caso_id, "via": via,
         "adjuntos": 0, "nota": False, "accion": None}

    metadata = []
    try:
        g = g or ingesta.cliente()
        crudos = g.adjuntos(mid)
        if crudos:
            metadata = _guardar_adjuntos(caso_id, mid, crudos)
    except Exception as e:
        r["error_adjuntos"] = str(e)[:200]

    texto = str(mensaje.get("cuerpo") or "").strip()

    if metadata:
        r["adjuntos"] = len(metadata)
        # El checklist pasa a `recibido`, NUNCA a `entregado` (§9).
        res = checklist.marcar_recibido(
            caso_id, quien="sistema",
            detalle=f"{len(metadata)} archivo(s) por correo, vía {via}")
        r["checklist"] = res.get("movidos") or res.get("nota")
        try:
            deposito.poner("respuestas", deposito.clave_segura(mid), {
                "message_id": mid, "caso_id": caso_id, "via": via,
                "adjuntos": metadata, "texto": texto[:4000], "cuando": _ahora()})
        except Exception as e:
            print(f"[relevo] no pude registrar la respuesta {mid}: {e}")
        # respuesta_parcial y no respuesta_recibida: el sistema sabe que llegó
        # algo, no que esté completo. Cerrar eso lo decide una persona.
        accion = "respuesta_parcial"
    else:
        # Sin archivos: el texto queda como nota, que es información igual.
        r["nota"] = bool(texto)
        try:
            deposito.poner("respuestas", deposito.clave_segura(mid), {
                "message_id": mid, "caso_id": caso_id, "via": via,
                "adjuntos": [], "texto": texto[:4000], "cuando": _ahora()})
        except Exception as e:
            print(f"[relevo] no pude registrar la respuesta {mid}: {e}")
        accion = "respuesta_parcial"

    try:
        casos.registrar(caso_id, accion, quien=quien,
                        detalle={"message_id": mid, "via": via,
                                 "adjuntos": len(metadata),
                                 "texto": texto[:500]})
        r["accion"] = accion
    except Exception as e:
        r["error_accion"] = str(e)[:200]

    return r


# ── la corrida ───────────────────────────────────────────────────────────
def correr(maximo=None):
    arranque = time.time()
    tope = maximo or MAX_POR_CORRIDA
    r = {"candidatos": 0, "procesados": 0, "duplicados": 0, "sin_match": 0,
         "propios": 0, "resultados": [], "error": None}

    por_hilo, por_token = _indice_solicitudes()
    if not por_hilo and not por_token:
        r["nota"] = ("no hay solicitudes enviadas todavía: nada que correlacionar "
                     "(el envío espera el scope gmail.send)")
        return r

    try:
        mensajes = almacen.leer()
    except Exception as e:
        r["error"] = f"leyendo el depósito: {str(e)[:200]}"
        return r

    g = None
    for m in mensajes:
        if time.time() - arranque > SEGUNDOS_LIMITE:
            r["nota"] = "se alcanzó el límite de tiempo; el resto queda para la próxima"
            break
        if r["procesados"] >= tope:
            r["nota"] = f"tope de {tope} por corrida; el resto queda para la próxima"
            break

        caso_id, via = correlacionar(m, por_hilo, por_token)
        if not caso_id:
            continue
        r["candidatos"] += 1

        if ya_procesado(m.get("id")):
            r["duplicados"] += 1
            continue
        if not _es_del_cliente(m):
            # Nuestro propio saliente también cae en el hilo. No se procesa,
            # pero se marca para no volver a mirarlo en cada corrida.
            r["propios"] += 1
            marcar_procesado(m.get("id"), caso_id, "propio")
            continue

        try:
            g = g or ingesta.cliente()
        except Exception as e:
            r["error"] = f"sin cliente de Gmail: {str(e)[:150]}"
            break

        res = procesar(m, caso_id, via, g=g)
        marcar_procesado(m.get("id"), caso_id,
                         "con_adjuntos" if res.get("adjuntos") else "solo_texto")
        r["procesados"] += 1
        r["resultados"].append(res)

    r["sin_match"] = len(mensajes) - r["candidatos"]
    r["segundos"] = round(time.time() - arranque, 1)
    return r
