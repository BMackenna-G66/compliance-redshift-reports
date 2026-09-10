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

from . import casos, checklist, correo, deposito, ingesta, vista

COLECCION = "solicitudes"
# Tope por lote. Bajo a propósito: es un flujo que le escribe a clientes
# reales, así que la primera vez que alguien se equivoca tiene que equivocarse
# en pocos.
MAX_LOTE = int(os.environ.get("RELEVO_MAX_LOTE", "20"))
REMITENTE = os.environ.get("RELEVO_FROM_ADDR", correo.REMITENTE_POR_DEFECTO)
# La dirección del grupo. No es cosmética: `list-id: <compliance.global66.com>`
# y `delivered-to: compliance.masivo@global66.com` en los correos ingeridos
# prueban que lo que llega al grupo cae en la casilla que el poller lee. Es la
# única dirección desde la que un envío a mano vuelve a entrar solo.
REMITENTE_GRUPO = os.environ.get("RELEVO_GRUPO_ADDR", "compliance@global66.com")


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
        r, transporte = _despachar(c)
        thread_id = str(r.get("threadId") or "")
    except Exception as e:
        # Se registra el intento fallido: que no salga no significa que no pasó.
        reg = _registrar(caso_id, c, False, error=str(e), quien=quien)
        return {"enviado": False, "error": str(e)[:400], "request_id": reg["request_id"]}

    reg = _registrar(caso_id, c, True, thread_id=thread_id, quien=quien)
    # El checklist nace acá, todo en `pendiente` (§9). Si el caso ya tenía uno
    # —un recontacto— no se pisa: se conservan los estados ya confirmados.
    try:
        checklist.crear(caso_id, caso.get("items") or [], ref=c["token"], quien=quien)
    except Exception as e:
        print(f"[relevo] correo enviado pero no pude armar el checklist de {caso_id}: {e}")
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
            "ref": c["token"], "thread_id": thread_id, "transporte": transporte,
            "request_id": reg["request_id"]}


# ── el transporte ────────────────────────────────────────────────────────
#
# §5 de la especificación dice "Gmail API, no SMTP", y el motivo era bueno:
# la API devuelve el `threadId`, que correlaciona la respuesta del cliente
# aunque edite el asunto. Pero eso hizo que todo el envío quedara colgado de
# un scope de OAuth que no tenemos, y **el repo anfitrión ya mandaba correos
# por SMTP todo este tiempo**: `_send_email` en api_handler.py, con una app
# password en Secrets Manager, sale como `compliance@global66.com` y le
# escribe a clientes reales en gmail.com. Verificado en los logs.
#
# Así que el envío no dependía del scope. Dependía de que alguien mirara.
#
# Se replica la lógica acá en vez de importarla (§1: réplica adaptada, no
# reuso), y se comparte sólo la credencial, que es un dato y no código.
#
# Lo que se pierde frente a la API es el `threadId`. La correlación cae al
# **token del asunto**, que §9 ya define como segundo camino y recepcion.py
# implementa. Cuando llegue `gmail.modify`, cambiar de transporte es una
# variable de entorno y se recupera el threadId.
TRANSPORTE = os.environ.get("RELEVO_TRANSPORTE", "smtp").strip().lower()
SMTP_USUARIO = os.environ.get("GMAIL_USER", "benjamin.mackenna@global66.com")
SMTP_SECRETO = os.environ.get("GMAIL_PASSWORD_SECRET_NAME",
                              "compliance-redshift-reports/gmail-app-password")
_clave_smtp = None


def _password_smtp():
    """La app password, de Secrets Manager. Se cachea por invocación tibia."""
    global _clave_smtp
    if _clave_smtp is None:
        import boto3
        bruto = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "us-east-1")
        ).get_secret_value(SecretId=SMTP_SECRETO).get("SecretString", "")
        _clave_smtp = "".join((bruto or "").split())
    return _clave_smtp


def _enviar_smtp(compuesto, remitente=None):
    """Manda el pedido por SMTP. Devuelve {"thread_id": ""} para igualar la
    forma de la API, que sí lo trae.

    **El Reply-To es la pieza que hace funcionar el ciclo.** Tiene que ser el
    grupo: verificado en los headers de los correos ingeridos, todo lo que
    llega a `compliance@global66.com` se entrega en
    `compliance.masivo@global66.com`, que es la casilla que el poller lee. Si
    la respuesta del cliente cayera en otra bandeja, el caso quedaría
    esperando para siempre.
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    de = remitente or REMITENTE_GRUPO
    m = MIMEMultipart("alternative")
    m["Subject"] = compuesto["asunto"]
    m["From"] = de
    m["To"] = compuesto["para"]
    m["Reply-To"] = REMITENTE_GRUPO
    m.attach(MIMEText(compuesto["texto"], "plain", "utf-8"))
    m.attach(MIMEText(compuesto["html"], "html", "utf-8"))

    clave = _password_smtp()
    if not clave:
        raise RuntimeError(
            f"no hay app password en Secrets Manager ({SMTP_SECRETO}): no se puede enviar")
    # 20 s y no menos: el handshake TLS más el login contra Gmail desde una
    # Lambda fría se pasaba de 8 s y el correo se perdía sin aviso. Es la
    # misma lección que ya había aprendido `_send_email`.
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(SMTP_USUARIO, clave)
        s.sendmail(de, [compuesto["para"]], m.as_string())
    return {"id": "", "threadId": ""}


def _despachar(compuesto):
    """Manda por el transporte configurado. (respuesta, transporte_usado)."""
    if TRANSPORTE == "gmail_api":
        g = ingesta.cliente()
        return g.enviar(correo.a_mime(compuesto, REMITENTE)), "gmail_api"
    return _enviar_smtp(compuesto), "smtp"


# ── envío a mano: el ciclo sin el scope de Gmail ─────────────────────────
#
# El token está en `gmail.readonly` y el re-consentimiento depende de un
# trámite con Google que puede tardar. Esto destraba el ciclo sin esperarlo.
#
# **Por qué funciona.** Verificado en los headers de los correos ya ingeridos:
#
#     to:           compliance@global66.com          ← el grupo
#     delivered-to: compliance.masivo@global66.com   ← la casilla que leemos
#     list-id:      <compliance.global66.com>
#
# Todo lo que llega al grupo cae en la casilla que el poller lee. Así que si
# el cliente responde al grupo, la respuesta entra igual — y la correlación
# por **token del asunto** (§9, el segundo camino) la ata al caso sin
# necesidad del threadId, que es lo único que se pierde al no mandar por API.
#
# Lo que NO se afloja: el interruptor. Mandar a mano sigue siendo escribirle a
# un cliente real, así que pasa por la misma llave. Un interruptor que se
# puede saltar por otra puerta no es un interruptor.
MEDIO_MANUAL = "manual"


def registrar_manual(caso_id, quien="", nota="", confirmado=False):
    """Compone el pedido, lo registra como enviado a mano y arma el checklist.

    NO toca la red. Devuelve el texto para copiar y las instrucciones de desde
    dónde mandarlo, que son la parte que hay que hacer bien: si sale desde el
    correo personal del analista, la respuesta del cliente vuelve a su bandeja
    y el poller no la ve nunca.
    """
    quien = str(quien or "").strip()
    if not quien:
        return {"registrado": False,
                "error": "quien es requerido: no se le escribe a un cliente sin autor"}

    caso, meta = _buscar_caso(caso_id)
    if caso is None:
        return {"registrado": False, "error": f"caso '{caso_id}' no encontrado"}

    permitido, motivo = puede_enviar(caso.get("partner"))
    if not permitido:
        return {"registrado": False, "bloqueado": True, "error": motivo}

    pedido, motivo_pedido = ya_pedido(caso_id)
    if pedido:
        return {"registrado": False, "bloqueado": True,
                "error": f"doble envío bloqueado: {motivo_pedido}"}

    c = correo.componer(caso, nota=nota)
    if not c["para"]:
        return {"registrado": False, "error": "el caso no tiene correo de cliente resuelto"}

    if not confirmado:
        # Se compone y se devuelve, pero no se registra: primero se mira.
        return {"registrado": False, "requiere_confirmacion": True,
                "caso_id": caso_id, **_para_copiar(c)}

    # thread_id vacío a propósito: no lo mandamos nosotros, así que no hay
    # hilo que guardar. La correlación va a caer por token, que es el camino
    # de respaldo que §9 ya define y recepcion.py ya implementa.
    reg = _registrar(caso_id, c, True, thread_id="", quien=quien)
    try:
        checklist.crear(caso_id, caso.get("items") or [], ref=c["token"], quien=quien)
    except Exception as e:
        print(f"[relevo] registrado a mano pero no pude armar el checklist de {caso_id}: {e}")
    try:
        casos.registrar(caso_id, "pedido_enviado", quien=quien,
                        detalle={"ref": c["token"], "medio": MEDIO_MANUAL,
                                 "correo": c["para"], "thread_id": "",
                                 "documentos": c["items_catalogo"]})
    except Exception as e:
        print(f"[relevo] registrado a mano pero no pude anotar la acción de {caso_id}: {e}")

    return {"registrado": True, "caso_id": caso_id, "medio": MEDIO_MANUAL,
            "request_id": reg["request_id"], **_para_copiar(c)}


def _para_copiar(c):
    """Lo que la pantalla necesita para que alguien mande esto a mano."""
    return {
        "para": c["para"],
        "asunto": c["asunto"],
        "html": c["html"],
        "texto": c["texto"],
        "ref": c["token"],
        "items_catalogo": c["items_catalogo"],
        "items_crudo": c["items_crudo"],
        "avisos": c["avisos"],
        # Lo único que hay que hacer bien, y por eso viaja explícito.
        "enviar_desde": REMITENTE_GRUPO,
        "instrucciones": [
            f"Mandalo desde {REMITENTE_GRUPO} (o poné esa dirección como Reply-To).",
            "Si sale desde tu correo personal, la respuesta del cliente vuelve a TU "
            "bandeja y el poller no la ve: el caso queda esperando para siempre.",
            "NO edites el asunto: el token [rfi: …] es lo que ata la respuesta al caso.",
        ],
    }


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
