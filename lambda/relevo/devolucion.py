"""Paso 9: la devolución al partner.

El ciclo RFI cierra devolviéndole al corresponsal lo que pidió. Hasta el paso 8
el módulo sabía pedirle al cliente, recibir su respuesta y recontactarlo; lo
que faltaba es el tramo final, que es el que le da sentido a todo el resto.

**Decisión 10 de §16, resuelta: en pantalla para copiar, no borrador en Gmail.**
El refresh token está en `gmail.readonly`. Un borrador necesita
`gmail.compose` o `gmail.modify` — que es un re-consentimiento *distinto* del
`gmail.send` que el paso 6 ya está esperando. Escribir hoy la rama del borrador
sería código que no puede correr ni probarse. Lo que funciona hoy es componer
la respuesta y que el analista la pegue en su cliente de correo, y eso es lo
que desbloquea la operación.

Cuando se haga el re-consentimiento conviene pedir **`gmail.modify`** en vez de
`gmail.send`: cubre los dos casos (enviar el pedido al cliente y dejar el
borrador de la devolución) en un solo viaje. Con eso, agregar el borrador acá
son ~15 líneas contra `drafts.create`.

**Los enlaces de descarga NO van en el correo.** Son URLs prefirmadas de S3:
quien tenga el link baja el documento sin autenticarse. Un documento de KYC de
un cliente viajando como link reenviable a un tercero es una fuga, no una
comodidad. Los enlaces existen sólo en la pantalla, para que el analista baje
los archivos y los adjunte él; el cuerpo del correo nombra los archivos y nada
más.

**El idioma lo elige quien manda.** Medido sobre la casilla real: Currencycloud,
Nium y dLocal escriben en inglés; OZ Câmbio en portugués. Así que el default es
inglés y hay selector. Las etiquetas de los ítems salen del catálogo de
`reglas.json` —la misma lista blanca de §8— traducidas ahí y no acá: el resumen
sigue componiéndose de estructura extraída, nunca de texto libre generado.

Lo único libre es la nota del analista, que la escribe una persona.
"""
import os
import time

from . import casos, checklist, deposito, reglas as R

# Cuánto vive un enlace de descarga. Corto a propósito: son documentos de
# identidad y comprobantes de un cliente, y el enlace no pide autenticación.
SEGUNDOS_ENLACE = int(os.environ.get("RELEVO_ENLACE_SEGUNDOS", "900"))

IDIOMAS = ("en", "es", "pt")

TEXTOS = {
    "en": {
        "asunto": "RE: {asunto}",
        "saludo": "Hi,",
        "intro": "Please find below our response to your information request{ref}.",
        "tx": "Transactions covered:",
        "pedido": "Information requested:",
        "entregado": "Provided by the customer:",
        "pendiente": "Still outstanding:",
        "archivos": "Attached files:",
        "sin_archivos": "The customer replied without attaching files; their answer is "
                        "transcribed above.",
        "cierre": "Please let us know if anything else is required.",
        "firma": "Kind regards,\nCompliance Team · Global66",
        "recibido_el": "received {fecha}",
    },
    "es": {
        "asunto": "RE: {asunto}",
        "saludo": "Hola,",
        "intro": "A continuación va nuestra respuesta a su solicitud de información{ref}.",
        "tx": "Operaciones incluidas:",
        "pedido": "Información solicitada:",
        "entregado": "Entregado por el cliente:",
        "pendiente": "Todavía pendiente:",
        "archivos": "Archivos adjuntos:",
        "sin_archivos": "El cliente respondió sin adjuntar archivos; su respuesta queda "
                        "transcrita más arriba.",
        "cierre": "Quedamos atentos si hace falta algo más.",
        "firma": "Saludos,\nEquipo de Compliance · Global66",
        "recibido_el": "recibido el {fecha}",
    },
    "pt": {
        "asunto": "RE: {asunto}",
        "saludo": "Olá,",
        "intro": "Segue abaixo nossa resposta à sua solicitação de informação{ref}.",
        "tx": "Operações incluídas:",
        "pedido": "Informação solicitada:",
        "entregado": "Entregue pelo cliente:",
        "pendiente": "Ainda pendente:",
        "archivos": "Arquivos anexos:",
        "sin_archivos": "O cliente respondeu sem anexar arquivos; a resposta está "
                        "transcrita acima.",
        "cierre": "Ficamos à disposição caso precise de algo mais.",
        "firma": "Atenciosamente,\nEquipe de Compliance · Global66",
        "recibido_el": "recebido em {fecha}",
    },
}


def _ahora():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def idioma_de(partner, config=None):
    """El idioma por defecto del partner, si el mantenedor declaró uno.

    Misma precedencia que la política de recontacto (§7): `idioma_<partner>`
    manda sobre `idioma_general`, y si no hay ninguno el default es inglés,
    que es lo que escriben tres de los cuatro corresponsales.
    """
    if config is None:
        from . import api as rapi
        config = rapi.leer_config()
    p = str(partner or "").lower().replace(" ", "_")
    for clave in (f"idioma_{p}", "idioma_general"):
        v = str(config.get(clave) or "").strip().lower()
        if v in IDIOMAS:
            return v
    return "en"


# ── el catálogo, en el idioma del partner ────────────────────────────────
_CATALOGO = None


def _etiquetas(idioma):
    """{item: etiqueta} en el idioma pedido, cayendo al español del catálogo.

    Cae al español y no a la clave técnica: `documento_identidad` no le dice
    nada a nadie, "Documento de identidad" sí, aunque esté en otro idioma.
    """
    global _CATALOGO
    if _CATALOGO is None:
        try:
            _CATALOGO = (R.cargar_reglas().get("requerimiento") or {}).get("catalogo") or []
        except Exception:
            _CATALOGO = []
    fuera = {}
    for it in _CATALOGO:
        clave = it.get("item")
        if clave:
            fuera[clave] = it.get(idioma) or it.get("es") or clave
    return fuera


def _texto_item(it, etiquetas):
    """La etiqueta traducida de un ítem del pedido.

    Los ítems del caso vienen como {item, es}. Se traduce por la CLAVE, que es
    lo estable; si el ítem no salió del catálogo —quedó en crudo— se muestra
    tal cual vino, porque inventarle una traducción sería inventar el pedido.
    """
    if isinstance(it, str):
        return etiquetas.get(it) or it
    clave = (it or {}).get("item") or ""
    return etiquetas.get(clave) or (it or {}).get("es") or clave or "(sin descripción)"


# ── a quién se le contesta ───────────────────────────────────────────────
def _mensaje(mid):
    if not deposito.activo() or not mid:
        return None
    return deposito.obtener("mensajes", deposito.clave_segura(mid))


def _header(headers, nombre):
    n = nombre.lower()
    for k, v in (headers or {}).items():
        if str(k).lower() == n:
            return str(v)
    return ""


def destinatario(caso):
    """(direccion, asunto_original, referencia) del correo del partner.

    Se responde al correo **real** del corresponsal, que vive en
    `X-Original-Sender`: el `From` de todos estos mensajes es
    compliance@global66.com porque el grupo de Google reescribe el remitente
    (§1 de partner.py). Contestarle al `From` sería escribirnos a nosotros.

    Se elige el correo accionable más reciente del caso: es el que tiene el
    pedido vigente y el hilo donde el partner espera la respuesta.
    """
    correos = list(caso.get("correos") or [])
    candidatos = [c for c in correos if c.get("accionable")] or correos
    for c in candidatos:
        m = _mensaje(c.get("id"))
        if not m:
            continue
        h = m.get("headers") or {}
        for campo in ("X-Original-Sender", "X-Original-From", "Reply-To", "From"):
            valor = _header(h, campo)
            if "@" in valor and "global66.com" not in valor.lower():
                import re
                d = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", valor)
                if d:
                    return d.group(0).lower(), c.get("asunto") or m.get("asunto") or "", {
                        "message_id": _header(h, "Message-ID"),
                        "gmail_id": c.get("id"),
                        "thread_id": c.get("thread_id") or m.get("thread_id") or "",
                        "url_gmail": c.get("url_gmail") or "",
                        "via": campo,
                        "fecha": c.get("fecha") or "",
                    }
    # Sin dirección utilizable: se devuelve el asunto igual, que sirve para
    # armar el "RE:" y para que el analista busque el hilo a mano.
    primero = candidatos[0] if candidatos else {}
    return "", primero.get("asunto") or "", {
        "gmail_id": primero.get("id", ""),
        "thread_id": primero.get("thread_id", ""),
        "url_gmail": primero.get("url_gmail", ""),
        "via": "",
        "fecha": primero.get("fecha", ""),
    }


# ── qué mandó el cliente ─────────────────────────────────────────────────
def respuestas_de(caso_id):
    """Las respuestas del cliente registradas por el poller del paso 7."""
    if not deposito.activo():
        return []
    todas = [r for r in deposito.todos("respuestas") if r.get("caso_id") == caso_id]
    return sorted(todas, key=lambda r: r.get("cuando", ""))


def adjuntos_de(caso_id, con_enlace=True):
    """Los archivos que mandó el cliente, con enlace de descarga temporal.

    El enlace es prefirmado y vive `SEGUNDOS_ENLACE`. No se pone en el correo
    (ver el encabezado del módulo): es para que el analista baje el archivo.
    """
    fuera = []
    for r in respuestas_de(caso_id):
        for a in (r.get("adjuntos") or []):
            fila = {
                "nombre": a.get("nombre") or "",
                "tipo": a.get("tipo") or "",
                "tamano": a.get("tamano") or 0,
                "cuando": r.get("cuando") or "",
                "s3_key": a.get("s3_key") or "",
                "url": "",
            }
            if con_enlace and fila["s3_key"]:
                try:
                    fila["url"] = deposito._s3().generate_presigned_url(
                        "get_object",
                        Params={"Bucket": deposito.BUCKET, "Key": fila["s3_key"]},
                        ExpiresIn=SEGUNDOS_ENLACE)
                    fila["expira_en_segundos"] = SEGUNDOS_ENLACE
                except Exception as e:
                    fila["error_enlace"] = str(e)[:150]
            fuera.append(fila)
    return fuera


def _texto_cliente(caso_id, maximo=3):
    """Lo que el cliente escribió, si escribió algo. Va tal cual: es su
    respuesta, no la nuestra, y recortarla o reescribirla sería tergiversarla."""
    fuera = []
    for r in respuestas_de(caso_id):
        t = str(r.get("texto") or "").strip()
        if t:
            fuera.append({"cuando": r.get("cuando") or "", "texto": t[:2000]})
    return fuera[-maximo:]


# ── componer ─────────────────────────────────────────────────────────────
def componer(caso, idioma="en", nota="", caso_id=None):
    """{asunto, texto, para, ...}. No toca la red más allá de leer el depósito.

    Sólo texto plano: la devolución la pega una persona en su cliente de
    correo, y un HTML pegado en Gmail arrastra estilos y se ve peor que el
    texto. El pedido al cliente sí es HTML porque lo manda la máquina.
    """
    if idioma not in IDIOMAS:
        idioma = "en"
    T = TEXTOS[idioma]
    cid = caso_id or caso.get("id") or ""
    etiquetas = _etiquetas(idioma)
    para, asunto_orig, ref = destinatario(caso)

    referencia = str(caso.get("caso_partner") or "").strip()
    txs = [str(t.get("valor") or "").strip()
           for t in (caso.get("transacciones") or []) if t.get("valor")]

    res = checklist.resumen(cid)
    docs = (checklist.leer(cid).get("documentos") or {})
    entregados, pendientes = [], []
    for clave, d in docs.items():
        etq = etiquetas.get(clave) or d.get("etiqueta") or clave
        (entregados if d.get("estado") in (checklist.RECIBIDO, checklist.ENTREGADO)
         else pendientes).append(etq)

    # Si el caso no tiene checklist —el pedido se marcó a mano y no salió de
    # acá— el pedido se muestra completo, sin partirlo: decir "entregado" de
    # algo que nadie confirmó sería afirmar un hecho que no está registrado.
    pedido = [_texto_item(it, etiquetas) for it in (caso.get("items") or [])]

    adj = adjuntos_de(cid, con_enlace=False)
    textos = _texto_cliente(cid)

    avisos = []
    if not para:
        avisos.append("No se pudo resolver el correo del partner desde los headers; "
                      "hay que copiar la respuesta al hilo a mano.")
    if not res.get("total"):
        avisos.append("El caso no tiene checklist: la respuesta lista el pedido completo "
                      "sin distinguir qué llegó. Conviene revisarla antes de mandarla.")
    elif pendientes:
        avisos.append(f"Quedan {len(pendientes)} ítem(s) sin entregar: la devolución sale "
                      f"como parcial.")
    if not adj and not textos:
        avisos.append("No hay ninguna respuesta del cliente registrada para este caso.")
    if res.get(checklist.RECIBIDO) and not res.get(checklist.ENTREGADO):
        avisos.append("Hay documentos en «recibido» que nadie marcó «entregado»: el "
                      "sistema sabe que llegaron, no que sirvan.")

    ref_txt = f" ({referencia})" if referencia else ""
    lineas = [T["saludo"], "", T["intro"].format(ref=ref_txt), ""]
    if txs:
        lineas.append(T["tx"])
        lineas += [f"  - {v}" for v in txs]
        lineas.append("")
    if pedido:
        lineas.append(T["pedido"])
        lineas += [f"  {i}. {x}" for i, x in enumerate(pedido, 1)]
        lineas.append("")
    if entregados:
        lineas.append(T["entregado"])
        lineas += [f"  - {x}" for x in entregados]
        lineas.append("")
    if pendientes:
        lineas.append(T["pendiente"])
        lineas += [f"  - {x}" for x in pendientes]
        lineas.append("")
    if adj:
        lineas.append(T["archivos"])
        for a in adj:
            fecha = str(a.get("cuando") or "")[:10]
            marca = f" ({T['recibido_el'].format(fecha=fecha)})" if fecha else ""
            lineas.append(f"  - {a['nombre']}{marca}")
        lineas.append("")
    elif textos:
        lineas += [T["sin_archivos"], ""]
    for t in textos:
        lineas += [f"> {l}" for l in t["texto"].splitlines() if l.strip()]
        lineas.append("")
    if nota:
        lineas += [str(nota).strip(), ""]
    lineas += [T["cierre"], "", T["firma"]]

    return {
        "para": para,
        "asunto": T["asunto"].format(asunto=asunto_orig) if asunto_orig else
                  (f"RE: {referencia}" if referencia else "RE: Compliance query"),
        "texto": "\n".join(lineas),
        "idioma": idioma,
        "referencia": referencia,
        "transacciones": txs,
        "pedido": pedido,
        "entregados": entregados,
        "pendientes": pendientes,
        "archivos": [a["nombre"] for a in adj],
        "respuestas_texto": textos,
        "en_respuesta_a": ref,
        "checklist": {k: v for k, v in res.items() if k != "faltantes"},
        "avisos": avisos,
    }


# ── la pantalla ──────────────────────────────────────────────────────────
def _buscar_caso(caso_id):
    from . import vista
    d, meta = vista.completa()
    if d is None:
        return None, meta
    return next((c for c in d["casos"] if c.get("id") == caso_id), None), meta


def ya_devuelto(caso_id):
    """(sí, motivo). `devuelto` es terminal (§7): se avisa, no se repite solo."""
    for a in (casos.leer_acciones().get(caso_id) or []):
        if a.get("accion") == "devuelto":
            return True, f"ya se marcó devuelto el {a.get('cuando')} por {a.get('quien') or '?'}"
    return False, ""


def previsualizar(caso_id, idioma="", nota=""):
    """Todo lo que la pantalla necesita: el texto, los archivos y los avisos."""
    caso, meta = _buscar_caso(caso_id)
    if caso is None:
        return {"error": f"caso '{caso_id}' no encontrado", "meta": meta}

    idioma = (idioma or "").strip().lower() or idioma_de(caso.get("partner"))
    c = componer(caso, idioma=idioma, nota=nota, caso_id=caso_id)
    devuelto, motivo = ya_devuelto(caso_id)

    return {
        "caso_id": caso_id,
        "partner": caso.get("partner"),
        "estado": caso.get("estado"),
        "idiomas": list(IDIOMAS),
        # Los enlaces sí van acá: es la pantalla del analista, no el correo.
        "adjuntos": adjuntos_de(caso_id, con_enlace=True),
        "ya_devuelto": devuelto,
        "motivo_devuelto": motivo,
        "nota_enlaces": ("Los enlaces son temporales y no piden autenticación: bajá los "
                         "archivos y adjuntalos vos. No los pegues en el correo."),
        **c,
    }


def marcar_devuelto(caso_id, quien="", nota="", medio="correo_manual", idioma=""):
    """Registra la devolución. No manda nada: la manda la persona.

    Se guarda **qué** se devolvió —archivos, ítems entregados y pendientes— y
    no sólo que se devolvió: es lo que hace auditable el cierre del caso, y es
    lo que el espejo analítico lleva a Redshift.
    """
    quien = str(quien or "").strip()
    if not quien:
        return {"registrado": False,
                "error": "quien es requerido: la devolución la firma una persona"}

    caso, meta = _buscar_caso(caso_id)
    if caso is None:
        return {"registrado": False, "error": f"caso '{caso_id}' no encontrado"}

    devuelto, motivo = ya_devuelto(caso_id)
    if devuelto:
        return {"registrado": False, "error": f"doble devolución bloqueada: {motivo}",
                "bloqueado": True}

    idioma = (idioma or "").strip().lower() or idioma_de(caso.get("partner"))
    c = componer(caso, idioma=idioma, nota=nota, caso_id=caso_id)

    detalle = {
        "medio": medio,
        "para": c["para"],
        "asunto": c["asunto"],
        "idioma": idioma,
        "referencia": c["referencia"],
        "archivos": c["archivos"],
        "entregados": c["entregados"],
        "pendientes": c["pendientes"],
        "parcial": bool(c["pendientes"]),
        "nota": str(nota or "")[:1000],
        "thread_id": (c.get("en_respuesta_a") or {}).get("thread_id", ""),
    }
    try:
        ev = casos.registrar(caso_id, "devuelto", quien=quien, detalle=detalle)
    except Exception as e:
        return {"registrado": False, "error": f"no pude anotar la acción: {str(e)[:200]}"}

    # Rastro propio, además de la acción: la acción dice que se devolvió, esto
    # guarda el texto exacto que se mandó. Si mañana el partner discute qué se
    # respondió, la acción no alcanza.
    try:
        deposito.poner("devoluciones", deposito.clave_segura(f"{caso_id}|{ev['cuando']}"), {
            "caso_id": caso_id, "quien": quien, "cuando": ev["cuando"],
            "texto": c["texto"], **detalle,
        })
    except Exception as e:
        print(f"[relevo] devolución registrada pero no pude guardar el texto: {e}")

    return {"registrado": True, "caso_id": caso_id, "accion": ev,
            "parcial": detalle["parcial"], "archivos": c["archivos"]}
