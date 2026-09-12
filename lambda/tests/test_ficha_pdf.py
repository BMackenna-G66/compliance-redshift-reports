"""El PDF de la ficha.

Lo que se protege acá es que el documento **se genere**, no que se vea lindo.
`Paragraph` de reportlab interpreta un marcado tipo HTML, así que un `&` en la
razón social de una empresa o un `<correo@dominio>` dentro de un error de SMTP
no son un problema de estética: revientan la construcción del PDF entero y el
analista se queda sin documento, justo cuando lo necesita para un expediente.

Y esos caracteres llegan solos: `550 <alguien@x> not found` es una respuesta
literal de Gmail, y "Pérez & Cía" es un nombre de empresa perfectamente normal.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ficha_pdf as F  # noqa: E402

try:
    import reportlab  # noqa: F401
    HAY_REPORTLAB = True
except ImportError:
    HAY_REPORTLAB = False


def ficha_hostil():
    """Una ficha con todo lo que puede romper el marcado, en cada campo que
    viene de afuera: nombre de cliente, título de caso, asunto, error de SMTP,
    nombre de archivo y campo del perfil."""
    veneno = "Pérez & Cía <SA> \"quoted\" 'single' >>"
    return {
        "entity_id": "4084605", "kind": "b2c", "nombre": veneno,
        "periodo": "2026-06-11 a 2026-09-11 (3 meses)",
        "perfil": {"razon_social": veneno, "email": "a<b>@x.com"},
        "perfil_origen": "consulta en vivo",
        "avisos": [{"tono": "alto", "texto": f"Ojo con {veneno}"}],
        "productos": [
            {"producto": "Cuenta virtual", "tiene": True, "detalle": veneno,
             "desde": "2025-02-10", "evidencia": "perfil KYC"},
            {"producto": "Remesas", "tiene": True, "detalle": "63 envíos",
             "desde": "", "evidencia": "transacciones"},
            {"producto": "Cripto", "tiene": False, "detalle": "—",
             "desde": "", "evidencia": "bancos"},
        ],
        "resumen": {"n_efectivas": 63, "total_usd": "26513.78",
                    "ticket_promedio_usd": "420.85", "ticket_mayor_usd": "1004.85",
                    "paises_destino": 1, "beneficiarios": 34,
                    "n_devueltas": 1, "devuelto_usd": "382.04", "n_retenidas": 2},
        "por_pais": [{"pais": veneno, "n": 63, "usd": "26513.78"}],
        "por_mes": [{"mes": "2026-09", "n": 3, "usd": "1766.28", "n_cripto": 2}],
        "casos": [{"case_id": "c1", "title": veneno, "status": "open",
                   "assigned_to": "a@b.com", "created_at": "2026-09-01 10:00:00"}],
        "correos": [
            {"direccion": "enviado", "cuando": "2026-09-02 11:00:00",
             "para": "x@y.com", "de": "", "asunto": veneno, "cuerpo": veneno,
             "salio": False, "error": "550 <alguien@dominio.com> not found",
             "documentos": [veneno], "case_title": veneno},
            {"direccion": "recibido", "cuando": "2026-09-03 09:00:00",
             "de": "cliente@x.com", "para": "", "asunto": "", "cuerpo": veneno,
             "salio": True, "error": "", "documentos": ["a&b<c>.pdf"],
             "case_title": veneno},
        ],
        "documentos": {
            "solicitados": [{"documento": veneno, "cuando": "2026-09-02",
                             "salio": False, "case_id": "c1"}],
            "recibidos": [{"filename": "a&b<c>.pdf", "cuando": "2026-09-03",
                           "origen": "email_reply", "case_id": "c1"}],
        },
        "totales": {"casos": 1, "correos": 2, "enviados": 1, "recibidos": 1},
        "aviso_transaccional": "",
    }


class NombreDeArchivo(unittest.TestCase):
    def test_dice_de_quien_es(self):
        n = F.nombre_archivo({"entity_id": "4246021", "nombre": "Berenice Brizuela"})
        self.assertEqual(n, "ficha-4246021-Berenice-Brizuela.pdf")

    def test_un_nombre_hostil_no_se_escapa_a_la_ruta(self):
        """El nombre va en una clave de S3 y en un header Content-Disposition:
        una barra o una comilla ahí no es cosmética."""
        n = F.nombre_archivo({"entity_id": "1/../../etc", "nombre": 'a"b/c\\d'})
        self.assertNotIn("/", n)
        self.assertNotIn("..", n)
        self.assertNotIn('"', n)
        self.assertNotIn("\\", n)
        self.assertTrue(n.endswith(".pdf"))

    def test_sin_nombre_igual_devuelve_algo_usable(self):
        self.assertEqual(F.nombre_archivo({}), "ficha-cliente.pdf")


class Formato(unittest.TestCase):
    def test_montos_en_formato_local(self):
        self.assertEqual(F._fmt_usd("26513.78"), "USD 26.513,78")
        self.assertEqual(F._fmt_usd(0), "USD 0,00")

    def test_un_monto_ilegible_no_revienta(self):
        self.assertEqual(F._fmt_usd(None), "—")
        self.assertEqual(F._fmt_usd("ocho"), "—")


class Escapado(unittest.TestCase):
    def test_los_signos_del_marcado_se_neutralizan(self):
        self.assertEqual(F._txt("a & b < c > d"), "a &amp; b &lt; c &gt; d")

    def test_un_error_de_smtp_pasa_entero(self):
        """`550 <x@y> not found` es literal de Gmail: sin escapar, se lleva
        puesto el PDF."""
        self.assertNotIn("<", F._txt("550 <alguien@dominio.com> not found"))


@unittest.skipUnless(HAY_REPORTLAB, "reportlab no instalado en este entorno")
class SeGenera(unittest.TestCase):
    def test_una_ficha_normal_produce_un_pdf(self):
        import json
        datos = F.construir(ficha_hostil(), pedido_por="a@b.com",
                            ahora="2026-09-12 19:50:00")
        self.assertTrue(datos.startswith(b"%PDF-"))
        self.assertGreater(len(datos), 3000)

    def test_los_datos_hostiles_no_rompen_la_construccion(self):
        """El test que justifica el archivo: si algún campo se olvidó de pasar
        por `_txt`, esto levanta."""
        datos = F.construir(ficha_hostil())
        self.assertTrue(datos.startswith(b"%PDF-"))

    def test_una_ficha_vacia_no_revienta(self):
        """Un cliente sin casos, sin correos y sin transacciones es un caso
        real —alguien que recién entró— y tiene que poder imprimirse."""
        for vacia in ({}, {"entity_id": "1", "kind": "b2c"},
                      {"entity_id": "1", "productos": [], "casos": [],
                       "correos": [], "documentos": {}, "resumen": {}}):
            datos = F.construir(vacia)
            self.assertTrue(datos.startswith(b"%PDF-"))

    def test_el_logo_viaja_con_el_modulo(self):
        """Si falta, el PDF sale igual pero sin identidad: mejor que levante
        acá que descubrirlo en un documento que ya se mandó afuera."""
        import os
        self.assertTrue(os.path.exists(F.LOGO), f"falta el logo en {F.LOGO}")

    def test_una_ficha_larga_pagina_sin_filas_huerfanas(self):
        """Con muchos correos el documento pasa de una página. Lo que se
        verifica es que la historia entre completa: reportlab se queda sin
        espacio en silencio si un frame está mal calculado."""
        f = ficha_hostil()
        f["correos"] = f["correos"] * 40
        datos = F.construir(f)
        self.assertTrue(datos.startswith(b"%PDF-"))
        self.assertGreater(datos.count(b"/Type /Page"), 1)


class Empaquetado(unittest.TestCase):
    def test_el_modulo_y_el_logo_viajan_en_el_paquete(self):
        build = (Path(__file__).resolve().parents[2] / "build_lambda.sh").read_text()
        self.assertIn("lambda/ficha_pdf.py", build)
        self.assertIn("lambda/assets/", build)

    def test_reportlab_esta_declarado(self):
        req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
        self.assertIn("reportlab", req.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
