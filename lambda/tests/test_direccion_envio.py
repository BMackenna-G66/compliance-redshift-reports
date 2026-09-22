# -*- coding: utf-8 -*-
"""La validación del destinatario de un correo.

EL INCIDENTE QUE LA ORIGINA. El 17 y el 22 de septiembre de 2026, cinco
correos a un cliente no salieron. El caso mostraba:

    UnicodeEncodeError: 'ascii' codec can't encode character '\\xfa'
    in position 56: ordinal not in range(128)

Nada en ese mensaje dice que el problema era el destinatario. Lo era: en el
campo del correo había quedado guardado el texto «Bloqueo preventivo por
alerta transaccional según Watchtower [12:23]Recordatorio:». `smtplib` escribe
la dirección cruda en `RCPT TO:<...>` y codifica ese comando en ASCII; la `ú`
de «según» cae justo en la posición 56.

El quinto intento falló distinto —`SMTPRecipientsRefused` con `<Bloqueo>`—
porque el servidor cortó la dirección en el primer espacio. Dos síntomas, una
sola causa.

Se leen las funciones con `ast` y se ejecutan aisladas: importar
`api_handler` arrastra boto3 y credenciales, y este test tiene que correr en
cualquier lado.
"""
import ast
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
API = RAIZ / "lambda" / "api_handler.py"


def _cargar():
    """Ejecuta sólo `_FORMA_CORREO` y `_direccion_de_envio`, sin el módulo."""
    arbol = ast.parse(API.read_text(encoding="utf-8"))
    quiero = {"_FORMA_CORREO", "_direccion_de_envio"}
    piezas = []
    for nodo in arbol.body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name in quiero:
            piezas.append(nodo)
        elif isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name) and destino.id in quiero:
                    piezas.append(nodo)
    assert len(piezas) == 2, f"no encontré las dos piezas: {len(piezas)}"
    espacio = {"re": re}
    exec(compile(ast.Module(body=piezas, type_ignores=[]), "<api>", "exec"), espacio)
    return espacio["_direccion_de_envio"]


direccion_de_envio = _cargar()

# El valor exacto que había en producción.
EL_TEXTO_QUE_ROMPIO = "Bloqueo preventivo por alerta transaccional según Watchtower [12:23]Recordatorio:"


class ElCasoDeProduccion(unittest.TestCase):

    def test_el_texto_que_rompio_se_rechaza(self):
        direccion, problema = direccion_de_envio(EL_TEXTO_QUE_ROMPIO)
        self.assertEqual(direccion, "")
        self.assertTrue(problema)

    def test_el_mensaje_dice_cual_era_el_problema(self):
        """El error tiene que nombrar al destinatario.

        El de antes hablaba de códecs y de la posición 56 de una cadena que
        nadie ve. Éste tiene que poder leerse sin abrir el código.
        """
        _, problema = direccion_de_envio(EL_TEXTO_QUE_ROMPIO)
        self.assertIn("no es una dirección de correo", problema)
        self.assertIn("Bloqueo preventivo", problema)

    def test_un_destinatario_larguisimo_se_recorta(self):
        """Sin recorte, un pegado accidental de mil caracteres entra entero en
        el registro del caso y lo vuelve ilegible."""
        _, problema = direccion_de_envio("x " * 400)
        self.assertLess(len(problema), 120)
        self.assertIn("…", problema)


class LoQueSiEsUnaDireccion(unittest.TestCase):

    def test_una_direccion_normal_pasa(self):
        for d in ["ana@global66.com", "a.b+c@sub.dominio.cl", "x_1@dominio.com.ar"]:
            direccion, problema = direccion_de_envio(d)
            self.assertEqual(problema, "", d)
            self.assertEqual(direccion, d)

    def test_se_le_saca_el_espacio_de_los_costados(self):
        direccion, problema = direccion_de_envio("  ana@global66.com  ")
        self.assertEqual(problema, "")
        self.assertEqual(direccion, "ana@global66.com")

    def test_acepta_nombre_con_direccion_entre_angulos(self):
        """Es una forma válida y alguien la va a pegar tarde o temprano.

        Lo que viaja en el sobre es sólo la dirección: es lo único que SMTP
        admite en `RCPT TO`.
        """
        direccion, problema = direccion_de_envio("Ana Pérez <ana@global66.com>")
        self.assertEqual(problema, "")
        self.assertEqual(direccion, "ana@global66.com")


class LoQueNoEsUnaDireccion(unittest.TestCase):

    def test_vacio(self):
        for v in ["", "   ", None]:
            _, problema = direccion_de_envio(v)
            self.assertIn("no hay ninguna", problema)

    def test_sin_arroba(self):
        _, problema = direccion_de_envio("ana.global66.com")
        self.assertTrue(problema)

    def test_dos_arrobas(self):
        _, problema = direccion_de_envio("ana@otro@global66.com")
        self.assertTrue(problema)

    def test_dominio_sin_punto(self):
        _, problema = direccion_de_envio("ana@localhost")
        self.assertTrue(problema)

    def test_con_espacio_adentro(self):
        """El caso del incidente en su forma más chica."""
        _, problema = direccion_de_envio("ana perez@global66.com")
        self.assertTrue(problema)

    def test_con_acentos_en_la_direccion(self):
        """Lo que hacía estallar a smtplib.

        Existen direcciones internacionalizadas, pero Gmail por SMTP simple no
        las acepta: mejor rechazarlas con un mensaje claro que con un
        UnicodeEncodeError.
        """
        _, problema = direccion_de_envio("josé@global66.com")
        self.assertTrue(problema)

    def test_varias_direcciones_separadas_por_coma(self):
        """`sendmail` recibe una lista, no una cadena con comas.

        Mandar «a@x.com, b@y.com» en un solo campo termina en un `RCPT TO`
        con una dirección que no existe.
        """
        _, problema = direccion_de_envio("a@global66.com, b@global66.com")
        self.assertTrue(problema)

    def test_con_salto_de_linea(self):
        """Un salto de línea en una cabecera es inyección de cabeceras."""
        _, problema = direccion_de_envio("ana@global66.com\nBcc: otro@ajeno.com")
        self.assertTrue(problema)


class ElCorteEstaEnElLugarCorrecto(unittest.TestCase):
    """Que la validación viva en `_send_email` y no en cada uno de los que llaman."""

    def test_send_email_valida_antes_de_conectarse(self):
        texto = API.read_text(encoding="utf-8")
        i = texto.index("def _send_email(")
        cuerpo = texto[i:texto.index("\ndef ", i + 10)]
        self.assertIn("_direccion_de_envio(to)", cuerpo,
                      "_send_email tiene que validar el destinatario")
        # La validación va antes de pedir la contraseña y de abrir la conexión.
        self.assertLess(cuerpo.index("_direccion_de_envio(to)"),
                        cuerpo.index("_get_gmail_password()"),
                        "se valida antes de ir a buscar la app password")
        self.assertLess(cuerpo.index("_direccion_de_envio(to)"),
                        cuerpo.index("SMTP_SSL"),
                        "se valida antes de abrir la conexión")

    def test_el_sobre_lleva_la_direccion_limpia(self):
        """`sendmail` tiene que recibir la dirección normalizada, no el crudo.

        Si recibiera `to`, «Ana <ana@x.com>» volvería a romper en `RCPT TO`.
        """
        texto = API.read_text(encoding="utf-8")
        i = texto.index("def _send_email(")
        cuerpo = texto[i:texto.index("\ndef ", i + 10)]
        self.assertIn("server.sendmail(sender, [destino]", cuerpo)

    def test_el_pedido_manual_corta_antes_de_crear_el_caso(self):
        """Si el correo no puede salir, no se crea un caso ni un pedido fallido."""
        texto = API.read_text(encoding="utf-8")
        i = texto.index("def send_manual_document_request(")
        cuerpo = texto[i:texto.index("\ndef ", i + 10)]
        self.assertIn("_direccion_de_envio(correo)", cuerpo)
        self.assertLess(cuerpo.index("_direccion_de_envio(correo)"),
                        cuerpo.index("create_case("),
                        "se valida antes de crear el caso")


if __name__ == "__main__":
    unittest.main(verbosity=2)
