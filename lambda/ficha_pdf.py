"""La ficha del cliente como PDF, con la identidad de Global66.

Sale de lo mismo que la ficha en pantalla (`ficha_cliente.py` +
`get_client_dossier`): este módulo no consulta nada, sólo maqueta. Esa
separación es deliberada — el PDF que se adjunta a un expediente y lo que el
analista vio en pantalla tienen que ser el mismo dato, y la única forma de
garantizarlo es que salgan de la misma consulta.

**Por qué un PDF y no el Excel que ya existe.** El export de casos genera una
planilla, que sirve para trabajar los datos. Esto es otra cosa: un documento
que se adjunta a un expediente, se manda a un regulador o se archiva. Tiene
que verse igual en cualquier máquina, no ser editable por accidente y llevar
la marca de la casa.

**Procedencia en el documento mismo.** Cada página dice cuándo se generó,
quién lo pidió y que es de uso interno. Un resumen de un cliente sin fecha ni
autor es inútil en una auditoría: nadie puede decir si refleja lo que se sabía
en ese momento o algo posterior.

**Datos personales.** El PDF lleva nombre, documento, correo y volumen de un
cliente. Se guarda en S3 con enlace corto y las corridas siguientes borran los
viejos, igual que los zips de adjuntos: dejarlos acumulándose es duplicar
datos sensibles sin motivo.
"""
import io
import os
import re
import time

# Paleta de Global66, sacada de las plantillas de correo corporativas
# (`templates/email_general_b2c.html`) para que el PDF y los correos que ve el
# mismo cliente se vean de la misma empresa.
AZUL = "#1433b4"
OSCURO = "#0a1433"
LILA = "#5d65ac"
GRIS = "#64748b"
GRIS_CLARO = "#e2e8f0"
ROJO = "#b91c1c"
VERDE = "#15803d"

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "global66.png")

# Sin punto a propósito: la extensión la agrega `nombre_archivo`, así que las
# partes no lo necesitan — y dejarlo pasar permitía que un `..` sobreviviera
# entero al saneado.
_SEGURO = re.compile(r"[^A-Za-z0-9_-]+")


def nombre_archivo(ficha):
    """'ficha-4246021-Berenice-Brizuela.pdf'. El nombre tiene que decir de
    quién es: el analista baja cinco y no puede tener que abrirlos para saber
    cuál es cuál.

    **Los dos pedazos se sanean, no sólo el nombre.** Esto termina dentro de un
    header `Content-Disposition: attachment; filename="..."`, así que una
    comilla o una barra en cualquiera de los dos deja de ser cosmética. El
    `entity_id` viene del caso y hoy es siempre numérico, pero se pone a mano
    en el alta y nada garantiza que siga siéndolo.
    """
    partes = []
    for crudo, tope in ((ficha.get("entity_id") or "cliente", 40),
                        (ficha.get("nombre") or "", 40)):
        limpio = _SEGURO.sub("-", str(crudo)).strip("-")[:tope].strip("-")
        if limpio:
            partes.append(limpio)
    return "ficha-" + "-".join(partes or ["cliente"]) + ".pdf"


def _fmt_usd(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    # Formato local: punto para miles, coma para decimales.
    return "USD " + f"{n:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _n(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _miles(v):
    return f"{_n(v):,}".replace(",", ".")


def construir(ficha, pedido_por="", ahora=""):
    """Los bytes del PDF. `ficha` es la respuesta de `get_client_dossier`."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,
                                    NextPageTemplate,
                                    PageTemplate, Paragraph, Spacer, Table,
                                    TableStyle)

    ficha = ficha or {}
    buf = io.BytesIO()
    ancho, alto = A4
    margen = 18 * mm

    ss = getSampleStyleSheet()
    P = ParagraphStyle("p", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.5,
                       leading=11.5, textColor=colors.HexColor(OSCURO))
    P_MINI = ParagraphStyle("mini", parent=P, fontSize=7, leading=9,
                            textColor=colors.HexColor(GRIS))
    H1 = ParagraphStyle("h1", parent=P, fontName="Helvetica-Bold", fontSize=17,
                        leading=21, textColor=colors.HexColor(OSCURO), spaceAfter=1)
    # `keepWithNext`: sin esto un título de sección cae al pie de una página y
    # su tabla arranca en la siguiente, que es la forma más fácil de que
    # alguien lea una tabla creyendo que es de otra sección.
    H2 = ParagraphStyle("h2", parent=P, fontName="Helvetica-Bold", fontSize=10,
                        leading=13, textColor=colors.HexColor(AZUL),
                        spaceBefore=11, spaceAfter=4, keepWithNext=1)
    TH = ParagraphStyle("th", parent=P, fontName="Helvetica-Bold", fontSize=8,
                        textColor=colors.white)
    # Un encabezado a la izquierda sobre una columna de números a la derecha
    # obliga a buscar a qué corresponde cada cifra.
    TH_R = ParagraphStyle("thr", parent=TH, alignment=TA_RIGHT)
    TD_R = ParagraphStyle("tdr", parent=P, alignment=TA_RIGHT)

    # El banner es 1800x483; se escala al ancho útil manteniendo la proporción
    # para que el logo no salga deformado. Se calcula una sola vez porque de
    # esto depende dónde empieza el texto de la portada.
    ancho_util = ancho - 2 * margen
    alto_logo = ancho_util * 483 / 1800
    # Dónde termina el banner, medido desde arriba: franja azul + logo + aire.
    fin_banner = 6 * mm + alto_logo + 5 * mm

    def _fondo(canvas, doc):
        """Cabecera y pie en cada página. La procedencia va en el pie y no en
        la portada a propósito: si alguien imprime o fotocopia una hoja suelta,
        esa hoja sigue diciendo de cuándo es y quién la pidió."""
        canvas.saveState()
        # Franja superior
        canvas.setFillColor(colors.HexColor(AZUL))
        canvas.rect(0, alto - 6 * mm, ancho, 6 * mm, stroke=0, fill=1)
        if doc.page == 1 and os.path.exists(LOGO):
            canvas.drawImage(LOGO, margen, alto - fin_banner + 2 * mm,
                             width=ancho_util, height=alto_logo, mask="auto")
        # Pie
        canvas.setFillColor(colors.HexColor(GRIS))
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(margen, 10 * mm,
                          f"Documento de uso interno · Generado por WatchTower el {ahora}"
                          + (f" a pedido de {pedido_por}" if pedido_por else ""))
        canvas.drawRightString(ancho - margen, 10 * mm, f"Página {doc.page}")
        canvas.setStrokeColor(colors.HexColor(GRIS_CLARO))
        canvas.line(margen, 13 * mm, ancho - margen, 13 * mm)
        canvas.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=margen, rightMargin=margen,
                          topMargin=margen, bottomMargin=20 * mm,
                          title=f"Ficha del cliente — {ficha.get('nombre') or ''}",
                          author="Global66 · Equipo Cumplimiento")
    # Dos plantillas: la primera deja lugar para el banner, las siguientes
    # arrancan arriba de todo. Hay que pedir explícitamente el cambio con un
    # `NextPageTemplate` en la historia — sin eso reportlab usa la primera
    # plantilla para SIEMPRE, y las páginas 2 en adelante salen con el hueco
    # del banner reservado pero vacío, dejando filas huérfanas flotando a
    # media página. Visto y corregido.
    PIE = 20 * mm
    doc.addPageTemplates([
        PageTemplate(id="portada", onPage=_fondo, frames=[Frame(
            margen, PIE, ancho_util, alto - fin_banner - PIE, id="f1")]),
        PageTemplate(id="resto", onPage=_fondo, frames=[Frame(
            margen, PIE, ancho_util, alto - 6 * mm - 8 * mm - PIE, id="f2")]),
    ])

    def tabla(datos, anchos, cabecera=True, zebra=True):
        t = Table(datos, colWidths=anchos, repeatRows=1 if cabecera else 0)
        est = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor(GRIS_CLARO)),
        ]
        if cabecera:
            est.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(AZUL)))
        if zebra:
            for i in range(1 if cabecera else 0, len(datos)):
                if i % 2 == (1 if cabecera else 0):
                    est.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))
        t.setStyle(TableStyle(est))
        return t

    def seccion(titulo, cuerpo, nota=None):
        """Título + nota + tabla como un bloque indivisible.

        `keepWithNext` no alcanza: encadena sólo con el flowable inmediatamente
        siguiente, así que en la secuencia título → nota → tabla el título se
        quedaba pegado a la nota al pie de una página y la tabla arrancaba en
        la siguiente, sin encabezado de sección. En un documento de auditoría
        eso es una tabla que alguien puede leer creyendo que es de otra cosa.
        Si el bloque no entra en una página, reportlab lo parte igual — que es
        lo correcto para una tabla larga.
        """
        piezas = [Paragraph(titulo, H2)]
        if nota:
            piezas.append(Paragraph(nota, P_MINI))
            piezas.append(Spacer(1, 3))
        piezas.append(cuerpo)
        return KeepTogether(piezas)

    util = ancho_util
    # A partir de la página 2 manda la plantilla sin banner (ver arriba).
    el = [NextPageTemplate("resto")]

    # ── identificación ──
    el.append(Paragraph("Ficha del cliente", H1))
    el.append(Paragraph(_txt(ficha.get("nombre") or "(sin nombre)"),
                        ParagraphStyle("n", parent=P, fontSize=12, leading=15,
                                       fontName="Helvetica-Bold",
                                       textColor=colors.HexColor(AZUL))))
    etiqueta = "company_id" if ficha.get("kind") == "b2b" else "customer_id"
    el.append(Paragraph(
        f"{etiqueta} {_txt(ficha.get('entity_id',''))} &nbsp;·&nbsp; "
        f"Actividad: {_txt(ficha.get('periodo') or 'sin transacciones')}", P_MINI))
    el.append(Spacer(1, 7))

    # ── avisos ──
    for a in (ficha.get("avisos") or []):
        color = ROJO if a.get("tono") == "alto" else "#92400e"
        fondo = "#fef2f2" if a.get("tono") == "alto" else "#fffbeb"
        t = Table([[Paragraph(f"<b>{'⚠' if a.get('tono')=='alto' else '•'}</b> "
                              + _txt(a.get("texto", "")),
                              ParagraphStyle("av", parent=P,
                                             textColor=colors.HexColor(color)))]],
                  colWidths=[util])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(fondo)),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(color)),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]))
        el.append(t)
        el.append(Spacer(1, 4))

    # ── productos ──
    filas = [[Paragraph("Producto", TH), Paragraph("Detalle", TH),
              Paragraph("Evidencia", TH)]]
    for p in (ficha.get("productos") or []):
        tiene = bool(p.get("tiene"))
        filas.append([
            Paragraph(("<b>SÍ</b>  " if tiene else "no  ") + _txt(p.get("producto", "")),
                      ParagraphStyle("pr", parent=P,
                                     textColor=colors.HexColor(VERDE if tiene else GRIS))),
            Paragraph(_txt(p.get("detalle") or "—"), P),
            Paragraph(_txt(p.get("evidencia") or ""), P_MINI),
        ])
    el.append(seccion("Productos", tabla(filas, [util * 0.24, util * 0.40, util * 0.36])))

    # ── resumen transaccional ──
    aviso_tx = ficha.get("aviso_transaccional")
    r = ficha.get("resumen") or {}
    if not r:
        el.append(seccion("Resumen transaccional",
                          Paragraph(_txt(aviso_tx or "Sin datos transaccionales."),
                                    P_MINI)))
    else:
        metricas = [
            ("Operaciones efectivas", _miles(r.get("n_efectivas"))),
            ("Volumen movido", _fmt_usd(r.get("total_usd"))),
            ("Ticket promedio", _fmt_usd(r.get("ticket_promedio_usd"))),
            ("Ticket mayor", _fmt_usd(r.get("ticket_mayor_usd"))),
            ("Países de destino", _miles(r.get("paises_destino"))),
            ("Beneficiarios distintos", _miles(r.get("beneficiarios"))),
        ]
        # Devueltas y retenidas sólo si las hay: un cero ocupando lugar entrena
        # a no mirar la casilla.
        if _n(r.get("n_devueltas")):
            metricas.append(("Devueltas", f"{_miles(r.get('n_devueltas'))} · "
                                          f"{_fmt_usd(r.get('devuelto_usd'))}"))
        if _n(r.get("n_retenidas")):
            metricas.append(("Retenidas por compliance", _miles(r.get("n_retenidas"))))

        # En dos columnas de pares etiqueta/valor, para que entre en el ancho.
        filas, fila = [], []
        for etq, val in metricas:
            fila += [Paragraph(etq, P_MINI), Paragraph(f"<b>{val}</b>", TD_R)]
            if len(fila) == 4:
                filas.append(fila)
                fila = []
        if fila:
            filas.append(fila + [""] * (4 - len(fila)))
        el.append(seccion(
            "Resumen transaccional",
            tabla(filas, [util * 0.27, util * 0.23] * 2, cabecera=False, zebra=False),
            nota=(_txt(aviso_tx) + "<br/>" if aviso_tx else "")
                 + "Sólo operaciones efectivas (exitosas o enviadas)."))

    # ── destinos ──
    paises = ficha.get("por_pais") or []
    if paises:
        filas = [[Paragraph("País", TH), Paragraph("Operaciones", TH_R),
                  Paragraph("Monto", TH_R)]]
        for p in paises:
            filas.append([Paragraph(_txt(p.get("pais") or "—"), P),
                          Paragraph(_miles(p.get("n")), TD_R),
                          Paragraph(_fmt_usd(p.get("usd")), TD_R)])
        el.append(seccion("Destinos", tabla(filas, [util * 0.5, util * 0.2, util * 0.3])))

    # ── mes a mes ──
    meses = ficha.get("por_mes") or []
    if meses:
        filas = [[Paragraph("Mes", TH), Paragraph("Operaciones", TH_R),
                  Paragraph("Monto", TH_R), Paragraph("De las cuales, cripto", TH_R)]]
        for m in meses:
            filas.append([Paragraph(_txt(m.get("mes") or ""), P),
                          Paragraph(_miles(m.get("n")), TD_R),
                          Paragraph(_fmt_usd(m.get("usd")), TD_R),
                          Paragraph(_miles(m.get("n_cripto")) if _n(m.get("n_cripto"))
                                    else "—", TD_R)])
        el.append(seccion("Actividad mes a mes",
                          tabla(filas, [util * 0.22, util * 0.2, util * 0.3, util * 0.28])))

    # ── casos ──
    casos = ficha.get("casos") or []
    if not casos:
        el.append(seccion("Casos (0)", Paragraph("Sin casos registrados.", P_MINI)))
    else:
        filas = [[Paragraph("Caso", TH), Paragraph("Estado", TH),
                  Paragraph("Asignado a", TH), Paragraph("Creado", TH)]]
        for c in casos:
            filas.append([Paragraph(_txt(c.get("title") or c.get("case_id", "")), P),
                          Paragraph(_txt(c.get("status") or "—"), P),
                          Paragraph(_txt(c.get("assigned_to") or "sin asignar"), P_MINI),
                          Paragraph(_txt(c.get("created_at") or "")[:10], P_MINI)])
        el.append(seccion(f"Casos ({len(casos)})",
                          tabla(filas, [util * 0.44, util * 0.13, util * 0.29, util * 0.14])))

    # ── documentación ──
    docs = ficha.get("documentos") or {}
    ped, rec = docs.get("solicitados") or [], docs.get("recibidos") or []
    _titulo_doc = f"Documentación ({len(ped)} pedida · {len(rec)} recibida)"
    _nota_doc = (
        "Las dos columnas van por separado a propósito: el nombre del archivo que "
        "manda el cliente no se parece al ítem que se le pidió, y emparejarlos "
        "automáticamente inventaría una correspondencia que nadie verificó.")
    filas = [[Paragraph("Pedida", TH), Paragraph("Cuándo", TH),
              Paragraph("Recibida", TH), Paragraph("Cuándo", TH)]]
    for i in range(max(len(ped), len(rec))):
        a = ped[i] if i < len(ped) else {}
        b = rec[i] if i < len(rec) else {}
        filas.append([
            Paragraph(_txt(a.get("documento") or ""), P),
            Paragraph(_txt(a.get("cuando") or "")[:10]
                      + ("" if a.get("salio", True) else " (no salió)"), P_MINI),
            Paragraph(_txt(b.get("filename") or ""), P),
            Paragraph(((_txt(b.get("cuando") or "")[:10]) +
                       (" · del cliente" if b.get("origen") == "email_reply"
                        else (" · subido" if b else ""))), P_MINI),
        ])
    if len(filas) == 1:
        el.append(seccion(_titulo_doc,
                          Paragraph("Sin documentación registrada.", P_MINI)))
    else:
        el.append(seccion(
            _titulo_doc,
            tabla(filas, [util * 0.3, util * 0.18, util * 0.32, util * 0.20]),
            nota=_nota_doc))

    # ── correos ──
    correos = ficha.get("correos") or []
    tot = ficha.get("totales") or {}
    _titulo_mail = (f"Historial de correos ({_n(tot.get('enviados'))} enviados · "
                    f"{_n(tot.get('recibidos'))} recibidos)")
    if not correos:
        el.append(seccion(_titulo_mail, Paragraph("Sin correos registrados.", P_MINI)))
    else:
        filas = [[Paragraph("Fecha", TH), Paragraph("Dir.", TH),
                  Paragraph("Contraparte", TH), Paragraph("Asunto / contenido", TH)]]
        for m in correos:
            enviado = m.get("direccion") == "enviado"
            fallo = enviado and not m.get("salio")
            cuerpo = str(m.get("cuerpo") or "").strip().replace("\n", " ")
            if len(cuerpo) > 220:
                cuerpo = cuerpo[:220] + "…"
            txt = _txt(m.get("asunto") or "")
            if fallo:
                # El error de SMTP se escapa sí o sí: Gmail devuelve cosas como
                # `550 <alguien@dominio> not found`, y esos signos entran al
                # marcado de Paragraph y tumban el PDF entero.
                txt = (f"<font color='{ROJO}'><b>NO SE ENVIÓ</b> "
                       f"({_txt(m.get('error') or 'sin detalle')})</font><br/>" + txt)
            if cuerpo:
                txt += (("<br/>" if txt else "")
                        + f"<font color='{GRIS}'>{_txt(cuerpo)}</font>")
            adj = m.get("documentos") or []
            if adj:
                txt += (f"<br/><font color='{LILA}'>"
                        + _txt(("Pedido: " if enviado else "Adjunto: ")
                                   + ", ".join(str(x) for x in adj)) + "</font>")
            filas.append([
                Paragraph(_txt(m.get("cuando") or "")[:16], P_MINI),
                Paragraph("enviado" if enviado else "recibido",
                          ParagraphStyle("d", parent=P_MINI,
                                         textColor=colors.HexColor(GRIS if enviado else AZUL))),
                Paragraph(_txt((m.get("para") if enviado else m.get("de")) or ""), P_MINI),
                Paragraph(txt or "—", P),
            ])
        el.append(seccion(
            _titulo_mail,
            tabla(filas, [util * 0.13, util * 0.11, util * 0.24, util * 0.52])))

    # ── perfil KYC ──
    perfil = ficha.get("perfil") or {}
    if perfil:
        campos = [(k.replace("_", " "), v) for k, v in perfil.items()
                  if v not in (None, "") and str(v).lower() not in ("none", "null")]
        filas, fila = [], []
        for k, v in campos:
            fila += [Paragraph(_txt(k), P_MINI),
                     Paragraph(f"<b>{_txt(str(v))}</b>", P)]
            if len(fila) == 4:
                filas.append(fila)
                fila = []
        if fila:
            filas.append(fila + [""] * (4 - len(fila)))
        if filas:
            el.append(seccion(
                "Perfil KYC / compliance",
                tabla(filas, [util * 0.22, util * 0.28] * 2,
                      cabecera=False, zebra=False),
                nota=f"Fuente: {_txt(ficha.get('perfil_origen') or '—')}"))

    doc.build(el)
    return buf.getvalue()


def _txt(t):
    """`Paragraph` interpreta marcado propio: un `&` o un `<` del nombre de un
    archivo del cliente rompería la construcción entera del PDF."""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
