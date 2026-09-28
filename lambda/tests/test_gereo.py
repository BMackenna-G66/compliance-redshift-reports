# -*- coding: utf-8 -*-
"""El cliente de la API de GEREO.

LO QUE VIGILA, en orden de qué duele más si se rompe:

1. **Que la clave no termine en el repo.** Es público. Una clave escrita en
   el código hay que rotarla el mismo día y la integración se corta.

2. **Que no se loguee la respuesta.** Trae nombre, documento, dirección y
   teléfono de personas reales más el detalle de sus operaciones. Un `print`
   del response completo queda en CloudWatch por años.

3. **Que `es_detencion` no se trate como error.** GEREO responde 200 cuando
   el cliente existe pero es de otro país. Es la regla de negocio
   funcionando; contarlo como falla llenaría el tablero de errores que no lo
   son, y reintentarlo da exactamente lo mismo.

4. **Que sólo el 503 se reintente.** Un 404 y un 422 no mejoran insistiendo.

5. **Que la matriz por país se valide antes de salir a la red.** GEREO
   rechaza igual, pero con un viaje a su base de datos —la misma que atiende
   la pantalla de sus analistas— para decirnos algo que ya sabíamos.
"""
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gereo as G  # noqa: E402


def _respuesta(cuerpo):
    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return _R(json.dumps(cuerpo).encode())


def abrir_con(cuerpo):
    visto = {}

    def abrir(req, timeout=None):
        visto["url"] = req.full_url
        visto["headers"] = dict(req.headers)
        visto["cuerpo"] = json.loads(req.data) if req.data else None
        visto["timeout"] = timeout
        return _respuesta(cuerpo)
    abrir.visto = visto
    return abrir


def abrir_error(codigo, cuerpo):
    def abrir(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, codigo, "err", {},
            io.BytesIO(json.dumps(cuerpo).encode()))
    return abrir


class LaClaveNoVaEnElCodigo(unittest.TestCase):

    def test_el_modulo_no_trae_ninguna_clave_escrita(self):
        fuente = Path(G.__file__).read_text(encoding="utf-8")
        self.assertIn("get_secret_value", fuente,
                      "la clave sale de Secrets Manager")
        # Nada con pinta de clave: el repo es público.
        for sospechoso in ("X-API-Key: ", "wt_", "gereo_key ="):
            self.assertNotIn(sospechoso + "e", fuente)

    def test_viaja_en_el_header_y_no_en_la_url(self):
        G._clave_cache = "clave-de-prueba"
        abrir = abrir_con({"estado": "ok"})
        G.salud(abrir=abrir)
        self.assertEqual(abrir.visto["headers"].get("X-api-key"), "clave-de-prueba")
        self.assertNotIn("clave-de-prueba", abrir.visto["url"])

    def test_sin_clave_no_sale_a_la_red(self):
        G._clave_cache = ""
        os.environ.pop("GEREO_API_KEY", None)

        def no_llamar(req, timeout=None):
            raise AssertionError("no tenía que haber salido a la red")
        with self.assertRaises(G.ErrorGereo):
            G.salud(abrir=no_llamar)


class NoSeLogueaLaRespuesta(unittest.TestCase):
    """Un `print` del response completo vive años en CloudWatch."""

    def test_no_se_imprime_el_cuerpo_en_ningun_lado(self):
        fuente = Path(G.__file__).read_text(encoding="utf-8")
        for linea in fuente.splitlines():
            if "print(" not in linea:
                continue
            for prohibido in ("{d}", "{crudo}", "{cuerpo}", "{doc}", "{resp"):
                self.assertNotIn(prohibido, linea,
                                 f"esta línea loguea el cuerpo: {linea.strip()}")


class LaDetencionNoEsUnError(unittest.TestCase):

    def test_un_cliente_de_otro_pais_devuelve_detenido(self):
        G._clave_cache = "k"
        abrir = abrir_con({
            "estado": "DETENIDO_PAIS_NO_CHILE", "es_detencion": True,
            "mensaje": "El país de origen del cliente '9999999' es 'PE'."})
        d = G.generar_ros({"pais": "Chile", "customer_id": "9999999",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                          abrir=abrir)
        self.assertTrue(d["detenido"])
        self.assertIn("PE", d["mensaje"])

    def test_no_levanta_excepcion(self):
        """Si fuera excepción, el tablero lo contaría como falla de la API."""
        G._clave_cache = "k"
        abrir = abrir_con({"estado": "DETENIDO_PAIS_NO_CHILE",
                           "es_detencion": True, "mensaje": "x"})
        G.generar_ros({"pais": "Chile", "customer_id": "1",
                       "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                      abrir=abrir)   # no tiene que tirar


class SoloElQuinientosTresSeReintenta(unittest.TestCase):

    def _error(self, codigo, cuerpo=None):
        G._clave_cache = "k"
        try:
            G.salud(abrir=abrir_error(codigo, cuerpo or {}))
        except G.ErrorGereo as e:
            return e
        raise AssertionError("tenía que fallar")

    def test_el_503_si(self):
        self.assertTrue(self._error(503).reintentable)

    def test_el_404_no(self):
        """«Ese cliente no existe» no mejora insistiendo."""
        self.assertFalse(self._error(404).reintentable)

    def test_el_422_no_y_dice_qué_campo(self):
        e = self._error(422, {"estado": "OPCION_INVALIDA",
                              "campo": "clientes_asociados",
                              "mensaje": "no admite clientes asociados."})
        self.assertFalse(e.reintentable)
        self.assertEqual(e.campo, "clientes_asociados")

    def test_el_401_avisa_que_es_la_clave(self):
        e = self._error(401)
        self.assertIn("clave", e.mensaje.lower())

    def test_un_corte_de_red_si_se_reintenta(self):
        G._clave_cache = "k"

        def cae(req, timeout=None):
            raise TimeoutError("se cortó")
        with self.assertRaises(G.ErrorGereo) as c:
            G.salud(abrir=cae)
        self.assertTrue(c.exception.reintentable)


class LaMatrizPorPaisSeValidaAntes(unittest.TestCase):
    """GEREO lo rechaza igual, pero con un viaje a su base de datos."""

    def base(self, **kw):
        d = {"pais": "Chile", "customer_id": "1", "tipo_cliente": "B2C",
             "fecha_inicio": "01/2025"}
        d.update(kw)
        return d

    def test_argentina_no_admite_b2b(self):
        faltan = G.validar(self.base(pais="Argentina", tipo_cliente="B2B"))
        self.assertTrue(any("B2C" in f for f in faltan))

    def test_argentina_no_admite_asociados(self):
        faltan = G.validar(self.base(pais="Argentina",
                                     clientes_asociados=["2"]))
        self.assertTrue(any("asociados" in f for f in faltan))

    def test_colombia_no_admite_asociados(self):
        faltan = G.validar(self.base(pais="Colombia",
                                     clientes_asociados=["2"]))
        self.assertTrue(any("único cliente" in f for f in faltan))

    def test_chile_admite_hasta_quince(self):
        self.assertEqual(
            G.validar(self.base(clientes_asociados=[str(i) for i in range(15)])),
            [])
        self.assertTrue(
            G.validar(self.base(clientes_asociados=[str(i) for i in range(16)])))

    def test_un_pais_de_fuera_se_rechaza(self):
        self.assertTrue(G.validar(self.base(pais="Perú")))

    def test_la_fecha_tiene_que_ser_mes_y_anio(self):
        self.assertTrue(G.validar(self.base(fecha_inicio="2025-01")))
        self.assertTrue(G.validar(self.base(fecha_inicio="13/2025")))
        self.assertEqual(G.validar(self.base(fecha_inicio="12/2025")), [])

    def test_no_sale_a_la_red_si_el_pedido_esta_mal(self):
        G._clave_cache = "k"

        def no_llamar(req, timeout=None):
            raise AssertionError("no tenía que salir")
        with self.assertRaises(G.ErrorGereo):
            G.generar_ros(self.base(pais="Colombia",
                                    clientes_asociados=["2"]), abrir=no_llamar)


class ElCuerpoQueSeManda(unittest.TestCase):

    def test_natural_y_juridica_se_normalizan(self):
        self.assertEqual(G.normalizar_tipo("natural"), "B2C")
        self.assertEqual(G.normalizar_tipo("juridica"), "B2B")
        self.assertEqual(G.normalizar_tipo("b2b"), "B2B")

    def test_los_campos_opcionales_no_viajan_vacios(self):
        c = G.cuerpo_para({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"})
        self.assertNotIn("fecha_fin", c)
        self.assertNotIn("clientes_asociados", c)
        self.assertNotIn("incluir_pdf", c)

    def test_el_pdf_solo_si_se_pide(self):
        """Armarlo le suma segundos a cada llamada."""
        c = G.cuerpo_para({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025",
                           "incluir_pdf": True})
        self.assertTrue(c["incluir_pdf"])

    def test_los_asociados_aceptan_texto_separado_por_coma(self):
        c = G.cuerpo_para({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025",
                           "clientes_asociados": "2, 3 ,4"})
        self.assertEqual(c["clientes_asociados"], ["2", "3", "4"])

    def test_el_timeout_es_generoso(self):
        """El documento pide 60 s o más: un ROS consulta, evalúa y redacta."""
        self.assertGreaterEqual(G.TIMEOUT_ROS, 60)


class LoQueSeDevuelve(unittest.TestCase):

    RESPUESTA = {
        "estado": "OK",
        "opciones": {"pais": "Chile", "meses": 6},
        "ros_doc": {
            "meta": {"advertencias": ["La 'Temática' queda sin seleccionar."]},
            "reglas": [{"id": "R01", "gatillada": False}],
        },
        "senales": [],
        "pdf_base64": None,
    }

    def test_las_advertencias_suben_al_primer_nivel(self):
        """Es lo que el analista tiene que ver primero, no una nota al pie
        escondida en meta."""
        G._clave_cache = "k"
        d = G.generar_ros({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                          abrir=abrir_con(self.RESPUESTA))
        self.assertEqual(len(d["advertencias"]), 1)
        self.assertIn("Temática", d["advertencias"][0])

    def test_se_guarda_el_eco_de_las_opciones(self):
        """Es el registro de con qué parámetros se emitió, incluido el mes de
        término que GEREO resuelve solo."""
        G._clave_cache = "k"
        d = G.generar_ros({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                          abrir=abrir_con(self.RESPUESTA))
        self.assertEqual(d["opciones"]["meses"], 6)

    def test_senales_y_reglas_son_cosas_distintas(self):
        """`senales` son las gatilladas; `ros_doc.reglas`, todas las
        evaluadas. La diferencia entre «esto disparó» y «esto se miró y no
        disparó» es justo lo que se audita."""
        G._clave_cache = "k"
        d = G.generar_ros({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                          abrir=abrir_con(self.RESPUESTA))
        self.assertEqual(d["senales"], [])
        self.assertEqual(len(d["ros_doc"]["reglas"]), 1)


class ElPaisYElReguladorSonLoMismo(unittest.TestCase):
    """`ros.py` trabaja con reguladores y GEREO con países. Si los dos mapas
    se separan, un ROS de Chile terminaría pidiéndose a la UIF argentina."""

    def test_los_tres_reguladores_de_ros_tienen_pais(self):
        import ros as R
        for codigo in R.REGULADORES:
            self.assertIn(codigo, G.PAIS_POR_REGULADOR,
                          f"{codigo} no tiene país en el cliente de GEREO")

    def test_y_los_paises_coinciden(self):
        import ros as R
        for codigo, pais in G.PAIS_POR_REGULADOR.items():
            self.assertEqual(R.REGULADORES[codigo]["pais"], pais)


if __name__ == "__main__":
    unittest.main(verbosity=2)
