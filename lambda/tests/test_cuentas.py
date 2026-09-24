# -*- coding: utf-8 -*-
"""`GET /search/accounts` — el mantenedor de cuentas internas.

LO QUE VIGILA ESTE ARCHIVO. El mantenedor tiene campos de texto libre que
terminan en una consulta a Redshift, así que la propiedad que hay que sostener
no es «devuelve las filas correctas» sino **el texto que escribe el analista
nunca entra en la sentencia**. Eso se puede romper con un solo cambio bien
intencionado —pasar de parámetro ligado a f-string porque «era más corto»— y
no falla, no avisa y no se ve en la pantalla.

Por eso los tests miran el SQL que sale, no sólo la respuesta: un test que sólo
compruebe el JSON pasaría igual con la versión insegura.

Los tres últimos son de otra cosa: que agregar esto no se lleve puesto nada de
lo que ya andaba.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_handler as A  # noqa: E402


class _Espia:
    """Se pone en lugar de `_rs_exec` y anota con qué lo llamaron."""

    def __init__(self, filas=None, revienta=None):
        self.filas = filas if filas is not None else []
        self.revienta = revienta
        self.sql = None
        self.params = None

    def __call__(self, sql, params=None):
        self.sql, self.params = sql, params
        if self.revienta:
            raise RuntimeError(self.revienta)
        return self.filas


def llamar(filtros, limite=200, filas=None, revienta=None):
    espia = _Espia(filas, revienta)
    original = A._rs_exec
    A._rs_exec = espia
    try:
        r = A.buscar_cuentas(filtros, limite)
    finally:
        A._rs_exec = original
    return r["statusCode"], json.loads(r["body"]), espia


class ElValorNoEntraEnElSQL(unittest.TestCase):
    """La única propiedad que no se puede perder."""

    def test_el_valor_viaja_ligado_y_no_en_el_texto(self):
        _, _, e = llamar({"cuenta": "GB00TCCL00000000000000"})
        self.assertNotIn("GB00TCCL00000000000000", e.sql,
                         "el valor quedó escrito dentro de la sentencia")
        self.assertEqual(e.params, {"cuenta": "GB00TCCL00000000000000"})
        self.assertIn(":cuenta", e.sql)

    def test_una_comilla_tampoco_llega_al_texto(self):
        veneno = "x'; DROP TABLE account; --"
        _, _, e = llamar({"cuenta": veneno})
        self.assertNotIn("DROP TABLE", e.sql)
        self.assertNotIn("'", e.sql.split("WHERE")[1],
                         "el WHERE no tiene que tener literales de texto")
        self.assertEqual(e.params["cuenta"], veneno)

    def test_sólo_se_puede_filtrar_por_las_columnas_declaradas(self):
        """Si el front manda un campo que no está en el diccionario, se
        ignora. Si no, el nombre de columna —que sí va al texto— lo elegiría
        quien llame a la API."""
        _, _, e = llamar({"cuenta": "GB42", "a.account_id) OR (1=1": "x"})
        self.assertNotIn("1=1", e.sql)
        self.assertEqual(set(e.params), {"cuenta"})


class LosFiltros(unittest.TestCase):

    def test_sin_ningun_filtro_no_consulta(self):
        """Sin WHERE esto recorre la tabla entera: se rechaza antes de salir."""
        codigo, cuerpo, e = llamar({})
        self.assertEqual(codigo, 400)
        self.assertIsNone(e.sql, "no tenía que haber llegado a la base")
        self.assertIn("filtro", cuerpo["error"].lower())

    def test_un_campo_en_blanco_es_como_no_mandarlo(self):
        codigo, _, e = llamar({"cuenta": "GB42", "moneda": "   "})
        self.assertEqual(codigo, 200)
        self.assertEqual(set(e.params), {"cuenta"})

    def test_dos_filtros_se_combinan_con_and(self):
        _, _, e = llamar({"cuenta": "GB42", "moneda": "EUR"})
        donde = e.sql.split("WHERE")[1].split("ORDER BY")[0]
        self.assertIn("AND", donde)
        self.assertIn("ba.bank_account_number = :cuenta", donde)
        self.assertIn("ag.currency_code = :moneda", donde)

    def test_los_filtros_vuelven_en_la_respuesta(self):
        """La pantalla tiene que poder mostrar sobre qué se buscó: una tabla
        sin decir de qué consulta salió es cómo se pega un resultado viejo en
        un informe."""
        _, cuerpo, _ = llamar({"cuenta": "GB42", "moneda": "EUR"})
        self.assertEqual(cuerpo["filters"], {"cuenta": "GB42", "moneda": "EUR"})


class ElTope(unittest.TestCase):

    def test_se_pide_una_fila_de_mas_para_saber_si_hay_mas(self):
        _, _, e = llamar({"cuenta": "GB42"}, limite=10)
        self.assertIn("LIMIT 11", e.sql)

    def test_avisa_cuando_cortó(self):
        filas = [{"cuenta": str(i)} for i in range(11)]
        _, cuerpo, _ = llamar({"cuenta": "GB42"}, limite=10, filas=filas)
        self.assertTrue(cuerpo["truncated"])
        self.assertEqual(cuerpo["count"], 10)
        self.assertEqual(len(cuerpo["rows"]), 10,
                         "la fila de sondeo no se devuelve")

    def test_no_avisa_cuando_no_cortó(self):
        filas = [{"cuenta": str(i)} for i in range(3)]
        _, cuerpo, _ = llamar({"cuenta": "GB42"}, limite=10, filas=filas)
        self.assertFalse(cuerpo["truncated"])

    def test_un_limite_absurdo_se_recorta(self):
        _, cuerpo, e = llamar({"cuenta": "GB42"}, limite=99999)
        self.assertEqual(cuerpo["limit"], A.CUENTAS_TOPE)
        self.assertIn(f"LIMIT {A.CUENTAS_TOPE + 1}", e.sql)

    def test_un_limite_que_no_es_numero_no_rompe(self):
        codigo, cuerpo, _ = llamar({"cuenta": "GB42"}, limite="ocho")
        self.assertEqual(codigo, 200)
        self.assertEqual(cuerpo["limit"], 200)


class CuandoLaBaseFalla(unittest.TestCase):

    def test_un_error_de_redshift_no_se_ve_como_cero_cuentas(self):
        """`_rs_exec_multi` devuelve [] cuando algo falla, y acá eso sería
        decir «esta cuenta no existe» sobre una cuenta que sí existe. En un
        requerimiento eso es una respuesta equivocada firmada por nosotros."""
        codigo, cuerpo, _ = llamar({"cuenta": "GB42"},
                                   revienta="cluster paused")
        self.assertEqual(codigo, 503)
        self.assertIn("paused", cuerpo["error"])
        self.assertNotIn("rows", cuerpo)


class NoRompeLoQueYaAndaba(unittest.TestCase):
    """`_rs_exec` ganó un argumento. Si ese argumento no fuera opcional, o si
    mandara `Parameters` vacío cuando no hay ninguno, se llevaría puestas las
    decenas de llamadas que ya existen."""

    def test_rs_exec_sigue_aceptando_una_sola_sentencia(self):
        import inspect
        firma = inspect.signature(A._rs_exec)
        self.assertEqual(list(firma.parameters), ["sql", "params"])
        self.assertIsNone(firma.parameters["params"].default)

    def test_sin_parametros_no_manda_el_campo_Parameters(self):
        """Redshift rechaza `Parameters: []`, así que una llamada de las
        viejas no puede terminar mandándolo."""
        visto = {}

        class _Cliente:
            def execute_statement(self, **kw):
                visto.update(kw)
                raise RuntimeError("corta acá: ya vimos lo que importaba")

        original = A.redshift_data
        A.redshift_data = _Cliente()
        try:
            with self.assertRaises(RuntimeError):
                A._rs_exec("SELECT 1")
        finally:
            A.redshift_data = original
        self.assertNotIn("Parameters", visto)

    def test_con_parametros_los_manda_con_la_forma_del_data_api(self):
        visto = {}

        class _Cliente:
            def execute_statement(self, **kw):
                visto.update(kw)
                raise RuntimeError("corta acá")

        original = A.redshift_data
        A.redshift_data = _Cliente()
        try:
            with self.assertRaises(RuntimeError):
                A._rs_exec("SELECT :x", {"x": 7})
        finally:
            A.redshift_data = original
        self.assertEqual(visto["Parameters"], [{"name": "x", "value": "7"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
