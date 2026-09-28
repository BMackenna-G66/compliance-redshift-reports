# -*- coding: utf-8 -*-
"""El informe de gestión de casos, dibujado para correo.

TERCER DIBUJO DE LOS MISMOS NÚMEROS. `informe_casos` calcula, `informe_pdf`
dibuja el PDF y esto dibuja el correo. Los tres comparten la cuenta a
propósito: dos definiciones de «caso gestionado» terminan en un PDF y un
correo que dicen cosas distintas del mismo día, y nadie sabe cuál creer.

POR QUÉ EL HTML ES ASÍ DE FEO. Gmail y Outlook tiran las hojas de estilo y
las clases, y no entienden flexbox ni grid. Todo va en `<table>` anidadas con
estilos en línea y la fuente repetida en cada celda. No es descuido: es la
única forma de que se vea igual en los tres clientes donde se va a abrir.

LO QUE ESTE INFORME NO MIDE, y está escrito en el encabezado del correo
porque es donde hace falta: mide actividad registrada en la herramienta, no
desempeño. Un caso difícil y uno trivial cuentan lo mismo, el que toma los
casos que nadie quiere sale peor, y lo que se trabaja por fuera —una llamada,
un Slack— no existe acá.
"""
from __future__ import annotations

import datetime as dt

import informe_casos as cuenta

# ── Paleta ───────────────────────────────────────────────────────────────
NAVY = "#131F44"
NAVY2 = "#1C2E65"
AZUL = "#0F48C7"
VERDE = "#01A876"
VERDE_CLARO = "#01D196"
AMBAR = "#D97706"
ROJO = "#DC2626"
GRIS = "#BFBFBF"
BORDE = "#e2e8f0"

F = "font-family:Arial,Helvetica,sans-serif;"

# Semáforo por antigüedad. Los cortes son los de la spec.
SEMAFORO = (
    (6, "#C3FFEE", "#007a5a"),
    (13, "#FFEED9", "#9F5900"),
    (29, "#FFEBEE", "#c62828"),
)
SEMAFORO_VENCIDO = ("#b71c1c", "#fff")

# Los tramos del pivot. El `30d+` NO estaba en el informe original —los casos
# de más de 30 días no caían en ninguna columna y desaparecían de la tabla,
# que es justo lo que un informe de gestión tiene que mostrar.
TRAMOS = (
    ("<3d", 0, 3),
    ("3-7d", 3, 7),
    ("7-14d", 7, 14),
    ("14-30d", 14, 30),
    ("30d+", 30, 10 ** 6),
)


def esc(v) -> str:
    """Todo valor dinámico pasa por acá. Un título de caso trae el nombre y el
    id de un cliente, y un `&` sin escapar rompe el correo en silencio."""
    if v is None or v == "":
        return "—"
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _num(v, cero_es_raya=True):
    """Los ceros se muestran como `—` salvo en los totales.

    Una tabla llena de ceros esconde el número que importa; una con rayas deja
    ver dónde hay algo."""
    if v in (None, ""):
        return "—"
    if cero_es_raya and v == 0:
        return "—"
    return v


# ── Piezas ───────────────────────────────────────────────────────────────

def seccion(titulo: str) -> str:
    return ('<tr><td style="padding:22px 24px 10px;">'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="background:{NAVY};border-radius:8px;">'
            f'<tr><td style="padding:11px 18px;{F}">'
            f'<span style="font-size:13px;font-weight:700;color:#fff;{F}">'
            f'{esc(titulo)}</span></td></tr></table></td></tr>')


def fila(html: str) -> str:
    return f'<tr><td style="padding:0 24px 18px;">{html}</td></tr>'


def carta(titulo: str, contenido: str, boton_html: str = "") -> str:
    t = (f'<div style="font-size:10px;font-weight:700;color:{AZUL};'
         f'text-transform:uppercase;letter-spacing:.5px;border-left:3px solid {AZUL};'
         f'padding-left:8px;{F}">{esc(titulo)}</div>')
    if boton_html:
        cabecera = ('<table width="100%" cellpadding="0" cellspacing="0" border="0"'
                    ' style="margin-bottom:10px;"><tr>'
                    f'<td valign="middle">{t}</td>'
                    f'<td align="right" valign="middle">{boton_html}</td></tr></table>')
    else:
        cabecera = t.replace("padding-left:8px;", "padding-left:8px;margin-bottom:10px;")
    return ('<table width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="border:1px solid {BORDE};border-radius:8px;background:#fff;">'
            f'<tr><td style="padding:13px 14px;">{cabecera}{contenido}</td></tr></table>')


def dos_columnas(izq: str, der: str) -> str:
    return ('<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td width="49%" valign="top">{izq}</td><td width="2%"></td>'
            f'<td width="49%" valign="top">{der}</td></tr></table>')


def boton(url: str, texto: str) -> str:
    return (f'<a href="{url}" target="_blank" style="display:inline-block;'
            'padding:5px 13px;background:#2d3748;color:#fff;border-radius:6px;'
            f'font-size:11px;font-weight:600;text-decoration:none;{F}">'
            f'{esc(texto)} &#8594;</a>')


def th(t: str, align: str = "left") -> str:
    return (f'<th style="padding:8px 10px;text-align:{align};font-size:10px;'
            f'color:#fff;font-weight:600;background:{NAVY2};white-space:nowrap;{F}">'
            f'{esc(t)}</th>')


def td(v, align: str = "left", par: bool = False, extra: str = "") -> str:
    fondo = "#f7fafc" if par else "#fff"
    return (f'<td style="padding:7px 10px;text-align:{align};font-size:11px;'
            f'color:{NAVY};background:{fondo};border-bottom:1px solid {BORDE};'
            f'{extra}{F}">{esc(v)}</td>')


def td_html(html: str, align: str = "left", par: bool = False) -> str:
    """Igual que `td`, pero el contenido ya viene armado y escapado.

    Lo usan las celdas con una dirección de correo: ahí adentro va un `<a>`
    propio para que el cliente no lo pinte de azul con subrayado."""
    fondo = "#f7fafc" if par else "#fff"
    return (f'<td style="padding:7px 10px;text-align:{align};font-size:11px;'
            f'background:{fondo};border-bottom:1px solid {BORDE};{F}">{html}</td>')


def td_persona(correo, par: bool = False) -> str:
    return td_html(correo_texto(correo, NAVY), "left", par)


def td_total(v, align: str = "left") -> str:
    return (f'<td style="padding:7px 10px;text-align:{align};font-size:11px;'
            f'color:{NAVY};font-weight:700;background:#edf2f7;'
            f'border-top:2px solid #CBD5E0;{F}">{esc(v)}</td>')


def tabla(cabeza: str, cuerpo: str) -> str:
    return ('<table width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="border-collapse:collapse;border:1px solid {BORDE};">'
            f'<thead>{cabeza}</thead><tbody>{cuerpo}</tbody></table>')


def vacio(texto: str) -> str:
    return (f'<p style="color:{GRIS};font-size:11px;padding:6px 0;'
            f'font-style:italic;{F}">{esc(texto)}</p>')


def nombre_de(correo: str) -> str:
    """«francia.villalobos@global66.com» → «Francia Villalobos».

    El correo entero en negrita blanca ocupa media fila y no se lee. El nombre
    arriba y la dirección chiquita abajo dicen lo mismo y se barren de un
    vistazo."""
    c = str(correo or "").strip()
    if "@" not in c:
        return c or "—"
    return " ".join(p.capitalize() for p in c.split("@")[0].replace("_", ".").split(".") if p)


def correo_texto(correo: str, color: str, extra: str = "") -> str:
    """La dirección, envuelta en un enlace con el color que le corresponde.

    NO ES DECORACIÓN. Gmail y Outlook detectan las direcciones sueltas y las
    convierten en enlaces con SU estilo: azul y subrayado. Sobre el navy de la
    fila eso queda azul sobre azul y no se lee — que es exactamente cómo se
    veía este informe en la casilla.

    Envolverlo uno mismo en un `<a>` con el color puesto evita que el cliente
    lo vuelva a enlazar, y de paso el clic escribe a la persona, que es lo que
    uno quiere hacer con ese dato.
    """
    c = str(correo or "").strip()
    if "@" not in c:
        return f'<span style="color:{color};{extra}{F}">{esc(c or "—")}</span>'
    return (f'<a href="mailto:{esc(c)}" style="color:{color};text-decoration:none;'
            f'{extra}{F}">{esc(c)}</a>')


def badge_edad(dias) -> str:
    """El T-N con su color. Es lo que deja barrer la tabla sin leerla."""
    n = int(dias or 0)
    fondo, color = SEMAFORO_VENCIDO
    for tope, bg, c in SEMAFORO:
        if n <= tope:
            fondo, color = bg, c
            break
    return ('<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
            f'font-size:9px;font-weight:700;background:{fondo};color:{color};{F}">'
            f'T-{n}</span>')


# ── La matriz de KPIs ────────────────────────────────────────────────────

def _celda_kpi(valor, color: str) -> str:
    vacia = valor is None
    return (f'<td style="padding:14px 8px;text-align:center;background:#fff;'
            f'border-left:1px solid {BORDE};{F}">'
            f'<div style="font-size:26px;font-weight:700;'
            f'color:{GRIS if vacia else color};line-height:1.05;{F}">'
            f'{esc("—" if vacia else valor)}</div></td>')


def si_mayor_a_cero(alerta: str):
    return lambda v: alerta if (v or 0) > 0 else NAVY


def fijo(hex_: str):
    return lambda v: hex_


COLUMNAS_KPI = (
    ("Casos", "total", fijo(NAVY)),
    ("Abiertos", "abiertos", fijo(AZUL)),
    ("Cerrados", "cerrados", fijo(VERDE)),
    ("Sin tocar", "sin_tocar", si_mayor_a_cero(AMBAR)),
    ("Vencidos", "vencidos", si_mayor_a_cero(ROJO)),
)


def matriz_kpi(filas: list, columnas: tuple = None) -> str:
    """filas: [(etiqueta, indicadores)]. Una por persona, más el total.

    `columnas` se pasa porque los dos informes miden cosas distintas con la
    misma tabla: casos o alertas. Por omisión, las de casos."""
    columnas = columnas or COLUMNAS_KPI
    cabeza = (f'<tr style="background:{NAVY};">'
              f'<th style="padding:10px 8px;text-align:left;font-size:10px;color:#fff;'
              f'font-weight:600;text-transform:uppercase;letter-spacing:.6px;{F}">'
              '&nbsp;</th>')
    for etiqueta, _, _ in columnas:
        cabeza += (f'<th style="padding:10px 8px;text-align:center;font-size:10px;'
                   f'color:#fff;font-weight:600;text-transform:uppercase;'
                   f'letter-spacing:.6px;{F}">{esc(etiqueta)}</th>')
    cabeza += "</tr>"

    cuerpo = ""
    for i, (etiqueta, datos) in enumerate(filas):
        borde = f' style="border-bottom:1px solid {BORDE};"' if i < len(filas) - 1 else ""
        # El nombre arriba y la dirección chiquita abajo. El correo entero en
        # negrita ocupaba media fila, y el cliente además lo pintaba de azul
        # sobre el navy: ilegible.
        if "@" in str(etiqueta):
            titulo = (f'<div style="font-size:12px;font-weight:700;color:#fff;'
                      f'{F}">{esc(nombre_de(etiqueta))}</div>'
                      '<div style="font-size:9px;margin-top:2px;'
                      f'{F}">'
                      + correo_texto(etiqueta, "rgba(255,255,255,0.55)")
                      + '</div>')
        else:
            titulo = (f'<div style="font-size:12px;font-weight:700;color:#fff;'
                      f'letter-spacing:.6px;{F}">{esc(etiqueta)}</div>')
        cuerpo += (f"<tr{borde}>"
                   f'<td style="padding:12px 14px;background:{NAVY2};{F}">'
                   f'{titulo}</td>')
        for _, clave, color in columnas:
            v = datos.get(clave)
            cuerpo += _celda_kpi(v, color(v))
        cuerpo += "</tr>"

    return ('<table width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="border-collapse:collapse;border:1px solid {BORDE};'
            'border-radius:8px;overflow:hidden;">'
            f'<thead>{cabeza}</thead><tbody>{cuerpo}</tbody></table>')


# ── El pivot por antigüedad ──────────────────────────────────────────────

def _tramo(dias) -> str:
    d = dias or 0
    for nombre, desde, hasta in TRAMOS:
        if desde <= d < hasta:
            return nombre
    return TRAMOS[-1][0]


def pivot(pares: list, etiqueta: str, vacio_texto: str,
          persona: bool = True) -> str:
    """El reparto por antigüedad de una lista de `(clave, días)`.

    Genérico porque lo usan dos informes con dimensiones distintas —casos por
    persona, alertas por persona y por regla— y la tabla es la misma. Lo que
    cambia es cómo se dibuja la primera columna: un correo se envuelve en un
    `<a>` para que el cliente no lo pinte de azul, un nombre de regla no.
    """
    if not pares:
        return vacio(vacio_texto)

    nombres = [t[0] for t in TRAMOS]
    mapa: dict = {}
    for k, dias in pares:
        if k not in mapa:
            mapa[k] = dict.fromkeys(nombres, 0)
        mapa[k][_tramo(None if dias is None else int(dias))] += 1

    totales = dict.fromkeys(nombres, 0)
    total_general = 0
    cuerpo = ""
    # De mayor a menor: la fila que importa queda arriba.
    orden = sorted(mapa.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    for i, (k, valores) in enumerate(orden):
        par = i % 2 == 1
        suma = sum(valores.values())
        total_general += suma
        celdas = ""
        for n in nombres:
            totales[n] += valores[n]
            celdas += td(_num(valores[n]), "right", par)
        primera = td_persona(k, par) if persona else td(k, "left", par)
        cuerpo += f"<tr>{primera}{celdas}{td(suma, 'right', par)}</tr>"

    cuerpo += ("<tr>" + td_total("Total")
               + "".join(td_total(totales[n], "right") for n in nombres)
               + td_total(total_general, "right") + "</tr>")
    cabeza = ("<tr>" + th(etiqueta)
              + "".join(th(n, "right") for n in nombres)
              + th("Total", "right") + "</tr>")
    return tabla(cabeza, cuerpo)


def pivot_antiguedad(abiertos: list, ahora=None) -> str:
    """Los casos abiertos de cada persona, repartidos por antigüedad.

    Por persona y no por equipo: el equipo promedia y esconde justo lo que hay
    que ver. Un equipo con 33 abiertos «repartidos» puede ser una persona con
    15 y cuatro con cuatro, y el informe existe para que eso se note.

    Los sin asignar quedan en su propia fila y no se reparten: no son de
    nadie, y meterlos dentro de alguien haría desaparecer la alerta.
    """
    pares = [(cuenta.normalizar_analista(c.get("assigned_to")),
              cuenta.dias_abierto(c, ahora)) for c in abiertos]
    return pivot(pares, "Persona",
                 "No hay casos abiertos en el recorte del informe.")


# ── Las cartas ───────────────────────────────────────────────────────────

def _carta_tiempos(datos: dict) -> str:
    """Cierre y antigüedad, por equipo.

    El promedio va con la mediana al lado y no en su lugar: con un caso de 61
    días entre 16, el promedio dice una cosa y la mediana otra, y mostrar uno
    solo deja pensar que todos tardan lo mismo.
    """
    filas = ""
    for i, e in enumerate(datos["equipos"]):
        par = i % 2 == 1
        filas += ("<tr>" + td(e["equipo"], "left", par)
                  + td(_num(e["cierre_promedio"]), "right", par)
                  + td(_num(e["cierre_mediana"]), "right", par)
                  + td(_num(e["cierre_max"]), "right", par) + "</tr>")
    g = datos["total_general"]
    filas += ("<tr>" + td_total("Total")
              + td_total(_num(g["cierre_promedio"]), "right")
              + td_total(_num(g["cierre_mediana"]), "right")
              + td_total(_num(g["cierre_max"]), "right") + "</tr>")
    cabeza = ("<tr>" + th("Equipo") + th("Promedio", "right")
              + th("Mediana", "right") + th("Máximo", "right") + "</tr>")
    return carta("Días hasta el cierre", tabla(cabeza, filas))


def _carta_antiguedad(datos: dict) -> str:
    filas = ""
    for i, e in enumerate(datos["equipos"]):
        par = i % 2 == 1
        filas += ("<tr>" + td(e["equipo"], "left", par)
                  + td(_num(e["abiertos"]), "right", par)
                  + td(_num(e["edad_promedio_abiertos"]), "right", par)
                  + td(_num(e["mas_viejo_abierto"]), "right", par) + "</tr>")
    g = datos["total_general"]
    filas += ("<tr>" + td_total("Total")
              + td_total(g["abiertos"], "right")
              + td_total(_num(g["edad_promedio_abiertos"]), "right")
              + td_total(_num(g["mas_viejo_abierto"]), "right") + "</tr>")
    cabeza = ("<tr>" + th("Equipo") + th("Abiertos", "right")
              + th("Edad prom.", "right") + th("Más viejo", "right") + "</tr>")
    return carta("Antigüedad de los abiertos (días)", tabla(cabeza, filas))


def _carta_analistas(datos: dict, url: str) -> str:
    filas = ""
    for i, a in enumerate(datos["analistas"]):
        par = i % 2 == 1
        filas += ("<tr>" + td_persona(a["analista"], par)
                  + td(a["equipo"], "left", par)
                  + td(a["total"], "right", par)
                  + td(_num(a["abiertos"]), "right", par)
                  + td(_num(a["cerrados"]), "right", par)
                  + td(_num(a["sin_tocar"]), "right", par,
                       f"color:{AMBAR};font-weight:700;" if a["sin_tocar"] else "")
                  + td(_num(a["vencidos"]), "right", par,
                       f"color:{ROJO};font-weight:700;" if a["vencidos"] else "")
                  + td(_num(a["cierre_promedio"]), "right", par) + "</tr>")
    if not filas:
        return carta("Por analista", vacio("Sin casos en el recorte."))
    cabeza = ("<tr>" + th("Analista") + th("Equipo")
              + "".join(th(t, "right") for t in
                        ("Casos", "Abiertos", "Cerrados", "Sin tocar",
                         "Vencidos", "Cierre prom."))
              + "</tr>")
    return carta("Por analista", tabla(cabeza, filas),
                 boton(url, "Ver los casos"))


def _carta_viejos(abiertos: list, url: str, ahora=None, tope: int = 25) -> str:
    """Los abiertos hace más de tres días, del más viejo al menos.

    Se corta en 25 y se dice cuántos quedaron afuera. Un correo con 300 filas
    no lo lee nadie y además revienta el límite de tamaño de Gmail; el listado
    completo está en la pantalla, que es donde se puede trabajar.
    """
    viejos = []
    for c in abiertos:
        d = cuenta.dias_abierto(c, ahora)
        if d is not None and d > 3:
            viejos.append((int(d), c))
    if not viejos:
        return carta("Abiertos hace más de 3 días",
                     vacio("Ninguno. Todos los casos abiertos tienen 3 días o menos."))
    viejos.sort(key=lambda x: -x[0])

    filas = ""
    for i, (dias, c) in enumerate(viejos[:tope]):
        par = i % 2 == 1
        fondo = "#f7fafc" if par else "#fff"
        filas += (
            "<tr>"
            f'<td style="padding:7px 10px;font-size:11px;background:{fondo};'
            f'border-bottom:1px solid {BORDE};{F}">{badge_edad(dias)}</td>'
            + td(c.get("title") or c.get("case_id"), "left", par)
            + td_persona(cuenta.normalizar_analista(c.get("assigned_to")), par)
            + td(str(c.get("created_at") or "")[:10], "left", par)
            + td((c.get("sla_etiqueta") or c.get("sla_estado") or "—"), "left", par,
                 f"color:{ROJO};font-weight:700;"
                 if c.get("sla_estado") == "vencido" else "")
            + "</tr>")
    cabeza = ("<tr>" + th("Antigüedad") + th("Caso") + th("Analista")
              + th("Creado") + th("Plazo") + "</tr>")
    contenido = tabla(cabeza, filas)
    if len(viejos) > tope:
        contenido += (f'<p style="font-size:10px;color:{GRIS};margin:8px 0 0;{F}">'
                      f'Se muestran los {tope} más viejos de {len(viejos)}. '
                      'El resto está en la pantalla de casos.</p>')
    return carta(f"Abiertos hace más de 3 días ({len(viejos)})", contenido,
                 boton(url, "Detalle casos"))


# ── El correo ────────────────────────────────────────────────────────────

def _periodo(filtro: dict) -> str:
    desde, hasta = filtro.get("desde") or "", filtro.get("hasta") or ""
    if desde and hasta:
        return f"casos creados entre {desde} y {hasta}"
    if desde:
        return f"casos creados desde {desde}"
    if hasta:
        return f"casos creados hasta {hasta}"
    return "todos los casos vigentes"


def asunto(datos: dict, hoy: str) -> str:
    return f"Reporte de gestión de casos · {hoy} · Global66"


def construir(datos: dict, url_casos: str, ahora=None, generado_por: str = "") -> str:
    """El HTML completo del correo."""
    ahora = ahora or dt.datetime.utcnow()
    hoy = ahora.strftime("%d-%m-%Y")
    g = datos["total_general"]
    abiertos = [c for c in datos["casos"] if not cuenta.esta_cerrado(c)]

    # La matriz va POR PERSONA, con el correo como identificador. El equipo
    # promedia y esconde: un equipo con 33 abiertos puede ser una persona con
    # 15 y cuatro con cuatro, y eso es justo lo que hay que ver. El total
    # general queda arriba de todo para no perder la referencia.
    filas_kpi = [("Todos", g)] + [(a["analista"], a) for a in datos["analistas"]]

    cuerpo = (
        # ── Resumen ──
        '<tr><td style="padding:8px 24px 16px;">' + matriz_kpi(filas_kpi) + "</td></tr>"

        # ── Sección 1: los abiertos ──
        + seccion("Casos abiertos")
        + fila(carta("Por persona y antigüedad", pivot_antiguedad(abiertos, ahora)))
        + fila(dos_columnas(_carta_tiempos(datos), _carta_antiguedad(datos)))
        + fila(_carta_viejos(abiertos, url_casos, ahora))

        # ── Sección 2: la carga ──
        + seccion("Carga por analista")
        + fila(_carta_analistas(datos, url_casos))
    )

    nota = ("Mide actividad registrada en la herramienta, no desempeño. "
            "Un caso difícil y uno trivial cuentan lo mismo.")
    # También acá: suelta, el cliente la pinta de azul y subrayada en medio
    # de una línea gris de 10px.
    pie_extra = (" &middot; pedido por " + correo_texto(generado_por, GRIS)
                 if generado_por else "")

    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">'
        '<title>Reporte de gestión de casos</title></head>'
        '<body style="margin:0;padding:0;background:#f0f2f5;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background:#f0f2f5;"><tr><td align="center" style="padding:24px 16px;">'
        '<table width="860" cellpadding="0" cellspacing="0" border="0"'
        ' style="background:#fff;border-radius:8px;border:1px solid #dde1e7;'
        'max-width:100%;">'

        # HEADER
        f'<tr><td style="background:{NAVY};border-radius:8px 8px 0 0;'
        'padding:22px 28px 20px;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="middle"><div style="font-size:18px;font-weight:800;color:#fff;{F}">'
        'Global66</div>'
        '<div style="font-size:9px;font-weight:600;color:rgba(255,255,255,0.5);'
        f'text-transform:uppercase;letter-spacing:1px;margin-top:2px;{F}">'
        'Compliance &middot; Gestión de casos</div></td>'
        '<td align="right" valign="middle"><div style="display:inline-block;'
        'background:rgba(1,209,150,0.15);border:1px solid rgba(1,209,150,0.4);'
        f'border-radius:20px;padding:4px 14px;font-size:10px;color:{VERDE_CLARO};'
        f'font-weight:600;{F}">Generado &middot; {esc(hoy)}</div></td>'
        '</tr></table>'
        '<div style="margin-top:14px;padding-top:12px;'
        'border-top:1px solid rgba(255,255,255,0.12);">'
        f'<div style="font-size:17px;font-weight:800;color:#fff;{F}">'
        'Reporte de gestión de casos</div>'
        '<div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:3px;'
        f'{F}">{esc(_periodo(datos["filtro"]))} &middot; {esc(nota)}</div>'
        '</div></td></tr>'

        # RESUMEN
        '<tr><td style="padding:20px 24px 4px;">'
        f'<div style="font-size:9px;font-weight:700;color:{GRIS};'
        f'text-transform:uppercase;letter-spacing:1px;{F}">Resumen</div></td></tr>'
        + cuerpo +

        # FOOTER
        f'<tr><td style="padding:18px 24px;text-align:center;'
        f'border-top:1px solid {BORDE};">'
        f'<p style="font-size:10px;color:{GRIS};margin:0;{F}">'
        'Generado automáticamente &middot; '
        f'<span style="color:{AZUL};font-weight:700;{F}">Global66 Compliance</span>'
        f'{pie_extra}</p></td></tr>'
        '</table></td></tr></table></body></html>')


def texto_plano(datos: dict, hoy: str) -> str:
    """El cuerpo alternativo. No es decorativo: un cliente que no muestra HTML
    tiene que poder leer los números, no un correo en blanco."""
    g = datos["total_general"]
    lineas = [
        f"Reporte de gestión de casos · {hoy} · Global66",
        _periodo(datos["filtro"]).capitalize(),
        "",
        f"Casos: {g['total']} · abiertos: {g['abiertos']} · cerrados: {g['cerrados']}",
        f"Sin tocar: {g['sin_tocar']} · vencidos: {g['vencidos']}",
        "",
        "Por equipo:",
    ]
    for e in datos["equipos"]:
        lineas.append(f"  {e['equipo']}: {e['total']} casos "
                      f"({e['abiertos']} abiertos, {e['vencidos']} vencidos)")
    lineas += ["", "Mide actividad registrada en la herramienta, no desempeño."]
    return "\n".join(lineas)


# ═════════════════════════════════════════════════════════════════════════
# EL INFORME DE ALERTAS
# ─────────────────────────────────────────────────────────────────────────
# Mismo dibujo, otra pregunta. Reusa todas las piezas de arriba porque los
# dos correos tienen que verse como el mismo producto: si cada informe trae
# su propia tabla y su propio azul, en tres meses hay cinco diseños.
# ═════════════════════════════════════════════════════════════════════════

import informe_alertas as cuenta_alertas  # noqa: E402

COLUMNAS_KPI_ALERTAS = (
    ("Alertas", "total", fijo(NAVY)),
    ("Con caso", "con_caso", fijo(VERDE)),
    ("Sin caso", "sin_caso", si_mayor_a_cero(AMBAR)),
    ("Prioridad alta", "alta", fijo(AZUL)),
    ("Sin caso +30d", "sin_caso_viejas", si_mayor_a_cero(ROJO)),
)


def _carta_reglas(datos: dict) -> str:
    """Qué regla acumula. Una regla que dispara mucho y termina en pocos casos
    es una regla mal calibrada, no un equipo lento — y eso sólo se ve poniendo
    las dos columnas juntas."""
    filas = ""
    for i, r in enumerate(datos["reglas"]):
        par = i % 2 == 1
        filas += ("<tr>" + td(r["regla"], "left", par)
                  + td(r["total"], "right", par)
                  + td(_num(r["con_caso"]), "right", par)
                  + td(_num(r["sin_caso"]), "right", par,
                       f"color:{AMBAR};font-weight:700;" if r["sin_caso"] else "")
                  + td(f'{r["pct_con_caso"]}%', "right", par)
                  + td(_num(r["mas_vieja"]), "right", par) + "</tr>")
    g = datos["total_general"]
    filas += ("<tr>" + td_total("Total") + td_total(g["total"], "right")
              + td_total(_num(g["con_caso"]), "right")
              + td_total(_num(g["sin_caso"]), "right")
              + td_total(f'{g["pct_con_caso"]}%', "right")
              + td_total(_num(g["mas_vieja"]), "right") + "</tr>")
    cabeza = ("<tr>" + th("Regla")
              + "".join(th(t, "right") for t in
                        ("Alertas", "Con caso", "Sin caso", "% a caso",
                         "Más vieja"))
              + "</tr>")
    return carta("Por regla", tabla(cabeza, filas))


def _carta_sin_caso(alertas: list, url: str, ahora=None, tope: int = 25) -> str:
    """Las que nadie convirtió en caso, de la más vieja a la menos.

    Es lo accionable del informe: una alerta sin caso y con semanas encima es
    trabajo que no empezó, no trabajo atrasado."""
    viejas = []
    for a in alertas:
        if cuenta_alertas.tiene_caso(a):
            continue
        d = cuenta_alertas.dias_abierta(a, ahora)
        if d is not None:
            viejas.append((int(d), a))
    if not viejas:
        return carta("Sin caso", vacio("Todas las alertas terminaron en un caso."))
    viejas.sort(key=lambda x: -x[0])

    filas = ""
    for i, (dias, a) in enumerate(viejas[:tope]):
        par = i % 2 == 1
        fondo = "#f7fafc" if par else "#fff"
        filas += ("<tr>"
                  f'<td style="padding:7px 10px;font-size:11px;background:{fondo};'
                  f'border-bottom:1px solid {BORDE};{F}">{badge_edad(dias)}</td>'
                  + td(a.get("report_name") or "(sin regla)", "left", par)
                  + td(a.get("entity_value") or "—", "left", par)
                  + td_persona(cuenta_alertas.normalizar_analista(
                      a.get("assigned_to")), par)
                  + td((a.get("priority") or "—"), "left", par)
                  + "</tr>")
    cabeza = ("<tr>" + th("Antigüedad") + th("Regla") + th("Entidad")
              + th("Asignada a") + th("Prioridad") + "</tr>")
    contenido = tabla(cabeza, filas)
    if len(viejas) > tope:
        contenido += (f'<p style="font-size:10px;color:{GRIS};margin:8px 0 0;{F}">'
                      f'Se muestran las {tope} más viejas de {len(viejas)}. '
                      'El resto está en la bandeja.</p>')
    return carta(f"Sin caso ({len(viejas)})", contenido, boton(url, "Ver la bandeja"))


def _nota_de_lo_que_no_se_mide(datos: dict) -> str:
    """Lo que la herramienta NO registra, dicho en el correo.

    Sin esto, quien lo lee supone que «gestionadas» es cero porque nadie
    gestionó, cuando en realidad es cero porque nadie lo marca. Un cero que
    significa «no lo medimos» es peor que una columna ausente."""
    n = len(datos["alertas"])
    return carta("Lo que este informe no mide",
                 f'<p style="font-size:11px;color:{NAVY};margin:0;line-height:1.6;{F}">'
                 'No hay columnas de <strong>gestionadas</strong>, '
                 '<strong>cerradas</strong> ni <strong>cumplimiento de SLA</strong> '
                 'porque la herramienta todavía no registra eso: '
                 f'<strong>{n}</strong> de {n} alertas están en estado '
                 '<span style="font-family:Menlo,Consolas,monospace;">active</span> '
                 'y ninguna tiene marca de '
                 'revisión. Mostrarlas en cero se leería como «nadie gestionó '
                 'nada», que no es lo que dice el dato. Lo que sí se mide es '
                 'quién la tiene, hace cuánto entró y si terminó en un caso.'
                 '</p>')


def asunto_alertas(hoy: str) -> str:
    return f"Reporte de alertas · {hoy} · Global66"


def construir_alertas(datos: dict, url_bandeja: str, ahora=None,
                      generado_por: str = "") -> str:
    ahora = ahora or dt.datetime.utcnow()
    hoy = ahora.strftime("%d-%m-%Y")
    g = datos["total_general"]
    alertas = datos["alertas"]

    filas_kpi = [("Todas", g)] + [(p["persona"], p) for p in datos["personas"]]

    pares_persona = [(cuenta_alertas.normalizar_analista(a.get("assigned_to")),
                      cuenta_alertas.dias_abierta(a, ahora)) for a in alertas]
    pares_regla = [(a.get("report_name") or "(sin regla)",
                    cuenta_alertas.dias_abierta(a, ahora)) for a in alertas]

    cuerpo = (
        '<tr><td style="padding:8px 24px 16px;">'
        + matriz_kpi(filas_kpi, COLUMNAS_KPI_ALERTAS) + "</td></tr>"

        + seccion("Alertas abiertas")
        + fila(carta("Por persona y antigüedad",
                     pivot(pares_persona, "Persona",
                           "No hay alertas en el recorte del informe.")))
        + fila(carta("Por regla y antigüedad",
                     pivot(pares_regla, "Regla",
                           "No hay alertas en el recorte del informe.",
                           persona=False)))
        + fila(_carta_reglas(datos))

        + seccion("Lo que falta convertir en caso")
        + fila(_carta_sin_caso(alertas, url_bandeja, ahora))
        + fila(_nota_de_lo_que_no_se_mide(datos))
    )

    nota = ("Mide lo que la herramienta registra: quién tiene cada alerta, "
            "hace cuánto entró y si terminó en un caso.")
    pie_extra = (" &middot; pedido por " + correo_texto(generado_por, GRIS)
                 if generado_por else "")

    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">'
        '<title>Reporte de alertas</title></head>'
        '<body style="margin:0;padding:0;background:#f0f2f5;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background:#f0f2f5;"><tr><td align="center" style="padding:24px 16px;">'
        '<table width="860" cellpadding="0" cellspacing="0" border="0"'
        ' style="background:#fff;border-radius:8px;border:1px solid #dde1e7;'
        'max-width:100%;">'
        f'<tr><td style="background:{NAVY};border-radius:8px 8px 0 0;'
        'padding:22px 28px 20px;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="middle"><div style="font-size:18px;font-weight:800;color:#fff;{F}">'
        'Global66</div>'
        '<div style="font-size:9px;font-weight:600;color:rgba(255,255,255,0.5);'
        f'text-transform:uppercase;letter-spacing:1px;margin-top:2px;{F}">'
        'Compliance &middot; Alertas</div></td>'
        '<td align="right" valign="middle"><div style="display:inline-block;'
        'background:rgba(1,209,150,0.15);border:1px solid rgba(1,209,150,0.4);'
        f'border-radius:20px;padding:4px 14px;font-size:10px;color:{VERDE_CLARO};'
        f'font-weight:600;{F}">Generado &middot; {esc(hoy)}</div></td>'
        '</tr></table>'
        '<div style="margin-top:14px;padding-top:12px;'
        'border-top:1px solid rgba(255,255,255,0.12);">'
        f'<div style="font-size:17px;font-weight:800;color:#fff;{F}">'
        'Reporte de alertas</div>'
        '<div style="font-size:10px;color:rgba(255,255,255,0.5);margin-top:3px;'
        f'{F}">{esc(_periodo_alertas(datos["filtro"]))} &middot; {esc(nota)}</div>'
        '</div></td></tr>'
        '<tr><td style="padding:20px 24px 4px;">'
        f'<div style="font-size:9px;font-weight:700;color:{GRIS};'
        f'text-transform:uppercase;letter-spacing:1px;{F}">Resumen</div></td></tr>'
        + cuerpo +
        f'<tr><td style="padding:18px 24px;text-align:center;'
        f'border-top:1px solid {BORDE};">'
        f'<p style="font-size:10px;color:{GRIS};margin:0;{F}">'
        'Generado automáticamente &middot; '
        f'<span style="color:{AZUL};font-weight:700;{F}">Global66 Compliance</span>'
        f'{pie_extra}</p></td></tr>'
        '</table></td></tr></table></body></html>')


def _periodo_alertas(filtro: dict) -> str:
    desde, hasta = filtro.get("desde") or "", filtro.get("hasta") or ""
    if desde and hasta:
        return f"alertas creadas entre {desde} y {hasta}"
    if desde:
        return f"alertas creadas desde {desde}"
    if hasta:
        return f"alertas creadas hasta {hasta}"
    return "todas las alertas abiertas"


def texto_plano_alertas(datos: dict, hoy: str) -> str:
    g = datos["total_general"]
    lineas = [
        f"Reporte de alertas · {hoy} · Global66", "",
        f"Alertas: {g['total']} · con caso: {g['con_caso']} "
        f"({g['pct_con_caso']}%) · sin caso: {g['sin_caso']}",
        f"Sin caso hace más de 30 días: {g['sin_caso_viejas']}", "",
        "Por persona:",
    ]
    for p in datos["personas"]:
        lineas.append(f"  {p['persona']}: {p['total']} alertas "
                      f"({p['sin_caso']} sin caso)")
    lineas += ["", "No se miden gestionadas ni SLA: la herramienta todavía no "
               "registra la revisión de una alerta."]
    return "\n".join(lineas)
