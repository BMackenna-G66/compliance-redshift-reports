"""Envío a mano: el ciclo sin el scope de Gmail.

Lo que se prueba es que la puerta de atrás no sea más floja que la de adelante
—mismo interruptor, mismo bloqueo de doble envío, mismo autor obligatorio— y
que deje el rastro que la recepción necesita para correlacionar por token,
porque sin threadId el token es lo único que ata la respuesta al caso.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from relevo import (casos, checklist, correo, envio,  # noqa: E402
                    interruptores, recepcion)


class FalsoDeposito:
    def __init__(self):
        self.datos = {}
        self.BUCKET = "bucket-de-prueba"
        self.PREFIJO = "relevo"

    def activo(self):
        return True

    def clave_segura(self, v):
        return str(v).replace("/", "_").replace(":", "_")

    def obtener(self, col, clave):
        return self.datos.get((col, clave))

    def poner(self, col, clave, dato, solo_si_falta=False):
        self.datos[(col, clave)] = dato
        return True

    def todos(self, col, sub=""):
        pref = col.strip("/") + "/"
        return [v for (c, _), v in self.datos.items() if c == col or c.startswith(pref)]


CASO = {
    "id": "dlocal:rmt:28328978",
    "partner": "dLocal",
    "estado": "listo_para_pedir",
    "items": [{"item": "origen_fondos", "es": "Origen de los fondos"},
              {"item": "domicilio", "es": "Domicilio"}],
    "transacciones": [{"llave": "rmt", "valor": "28328978", "datos": {}}],
    "correos": [], "acciones": [], "plazo": "",
    "cliente": {"cliente_id": 1147449, "cliente_nombre": "Carlos Gonzalez",
                "cliente_correo": "caragova1985@gmail.com"},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.dep = FalsoDeposito()
        self.previos = (envio.deposito, checklist.deposito, casos.deposito,
                        recepcion.deposito)
        envio.deposito = checklist.deposito = casos.deposito = self.dep
        recepcion.deposito = self.dep
        # El caso y el interruptor, sin tocar la red.
        envio._buscar_caso = lambda cid: (CASO if cid == CASO["id"] else None, {})
        # Se parchea la FUENTE de la configuración, no `puede_enviar`: así los
        # tests ejercitan la lógica real del tablero (maestro, general y por
        # partner) en vez de un doble que podría no coincidir con ella.
        self.cfg = {"sw_envio_general": True}
        self._config_real = interruptores._config
        interruptores._config = lambda: self.cfg

    def tearDown(self):
        interruptores._config = self._config_real
        (envio.deposito, checklist.deposito, casos.deposito,
         recepcion.deposito) = self.previos


class LaPuertaDeAtrasNoEsMasFloja(Base):
    def test_respeta_el_interruptor_general(self):
        """Mandar a mano sigue siendo escribirle a un cliente real."""
        self.cfg = {"sw_envio_general": False}
        interruptores._config = lambda: self.cfg
        r = envio.registrar_manual(CASO["id"], quien="ana@global66.com", confirmado=True)
        self.assertFalse(r["registrado"])
        self.assertTrue(r["bloqueado"])
        self.assertIn("interruptor general", r["error"])

    def test_respeta_el_interruptor_del_partner(self):
        self.cfg = {"sw_envio_general": True, "sw_envio_dlocal": False}
        interruptores._config = lambda: self.cfg
        r = envio.registrar_manual(CASO["id"], quien="ana@global66.com", confirmado=True)
        self.assertFalse(r["registrado"])
        self.assertIn("dLocal", r["error"])

    def test_exige_autor(self):
        r = envio.registrar_manual(CASO["id"], quien="", confirmado=True)
        self.assertFalse(r["registrado"])
        self.assertIn("quien es requerido", r["error"])

    def test_sin_confirmar_compone_pero_no_registra(self):
        r = envio.registrar_manual(CASO["id"], quien="ana@global66.com")
        self.assertFalse(r["registrado"])
        self.assertTrue(r["requiere_confirmacion"])
        self.assertTrue(r["texto"])
        self.assertEqual(envio.solicitudes_de(CASO["id"]), [])
        self.assertEqual(checklist.resumen(CASO["id"])["total"], 0)

    def test_bloquea_el_doble_envio(self):
        envio.registrar_manual(CASO["id"], quien="ana@global66.com", confirmado=True)
        r = envio.registrar_manual(CASO["id"], quien="ana@global66.com", confirmado=True)
        self.assertFalse(r["registrado"])
        self.assertTrue(r["bloqueado"])
        self.assertIn("doble envío", r["error"])

    def test_no_registra_sin_correo_de_cliente(self):
        envio._buscar_caso = lambda cid: (dict(CASO, cliente={"cliente_id": 1}), {})
        r = envio.registrar_manual(CASO["id"], quien="ana@global66.com", confirmado=True)
        self.assertFalse(r["registrado"])
        self.assertIn("correo de cliente", r["error"])


class DejaElRastroQueLaRecepcionNecesita(Base):
    def setUp(self):
        super().setUp()
        self.r = envio.registrar_manual(CASO["id"], quien="ana@global66.com", confirmado=True)

    def test_registra_la_solicitud_como_enviada(self):
        self.assertTrue(self.r["registrado"])
        ss = envio.solicitudes_de(CASO["id"])
        self.assertEqual(len(ss), 1)
        self.assertTrue(ss[0]["enviado"])
        self.assertEqual(ss[0]["thread_id"], "")   # no lo mandamos nosotros
        self.assertEqual(ss[0]["ref"], self.r["ref"])

    def test_arma_el_checklist_todo_pendiente(self):
        res = checklist.resumen(CASO["id"])
        self.assertEqual(res["total"], 2)
        self.assertEqual(res[checklist.PENDIENTE], 2)
        self.assertEqual(res[checklist.ENTREGADO], 0)

    def test_anota_la_accion_con_el_medio(self):
        acc = casos.leer_acciones().get(CASO["id"]) or []
        self.assertEqual([a["accion"] for a in acc], ["pedido_enviado"])
        self.assertEqual(acc[0]["detalle"]["medio"], "manual")
        self.assertEqual(acc[0]["quien"], "ana@global66.com")

    def test_la_respuesta_correlaciona_POR_TOKEN_sin_thread_id(self):
        """Es la pieza que sostiene todo el camino manual: sin threadId, el
        token del asunto tiene que alcanzar para atar la respuesta al caso."""
        asunto = correo.asunto_de(self.r["ref"])
        mensaje = {"id": "m-respuesta", "thread_id": "hilo-que-no-conocemos",
                   "asunto": f"Re: {asunto}", "headers": {"From": "cliente@example.com"}}
        caso_id, via = recepcion.correlacionar(mensaje)
        self.assertEqual(caso_id, CASO["id"])
        self.assertEqual(via, "token")

    def test_un_asunto_editado_por_el_cliente_pierde_la_correlacion(self):
        """Documenta el costo real de no mandar por API: si el cliente borra
        el token y no hay threadId, no queda por dónde atarlo. Por eso la
        pantalla insiste en no editar el asunto."""
        mensaje = {"id": "m2", "thread_id": "otro", "asunto": "Documentos adjuntos",
                   "headers": {"From": "cliente@example.com"}}
        caso_id, via = recepcion.correlacionar(mensaje)
        self.assertIsNone(caso_id)
        self.assertEqual(via, "")

    def test_dice_desde_donde_mandarlo(self):
        self.assertEqual(self.r["enviar_desde"], "compliance@global66.com")
        self.assertTrue(any("bandeja" in i for i in self.r["instrucciones"]))


class TratoSegunElCliente(unittest.TestCase):
    def test_una_empresa_recibe_trato_de_usted(self):
        c = correo.componer(dict(CASO, cliente={
            "cliente_id": 1, "cliente_nombre": "POWERLAND LLC", "cliente_correo": "a@b.com"}))
        self.assertIn("Estimados", c["texto"])
        self.assertIn("sus operaciones", c["texto"])
        self.assertNotIn("tus operaciones", c["texto"])
        self.assertTrue(any("parece una empresa" in a for a in c["avisos"]))

    def test_una_persona_conserva_el_texto_de_siempre(self):
        c = correo.componer(CASO)
        self.assertIn("Hola Carlos Gonzalez,", c["texto"])
        self.assertIn("tus operaciones", c["texto"])
        self.assertFalse(any("parece una empresa" in a for a in c["avisos"]))

    def test_la_deteccion_no_confunde_personas_con_empresas(self):
        personas = ["Robert Hernando Ruiz Herrera", "Ana Sacnun", "Luis Sanchez",
                    "Michelle Juliette Gerdel Castellanos", "Nataly Yepes Pinilla"]
        empresas = ["POWERLAND LLC", "BLESS CORP SPA", "Comercial Latam Ltda",
                    "Nataly Yepes Pinilla SAS", "VEEM INC", "COMECIAL Y SERVICIOS SPA"]
        for n in personas:
            self.assertFalse(correo.es_empresa(n), n)
        for n in empresas:
            self.assertTrue(correo.es_empresa(n), n)


if __name__ == "__main__":
    unittest.main()


class UnPedidoVacioNoSale(Base):
    """43 de 146 casos accionables (29%) no tienen ni un ítem del catálogo, y
    16 estaban en `listo_para_pedir`. Sin bloqueo, el correo salía igual."""

    SIN_NADA = {**CASO, "items": [], "no_reconocido": [],
                "resumen": "OZ Câmbio abrió un requerimiento y no se pudo extraer "
                           "qué pide. Hay que leer el correo."}

    def test_el_resumen_interno_NO_llega_al_cuerpo(self):
        c = correo.componer(self.SIN_NADA)
        self.assertEqual(c["items_catalogo"], [])
        self.assertEqual(c["items_crudo"], [])
        self.assertNotIn("no se pudo extraer", c["texto"])
        self.assertNotIn("Hay que leer el correo", c["texto"])
        self.assertNotIn("no se pudo extraer", c["html"])

    def test_las_lineas_del_partner_NO_llegan_al_correo(self):
        """Se devuelven para que la PANTALLA las muestre, pero no se componen
        en el cuerpo: son texto libre, y §8 dice que el pedido sale del
        catálogo. Los casos reales tenían firmas ajenas, metadata de Zendesk
        y CSS suelto ahí adentro."""
        caso = {**self.SIN_NADA,
                "no_reconocido": ["Ma. Carla D. Alarde", "[KKJL2N-9ZN3M]",
                                  "body[dir=rt"]}
        c = correo.componer(caso)
        self.assertEqual(len(c["items_crudo"]), 3)      # la pantalla sí los ve
        for basura in ("Ma. Carla D. Alarde", "KKJL2N-9ZN3M", "body[dir=rt"):
            self.assertNotIn(basura, c["texto"], basura)
            self.assertNotIn(basura, c["html"], basura)

    def test_con_crudo_pero_sin_catalogo_TAMPOCO_se_manda(self):
        envio._buscar_caso = lambda cid: (
            {**self.SIN_NADA, "no_reconocido": ["Ma. Carla D. Alarde"]}, {})
        r = envio.enviar(self.SIN_NADA["id"], quien="ana@global66.com")
        self.assertFalse(r["enviado"])
        self.assertTrue(r["bloqueado"])
        self.assertIn("catálogo", r["error"])

    def test_enviar_lo_bloquea(self):
        envio._buscar_caso = lambda cid: (self.SIN_NADA, {})
        r = envio.enviar(self.SIN_NADA["id"], quien="ana@global66.com")
        self.assertFalse(r["enviado"])
        self.assertTrue(r["bloqueado"])
        self.assertIn("ningún documento del catálogo", r["error"])

    def test_el_envio_a_mano_tambien_lo_bloquea(self):
        envio._buscar_caso = lambda cid: (self.SIN_NADA, {})
        r = envio.registrar_manual(self.SIN_NADA["id"], quien="ana@global66.com",
                                   confirmado=True)
        self.assertFalse(r["registrado"])
        self.assertTrue(r["bloqueado"])

    def test_se_puede_saltar_a_proposito_con_revisado(self):
        """Quien redactó el pedido a mano se hace cargo."""
        envio._buscar_caso = lambda cid: (self.SIN_NADA, {})
        ok, _ = envio.hay_algo_que_pedir(correo.componer(self.SIN_NADA))
        self.assertFalse(ok)
        r = envio.registrar_manual(self.SIN_NADA["id"], quien="ana@global66.com",
                                   confirmado=True, revisado=True)
        self.assertTrue(r["registrado"])

    def test_un_caso_con_items_no_se_bloquea(self):
        ok, motivo = envio.hay_algo_que_pedir(correo.componer(CASO))
        self.assertTrue(ok)
        self.assertEqual(motivo, "")


class FormatoCorporativo(unittest.TestCase):
    """El correo sale con la plantilla oficial, la misma del ciclo AML.

    Dos diseños distintos que dicen ser Global66 es exactamente lo que un
    cliente no puede distinguir de un phishing.
    """

    CASO = {**CASO, "plazo": "8 de septiembre de 2026"}

    def _html(self, nombre):
        from relevo import plantilla
        plantilla._cache = None
        return correo.componer({**self.CASO, "cliente": {
            "cliente_id": 1, "cliente_nombre": nombre,
            "cliente_correo": "a@b.com"}})["html"]

    def test_usa_la_plantilla_oficial(self):
        from relevo import plantilla
        self.assertTrue(plantilla.disponible(), "base.html no viajó en el paquete")
        self.assertIn("Equipo Global66", self._html("Ana Perez"))

    def test_no_deja_marcadores_sin_reemplazar(self):
        """Un correo que le llega al cliente diciendo "TEXTO LIBRE" o
        "{!Account.first_name__c}" es peor que uno feo."""
        for nombre in ("Ana Perez", "MACKENNA SOLUCIONES SPA"):
            h = self._html(nombre)
            from relevo import plantilla
            self.assertFalse(plantilla.quedan_marcadores(h), nombre)
            self.assertNotIn("TEXTO LIBRE", h)
            self.assertNotIn("{!", h)

    def test_el_contenido_entra_en_la_plantilla(self):
        h = self._html("Ana Perez")
        self.assertIn("Origen de los fondos", h)
        self.assertIn("8 de septiembre de 2026", h)
        self.assertIn("Ana Perez", h)

    def test_una_empresa_conserva_el_trato_de_usted(self):
        h = self._html("MACKENNA SOLUCIONES SPA")
        for formal in ("Estimados de", "su respuesta", "envíen", "Tienen dudas"):
            self.assertIn(formal, h, formal)
        self.assertNotIn("Quedamos atentos a tu respuesta", h)

    def test_una_persona_conserva_el_tuteo_de_la_plantilla(self):
        h = self._html("Ana Perez")
        self.assertIn("Hola Ana Perez,", h)
        self.assertIn("Quedamos atentos a tu respuesta", h)
        # La plantilla habla de tú; "Mantené" es voseo y se notaba la mezcla.
        self.assertNotIn("Mantené", h)

    def test_el_nombre_se_escapa(self):
        """El nombre viene de la base y entra en un HTML."""
        h = self._html("<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", h)
        self.assertIn("&lt;script&gt;", h)

    def test_sin_plantilla_cae_al_formato_propio_y_no_rompe(self):
        """Si base.html no viaja en el paquete, el correo sale feo pero sale:
        un correo que no sale frena un caso."""
        from relevo import plantilla
        real, plantilla.RUTA = plantilla.RUTA, Path("/no/existe.html")
        plantilla._cache = None
        try:
            c = correo.componer(self.CASO)
            self.assertTrue(c["html"])
            self.assertIn("Origen de los fondos", c["html"])
        finally:
            plantilla.RUTA = real
            plantilla._cache = None

    def test_lo_inyectado_es_SOLO_contenido_en_linea(self):
        """El hueco de la plantilla vive dentro de un <p> y un <span>:

            <p style="…"><span style="…">TEXTO LIBRE<br>…</span></p>

        Un <p>, una <table> o un <ol> ahí adentro son HTML inválido — el
        navegador cierra el párrafo por su cuenta y el bloque se escapa del
        contenedor con estilo, perdiendo tipografía y color. En Outlook, para
        el que está hecha la plantilla, se rompe peor. Mi primera versión
        inyectaba los tres.

        Es el mismo contrato que respeta el renderizador de WatchTower, que
        inyecta sólo texto escapado con <br>.
        """
        import re
        from relevo import plantilla
        b = plantilla.bloque(
            datos=[("Monto", "1500.00")], catalogo=["Origen de los fondos"],
            plazo="8 de septiembre", nota="Nota.", empresa=False)
        etiquetas = set(re.findall(r"</?(\w+)", b))
        BLOQUE = {"p", "table", "tr", "td", "ol", "ul", "li", "div",
                  "h1", "h2", "h3", "blockquote"}
        self.assertEqual(etiquetas & BLOQUE, set(),
                         f"bloque() generó etiquetas de bloque: {etiquetas & BLOQUE}")
        self.assertTrue(etiquetas <= {"br", "strong", "em", "span", "a"}, etiquetas)

    def test_el_marcador_sigue_dentro_de_un_parrafo(self):
        """Si la plantilla cambiara y el hueco pasara a ser un contenedor de
        bloque, el test de arriba estaría cuidando algo que ya no aplica."""
        from relevo import plantilla
        html = plantilla.cargar()
        i = html.index(plantilla.MARCA_TEXTO)
        self.assertIn("<span", html[max(0, i - 200):i])
        self.assertIn("<p ", html[max(0, i - 400):i])
