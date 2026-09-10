"""El tablero de interruptores.

Lo que más importa acá no es que prendan y apaguen: es que las **dos clases
tengan semántica opuesta ante un fallo de configuración**. Un `envio_general`
que falla abierto manda correos que nadie autorizó; una `ingesta` que falla
cerrada deja el módulo ciego sin que nadie se entere. Confundirlas es el
error caro, así que va con test.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from relevo import interruptores as sw  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.cfg = {}
        self.real = sw._config
        sw._config = lambda: self.cfg

    def tearDown(self):
        sw._config = self.real


class ValoresPorDefecto(Base):
    def test_los_procesos_arrancan_PRENDIDOS(self):
        """Sólo leen: apagarlos por defecto dejaría el módulo muerto."""
        for p in ("ingesta", "vista", "resolucion", "recepcion", "espejo"):
            self.assertTrue(sw.valor(p), p)

    def test_el_envio_arranca_APAGADO(self):
        """§8: nadie le escribe a un cliente sin que alguien lo habilite."""
        self.assertFalse(sw.valor("envio_general"))

    def test_el_maestro_arranca_prendido(self):
        self.assertTrue(sw.valor("modulo"))

    def test_un_partner_sin_interruptor_propio_no_esta_declarado(self):
        """None ≠ False: "no declarado" significa que sigue al general."""
        self.assertIsNone(sw.valor("envio_dlocal"))


class SemanticaOpuestaAnteUnFallo(Base):
    def test_un_proceso_falla_ABIERTO(self):
        """Que S3 tosa no puede dejar la casilla sin leer durante horas."""
        def revienta():
            raise RuntimeError("S3 caído")
        sw._config = revienta
        ok, motivo = sw.puede_correr("ingesta")
        self.assertTrue(ok)
        self.assertEqual(motivo, "")

    def test_el_envio_falla_CERRADO(self):
        """Ante la duda no se le escribe a un cliente real."""
        def revienta():
            raise RuntimeError("S3 caído")
        sw._config = revienta
        with self.assertRaises(RuntimeError):
            sw.puede_salir("dLocal")


class ElMaestro(Base):
    def test_apaga_los_procesos(self):
        self.cfg = {"sw_modulo": False}
        ok, motivo = sw.puede_correr("ingesta")
        self.assertFalse(ok)
        self.assertIn("maestro", motivo)

    def test_apaga_el_envio_aunque_el_general_este_prendido(self):
        self.cfg = {"sw_modulo": False, "sw_envio_general": True}
        ok, motivo = sw.puede_salir()
        self.assertFalse(ok)
        self.assertIn("maestro", motivo)

    def test_prendido_no_estorba(self):
        self.cfg = {"sw_modulo": True, "sw_envio_general": True}
        self.assertTrue(sw.puede_salir()[0])
        self.assertTrue(sw.puede_correr("vista")[0])


class PorPartner(Base):
    def test_apagar_uno_no_apaga_los_demas(self):
        self.cfg = {"sw_envio_general": True, "sw_envio_dlocal": False}
        self.assertFalse(sw.puede_salir("dLocal")[0])
        self.assertTrue(sw.puede_salir("Nium")[0])
        self.assertTrue(sw.puede_salir("Currencycloud")[0])

    def test_el_general_apagado_gana_sobre_el_partner_prendido(self):
        self.cfg = {"sw_envio_general": False, "sw_envio_dlocal": True}
        ok, motivo = sw.puede_salir("dLocal")
        self.assertFalse(ok)
        self.assertIn("general", motivo)

    def test_el_nombre_del_partner_se_normaliza(self):
        self.cfg = {"sw_envio_general": True, "sw_envio_oz_câmbio": False}
        self.assertEqual(sw.clave_partner("OZ Câmbio"), "envio_oz_câmbio")
        self.assertFalse(sw.puede_salir("OZ Câmbio")[0])


class Compatibilidad(Base):
    def test_lee_el_diccionario_viejo(self):
        """Lo guardado antes de que existiera este archivo sigue valiendo."""
        self.cfg = {"interruptores": {"envio_general": True}}
        self.assertTrue(sw.valor("envio_general"))
        self.assertTrue(sw.puede_salir()[0])

    def test_la_clave_individual_manda_sobre_el_diccionario_viejo(self):
        self.cfg = {"interruptores": {"envio_general": True},
                    "sw_envio_general": False}
        self.assertFalse(sw.valor("envio_general"))


class Escritura(Base):
    def test_exige_autor(self):
        r = sw.cambiar("ingesta", False, quien="")
        self.assertIn("error", r)
        self.assertIn("quien es requerido", r["error"])

    def test_rechaza_una_clave_inventada(self):
        """Un typo en el front no puede crear un interruptor fantasma que
        nadie mira y que no apaga nada."""
        r = sw.cambiar("enviooo_general", False, quien="ana@global66.com")
        self.assertIn("error", r)
        self.assertIn("desconocido", r["error"])

    def test_acepta_las_claves_del_catalogo(self):
        declaradas = sw.declarados()
        for c in ("modulo", "ingesta", "vista", "resolucion", "recepcion",
                  "espejo", "envio_general"):
            self.assertIn(c, declaradas, c)


class Catalogo(unittest.TestCase):
    def test_cada_interruptor_dice_que_pasa_al_apagarlo(self):
        """La pantalla muestra esto. Un interruptor sin consecuencia escrita
        es un interruptor que alguien va a apretar sin saber qué hace."""
        for i in sw.CATALOGO:
            self.assertTrue(i.get("etiqueta"), i["clave"])
            self.assertTrue(i.get("descripcion"), i["clave"])
            self.assertTrue(i.get("al_apagar"), i["clave"])
            self.assertIn(i.get("tipo"), (sw.PROCESO, sw.SALIDA, sw.MAESTRO))

    def test_no_hay_claves_repetidas(self):
        claves = [i["clave"] for i in sw.catalogo_completo()]
        self.assertEqual(len(claves), len(set(claves)))

    def test_los_cinco_procesos_estan(self):
        procesos = {i["clave"] for i in sw.CATALOGO if i["tipo"] == sw.PROCESO}
        self.assertEqual(procesos, {"ingesta", "vista", "resolucion",
                                    "recepcion", "espejo"})


if __name__ == "__main__":
    unittest.main()
