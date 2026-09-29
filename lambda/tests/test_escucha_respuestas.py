# -*- coding: utf-8 -*-
"""La escucha de respuestas de clientes.

POR QUÉ EXISTE ESTE ARCHIVO. El 29-09-2026 se descubrió que la escucha
llevaba OCHO DÍAS caída: la app password de `compliance.masivo@global66.com`
dejó de servir y el proceso —que corre cada 10 minutos— devolvía el error sin
que nadie lo viera. La única huella era que la invocación duraba 488 ms en vez
de segundos. Durante esos ocho días, lo que respondieron los clientes no entró
a ningún caso, y los casos decían «no respondió».

Dos cosas se rompieron y las dos se vigilan acá:

1. **El silencio.** Un canal de contacto con clientes que se corta tiene que
   gritar. Ahora el fallo queda como ERROR en el log y avisa por Slack.

2. **Los espacios de la app password.** Google la muestra en 4 grupos de 4 y
   es naturalísimo guardarla tal cual; IMAP la rechaza con el MISMO error que
   una clave revocada. Quien intente recuperar el canal cargando la clave
   nueva vería «no funciona» y concluiría que Google se la revocó de nuevo.
   `_get_gmail_password()` ya limpiaba los espacios para SMTP; esta no.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_handler as A  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


class LaClaveSeLimpiaComoLaDeSMTP(unittest.TestCase):

    def _con_secreto(self, valor):
        class _SM:
            def get_secret_value(self, SecretId):               # noqa: N803
                return {"SecretString": valor}
        orig_sm, orig_arn = A.secrets_client, A.DOC_REPLY_IMAP_SECRET_ARN
        A.secrets_client, A.DOC_REPLY_IMAP_SECRET_ARN = _SM(), "arn:algo"
        try:
            return A._get_imap_password()
        finally:
            A.secrets_client, A.DOC_REPLY_IMAP_SECRET_ARN = orig_sm, orig_arn

    def test_los_cuatro_grupos_de_cuatro_se_pegan(self):
        """Así la muestra Google, y así se guarda sin pensarlo."""
        self.assertEqual(self._con_secreto("abcd efgh ijkl mnop"),
                         "abcdefghijklmnop")

    def test_tambien_los_saltos_de_linea(self):
        self.assertEqual(self._con_secreto("\nabcd efgh\tijkl mnop \n"),
                         "abcdefghijklmnop")

    def test_una_clave_limpia_no_se_toca(self):
        self.assertEqual(self._con_secreto("abcdefghijklmnop"),
                         "abcdefghijklmnop")

    def test_hace_lo_mismo_que_la_de_smtp(self):
        """Las dos leen una app password de Google. Que una limpie y la otra
        no es la clase de diferencia que sólo se descubre en un incidente."""
        import inspect
        smtp = inspect.getsource(A._get_gmail_password)
        imap = inspect.getsource(A._get_imap_password)
        self.assertIn("split()", imap)
        self.assertTrue("replace(" in smtp or "split()" in smtp)


class ElFalloNoPuedeSerSilencioso(unittest.TestCase):
    """Ocho días sin que nadie se entere fue el problema de fondo."""

    def _despacho(self):
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index('if report_name == "poll_document_replies":')
        return fuente[i:i + 900]

    def test_un_error_se_loguea_como_error(self):
        cuerpo = self._despacho()
        self.assertIn("logger.error", cuerpo)

    def test_y_avisa_por_slack(self):
        cuerpo = self._despacho()
        self.assertIn("_avisar_escucha_caida", cuerpo)

    def test_el_resultado_bueno_tambien_queda_registrado(self):
        """Sin esto, «no pasó nada» y «no corrió» se ven igual en el log."""
        cuerpo = self._despacho()
        self.assertIn("logger.info", cuerpo)

    def test_el_aviso_no_va_al_canal_del_equipo(self):
        """Pedido explícito: es una falla de infraestructura que resuelve una
        persona, y en un canal compartido se vuelve ruido que todos aprenden
        a saltear — que es cómo se pierden ocho días."""
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def _avisar_escucha_caida(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        self.assertNotIn("SLACK_SECRET_ARN", cuerpo,
                         "está usando el webhook del canal del equipo")
        self.assertIn("SLACK_DM_SECRET_ARN", cuerpo)

    def test_sin_webhook_privado_avisa_por_correo(self):
        """Quedarse sin webhook no puede significar quedarse sin aviso: ese
        es exactamente el modo de falla que este aviso existe para tapar."""
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def _avisar_escucha_caida(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        self.assertIn("AVISO_FALLA_EMAIL", cuerpo)
        self.assertIn("_send_email_gmail", cuerpo)

    def test_la_marca_de_tiempo_solo_se_escribe_si_avisó(self):
        """Si no se pudo avisar, no se anota: si no, el primer intento
        fallido silenciaría la hora siguiente."""
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def _avisar_escucha_caida(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        j = cuerpo.index("put_object")
        # La propiedad, no el texto: la escritura de la marca está detrás de
        # `avisado`, se escriba esa condición como se escriba.
        guarda = cuerpo[:j].rsplit("if avisado", 1)
        self.assertEqual(len(guarda), 2, "la marca no está detrás de `avisado`")
        self.assertNotIn("put_object", guarda[1])

    def test_una_prueba_no_silencia_la_falla_real(self):
        """Probar el aviso escribía la marca de «ya avisé esta hora», así que
        una prueba taparía una caída de verdad en los 60 minutos siguientes.
        Es la clase de detalle que convierte una herramienta de diagnóstico en
        un agujero."""
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def _avisar_escucha_caida(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        j = cuerpo.index("put_object")
        self.assertIn("not es_prueba", cuerpo[:j])

    def test_se_puede_probar_el_aviso_sin_romper_la_recepcion(self):
        """La lección del incidente no fue la contraseña: fue que el aviso no
        existía y nadie lo notó en ocho días. Un aviso que nunca se probó es
        un aviso del que no se sabe si funciona."""
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        self.assertIn('report_name == "probar_aviso_falla"', fuente)
        i = fuente.index('report_name == "probar_aviso_falla"')
        self.assertIn("es_prueba=True", fuente[i:i + 500])

    def test_el_mensaje_de_prueba_se_anuncia_como_prueba(self):
        """Nadie tiene que entrar en pánico por una prueba."""
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def _avisar_escucha_caida(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        self.assertIn("PRUEBA", cuerpo)

    def test_el_aviso_no_se_repite_cada_diez_minutos(self):
        """Un canal caído días generaría cientos de mensajes y el canal de
        avisos se volvería ruido que nadie mira — otra forma de no
        enterarse."""
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def _avisar_escucha_caida(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        self.assertIn("3600", cuerpo)

    def test_avisar_nunca_rompe_la_corrida(self):
        """Si Slack falla, la escucha tiene que seguir: el aviso es
        secundario al trabajo."""
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def _avisar_escucha_caida(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        self.assertIn("except Exception", cuerpo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
