"""El formato corporativo: los correos de Relevo salen con la marca de siempre.

Hasta ahora el módulo armaba su propio HTML —una tabla con una barra naranja—
que se parecía al de WatchTower sin serlo. Un cliente que recibe un correo de
Compliance por una alerta AML y otro por un RFI tiene que ver la misma
Global66; dos diseños distintos que dicen ser nosotros es exactamente lo que
un cliente no puede distinguir de un phishing.

Se usa la plantilla oficial de **texto libre** (`email_texto_libre.html`), que
es la que aporta cabecera, tipografía, saludo, cierre, firma y pie. Relevo
sólo compone **el medio**: los datos de la operación, la lista de documentos
y el plazo.

**Se copia el archivo, no se importa `_render_email_template`** (§1: réplica
adaptada, no reuso). El original vive en `lambda/templates/` y lo consume el
ciclo AML; si mañana alguien lo cambia para una campaña de alertas, Relevo no
se entera y eso es deseable. La copia vive en `plantillas/base.html`.

**Los dos marcadores del original se respetan tal cual** porque son los que
la plantilla trae de Salesforce:

    {!Account.first_name__c}                    → el nombre del cliente
    TEXTO LIBRE<br>TEXTO LIBRE<br>TEXTO LIBRE   → el bloque que llenamos

**El trato de usted sobrevive.** La plantilla saluda "Hola {nombre}," y cierra
"Quedamos atentos a tu respuesta" — tuteo. A una razón social eso se lee mal,
y el 9% de los clientes lo son. Para esos casos se reemplazan esas dos frases
después de renderizar; el resto del diseño queda intacto.
"""
import html as _html
import re
from pathlib import Path

RUTA = Path(__file__).resolve().parent / "plantillas" / "base.html"

MARCA_NOMBRE = "{!Account.first_name__c}"
MARCA_TEXTO = "TEXTO LIBRE<br>TEXTO LIBRE<br>TEXTO LIBRE"

# Las frases en tuteo que trae la plantilla, y su versión formal. Se listan
# acá y no se buscan por heurística: son dos, están escritas, y adivinarlas
# con una regex sobre el HTML sería frágil y silencioso al fallar.
FORMAL = [
    ("Hola {nombre},", "Estimados de {nombre}:"),
    ("Quedamos atentos a tu respuesta.", "Quedamos atentos a su respuesta."),
    ("¿Tienes dudas?", "¿Tienen dudas?"),
]

_cache = None


def cargar():
    """El HTML de la plantilla. Se cachea: es el mismo en toda la invocación."""
    global _cache
    if _cache is None:
        _cache = RUTA.read_text(encoding="utf-8")
    return _cache


def disponible():
    """False si el archivo no viajó en el paquete. Lo usa el compositor para
    caer al HTML propio en vez de romper el envío por un problema de empaque."""
    try:
        return bool(cargar().strip())
    except Exception as e:
        print(f"[relevo/plantilla] no pude leer {RUTA}: {e}")
        return False


def _parrafo(texto):
    return f'<p style="margin:0 0 12px">{texto}</p>'


def bloque(datos=None, catalogo=None, plazo="", nota="", empresa=False):
    """El medio del correo, en HTML, listo para entrar en la plantilla.

    `datos` es [(etiqueta, valor)] y `catalogo` la lista de documentos ya
    traducida. Todo se escapa: los valores vienen de un correo de un tercero
    y de nuestra propia base, y ninguno de los dos es HTML de confianza.
    """
    e = lambda v: _html.escape(str(v or "").strip())  # noqa: E731
    partes = [_parrafo(
        "Estamos realizando una revisión de rutina sobre una de "
        f"{'sus' if empresa else 'tus'} operaciones y necesitamos algunos "
        "antecedentes para poder completarla.")]

    if datos:
        filas = "".join(
            f'<tr><td style="padding:4px 12px 4px 0;color:#666">{e(k)}</td>'
            f'<td style="padding:4px 0"><strong>{e(v)}</strong></td></tr>'
            for k, v in datos)
        partes.append(_parrafo("Se trata de esta operación:"))
        partes.append(f'<table style="border-collapse:collapse;margin:0 0 12px">{filas}</table>')

    if catalogo:
        items = "".join(f"<li style='margin:0 0 6px'>{e(x)}</li>" for x in catalogo)
        partes.append(_parrafo("Para poder continuar necesitamos que nos "
                               f"{'envíen' if empresa else 'envíes'}:"))
        partes.append(f'<ol style="margin:0 0 12px;padding-left:22px">{items}</ol>')

    partes.append(_parrafo(
        f"{'Les' if empresa else 'Te'} pedimos responder "
        f"<strong>{e(plazo)}</strong>." if plazo else
        f"{'Les' if empresa else 'Te'} pedimos responder a la brevedad."))

    if nota:
        partes.append(_parrafo(e(nota)))

    partes.append(_parrafo(
        f"{'Pueden' if empresa else 'Puedes'} responder directamente a este correo "
        f"adjuntando los documentos. <strong>"
        f"{'Mantengan' if empresa else 'Mantén'} el asunto tal como está</strong>: "
        "es lo que nos permite asociar la respuesta a la solicitud."))
    return "".join(partes)


def componer(nombre, contenido_html, empresa=False):
    """Mete el nombre y el bloque en la plantilla oficial.

    Devuelve el HTML completo, o None si la plantilla no está disponible —
    el compositor decide qué hacer con eso, no se rompe acá.
    """
    if not disponible():
        return None
    html = cargar()
    seguro = _html.escape(str(nombre or "").strip()) or "cliente"

    if empresa:
        # Antes de reemplazar el nombre: las frases formales lo llevan dentro.
        for tuteo, formal in FORMAL:
            html = html.replace(tuteo.format(nombre=MARCA_NOMBRE),
                                formal.format(nombre=MARCA_NOMBRE))

    html = html.replace(MARCA_NOMBRE, seguro)
    if MARCA_TEXTO in html:
        html = html.replace(MARCA_TEXTO, contenido_html)
    else:
        # Si la plantilla cambió y el marcador ya no está, es preferible
        # enterarse que mandar un correo con "TEXTO LIBRE" adentro.
        print("[relevo/plantilla] el marcador de texto libre no está en base.html")
        return None
    return html


def quedan_marcadores(html):
    """True si sobró algún marcador sin reemplazar. Lo mira el compositor:
    un correo que le llega al cliente diciendo "TEXTO LIBRE" o
    "{!Account.first_name__c}" es peor que uno feo."""
    if not html:
        return False
    return bool(re.search(r"\{!\w+[.\w]*\}|TEXTO LIBRE", html))
