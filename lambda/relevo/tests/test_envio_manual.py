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

from relevo import casos, checklist, correo, envio, recepcion  # noqa: E402


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
        self._sw = {"envio_general": True}
        envio.interruptores = lambda: self._sw

    def tearDown(self):
        (envio.deposito, checklist.deposito, casos.deposito,
         recepcion.deposito) = self.previos


class LaPuertaDeAtrasNoEsMasFloja(Base):
    def test_respeta_el_interruptor_general(self):
        """Mandar a mano sigue siendo escribirle a un cliente real."""
        self._sw = {"envio_general": False}
        r = envio.registrar_manual(CASO["id"], quien="ana@global66.com", confirmado=True)
        self.assertFalse(r["registrado"])
        self.assertTrue(r["bloqueado"])
        self.assertIn("interruptor general", r["error"])

    def test_respeta_el_interruptor_del_partner(self):
        self._sw = {"envio_general": True, "envio_dlocal": False}
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
