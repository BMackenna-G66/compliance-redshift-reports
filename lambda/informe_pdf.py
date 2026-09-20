# -*- coding: utf-8 -*-
"""El informe de gestión de casos, en PDF.

Mismo lenguaje visual que la ficha del cliente (`ficha_pdf.py`): franja azul,
banner en la portada, tablas con zebra, procedencia en el pie de cada página.
Los números los calcula `informe_casos.py`; acá sólo se dibujan.

La estructura sigue lo que se pidió: primero el total, después un bloque por
equipo, y dentro de cada equipo el detalle por analista.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re

AZUL = "#1433b4"
OSCURO = "#0a1433"
LILA = "#5d65ac"
GRIS = "#64748b"
GRIS_CLARO = "#e2e8f0"
ROJO = "#b91c1c"
AMBAR = "#b45309"
VERDE = "#15803d"

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "global66.png")

_SEGURO = re.compile(r"[^A-Za-z0-9_-]+")


def nombre_archivo(filtro) -> str:
    """El nombre del archivo que baja. Se sanea TODO lo que viene de afuera:
    esto termina en una cabecera `Content-Disposition`, y un salto de línea ahí
    permite inyectar cabeceras."""
    partes = ["informe_gestion"]
    for clave in ("desde", "hasta"):
        v = _SEGURO.sub("", str((filtro or {}).get(clave) or ""))[:10]
        if v:
            partes.append(v)
    quien = _SEGURO.sub("", str((filtro or {}).get("analista") or "").split("@")[0])[:24]
    if quien:
        partes.append(quien)
    return "_".join(partes)[:90] + ".pdf"


def _txt(v) -> str:
    """Todo lo que entra a un Paragraph pasa por acá: reportlab interpreta un
    subconjunto de HTML, así que un `&` o un `<` sin escapar rompe el PDF."""
    import html as _h
    return _h.escape(str(v if v is not None else ""))


def _num(v, sufijo=""):
    """Número en español: punto para miles, coma para decimales.

    El intercambio va por un carácter intermedio a propósito. Reemplazar coma
    por punto y después punto por coma en dos pasos deja 1.234,5 convertido en
    1,234,5: el segundo reemplazo pisa lo que hizo el primero.
    """
    if v is None:
        return "—"
    s = f"{v:,.1f}" if isinstance(v, float) else f"{v:,}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".") + sufijo


def _corto(email) -> str:
    """El nombre con el que se lee una tabla: `francia.villalobos`."""
    e = str(email or "")
    if "@" not in e:
        return e
    return e.split("@")[0].replace(".", " ").title()


def construir(datos, pedido_por="", ahora=""):
    """Devuelve los bytes del PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,
                                    NextPageTemplate, PageBreak, PageTemplate,
                                    Paragraph, Spacer, Table, TableStyle)

    ahora = ahora or dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    buf = io.BytesIO()
    ancho, alto = A4
    margen = 15 * mm

    ss = getSampleStyleSheet()
    P = ParagraphStyle("p", parent=ss["BodyText"], fontName="Helvetica", fontSize=8.5,
                       leading=11, textColor=colors.HexColor(OSCURO), spaceAfter=0)
    P_MINI = ParagraphStyle("mini", parent=P, fontSize=7, leading=9,
                            textColor=colors.HexColor(GRIS))
    H1 = ParagraphStyle("h1", parent=P, fontName="Helvetica-Bold", fontSize=17,
                        leading=21, textColor=colors.HexColor(AZUL), spaceAfter=2)
    H2 = ParagraphStyle("h2", parent=P, fontName="Helvetica-Bold", fontSize=10,
                        leading=13, textColor=colors.HexColor(AZUL), spaceBefore=9,
                        spaceAfter=4)
    H3 = ParagraphStyle("h3", parent=P, fontName="Helvetica-Bold", fontSize=8.5,
                        leading=11, textColor=colors.HexColor(LILA), spaceBefore=5,
                        spaceAfter=2)
    TH = ParagraphStyle("th", parent=P, fontName="Helvetica-Bold", fontSize=8,
                        leading=10, textColor=colors.white)
    TH_R = ParagraphStyle("thr", parent=TH, alignment=TA_RIGHT)
    TD_R = ParagraphStyle("tdr", parent=P, alignment=TA_RIGHT)
    TD_B = ParagraphStyle("tdb", parent=P, fontName="Helvetica-Bold")
    TD_BR = ParagraphStyle("tdbr", parent=TD_B, alignment=TA_RIGHT)

    ancho_util = ancho - 2 * margen
    alto_logo = ancho_util * 483 / 1800
    fin_banner = 6 * mm + alto_logo + 5 * mm

    def _fondo(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(AZUL))
        canvas.rect(0, alto - 6 * mm, ancho, 6 * mm, stroke=0, fill=1)
        if doc.page == 1 and os.path.exists(LOGO):
            canvas.drawImage(LOGO, margen, alto - fin_banner + 2 * mm,
                             width=ancho_util, height=alto_logo, mask="auto")
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
                          title="Informe de gestión de casos",
                          author="Global66 · Equipo Cumplimiento")
    PIE = 20 * mm
    doc.addPageTemplates([
        PageTemplate(id="portada", onPage=_fondo, frames=[Frame(
            margen, PIE, ancho_util, alto - fin_banner - PIE, id="f1")]),
        PageTemplate(id="resto", onPage=_fondo, frames=[Frame(
            margen, PIE, ancho_util, alto - 6 * mm - 8 * mm - PIE, id="f2")]),
    ])

    def tabla(datos_t, anchos, cabecera=True, zebra=True, total_abajo=False):
        t = Table(datos_t, colWidths=anchos, repeatRows=1 if cabecera else 0)
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
            for i in range(1 if cabecera else 0, len(datos_t)):
                if i % 2 == (1 if cabecera else 0):
                    est.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8fafc")))
        if total_abajo:
            est.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef1fb")))
            est.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor(AZUL)))
        t.setStyle(TableStyle(est))
        return t

    def seccion(titulo, cuerpo, nota=None):
        """Título + nota + tabla como un bloque indivisible: `keepWithNext` no
        encadena más allá del flowable siguiente, y el título terminaba al pie
        de una página con la tabla en la otra."""
        piezas = [Paragraph(titulo, H2)]
        if nota:
            piezas += [Paragraph(nota, P_MINI), Spacer(1, 3)]
        piezas.append(cuerpo)
        return KeepTogether(piezas)

    filtro = datos.get("filtro") or {}
    g = datos.get("total_general") or {}
    el = [NextPageTemplate("resto")]

    # ── portada ──
    el.append(Paragraph("Informe de gestión de casos", H1))
    recorte = []
    if filtro.get("desde") or filtro.get("hasta"):
        recorte.append(f"Casos creados entre {_txt(filtro.get('desde') or 'el inicio')} "
                       f"y {_txt(filtro.get('hasta') or 'hoy')}")
    else:
        recorte.append("Todos los casos, sin recorte de fechas")
    if filtro.get("analista"):
        recorte.append(f"Analista: {_txt(filtro['analista'])}")
    if filtro.get("equipo"):
        recorte.append(f"Equipo: {_txt(filtro['equipo'])}")
    el.append(Paragraph(" · ".join(recorte), P_MINI))
    el.append(Spacer(1, 10))

    # ── el resumen, en números grandes ──
    resumen = [[
        Paragraph("Casos", TH), Paragraph("Abiertos", TH_R), Paragraph("Cerrados", TH_R),
        Paragraph("Gestionados", TH_R), Paragraph("Sin tocar", TH_R),
        Paragraph("Vencidos", TH_R),
    ], [
        Paragraph(_num(g.get("total")), TD_B),
        Paragraph(_num(g.get("abiertos")), TD_BR),
        Paragraph(f"{_num(g.get('cerrados'))}  ({_num(g.get('pct_cerrados'))}%)", TD_BR),
        Paragraph(f"{_num(g.get('gestionados'))}  ({_num(g.get('pct_gestionados'))}%)", TD_BR),
        Paragraph(_num(g.get("sin_tocar")), TD_BR),
        Paragraph(_num(g.get("vencidos")), TD_BR),
    ]]
    u = ancho_util
    el.append(tabla(resumen, [u * .18, u * .15, u * .19, u * .2, u * .14, u * .14]))
    el.append(Spacer(1, 8))

    tiempos = [[
        Paragraph("Tiempo de cierre", TH), Paragraph("Promedio", TH_R),
        Paragraph("Mediana", TH_R), Paragraph("Máximo", TH_R),
        Paragraph("Antigüedad de lo abierto", TH_R), Paragraph("El más viejo", TH_R),
    ], [
        Paragraph("Días", P),
        Paragraph(_num(g.get("cierre_promedio")), TD_R),
        Paragraph(_num(g.get("cierre_mediana")), TD_R),
        Paragraph(_num(g.get("cierre_max")), TD_R),
        Paragraph(_num(g.get("edad_promedio_abiertos")), TD_R),
        Paragraph(_num(g.get("mas_viejo_abierto")), TD_R),
    ]]
    el.append(tabla(tiempos, [u * .2, u * .14, u * .13, u * .13, u * .25, u * .15]))
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        "<b>Cómo leer estos números.</b> «Gestionado» es un caso que salió de "
        "<i>abierto</i> o que tiene al menos una nota; estar asignado no cuenta, "
        "porque asignar es repartir y no gestionar. «Sin tocar» son los casos "
        "abiertos sin ninguna nota: hasta donde la herramienta sabe, nadie los "
        "trabajó. La mediana va al lado del promedio porque un caso muy largo "
        "arrastra el promedio y hace parecer que todos tardan lo mismo.", P_MINI))
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "<b>Para qué sirve y para qué no.</b> Esto mide actividad registrada en "
        "la herramienta, no desempeño. Un caso difícil y uno trivial cuentan "
        "igual, quien toma los casos que nadie quiere sale peor, y lo que se "
        "trabaja por fuera —una llamada, un mensaje— no aparece. Sirve para ver "
        "carga, encontrar casos abandonados y detectar desbalances; para evaluar "
        "a una persona hay que mirar los casos, no el promedio.", P_MINI))

    # ── por equipo ──
    def fila_ind(nombre, ind, estilo_nombre=None):
        return [
            Paragraph(_txt(nombre), estilo_nombre or P),
            Paragraph(_num(ind.get("total")), TD_R),
            Paragraph(_num(ind.get("abiertos")), TD_R),
            Paragraph(_num(ind.get("cerrados")), TD_R),
            Paragraph(_num(ind.get("pct_gestionados"), "%"), TD_R),
            Paragraph(_num(ind.get("sin_tocar")), TD_R),
            Paragraph(_num(ind.get("cierre_promedio")), TD_R),
            Paragraph(_num(ind.get("cierre_mediana")), TD_R),
            Paragraph(_num(ind.get("vencidos")), TD_R),
        ]

    ENC = [Paragraph("Equipo", TH), Paragraph("Casos", TH_R), Paragraph("Abiertos", TH_R),
           Paragraph("Cerrados", TH_R), Paragraph("Gest.", TH_R),
           Paragraph("Sin tocar", TH_R), Paragraph("Cierre prom.", TH_R),
           Paragraph("Mediana", TH_R), Paragraph("Vencidos", TH_R)]
    ANCHOS = [u * .24, u * .08, u * .1, u * .1, u * .09, u * .11, u * .12, u * .09, u * .1]

    equipos = datos.get("equipos") or []
    if equipos:
        filas = [ENC] + [fila_ind(e["equipo"], e, TD_B) for e in equipos]
        filas.append(fila_ind("Total", g, TD_B))
        # Sin salto de página: en la portada sobraba media hoja y el resumen
        # por equipo entra justo debajo de las notas.
        el.append(Spacer(1, 4))
        el.append(seccion(
            "Resumen por equipo", tabla(filas, ANCHOS, total_abajo=True),
            "«Cierre prom.» y «Mediana» están en días y sólo consideran casos ya "
            "cerrados; un equipo sin cierres muestra un guion."))

    # ── el detalle, equipo por equipo ──
    ENC_A = [Paragraph("Analista", TH)] + ENC[1:]
    for e in equipos:
        filas = [ENC_A] + [fila_ind(_corto(a["analista"]), a) for a in e["analistas"]]
        filas.append(fila_ind("Total del equipo", e, TD_B))
        nota = None
        if e["equipo"] == "(sin asignar)":
            nota = ("Casos que no son de nadie. No se reparten entre los equipos a "
                    "propósito: esconderlos adentro de uno haría desaparecer "
                    "justamente lo que hay que ver.")
        el.append(seccion(f"Equipo: {_txt(e['equipo'])}",
                          tabla(filas, ANCHOS, total_abajo=True), nota))

    # ── los casos sin tocar, con nombre y apellido ──
    sin_tocar = [c for c in (datos.get("casos") or [])
                 if (c.get("status") or "") == "open" and not int(c.get("note_count") or 0)]
    if sin_tocar:
        sin_tocar.sort(key=lambda c: c.get("created_at") or "")
        filas = [[Paragraph("Caso", TH), Paragraph("Cliente", TH),
                  Paragraph("Alerta", TH), Paragraph("Asignado a", TH),
                  Paragraph("Creado", TH), Paragraph("Días", TH_R)]]
        import informe_casos
        for c in sin_tocar[:60]:
            d = informe_casos.dias_abierto(c)
            filas.append([
                Paragraph(_txt((c.get("title") or "")[:38]), P),
                Paragraph(_txt(c.get("entity_name") or c.get("entity_id") or "—"), P),
                Paragraph(_txt((c.get("report_name") or "—").replace("_", " ")[:26]), P),
                Paragraph(_txt(_corto(informe_casos.normalizar_analista(
                    c.get("assigned_to"))).replace("(Sin Asignar)", "—")), P),
                Paragraph(_txt((c.get("created_at") or "")[:10]), P),
                Paragraph(_num(round(d, 1) if d is not None else None), TD_R),
            ])
        el.append(PageBreak())
        el.append(seccion(
            f"Casos abiertos sin ninguna nota ({len(sin_tocar)})",
            tabla(filas, [u * .26, u * .2, u * .2, u * .16, u * .11, u * .07]),
            ("Del más viejo al más nuevo. Son los que ningún registro muestra "
             "trabajados; es la lista para repartir o cerrar."
             + (f" Se listan los 60 más viejos de {len(sin_tocar)}."
                if len(sin_tocar) > 60 else ""))))

    doc.build(el)
    return buf.getvalue()
