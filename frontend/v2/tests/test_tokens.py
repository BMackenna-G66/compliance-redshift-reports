# -*- coding: utf-8 -*-
"""Los tokens visuales de v2: que se lean y que no se escapen.

POR QUÉ ESTO ES UN TEST Y NO UNA REVISIÓN A OJO
-----------------------------------------------
Al extraer la paleta del prototipo tres colores de nivel quedaron por debajo
del mínimo de contraste sin que se notara mirándolos: el rosa de CRÍTICO daba
3,6:1 sobre blanco, el naranja de ALTO 3,0:1 y el teal de BAJO 3,2:1. Se ven
bien en una captura y se pierden en un monitor de oficina con reflejo.

El gris de etiquetas era peor: 2,5:1, y es el color que el prototipo usa 112
veces, a 10 px, en la pantalla que un analista mira ocho horas.

Ninguno de esos cuatro se detecta leyendo el CSS. Por eso se miden.

EL UMBRAL. WCAG 2.1 AA pide 4.5:1 para texto normal. No se baja a 3:1 (el
umbral de texto grande) porque acá el texto chico es la regla: la tabla va a
12 px y las etiquetas a 10 px.
"""
import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "src" / "estilo" / "tokens.css"
MINIMO = 4.5


# ── Medición ────────────────────────────────────────────────────────────────

def _luminancia(hexa):
    """Luminancia relativa, fórmula de WCAG 2.1."""
    r, g, b = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contraste(frente, fondo):
    a, b = _luminancia(frente), _luminancia(fondo)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# ── Lectura del CSS ─────────────────────────────────────────────────────────

def _bloque(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.S)
    if not m:
        raise AssertionError("falta el bloque %s en tokens.css" % selector)
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)))


def _resolver(tokens, valor, saltos=0):
    """Sigue las referencias `var(--otro)`.

    Sin esto el medidor mira sólo los hex literales y da por buenos los tokens
    definidos como alias — que fue exactamente cómo se me escaparon los tres
    colores de nivel la primera vez.
    """
    valor = valor.strip()
    m = re.match(r"var\(\s*(--[\w-]+)\s*\)$", valor)
    if not m:
        return valor
    if saltos > 8:
        raise AssertionError("referencia circular en %s" % valor)
    destino = tokens.get(m.group(1))
    if destino is None:
        raise AssertionError("%s apunta a %s, que no existe" % (valor, m.group(1)))
    return _resolver(tokens, destino, saltos + 1)


def temas():
    css = CSS.read_text(encoding="utf-8")
    claro = _bloque(css, ":root")
    claro = {k: _resolver(claro, v) for k, v in claro.items()}
    crudo = {**claro, **_bloque(css, ':root[data-tema="oscuro"]')}
    oscuro = {k: _resolver(crudo, v) for k, v in crudo.items()}
    return {"claro": claro, "oscuro": oscuro}


# Las superficies sobre las que puede caer texto. `--superficie-3` es la que
# más aprieta: es el gris de las cabeceras y el fondo de las insignias, y dos
# colores que pasaban sobre blanco reprobaban sobre él.
SUPERFICIES = ["--fondo", "--superficie", "--superficie-2", "--superficie-3"]

# Los neutros de texto, que no llevan sufijo.
NEUTROS = ["--texto", "--texto-2", "--texto-mute"]

# Pares con un fondo propio, fuera de la grilla de arriba.
PARES_SUELTOS = [
    ("--estado-error-texto", "--estado-error-fondo"),
    ("--texto-sobre-oscuro", "--g66-navy-profundo"),
    ("--texto-sobre-oscuro", "--g66-azul"),
    ("--texto-sobre-oscuro", "--g66-navy-2"),
]


def pares(tokens):
    """Todo lo que se dibuja como letra, contra toda superficie donde puede caer.

    Se deriva en vez de listarse a mano: un token `-texto` nuevo queda cubierto
    sin que nadie se acuerde de agregarlo acá. Así apareció que
    `--nivel-alto-texto` no llegaba al mínimo sobre el gris de las insignias.
    """
    letras = [k for k in tokens if k.endswith("-texto")
              and k != "--texto-sobre-oscuro"] + NEUTROS
    return [(a, b) for a in sorted(set(letras)) for b in SUPERFICIES] + PARES_SUELTOS


# LO QUE ESTE TEST NO MIDE: los fondos `-tenue` llevan alfa (`#FF297014`) y se
# componen sobre lo que tengan debajo. Como son translúcidos al 8%, el color
# efectivo queda muy cerca de `--superficie`, que sí se mide.


class Contraste(unittest.TestCase):

    def test_todo_par_de_texto_se_lee_en_los_dos_temas(self):
        for nombre, tokens in temas().items():
            for frente, fondo in pares(tokens):
                a, b = tokens.get(frente, ""), tokens.get(fondo, "")
                with self.subTest(tema=nombre, par="%s sobre %s" % (frente, fondo)):
                    self.assertRegex(a, r"^#[0-9A-Fa-f]{6}$", "%s no es un hex" % frente)
                    self.assertRegex(b, r"^#[0-9A-Fa-f]{6}$", "%s no es un hex" % fondo)
                    r = contraste(a, b)
                    self.assertGreaterEqual(
                        round(r, 1), MINIMO,
                        "%s (%s) sobre %s (%s) da %.1f:1" % (frente, a, fondo, b, r))


class LaMedicionMide(unittest.TestCase):
    """Tests del medidor. Una revisión de accesibilidad que no puede fallar no
    sirve de nada, y este archivo ya me engañó una vez por no resolver `var()`."""

    def test_los_extremos_dan_lo_que_dice_la_norma(self):
        self.assertAlmostEqual(contraste("#000000", "#FFFFFF"), 21.0, places=1)
        self.assertAlmostEqual(contraste("#FFFFFF", "#FFFFFF"), 1.0, places=1)

    def test_el_orden_no_cambia_el_resultado(self):
        self.assertAlmostEqual(contraste("#303030", "#FFFFFF"),
                               contraste("#FFFFFF", "#303030"), places=6)

    def test_caza_el_gris_que_traia_el_prototipo(self):
        """#A4A3A4 es el gris original de las etiquetas: debe reprobar."""
        self.assertLess(contraste("#A4A3A4", "#FFFFFF"), MINIMO)

    def test_sigue_las_referencias(self):
        t = {"--a": "var(--b)", "--b": "var(--c)", "--c": "#123456"}
        self.assertEqual(_resolver(t, t["--a"]), "#123456")

    def test_una_referencia_rota_no_pasa_en_silencio(self):
        with self.assertRaises(AssertionError):
            _resolver({"--a": "var(--no-existe)"}, "var(--a)")

    def test_una_referencia_circular_no_cuelga(self):
        with self.assertRaises(AssertionError):
            _resolver({"--a": "var(--b)", "--b": "var(--a)"}, "var(--a)")


class Cobertura(unittest.TestCase):

    def test_el_tema_oscuro_redefine_todo_color_que_deba_cambiar(self):
        """Un token de color que el tema oscuro no redefina hereda el claro.
        Para los fondos y los textos eso es texto oscuro sobre lienzo negro."""
        t = temas()
        css = CSS.read_text(encoding="utf-8")
        oscuro_crudo = _bloque(css, ':root[data-tema="oscuro"]')
        criticos = ["--texto", "--texto-2", "--texto-mute", "--fondo",
                    "--superficie", "--superficie-2", "--superficie-3", "--borde"]
        for k in criticos:
            with self.subTest(k):
                self.assertIn(k, oscuro_crudo,
                              "%s no se redefine en el tema oscuro" % k)
        self.assertNotEqual(t["claro"]["--fondo"], t["oscuro"]["--fondo"])

    def test_ningun_token_queda_sin_valor(self):
        for nombre, tokens in temas().items():
            for k, v in tokens.items():
                with self.subTest(tema=nombre, token=k):
                    self.assertTrue(v.strip(), "%s está vacío" % k)


if __name__ == "__main__":
    unittest.main(verbosity=1)
