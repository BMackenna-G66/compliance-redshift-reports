# -*- coding: utf-8 -*-
"""Las plantillas de correo, sobre la base corporativa de Global66.

Existe por un error concreto. La base traía los huecos como las palabras
sueltas CUERPO y BOTON, y esas mismas palabras aparecían en los comentarios
del HTML que explican para qué sirve cada hueco. `str.replace` no distingue:
reemplazó las dos, así que el cuerpo del correo entró dos veces y de paso
partió un comentario al medio, dejando texto de andamiaje a la vista del
cliente. El HTML seguía siendo válido y el correo seguía saliendo — nada
reventaba, sólo salía mal.

Lo que se chequea es lo que ese error rompió y nada más:

  * los huecos se rellenan una vez, no dos (el saludo aparece una sola vez);
  * los marcadores que busca el renderizador siguen existiendo;
  * nada del andamiaje —marcadores, comentarios, placeholders— queda visible;
  * la cláusula de respuesta está en todos los correos a cliente;
  * el botón del formulario aparece cuando el correo pide el formulario, y
    desaparece con él cuando el analista destilda esa categoría.
"""
import os
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# api_handler lee estas al importarse; son nombres de recursos que acá no se
# tocan, pero sin ellas el import falla antes de llegar a las plantillas.
for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_handler as A  # noqa: E402
from relevo import plantilla  # noqa: E402

CLAUSULA = ("Respóndenos este correo adjuntando tus documentos a la brevedad. "
            "Conserva el asunto tal como está, así podemos vincular tu respuesta "
            "y procesar tu caso sin demoras.")

# Lo que jamás puede llegar al cliente: huecos sin rellenar, marcadores del
# renderizador o restos de un comentario que se partió.
ANDAMIAJE = ("@@CUERPO@@", "@@BOTON@@", "@@PIE@@", "{!Account", "{{N}}",
             "TEXTO LIBRE", "<!--B:", "<!--/B-->", "-->", "<!--")


class _Visible(HTMLParser):
    """El texto que el cliente llega a ver.

    Los comentarios no se recogen a propósito: si un comentario quedó bien
    formado, su contenido no se ve, y si quedó partido, el pedazo suelto
    aparece como datos y lo caza `test_nada_de_andamiaje_a_la_vista`.
    """

    MUDOS = {"style", "script", "title", "head"}  # contenedores, no void

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.trozos, self.mudo = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.MUDOS:
            self.mudo += 1

    def handle_endtag(self, tag):
        if tag in self.MUDOS and self.mudo:
            self.mudo -= 1

    def handle_data(self, dato):
        if not self.mudo:
            self.trozos.append(dato)


def visible(html):
    p = _Visible()
    p.feed(html)
    p.close()
    return re.sub(r"\s+", " ", " ".join(p.trozos)).replace(" ", " ").strip()


def render(clave, libre=None, docs=None):
    return A._render_email_template(clave, "Ana Pérez", libre, docs)


# Las que llevan texto libre no se pueden renderizar sin texto: el placeholder
# quedaría a la vista y el test lo marcaría, con razón.
LIBRE = {"texto_libre": "Tu documentación está en revisión.",
         "general_b2c_blanco": "Necesitamos el comprobante de la operación."}


class Plantillas(unittest.TestCase):

    def _todas(self):
        for clave in A.EMAIL_TEMPLATE_CATALOG:
            yield clave, render(clave, LIBRE.get(clave))

    def test_el_saludo_aparece_una_sola_vez(self):
        """El bug original: el cuerpo entero duplicado dentro del correo."""
        for clave, html in self._todas():
            with self.subTest(clave):
                self.assertEqual(visible(html).count("Hola Ana Pérez"), 1)

    def test_nada_de_andamiaje_a_la_vista(self):
        for clave, html in self._todas():
            texto = visible(html)
            for resto in ANDAMIAJE:
                with self.subTest(clave=clave, resto=resto):
                    self.assertNotIn(resto, texto)

    def test_la_clausula_esta_en_todos(self):
        for clave, html in self._todas():
            with self.subTest(clave):
                self.assertIn(CLAUSULA, visible(html))

    def test_los_marcadores_del_renderizador_siguen_ahi(self):
        """Antes de renderizar, el archivo tiene que traer lo que se reemplaza."""
        for clave, meta in A.EMAIL_TEMPLATE_CATALOG.items():
            crudo = A._load_email_template_html(clave)
            with self.subTest(clave):
                self.assertEqual(crudo.count(A._SF_MERGE_FIELD_NOMBRE), 1)
                if meta["requires_custom_text"]:
                    self.assertEqual(crudo.count(A._TEXTO_LIBRE_PLACEHOLDER), 1)
                else:
                    # Las de solicitud llevan los 4 puntos removibles, uno por
                    # cada nombre de _TEMPLATE_BLOCK_ORDER. Las APARICIONES son
                    # 5: "formulario" sale dos veces, el punto del texto y el
                    # botón, para que el botón se vaya junto con el punto.
                    nombres = re.findall(r"<!--B:([a-z]+)-->", crudo)
                    self.assertEqual(sorted(set(nombres)),
                                     sorted(A._TEMPLATE_BLOCK_ORDER))
                    self.assertEqual(nombres.count("formulario"), 2)
                    self.assertEqual(crudo.count("<!--/B-->"), len(nombres))
                    self.assertEqual(crudo.count("{{N}}"), 4)

    def test_el_boton_se_va_con_el_punto_del_formulario(self):
        """Un botón azul ofreciendo un formulario que el correo ya no menciona
        es peor que no tener botón."""
        completo = render("general_b2c")
        self.assertIn("Descargar formulario", visible(completo))

        sin_formulario = render("general_b2c", docs=["Domicilio", "Origen de fondo"])
        texto = visible(sin_formulario)
        self.assertNotIn("Descargar formulario", texto)
        self.assertNotIn("Formulario adjunto, completo y firmado", texto)
        # Y los puntos que quedaron se renumeran desde 1.
        self.assertIn("1. Comprobante de domicilio", texto)
        self.assertIn("2. Documentación que respalde el origen", texto)

    def test_el_boton_apunta_al_formulario_publicado(self):
        for clave, meta in A.EMAIL_TEMPLATE_CATALOG.items():
            if not meta["attachment"]:
                continue
            with self.subTest(clave):
                # El mismo archivo que viaja adjunto, servido por CloudFront:
                # el cuerpo sigue diciendo "Formulario adjunto", así que el
                # adjunto se queda y el botón es el atajo, no el reemplazo.
                self.assertIn(f"/formularios/{meta['attachment']}",
                              A._load_email_template_html(clave))


class PlantillasRelevo(unittest.TestCase):

    def test_cliente_una_sola_vez_y_con_clausula(self):
        html = plantilla.componer("Ana Pérez", "Necesitamos tu comprobante de domicilio.")
        self.assertIsNotNone(html)
        texto = visible(html)
        self.assertEqual(texto.count("Hola Ana Pérez"), 1)
        self.assertIn(CLAUSULA, texto)
        self.assertFalse(plantilla.quedan_marcadores(html))

    def test_empresa_usa_el_trato_formal(self):
        html = plantilla.componer("ACME SpA", "Necesitamos el balance.", empresa=True)
        texto = visible(html)
        self.assertIn("Estimados de ACME SpA:", texto)
        self.assertIn("Quedamos atentos a su respuesta.", texto)

    def test_las_frases_formales_existen_en_el_html(self):
        """Si una frase de FORMAL ya no está en la plantilla, el replace no
        hace nada y el correo a empresa sale tuteando sin que nadie se entere."""
        base = plantilla.cargar()
        for tuteo, _ in plantilla.FORMAL:
            frase = tuteo.format(nombre=plantilla.MARCA_NOMBRE)
            with self.subTest(frase):
                self.assertIn(frase, base)

    def test_partner_sin_la_clausula_del_cliente(self):
        """Del otro lado hay un analista de un banco corresponsal: pedirle que
        adjunte "tus documentos" no aplica, y delata que nadie lo revisó."""
        html = plantilla.componer_partner(
            [{"t": "p", "texto": "Please find the information requested."},
             {"t": "ol", "items": ["Purchase agreement", "Bank transfer receipt"]},
             {"t": "cita", "lineas": ["The funds come from the sale of my car."]}],
            "en")
        self.assertIsNotNone(html)
        texto = visible(html)
        self.assertNotIn(CLAUSULA, texto)
        self.assertNotIn("Respóndenos este correo", texto)
        for resto in ANDAMIAJE:
            self.assertNotIn(resto, texto)
        # El pie del partner, en el idioma del correo.
        self.assertIn("This message answers an information request", texto)
        self.assertIn("Purchase agreement", texto)

    def test_partner_en_cada_idioma(self):
        for idioma, marca in (("es", "Este mensaje responde"),
                              ("pt", "Esta mensagem responde"),
                              ("en", "This message answers")):
            html = plantilla.componer_partner([{"t": "p", "texto": "x"}], idioma)
            with self.subTest(idioma):
                self.assertIn(marca, visible(html))


if __name__ == "__main__":
    unittest.main(verbosity=1)
