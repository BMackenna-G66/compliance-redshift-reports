"""Paso 9, parte A: la devolución al partner.

Lo que se prueba es lo que puede hacer daño: que se le conteste al partner y no
a nuestra propia lista, que un ítem que nadie confirmó no salga como entregado,
que no se devuelva dos veces, y que los enlaces prefirmados no se filtren al
cuerpo del correo.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from relevo import checklist, devolucion  # noqa: E402


class FalsoDeposito:
    """Depósito en memoria, con la misma interfaz que usa devolucion.py."""

    def __init__(self):
        self.datos = {}
        self.BUCKET = "bucket-de-prueba"
        self.PREFIJO = "relevo"

    def activo(self):
        return True

    def clave_segura(self, v):
        return str(v).replace("/", "_")

    def obtener(self, col, clave):
        return self.datos.get((col, clave))

    def poner(self, col, clave, dato, solo_si_falta=False):
        self.datos[(col, clave)] = dato
        return True

    def todos(self, col, sub=""):
        # Igual que S3: lista por PREFIJO, no por igualdad. `casos.registrar`
        # escribe en "acciones/<caso>" y `leer_acciones` pide "acciones";
        # con igualdad exacta el doble no encontraría nada y el test pasaría
        # verde midiendo lo que no es.
        pref = col.strip("/") + "/"
        return [v for (c, _), v in self.datos.items()
                if c == col or c.startswith(pref)]

    def _s3(self):
        raise AssertionError("no se debe firmar ninguna URL en este camino")


CASO = {
    "id": "nium:caso:1088170",
    "partner": "Nium",
    "caso_partner": "1088170",
    "estado": "respuesta_recibida",
    "items": [{"item": "documento_identidad", "es": "Documento de identidad (frente y dorso)"},
              {"item": "origen_fondos", "es": "Origen de los fondos"}],
    "transacciones": [{"llave": "py", "valor": "PY75795516", "datos": {}}],
    "correos": [{"id": "m1", "thread_id": "t1", "asunto": "Additional information Required",
                 "accionable": True, "fecha": "2026-09-01 10:00",
                 "url_gmail": "https://mail.google.com/x"}],
    "cliente": {"cliente_id": 3950037, "cliente_nombre": "Maria Paula",
                "cliente_correo": "maria@example.com"},
    "acciones": [],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.dep = FalsoDeposito()
        self.reales = (devolucion.deposito, checklist.deposito)
        devolucion.deposito = self.dep
        checklist.deposito = self.dep
        # El correo del partner vive en los headers del mensaje crudo.
        self.dep.datos[("mensajes", "m1")] = {
            "id": "m1", "thread_id": "t1",
            "asunto": "Additional information Required",
            "headers": {"From": "Compliance <compliance@global66.com>",
                        "X-Original-Sender": "payments@nium.com",
                        "Message-ID": "<abc@nium.com>"},
        }

    def tearDown(self):
        devolucion.deposito, checklist.deposito = self.reales


class ContestarleAlPartner(Base):
    def test_responde_al_x_original_sender_no_al_from(self):
        """El From de todos estos correos es nuestra propia lista de Google."""
        para, asunto, ref = devolucion.destinatario(CASO)
        self.assertEqual(para, "payments@nium.com")
        self.assertEqual(asunto, "Additional information Required")
        self.assertEqual(ref["thread_id"], "t1")
        self.assertEqual(ref["via"], "X-Original-Sender")

    def test_nunca_devuelve_una_direccion_de_global66(self):
        self.dep.datos[("mensajes", "m1")]["headers"] = {
            "From": "Compliance <compliance@global66.com>",
            "Reply-To": "compliance.masivo@global66.com",
        }
        para, asunto, _ = devolucion.destinatario(CASO)
        self.assertEqual(para, "")
        self.assertEqual(asunto, "Additional information Required")

    def test_el_asunto_es_un_RE_del_original(self):
        c = devolucion.componer(CASO, idioma="en", caso_id=CASO["id"])
        self.assertEqual(c["asunto"], "RE: Additional information Required")


class LoQueDiceElCuerpo(Base):
    def test_sin_checklist_no_afirma_que_algo_se_entrego(self):
        c = devolucion.componer(CASO, idioma="en", caso_id=CASO["id"])
        self.assertEqual(c["entregados"], [])
        self.assertEqual(c["pendientes"], [])
        self.assertEqual(len(c["pedido"]), 2)
        self.assertTrue(any("no tiene checklist" in a for a in c["avisos"]))

    def test_separa_entregado_de_pendiente_segun_el_checklist(self):
        checklist.crear(CASO["id"], CASO["items"], ref="abc123", quien="tester")
        checklist.marcar(CASO["id"], "documento_identidad", checklist.ENTREGADO,
                         quien="analista@global66.com")
        c = devolucion.componer(CASO, idioma="en", caso_id=CASO["id"])
        self.assertEqual(c["entregados"], ["Identity document (front and back)"])
        self.assertEqual(c["pendientes"], ["Source of funds"])
        self.assertIn("Still outstanding:", c["texto"])

    def test_traduce_por_la_clave_del_catalogo(self):
        """La etiqueta sale del catálogo traducido, no de un string libre."""
        en = devolucion.componer(CASO, idioma="en", caso_id=CASO["id"])
        es = devolucion.componer(CASO, idioma="es", caso_id=CASO["id"])
        pt = devolucion.componer(CASO, idioma="pt", caso_id=CASO["id"])
        self.assertIn("Identity document (front and back)", en["texto"])
        self.assertIn("Documento de identidad (frente y dorso)", es["texto"])
        self.assertIn("Documento de identidade (frente e verso)", pt["texto"])

    def test_un_item_fuera_del_catalogo_se_muestra_tal_cual(self):
        caso = dict(CASO, items=[{"item": "", "es": "", "crudo": "algo raro"},
                                 {"item": "inventado_por_el_partner",
                                  "es": "Texto que vino en crudo"}])
        c = devolucion.componer(caso, idioma="en", caso_id=CASO["id"])
        self.assertIn("Texto que vino en crudo", c["texto"])

    def test_incluye_las_transacciones_del_caso(self):
        c = devolucion.componer(CASO, idioma="en", caso_id=CASO["id"])
        self.assertEqual(c["transacciones"], ["PY75795516"])
        self.assertIn("PY75795516", c["texto"])

    def test_la_nota_del_analista_entra_al_cuerpo(self):
        c = devolucion.componer(CASO, idioma="en", nota="El cliente confirmó por teléfono.",
                                caso_id=CASO["id"])
        self.assertIn("El cliente confirmó por teléfono.", c["texto"])


class EnlacesQueNoDebenFiltrarse(Base):
    def test_el_cuerpo_nombra_los_archivos_y_no_sus_urls(self):
        """Un enlace prefirmado en el correo al partner es una fuga (§9)."""
        self.dep.datos[("respuestas", "r1")] = {
            "message_id": "r1", "caso_id": CASO["id"], "via": "thread_id",
            "adjuntos": [{"nombre": "cedula.pdf", "tipo": "application/pdf",
                          "tamano": 1024, "s3_key": "relevo/adjuntos/x/y/cedula.pdf"}],
            "texto": "", "cuando": "2026-09-04 12:00:00",
        }
        c = devolucion.componer(CASO, idioma="en", caso_id=CASO["id"])
        self.assertEqual(c["archivos"], ["cedula.pdf"])
        self.assertIn("cedula.pdf", c["texto"])
        # componer() pide los adjuntos SIN enlace: si pidiera con enlace, el
        # _s3() del falso depósito levantaría AssertionError.
        self.assertNotIn("s3.amazonaws.com", c["texto"])
        self.assertNotIn("X-Amz-Signature", c["texto"])

    def test_la_respuesta_de_texto_del_cliente_va_citada(self):
        self.dep.datos[("respuestas", "r2")] = {
            "message_id": "r2", "caso_id": CASO["id"], "via": "token",
            "adjuntos": [], "texto": "Los fondos vienen de la venta de mi auto.",
            "cuando": "2026-09-04 12:00:00",
        }
        c = devolucion.componer(CASO, idioma="en", caso_id=CASO["id"])
        self.assertIn("> Los fondos vienen de la venta de mi auto.", c["texto"])


class Idioma(Base):
    def test_el_default_es_ingles(self):
        self.assertEqual(devolucion.idioma_de("Nium", config={}), "en")

    def test_el_mantenedor_del_partner_manda_sobre_el_general(self):
        cfg = {"idioma_general": "es", "idioma_oz_cambio": "pt"}
        self.assertEqual(devolucion.idioma_de("OZ Cambio", config=cfg), "pt")
        self.assertEqual(devolucion.idioma_de("Nium", config=cfg), "es")

    def test_un_idioma_invalido_no_rompe_ni_se_usa(self):
        self.assertEqual(devolucion.idioma_de("Nium", config={"idioma_general": "kl"}), "en")
        c = devolucion.componer(CASO, idioma="kl", caso_id=CASO["id"])
        self.assertEqual(c["idioma"], "en")


class Registro(Base):
    def setUp(self):
        super().setUp()
        # ya_devuelto() lee el registro de acciones, que vive en casos.py.
        self.dep_casos = devolucion.casos.deposito
        devolucion.casos.deposito = self.dep

    def tearDown(self):
        devolucion.casos.deposito = self.dep_casos
        super().tearDown()

    def test_exige_autor(self):
        r = devolucion.marcar_devuelto(CASO["id"], quien="")
        self.assertFalse(r["registrado"])
        self.assertIn("quien es requerido", r["error"])

    def test_sin_devolucion_previa_no_esta_devuelto(self):
        devuelto, motivo = devolucion.ya_devuelto(CASO["id"])
        self.assertFalse(devuelto)
        self.assertEqual(motivo, "")

    def test_una_devolucion_registrada_bloquea_la_segunda(self):
        devolucion.casos.registrar(CASO["id"], "devuelto", quien="ana@global66.com",
                                   detalle={"medio": "correo_manual"})
        devuelto, motivo = devolucion.ya_devuelto(CASO["id"])
        self.assertTrue(devuelto)
        self.assertIn("ya se marcó devuelto", motivo)
        self.assertIn("ana@global66.com", motivo)

    def test_registrar_no_manda_nada(self):
        """marcar_devuelto anota; el correo lo manda la persona (decisión 10)."""
        devolucion.casos.registrar(CASO["id"], "devuelto", quien="ana@global66.com",
                                   detalle={"medio": "correo_manual"})
        acciones = devolucion.casos.leer_acciones().get(CASO["id"]) or []
        self.assertEqual([a["accion"] for a in acciones], ["devuelto"])


if __name__ == "__main__":
    unittest.main()


class DescargaEnLote(Base):
    """El zip con todos los adjuntos del caso."""

    def setUp(self):
        super().setUp()
        from relevo import descarga
        self.descarga = descarga
        self.real = descarga.deposito
        descarga.deposito = self.dep

    def tearDown(self):
        self.descarga.deposito = self.real
        super().tearDown()

    def test_sin_archivos_avisa_y_no_arma_nada(self):
        r = self.descarga.zip_de_caso(CASO["id"])
        self.assertIn("error", r)
        self.assertIn("no tiene archivos", r["error"])

    def test_dos_archivos_con_el_MISMO_nombre_no_se_pisan(self):
        """El cliente manda el mismo formulario dos veces y en un zip el
        segundo sobreescribe al primero sin avisar."""
        usados = set()
        n1 = self.descarga._unico("cedula.pdf", usados)
        n2 = self.descarga._unico("cedula.pdf", usados)
        n3 = self.descarga._unico("cedula.pdf", usados)
        self.assertEqual([n1, n2, n3], ["cedula.pdf", "cedula (2).pdf", "cedula (3).pdf"])

    def test_un_nombre_sin_extension_tambien_se_desambigua(self):
        usados = set()
        self.assertEqual(self.descarga._unico("adjunto", usados), "adjunto")
        self.assertEqual(self.descarga._unico("adjunto", usados), "adjunto (2)")

    def test_el_zip_se_llama_como_el_caso(self):
        """Cinco archivos sueltos en Descargas no dicen de qué caso son."""
        n = self.descarga._nombre_zip("currencycloud:caso:1409820")
        self.assertTrue(n.endswith("-documentos.zip"))
        self.assertIn("1409820", n)
        self.assertNotIn(":", n)


class PlantillaDelPartner(unittest.TestCase):
    """La devolución va a un banco, no a un cliente."""

    def test_no_lleva_el_pie_de_consumo(self):
        """La plantilla de cliente trae «¿Tienes dudas?», centro de ayuda,
        WhatsApp y las tiendas de apps. A un analista de un corresponsal eso
        se le lee como una campaña de marketing mandada por error."""
        from relevo import plantilla
        h = plantilla.componer_partner("Hola")
        self.assertIsNotNone(h)
        for basura in ("¿Tienes dudas?", "Whatsapp", "Play Store", "App Store",
                       "Centro de ayuda"):
            self.assertNotIn(basura, h, basura)

    def test_conserva_la_marca(self):
        from relevo import plantilla
        h = plantilla.componer_partner("Hola")
        self.assertIn("d15k2d11r6t6rl", h)      # el logo oficial
        self.assertIn("#1433b4", h)             # el azul de marca

    def test_escapa_lo_que_viene_de_afuera(self):
        """Nombres de archivo y texto del cliente entran en un HTML."""
        from relevo import plantilla
        h = plantilla.componer_partner("<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", h)
        self.assertIn("&lt;script&gt;", h)

    def test_los_saltos_se_vuelven_br(self):
        from relevo import plantilla
        h = plantilla.componer_partner("linea uno\nlinea dos")
        self.assertIn("linea uno<br>linea dos", h)

    def test_no_deja_el_marcador_sin_reemplazar(self):
        from relevo import plantilla
        self.assertNotIn("CUERPO", plantilla.componer_partner("Hola"))


class EnviarAlPartner(Base):
    def setUp(self):
        super().setUp()
        from relevo import interruptores as sw
        self.sw = sw
        self.cfg = {"sw_envio_general": False}
        self._real = sw._config
        sw._config = lambda: self.cfg
        devolucion._buscar_caso = lambda cid: (CASO if cid == CASO["id"] else None, {})

    def tearDown(self):
        self.sw._config = self._real
        super().tearDown()

    def test_respeta_el_interruptor(self):
        """Va a un banco: no puede ser más flojo que escribirle a un cliente."""
        r = devolucion.enviar(CASO["id"], quien="ana@global66.com")
        self.assertFalse(r["enviado"])
        self.assertTrue(r["bloqueado"])
        self.assertIn("interruptor", r["error"])

    def test_exige_autor(self):
        self.cfg = {"sw_envio_general": True}
        r = devolucion.enviar(CASO["id"], quien="")
        self.assertFalse(r["enviado"])
        self.assertIn("quien es requerido", r["error"])
