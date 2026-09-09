"""Paso 9: el espejo analítico en Redshift.

Lo operativo del módulo vive en S3, un objeto por registro (ver `deposito.py`).
Eso es correcto para operar —append-only, concurrente, sobrevive al cluster
pausado— y es inservible para preguntar «cuántos RFI abrió Nium en agosto y
cuánto tardamos en devolverlos». Este archivo es el puente: un lote diario que
deja el estado del módulo en un esquema propio de Redshift, donde el resto de
compliance ya sabe consultar.

**No es la fuente de verdad. Es una copia.** El esquema se rehace completo en
cada corrida, así que nada de lo que se escriba acá puede desincronizarse del
depósito: si algo sale mal, la corrida siguiente lo arregla. Por eso tampoco
hay lógica de negocio propia — todo sale de `vista.completa()`, que es lo mismo
que muestra la pantalla, y una diferencia entre el espejo y la pantalla es un
bug del espejo.

**Cómo se cargan las filas, y por qué así.** Tres restricciones reales del
entorno, verificadas antes de escribir esto:

1. El rol de la Lambda tiene `redshift-data:ExecuteStatement` pero **no**
   `BatchExecuteStatement`. Así que no hay forma de mandar N sentencias
   parametrizadas en una transacción por esa vía.
2. Interpolar los valores en el SQL es exactamente lo que `redshift.py` prohíbe,
   y con razón: el texto viene de correos de terceros.
3. El rol del cluster (`AmazonRedshiftAllCommandsFullAccess`) tiene
   `s3:GetObject` sobre `arn:aws:s3:::*redshift*/*`, y el bucket se llama
   `compliance-redshift-reports-...`, así que **matchea**.

De ahí sale la solución, que además es la canónica de Redshift: las filas se
escriben como JSON Lines a S3 y entran con `COPY`. Cero interpolación de texto
ajeno, y el `DELETE` y el `COPY` viajan en una sola sentencia con `BEGIN/END`
para que una carga a medias no deje la tabla vacía.

**Si el cluster está pausado, no se lo despierta.** Es un lote de reporting: no
justifica el costo de encender el cluster fuera de la ventana, y como cada
corrida rehace todo, la del día siguiente no pierde nada. Se salta y lo dice.
`forzar=True` lo despierta, para poder correrlo a mano.
"""
import json
import os
import time
from datetime import datetime, timezone

from . import checklist, deposito, redshift as RS

ESQUEMA = os.environ.get("RELEVO_ESQUEMA", "relevo").strip() or "relevo"
PREFIJO_STAGE = os.environ.get("RELEVO_STAGE", "relevo/espejo").strip().strip("/")
# Si no está seteado se lee del cluster. La variable existe para poder fijarlo
# sin depender de redshift:DescribeClusters.
ROL_COPY = os.environ.get("REDSHIFT_COPY_ROLE", "").strip()

_ID = "VARCHAR(200)"
_TXT = "VARCHAR(1000)"

# Una sola definición por tabla: de acá salen el DDL, las claves del JSON y el
# recorte de cada VARCHAR. Dos listas que hay que mantener sincronizadas a mano
# es la forma más barata de que el espejo mienta.
TABLAS = {
    "casos": [
        ("caso_id", _ID), ("partner", "VARCHAR(80)"), ("caso_partner", "VARCHAR(120)"),
        ("estado", "VARCHAR(40)"), ("etapa", "SMALLINT"), ("accionable", "BOOLEAN"),
        ("cliente_id", "VARCHAR(40)"), ("cliente_nombre", "VARCHAR(300)"),
        ("cliente_correo", "VARCHAR(300)"), ("cliente_pais", "VARCHAR(20)"),
        ("n_transacciones", "INTEGER"), ("n_correos", "INTEGER"), ("n_items", "INTEGER"),
        ("plazo", "VARCHAR(300)"), ("primer_correo", "TIMESTAMP"), ("ultimo_correo", "TIMESTAMP"),
        ("intentos", "SMALLINT"), ("ultimo_contacto", "TIMESTAMP"),
        ("proximo_contacto", "TIMESTAMP"), ("vencido", "BOOLEAN"), ("agotado", "BOOLEAN"),
        ("ck_total", "SMALLINT"), ("ck_pendiente", "SMALLINT"),
        ("ck_recibido", "SMALLINT"), ("ck_entregado", "SMALLINT"),
        ("devuelto_en", "TIMESTAMP"), ("devuelto_por", "VARCHAR(200)"),
        ("devolucion_parcial", "BOOLEAN"),
        ("horas_pedido_a_respuesta", "DECIMAL(10,2)"),
        ("horas_respuesta_a_devolucion", "DECIMAL(10,2)"),
        ("snapshot_en", "TIMESTAMP"),
    ],
    "acciones": [
        ("caso_id", _ID), ("partner", "VARCHAR(80)"), ("accion", "VARCHAR(40)"),
        ("quien", "VARCHAR(200)"), ("cuando", "TIMESTAMP"),
        ("detalle", "VARCHAR(8000)"), ("snapshot_en", "TIMESTAMP"),
    ],
    "transacciones": [
        ("caso_id", _ID), ("partner", "VARCHAR(80)"), ("llave", "VARCHAR(60)"),
        ("valor", "VARCHAR(200)"), ("n_correos", "INTEGER"),
        ("ultimo_correo", "TIMESTAMP"), ("monto", "VARCHAR(60)"),
        ("moneda", "VARCHAR(20)"), ("beneficiario", "VARCHAR(300)"),
        ("remitente", "VARCHAR(300)"), ("snapshot_en", "TIMESTAMP"),
    ],
    "items": [
        ("caso_id", _ID), ("partner", "VARCHAR(80)"), ("item", "VARCHAR(80)"),
        ("etiqueta", "VARCHAR(300)"), ("estado", "VARCHAR(20)"),
        ("quien", "VARCHAR(200)"), ("cuando", "TIMESTAMP"), ("snapshot_en", "TIMESTAMP"),
    ],
    "solicitudes": [
        ("request_id", "VARCHAR(60)"), ("caso_id", _ID), ("correo", "VARCHAR(300)"),
        ("asunto", _TXT), ("ref", "VARCHAR(40)"), ("thread_id", "VARCHAR(60)"),
        ("enviado", "BOOLEAN"), ("error", _TXT), ("quien", "VARCHAR(200)"),
        ("n_documentos", "SMALLINT"), ("cuando", "TIMESTAMP"), ("snapshot_en", "TIMESTAMP"),
    ],
    "respuestas": [
        ("message_id", "VARCHAR(200)"), ("caso_id", _ID), ("via", "VARCHAR(20)"),
        ("n_adjuntos", "SMALLINT"), ("tiene_texto", "BOOLEAN"),
        ("cuando", "TIMESTAMP"), ("snapshot_en", "TIMESTAMP"),
    ],
    "devoluciones": [
        ("caso_id", _ID), ("quien", "VARCHAR(200)"), ("cuando", "TIMESTAMP"),
        ("medio", "VARCHAR(40)"), ("para", "VARCHAR(300)"), ("idioma", "VARCHAR(5)"),
        ("referencia", "VARCHAR(120)"), ("n_archivos", "SMALLINT"),
        ("n_pendientes", "SMALLINT"), ("parcial", "BOOLEAN"), ("snapshot_en", "TIMESTAMP"),
    ],
}


# ── normalización de valores ─────────────────────────────────────────────
def _ts(valor):
    """Cualquier marca de tiempo del módulo → 'YYYY-MM-DD HH:MM:SS' en UTC.

    Conviven cuatro formatos: el `internalDate` de Gmail ya formateado a
    'YYYY-MM-DD HH:MM' por transacciones.py, el ISO con offset que escribe
    `casos.registrar`, el 'YYYY-MM-DD HH:MM:SS' de gmtime del depósito, y
    strings vacíos. Todo se lleva a UTC sin zona, que es lo que guarda un
    TIMESTAMP de Redshift; lo que no se pueda leer va NULL, no una fecha
    inventada.
    """
    s = str(valor or "").strip()
    if not s:
        return None
    if s.isdigit() and len(s) >= 12:            # internalDate en milisegundos
        try:
            return datetime.fromtimestamp(int(s) / 1000, timezone.utc)\
                .strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _horas(desde, hasta):
    """Horas entre dos marcas ya normalizadas. None si falta alguna."""
    if not desde or not hasta:
        return None
    try:
        a = datetime.strptime(desde, "%Y-%m-%d %H:%M:%S")
        b = datetime.strptime(hasta, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return round((b - a).total_seconds() / 3600.0, 2)


_LARGO = {}


def _largos(tabla):
    """{columna: largo} de los VARCHAR, para recortar antes de subir."""
    if tabla not in _LARGO:
        fuera = {}
        for col, tipo in TABLAS[tabla]:
            if tipo.startswith("VARCHAR("):
                fuera[col] = int(tipo[8:-1])
        _LARGO[tabla] = fuera
    return _LARGO[tabla]


def _fila(tabla, datos):
    """Una fila lista para el JSONL: sólo columnas declaradas, ya recortadas.

    Se recorta acá y además se manda TRUNCATECOLUMNS en el COPY. Redundante a
    propósito: sin el recorte en Python un asunto largo se truncaría en silencio
    del lado de Redshift, y sin TRUNCATECOLUMNS un largo que no previmos
    tumbaría la carga completa de la tabla.
    """
    largos = _largos(tabla)
    fuera = {}
    for col, _ in TABLAS[tabla]:
        v = datos.get(col)
        if v is None or v == "":
            continue                            # ausente en el JSON = NULL
        if col in largos and isinstance(v, str):
            v = v[:largos[col]]
        fuera[col] = v
    return fuera


# ── armado de las filas ──────────────────────────────────────────────────
def _cliente_de(caso):
    cl = caso.get("cliente") or {}
    return cl.get("cliente") if isinstance(cl.get("cliente"), dict) else cl


def _checklists():
    """{caso_id: documentos} leyendo la colección UNA vez.

    Antes esto era `checklist.leer(cid)` + `checklist.resumen(cid)` por caso:
    dos GET a S3 secuenciales × 163 casos ≈ 25 s, medido cuando el lote se
    pasó de los 30 s del API Gateway. `deposito.todos` lee en paralelo y de
    una sola vez. Es el mismo arreglo que vista.py le hizo al caché de
    clientes por la misma razón.
    """
    fuera = {}
    if not deposito.activo():
        return fuera
    try:
        for doc in deposito.todos(checklist.COLECCION):
            cid = doc.get("caso_id")
            if cid:
                fuera[cid] = doc.get("documentos") or {}
    except Exception as e:
        print(f"[relevo/espejo] no pude leer los checklists: {e}")
    return fuera


def _resumen(docs):
    """Igual que checklist.resumen pero sobre documentos ya en memoria."""
    r = {e: 0 for e in checklist.ESTADOS}
    for d in (docs or {}).values():
        e = d.get("estado") or checklist.PENDIENTE
        r[e] = r.get(e, 0) + 1
    r["total"] = len(docs or {})
    return r


def construir(datos, ahora=None):
    """{tabla: [filas]} a partir de la vista completa. No toca la red."""
    ahora = ahora or time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    filas = {t: [] for t in TABLAS}
    lista = datos.get("casos") or []
    checklists = _checklists()

    # Las devoluciones se leen una vez, no por caso: son pocas y están en su
    # propia colección desde el paso 9.
    devs = {}
    try:
        for d in (deposito.todos("devoluciones") if deposito.activo() else []):
            cid = d.get("caso_id")
            if cid and (cid not in devs or (d.get("cuando") or "") > (devs[cid].get("cuando") or "")):
                devs[cid] = d
    except Exception as e:
        print(f"[relevo/espejo] no pude leer devoluciones: {e}")

    for c in lista:
        cid = c.get("id") or ""
        d = _cliente_de(c) or {}
        seg = c.get("seguimiento") or {}
        ck_docs = checklists.get(cid) or {}
        res = _resumen(ck_docs)

        acciones = c.get("acciones") or []
        primer_pedido = next((_ts(a.get("cuando")) for a in acciones
                              if a.get("accion") == "pedido_enviado"), None)
        primera_resp = next((_ts(a.get("cuando")) for a in acciones
                             if a.get("accion") in ("respuesta_parcial", "respuesta_recibida")),
                            None)
        dev_accion = next((a for a in reversed(acciones) if a.get("accion") == "devuelto"), None)
        dev_en = _ts((dev_accion or {}).get("cuando"))

        filas["casos"].append(_fila("casos", {
            "caso_id": cid,
            "partner": c.get("partner"),
            "caso_partner": c.get("caso_partner"),
            "estado": c.get("estado"),
            "etapa": c.get("etapa"),
            "accionable": bool(c.get("accionable")),
            "cliente_id": str(d.get("cliente_id") or "") or None,
            "cliente_nombre": d.get("cliente_nombre"),
            "cliente_correo": d.get("cliente_correo"),
            "cliente_pais": d.get("cliente_pais"),
            "n_transacciones": c.get("n_transacciones"),
            "n_correos": c.get("n_correos"),
            "n_items": len(c.get("items") or []),
            "plazo": c.get("plazo") if isinstance(c.get("plazo"), str) else
                     (c.get("plazo") or {}).get("texto"),
            "primer_correo": _ts(c.get("primera")),
            "ultimo_correo": _ts(c.get("ultima")),
            "intentos": seg.get("intentos"),
            "ultimo_contacto": _ts(seg.get("ultimo_contacto")),
            "proximo_contacto": _ts(seg.get("proximo_contacto")),
            "vencido": bool(seg.get("vencido")),
            "agotado": bool(seg.get("agotado")),
            "ck_total": res.get("total"),
            "ck_pendiente": res.get(checklist.PENDIENTE),
            "ck_recibido": res.get(checklist.RECIBIDO),
            "ck_entregado": res.get(checklist.ENTREGADO),
            "devuelto_en": dev_en,
            "devuelto_por": (dev_accion or {}).get("quien"),
            "devolucion_parcial": (bool(((dev_accion or {}).get("detalle") or {}).get("parcial"))
                                   if dev_accion else None),
            "horas_pedido_a_respuesta": _horas(primer_pedido, primera_resp),
            "horas_respuesta_a_devolucion": _horas(primera_resp, dev_en),
            "snapshot_en": ahora,
        }))

        for a in acciones:
            filas["acciones"].append(_fila("acciones", {
                "caso_id": cid, "partner": c.get("partner"),
                "accion": a.get("accion"), "quien": a.get("quien"),
                "cuando": _ts(a.get("cuando")),
                "detalle": json.dumps(a.get("detalle") or {}, ensure_ascii=False, default=str),
                "snapshot_en": ahora,
            }))

        for t in (c.get("transacciones") or []):
            dd = t.get("datos") or {}
            filas["transacciones"].append(_fila("transacciones", {
                "caso_id": cid, "partner": c.get("partner"),
                "llave": t.get("llave"), "valor": t.get("valor"),
                "n_correos": t.get("n_correos"), "ultimo_correo": _ts(t.get("ultima")),
                "monto": _plano(dd.get("monto")), "moneda": _plano(dd.get("moneda")),
                "beneficiario": _plano(dd.get("beneficiario")),
                "remitente": _plano(dd.get("remitente")),
                "snapshot_en": ahora,
            }))

        # Los ítems salen del checklist si existe, y del pedido si no. Lo que
        # nunca se hace es inventarle estado a un ítem sin checklist: queda
        # 'sin_checklist', que es la verdad.
        if ck_docs:
            for clave, doc in ck_docs.items():
                filas["items"].append(_fila("items", {
                    "caso_id": cid, "partner": c.get("partner"), "item": clave,
                    "etiqueta": doc.get("etiqueta"), "estado": doc.get("estado"),
                    "quien": doc.get("quien"), "cuando": _ts(doc.get("cuando")),
                    "snapshot_en": ahora,
                }))
        else:
            for it in (c.get("items") or []):
                clave = it.get("item") if isinstance(it, dict) else str(it)
                etq = it.get("es") if isinstance(it, dict) else str(it)
                filas["items"].append(_fila("items", {
                    "caso_id": cid, "partner": c.get("partner"), "item": clave,
                    "etiqueta": etq, "estado": "sin_checklist", "snapshot_en": ahora,
                }))

        dv = devs.get(cid)
        if dv:
            filas["devoluciones"].append(_fila("devoluciones", {
                "caso_id": cid, "quien": dv.get("quien"), "cuando": _ts(dv.get("cuando")),
                "medio": dv.get("medio"), "para": dv.get("para"), "idioma": dv.get("idioma"),
                "referencia": dv.get("referencia"),
                "n_archivos": len(dv.get("archivos") or []),
                "n_pendientes": len(dv.get("pendientes") or []),
                "parcial": bool(dv.get("parcial")), "snapshot_en": ahora,
            }))

    # Solicitudes y respuestas van completas, no por caso: una solicitud que
    # falló puede apuntar a un caso que ya no aparece en la vista, y perderla
    # sería perder justamente el intento fallido.
    if deposito.activo():
        try:
            for s in deposito.todos("solicitudes"):
                filas["solicitudes"].append(_fila("solicitudes", {
                    "request_id": s.get("request_id"), "caso_id": s.get("caso_id"),
                    "correo": s.get("correo"), "asunto": s.get("asunto"),
                    "ref": s.get("ref"), "thread_id": s.get("thread_id"),
                    "enviado": bool(s.get("enviado")), "error": s.get("error"),
                    "quien": s.get("quien"),
                    "n_documentos": len(s.get("documentos") or []),
                    "cuando": _ts(s.get("cuando")), "snapshot_en": ahora,
                }))
        except Exception as e:
            print(f"[relevo/espejo] no pude leer solicitudes: {e}")
        try:
            for r in deposito.todos("respuestas"):
                filas["respuestas"].append(_fila("respuestas", {
                    "message_id": r.get("message_id"), "caso_id": r.get("caso_id"),
                    "via": r.get("via"), "n_adjuntos": len(r.get("adjuntos") or []),
                    "tiene_texto": bool(str(r.get("texto") or "").strip()),
                    "cuando": _ts(r.get("cuando")), "snapshot_en": ahora,
                }))
        except Exception as e:
            print(f"[relevo/espejo] no pude leer respuestas: {e}")

    return filas


def _plano(v):
    """Los datos extraídos vienen a veces como {es, valor}. Sin esto el espejo
    guardaría el diccionario serializado en la columna."""
    if isinstance(v, dict):
        for k in ("valor", "value", "texto", "es"):
            if v.get(k) not in (None, ""):
                return str(v[k])
        return None
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x not in (None, "")) or None
    return str(v) if v not in (None, "") else None


# ── Redshift ─────────────────────────────────────────────────────────────
def _cliente_datos():
    import boto3
    cfg = RS.config()
    return boto3.client("redshift-data", region_name=cfg["region"]), cfg


def _correr(sql, cfg, cliente=None, timeout=None):
    """Una sentencia por la Data API, esperando el resultado. Sin parámetros:
    todo lo que viene de un correo entra por COPY, nunca por el SQL."""
    d = cliente or _cliente_datos()[0]
    r = d.execute_statement(ClusterIdentifier=cfg["cluster"], Database=cfg["base"],
                            DbUser=cfg["dbuser"], Sql=sql)
    sid, arranque = r["Id"], time.time()
    limite = timeout or cfg["timeout"]
    while True:
        st = d.describe_statement(Id=sid)
        if st["Status"] in ("FINISHED", "FAILED", "ABORTED"):
            break
        if time.time() - arranque > limite:
            try:
                d.cancel_statement(Id=sid)
            except Exception:
                pass
            raise RS.ErrorRedshift(f"timeout de {limite}s: {sql[:80]}")
        time.sleep(0.5)
    if st["Status"] != "FINISHED":
        raise RS.ErrorRedshift(f"{st['Status']}: {st.get('Error') or ''} — {sql[:120]}")
    return st


def ddl():
    """El DDL completo, idempotente. Se corre en cada corrida a propósito: es
    barato y hace que el espejo se instale solo en un ambiente nuevo."""
    fuera = [f"CREATE SCHEMA IF NOT EXISTS {ESQUEMA}"]
    for tabla, cols in TABLAS.items():
        cuerpo = ", ".join(f"{c} {t}" for c, t in cols)
        fuera.append(f"CREATE TABLE IF NOT EXISTS {ESQUEMA}.{tabla} ({cuerpo})")
    return fuera


def _rol_copy(cfg):
    if ROL_COPY:
        return ROL_COPY
    import boto3
    r = boto3.client("redshift", region_name=cfg["region"]).describe_clusters(
        ClusterIdentifier=cfg["cluster"])
    roles = r["Clusters"][0].get("IamRoles") or []
    if not roles:
        raise RS.ErrorRedshift(
            "el cluster no tiene rol IAM asociado: COPY no puede leer de S3. "
            "Seteá REDSHIFT_COPY_ROLE con el ARN de un rol con s3:GetObject.")
    return roles[0]["IamRoleArn"]


def _subir(tabla, filas):
    """Las filas como JSON Lines en S3. Devuelve la URI que consume el COPY."""
    clave = f"{PREFIJO_STAGE}/{tabla}.json"
    cuerpo = "\n".join(json.dumps(f, ensure_ascii=False, default=str) for f in filas)
    deposito._s3().put_object(Bucket=deposito.BUCKET, Key=clave,
                              Body=cuerpo.encode("utf-8"),
                              ContentType="application/x-ndjson")
    return f"s3://{deposito.BUCKET}/{clave}", len(cuerpo.encode("utf-8"))


def _estado_cluster(cfg):
    import boto3
    r = boto3.client("redshift", region_name=cfg["region"]).describe_clusters(
        ClusterIdentifier=cfg["cluster"])
    return r["Clusters"][0]["ClusterStatus"]


CLAVE_ULTIMA = "ultima"
COL_CORRIDAS = "espejo"


def _guardar_corrida(r):
    """Deja el resultado de la última corrida donde se pueda leer después.

    El lote corre en la Lambda de reportes, disparado en Event (asíncrono):
    quien lo dispara no recibe la respuesta. Sin esto, la única forma de saber
    si el espejo se actualizó sería leer CloudWatch, y entonces nadie lo
    mira. También sirve para responder «¿de cuándo son estos datos?».
    """
    try:
        if deposito.activo():
            deposito.poner(COL_CORRIDAS, CLAVE_ULTIMA, r)
    except Exception as e:
        print(f"[relevo/espejo] no pude guardar el resultado de la corrida: {e}")
    return r


def ultima():
    """El resultado de la última corrida, o None si nunca corrió."""
    if not deposito.activo():
        return None
    try:
        return deposito.obtener(COL_CORRIDAS, CLAVE_ULTIMA)
    except Exception:
        return None


def correr(forzar=False, solo=None):
    """El lote. Devuelve el detalle de qué escribió y qué no.

    `solo` limita a una tabla, para poder probar una sola. `forzar` despierta
    el cluster si está pausado.
    """
    arranque = time.time()
    r = {"esquema": ESQUEMA, "tablas": {}, "error": None, "saltado": False,
         "arrancado_en": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
         "forzado": bool(forzar)}

    if not deposito.activo():
        r["error"] = "el depósito de S3 no está activo (falta RELEVO_BUCKET)"
        return r

    cliente, cfg = _cliente_datos()
    try:
        estado = _estado_cluster(cfg)
    except Exception as e:
        estado = "desconocido"
        r["aviso_estado"] = str(e)[:200]
    r["cluster"] = estado

    if estado == "paused":
        if not forzar:
            r["saltado"] = True
            r["error"] = ("el cluster está pausado y no se despierta por un lote de "
                          "reporting: la próxima corrida rehace todo igual. "
                          "Con forzar=true se enciende.")
            r["segundos"] = round(time.time() - arranque, 1)
            return _guardar_corrida(r)
        import boto3
        boto3.client("redshift", region_name=cfg["region"]).resume_cluster(
            ClusterIdentifier=cfg["cluster"])
        for _ in range(60):
            time.sleep(10)
            if _estado_cluster(cfg) == "available":
                break
        r["cluster"] = _estado_cluster(cfg)

    from . import vista
    datos, meta = vista.completa()
    if datos is None:
        r["error"] = f"no hay snapshot de la vista: {meta.get('nota')}"
        r["segundos"] = round(time.time() - arranque, 1)
        return _guardar_corrida(r)
    r["meta_vista"] = meta

    t0 = time.time()
    filas = construir(datos)
    r["filas"] = {t: len(v) for t, v in filas.items()}
    r["segundos_armado"] = round(time.time() - t0, 1)

    try:
        for sql in ddl():
            _correr(sql, cfg, cliente)
        r["ddl"] = "ok"
    except Exception as e:
        detalle = str(e)[:300]
        if "not available" in detalle:
            detalle += (" — el cluster parece pausado y no se pudo verificar "
                        "antes (ver aviso_estado)")
        r["error"] = f"DDL: {detalle}"
        r["segundos"] = round(time.time() - arranque, 1)
        return _guardar_corrida(r)

    rol = None
    for tabla, v in filas.items():
        if solo and tabla != solo:
            continue
        detalle = {"filas": len(v)}
        try:
            if not v:
                # Sin filas igual se vacía la tabla: si ayer había casos y hoy
                # no, dejar los de ayer sería mostrar datos que ya no existen.
                _correr(f"DELETE FROM {ESQUEMA}.{tabla}", cfg, cliente)
                detalle["estado"] = "vaciada"
            else:
                uri, tamano = _subir(tabla, v)
                detalle["bytes_stage"] = tamano
                rol = rol or _rol_copy(cfg)
                # DELETE y COPY en una sola sentencia: si el COPY falla, el
                # DELETE se va con él y la tabla queda con los datos de ayer,
                # que es mucho mejor que quedar vacía.
                sql = (f"BEGIN; DELETE FROM {ESQUEMA}.{tabla}; "
                       f"COPY {ESQUEMA}.{tabla} FROM '{uri}' IAM_ROLE '{rol}' "
                       f"FORMAT AS JSON 'auto' TIMEFORMAT 'auto' "
                       f"TRUNCATECOLUMNS ACCEPTINVCHARS; END;")
                _correr(sql, cfg, cliente, timeout=max(cfg["timeout"], 120))
                detalle["estado"] = "cargada"
        except Exception as e:
            detalle["estado"] = "error"
            detalle["error"] = str(e)[:400]
        r["tablas"][tabla] = detalle

    fallidas = [t for t, d in r["tablas"].items() if d.get("estado") == "error"]
    if fallidas:
        r["error"] = f"fallaron {len(fallidas)} tabla(s): {', '.join(fallidas)}"
    r["segundos"] = round(time.time() - arranque, 1)
    return _guardar_corrida(r)
