"""Tests del caso y del eje cliente.

Lo que importa acá son tres reglas de negocio:
  · el id del caso es estable, porque es la clave del registro de acciones y
    la que se va a espejar al CRM;
  · el estado sale de las acciones registradas, no de un campo mutable;
  · un cliente con varios casos recibe UN pedido, no varios.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from relevo import casos as C                       # noqa: E402


def tx(**kw):
    base = {"partner": "Nium", "llave": "nium_payout_id", "valor": "79360845",
            "crudo": "PY79360845", "caso_partner": "", "accionable": True,
            "items": [], "no_reconocido": [], "plazo": "", "resumen": "",
            "datos": {}, "correos": [], "ultima": "2026-09-06 10:00", "n_correos": 1,
            "cliente": None}
    base.update(kw)
    return base


def resuelto(cid=4098010, correo="cliente@ejemplo.cl", **extra):
    return {"estado": "encontrado", "verificacion": {},
            "cliente": {"cliente_id": cid, "cliente_nombre": "ACME SpA",
                        "cliente_correo": correo, **extra}}


class IdDelCaso(unittest.TestCase):
    def test_usa_el_caso_del_partner_cuando_viene(self):
        self.assertEqual(C.id_de(tx(caso_partner="1088170")), "nium:caso:1088170")

    def test_cae_a_la_transaccion_cuando_no_viene(self):
        """dLocal y OZ no mandan número de caso: ahí el caso ES la transacción."""
        self.assertEqual(C.id_de(tx(partner="dLocal", llave="rmt", valor="28172225")),
                         "dlocal:rmt:28172225")

    def test_es_estable_ante_lo_que_cambia_con_cada_correo(self):
        a = C.id_de(tx(caso_partner="1088170", ultima="2026-09-06 10:00", n_correos=1))
        b = C.id_de(tx(caso_partner="1088170", ultima="2026-09-07 18:00", n_correos=9))
        self.assertEqual(a, b)

    def test_normaliza_el_nombre_del_partner(self):
        self.assertTrue(C.id_de(tx(partner="OZ Câmbio", caso_partner="X")).startswith("oz-cambio:"))


class Agrupado(unittest.TestCase):
    def test_un_caso_del_partner_junta_sus_transacciones(self):
        """Es el caso real del cliente 3950037: seis transacciones, un pedido."""
        ts = [tx(caso_partner="1088170", valor=str(v), cliente=resuelto())
              for v in range(70000000, 70000006)]
        cs = C.construir(ts, acciones={})
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0]["n_transacciones"], 6)

    def test_los_items_se_unen_sin_repetir(self):
        ts = [
            tx(caso_partner="1", valor="a", cliente=resuelto(),
               items=[{"item": "documento_identidad", "es": "Documento"}]),
            tx(caso_partner="1", valor="b", cliente=resuelto(),
               items=[{"item": "documento_identidad", "es": "Documento"},
                      {"item": "origen_fondos", "es": "Origen"}]),
        ]
        c = C.construir(ts, acciones={})[0]
        self.assertEqual({i["item"] for i in c["items"]},
                         {"documento_identidad", "origen_fondos"})

    def test_del_plazo_gana_el_que_vence_primero(self):
        ts = [tx(caso_partner="1", valor="a", cliente=resuelto(), plazo="2026-09-20"),
              tx(caso_partner="1", valor="b", cliente=resuelto(), plazo="2026-09-12")]
        self.assertEqual(C.construir(ts, acciones={})[0]["plazo"], "2026-09-12")

    def test_avisa_si_el_caso_apunta_a_dos_clientes(self):
        """Sería señal de que el agrupado está mal, y hay que verlo, no taparlo."""
        ts = [tx(caso_partner="1", valor="a", cliente=resuelto(cid=1)),
              tx(caso_partner="1", valor="b", cliente=resuelto(cid=2))]
        c = C.construir(ts, acciones={})[0]
        self.assertTrue(any("dos clientes distintos" in a for a in c.get("alertas", [])))

    def test_transacciones_sin_caso_de_partner_no_se_mezclan(self):
        ts = [tx(partner="dLocal", llave="rmt", valor="1", cliente=resuelto()),
              tx(partner="dLocal", llave="rmt", valor="2", cliente=resuelto())]
        self.assertEqual(len(C.construir(ts, acciones={})), 2)


class Estado(unittest.TestCase):
    def test_sin_cliente_no_se_puede_pedir(self):
        self.assertEqual(C.construir([tx()], acciones={})[0]["estado"], "sin_cliente")

    def test_cliente_sin_correo_es_su_propio_estado(self):
        """Se arregla en la base, no en la extracción: por eso no es sin_cliente."""
        c = C.construir([tx(cliente=resuelto(correo=None))], acciones={})[0]
        self.assertEqual(c["estado"], "sin_correo")

    def test_no_accionable_es_informativo(self):
        c = C.construir([tx(accionable=False, cliente=resuelto())], acciones={})[0]
        self.assertEqual(c["estado"], "informativo")

    def test_con_cliente_y_correo_esta_listo(self):
        c = C.construir([tx(cliente=resuelto())], acciones={})[0]
        self.assertEqual(c["estado"], "listo_para_pedir")

    def test_la_accion_registrada_le_gana_a_lo_derivado(self):
        t = tx(cliente=resuelto())
        acc = {C.id_de(t): [{"accion": "pedido_enviado", "cuando": "2026-09-06T10:00:00"}]}
        self.assertEqual(C.construir([t], acciones=acc)[0]["estado"], "pedido_enviado")

    def test_entre_las_no_terminales_manda_la_ultima_en_el_tiempo(self):
        """El ciclo no es lineal: tras una respuesta parcial y un recontacto,
        la verdad es que estamos esperando de nuevo. Un max() por posición
        diría «el cliente ya respondió», que es falso."""
        t = tx(cliente=resuelto())
        acc = {C.id_de(t): [
            {"accion": "pedido_enviado", "cuando": "2026-09-01T10:00:00"},
            {"accion": "respuesta_parcial", "cuando": "2026-09-03T10:00:00"},
            {"accion": "recontactado", "cuando": "2026-09-05T10:00:00"},
        ]}
        self.assertEqual(C.construir([t], acciones=acc)[0]["estado"], "recontactado")

    def test_las_terminales_son_pegajosas(self):
        """Un caso cerrado no vuelve al ruedo porque alguien registre otra cosa."""
        t = tx(cliente=resuelto())
        acc = {C.id_de(t): [
            {"accion": "cerrado", "cuando": "2026-09-05T10:00:00"},
            {"accion": "recontactado", "cuando": "2026-09-06T10:00:00"},
        ]}
        self.assertEqual(C.construir([t], acciones=acc)[0]["estado"], "cerrado")


class Recontacto(unittest.TestCase):
    """El seguimiento se DERIVA de contar acciones: no hay campo que se
    desincronice con el histórico."""

    def caso(self, acciones, items=None):
        t = tx(cliente=resuelto(), items=items or [{"item": "documento_identidad", "es": "Doc"},
                                                   {"item": "origen_fondos", "es": "Origen"}])
        return C.construir([t], acciones={C.id_de(t): acciones})[0]

    def test_cuenta_los_intentos(self):
        c = self.caso([{"accion": "pedido_enviado", "cuando": "2026-09-01T10:00:00"},
                       {"accion": "recontactado", "cuando": "2026-09-04T10:00:00"}])
        self.assertEqual(c["seguimiento"]["intentos"], 2)

    def test_una_respuesta_no_cuenta_como_intento(self):
        c = self.caso([{"accion": "pedido_enviado", "cuando": "2026-09-01T10:00:00"},
                       {"accion": "respuesta_parcial", "cuando": "2026-09-02T10:00:00"}])
        self.assertEqual(c["seguimiento"]["intentos"], 1)

    def test_el_proximo_contacto_es_en_dias_habiles(self):
        """Pedido el viernes con política de 3 días: toca el miércoles, no el lunes."""
        c = self.caso([{"accion": "pedido_enviado", "cuando": "2026-09-11T10:00:00"}])
        self.assertTrue(c["seguimiento"]["proximo_contacto"].startswith("2026-09-16"))

    def test_marca_vencido_cuando_ya_pasó_la_fecha(self):
        c = self.caso([{"accion": "pedido_enviado", "cuando": "2020-01-06T10:00:00"}])
        self.assertTrue(c["seguimiento"]["vencido"])

    def test_no_calcula_proximo_contacto_si_el_caso_ya_no_espera(self):
        c = self.caso([{"accion": "pedido_enviado", "cuando": "2020-01-06T10:00:00"},
                       {"accion": "respuesta_recibida", "cuando": "2020-01-07T10:00:00"}])
        self.assertEqual(c["seguimiento"]["proximo_contacto"], "")
        self.assertFalse(c["seguimiento"]["vencido"])

    def test_agotado_al_llegar_al_maximo_de_intentos(self):
        acc = [{"accion": "pedido_enviado", "cuando": "2026-09-01T10:00:00"}]
        acc += [{"accion": "recontactado", "cuando": f"2026-09-0{d}T10:00:00"} for d in (4, 8)]
        self.assertTrue(self.caso(acc)["seguimiento"]["agotado"])

    def test_lo_que_falta_es_el_pedido_menos_lo_recibido(self):
        """Es lo que permite recontactar sólo por el resto y no por todo."""
        c = self.caso([{"accion": "pedido_enviado", "cuando": "2026-09-01T10:00:00"},
                       {"accion": "respuesta_parcial", "cuando": "2026-09-02T10:00:00",
                        "detalle": {"recibidos": ["documento_identidad"]}}])
        self.assertEqual([i["item"] for i in c["seguimiento"]["faltantes"]], ["origen_fondos"])

    def test_sin_respuestas_falta_todo_lo_pedido(self):
        c = self.caso([{"accion": "pedido_enviado", "cuando": "2026-09-01T10:00:00"}])
        self.assertEqual(len(c["seguimiento"]["faltantes"]), 2)

    def test_si_llego_todo_no_falta_nada(self):
        c = self.caso([{"accion": "pedido_enviado", "cuando": "2026-09-01T10:00:00"},
                       {"accion": "respuesta_recibida", "cuando": "2026-09-02T10:00:00",
                        "detalle": {"recibidos": ["documento_identidad", "origen_fondos"]}}])
        self.assertEqual(c["seguimiento"]["faltantes"], [])

    def test_una_accion_sobre_un_caso_sin_cliente_igual_vale(self):
        """El correo salió: es un hecho, aunque la consulta a la base falle después."""
        t = tx()
        acc = {C.id_de(t): [{"accion": "pedido_enviado", "cuando": "2026-09-06T10:00:00"}]}
        self.assertEqual(C.construir([t], acciones=acc)[0]["estado"], "pedido_enviado")


class Registro(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name) / "acciones.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_ida_y_vuelta(self):
        C.registrar("nium:caso:1", "pedido_enviado", quien="ben@g66.com", ruta=self.ruta)
        leidas = C.leer_acciones(self.ruta)
        self.assertEqual(leidas["nium:caso:1"][0]["quien"], "ben@g66.com")

    def test_solo_agrega_nunca_reescribe(self):
        C.registrar("c1", "pedido_enviado", ruta=self.ruta)
        C.registrar("c1", "respuesta_recibida", ruta=self.ruta)
        self.assertEqual(len(C.leer_acciones(self.ruta)["c1"]), 2)

    def test_rechaza_una_accion_inventada(self):
        with self.assertRaises(ValueError):
            C.registrar("c1", "enviar_paloma", ruta=self.ruta)

    def test_ignora_una_linea_a_medio_escribir(self):
        self.ruta.write_text('{"caso":"c1","accion":"cerrado","cuando":"x"}\n{"caso":"c\n',
                             encoding="utf-8")
        self.assertEqual(len(C.leer_acciones(self.ruta)), 1)


class EjeCliente(unittest.TestCase):
    def test_un_cliente_con_dos_casos_es_un_solo_pedido(self):
        ts = [tx(partner="dLocal", llave="rmt", valor="1", cliente=resuelto(cid=7),
                 items=[{"item": "documento_identidad", "es": "Documento"}]),
              tx(partner="dLocal", llave="rmt", valor="2", cliente=resuelto(cid=7),
                 items=[{"item": "origen_fondos", "es": "Origen"}])]
        g = C.por_cliente(C.construir(ts, acciones={}))
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["n_casos"], 2)
        self.assertEqual(len(g[0]["items"]), 2, "los ítems de los dos casos se unen")

    def test_los_casos_sin_cliente_no_entran(self):
        self.assertEqual(C.por_cliente(C.construir([tx()], acciones={})), [])

    def test_la_etapa_del_cliente_es_la_del_caso_menos_avanzado(self):
        """Lo que hay que mirar es si al cliente le falta algo, no si algo avanzó."""
        t1 = tx(partner="dLocal", llave="rmt", valor="1", cliente=resuelto(cid=7))
        t2 = tx(partner="dLocal", llave="rmt", valor="2", cliente=resuelto(cid=7))
        acc = {C.id_de(t1): [{"accion": "devuelto", "cuando": "2026-09-06T10:00:00"}]}
        g = C.por_cliente(C.construir([t1, t2], acciones=acc))[0]
        self.assertEqual(g["etapa"], C.ETAPA["listo_para_pedir"])

    def test_cuenta_lo_que_falta_pedir(self):
        t1 = tx(partner="dLocal", llave="rmt", valor="1", cliente=resuelto(cid=7))
        t2 = tx(partner="dLocal", llave="rmt", valor="2", cliente=resuelto(cid=7))
        acc = {C.id_de(t1): [{"accion": "pedido_enviado", "cuando": "2026-09-06T10:00:00"}]}
        g = C.por_cliente(C.construir([t1, t2], acciones=acc))[0]
        self.assertEqual(g["n_por_pedir"], 1)


if __name__ == "__main__":
    unittest.main()
