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
# La del partner es OTRA a propósito. La de cliente trae pie de consumo —
# "¿Tienes dudas?", el centro de ayuda, WhatsApp, Play Store, App Store—, que a
# un analista de un banco corresponsal no le corresponde y se lee como si le
# hubiéramos mandado una campaña de marketing por error.
RUTA_PARTNER = Path(__file__).resolve().parent / "plantillas" / "partner.html"
MARCA_CUERPO = "CUERPO"

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


# El hueco de la plantilla vive DENTRO de un <p> y un <span>:
#
#   <p style="..."><span style="...">TEXTO LIBRE<br>TEXTO LIBRE<br>...</span></p>
#
# Así que lo que se inyecta tiene que ser **contenido en línea**. Un <p>, una
# <table> o un <ol> ahí adentro son HTML inválido: el navegador cierra el
# párrafo por su cuenta y el bloque se escapa del contenedor con estilo,
# perdiendo tipografía y color. En Outlook —y la plantilla trae
# `mso-line-height-alt`, o sea que está hecha para Outlook— se rompe peor.
#
# Es el mismo contrato que respeta `_render_email_template` de WatchTower, que
# inyecta sólo texto escapado con <br>. Por eso los correos AML se ven bien.
SALTO = "<br>"
DOBLE = "<br><br>"


def _e(v):
    return _html.escape(str(v or "").strip())


def bloque(datos=None, catalogo=None, plazo="", nota="", empresa=False):
    """El medio del correo, **en línea**, listo para entrar en la plantilla.

    `datos` es [(etiqueta, valor)] y `catalogo` la lista de documentos ya
    traducida. Todo se escapa: los valores vienen de un correo de un tercero
    y de nuestra propia base, y ninguno de los dos es HTML de confianza.
    """
    partes = ["Estamos realizando una revisión de rutina sobre una de "
              f"{'sus' if empresa else 'tus'} operaciones y necesitamos algunos "
              "antecedentes para poder completarla."]

    if datos:
        filas = SALTO.join(f"<strong>{_e(k)}:</strong> {_e(v)}" for k, v in datos)
        partes.append("Se trata de esta operación:" + SALTO + filas)

    if catalogo:
        items = SALTO.join(f"{i}. {_e(x)}" for i, x in enumerate(catalogo, 1))
        partes.append("Para poder continuar necesitamos que nos "
                      f"{'envíen' if empresa else 'envíes'}:" + SALTO + items)

    partes.append(
        f"{'Les' if empresa else 'Te'} pedimos responder "
        f"<strong>{_e(plazo)}</strong>." if plazo else
        f"{'Les' if empresa else 'Te'} pedimos responder a la brevedad.")

    if nota:
        partes.append(_e(nota))

    partes.append(
        f"{'Pueden' if empresa else 'Puedes'} responder directamente a este correo "
        "adjuntando los documentos. <strong>"
        f"{'Mantengan' if empresa else 'Mantén'} el asunto tal como está</strong>: "
        "es lo que nos permite asociar la respuesta a la solicitud.")
    return DOBLE.join(partes)


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


# ── la del partner ───────────────────────────────────────────────────────
_cache_partner = None


def cargar_partner():
    global _cache_partner
    if _cache_partner is None:
        _cache_partner = RUTA_PARTNER.read_text(encoding="utf-8")
    return _cache_partner


def componer_partner(texto_plano):
    """El texto de la devolución, dentro de la plantilla B2B.

    Entra texto plano y sale HTML: lo que compone `devolucion.componer()` son
    líneas, no marcado. Se escapa todo —el nombre del cliente, los nombres de
    archivo y lo que escribió el cliente vienen de afuera— y se convierten los
    saltos en <br>, que es el mismo contrato que respeta la plantilla de
    cliente: contenido en línea, nada de bloques.

    Devuelve None si la plantilla no está: el texto plano sigue sirviendo y
    quedarse sin poder devolver es peor que devolver sin marca.
    """
    try:
        base = cargar_partner()
    except Exception as e:
        print(f"[relevo/plantilla] no pude leer {RUTA_PARTNER}: {e}")
        return None
    if MARCA_CUERPO not in base:
        print("[relevo/plantilla] el marcador CUERPO no está en partner.html")
        return None
    cuerpo = _html.escape(str(texto_plano or "")).replace("\n", "<br>")
    return base.replace(MARCA_CUERPO, cuerpo)
