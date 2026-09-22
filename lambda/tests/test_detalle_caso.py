# -*- coding: utf-8 -*-
"""El detalle de un caso devuelve los campos del plazo.

POR QUÉ IMPORTA. `GET /cases` los calculaba y `GET /cases/{id}` no, así que el
detalle del front nuevo tenía que pedir además la lista COMPLETA —77 KB y 3,5
segundos— sólo para saber en qué punto del plazo estaba el caso que ya tenía
en pantalla.

Recalcularlo del lado del front no era opción: el plazo es una regla de
compliance, y dos definiciones del mismo plazo terminan en una pantalla que
dice «en plazo» sobre un caso que el sistema considera vencido.

Lo que estos tests vigilan es que las DOS rutas cuenten igual. Si se separan,
la lista y el detalle del mismo caso van a mostrar semáforos distintos, y nada
va a fallar: simplemente van a discrepar.
"""
import ast
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
API = RAIZ / "lambda" / "api_handler.py"


def _cuerpo(nombre: str) -> str:
    """El código de una función, leído sin importar el módulo."""
    texto = API.read_text(encoding="utf-8")
    for nodo in ast.parse(texto).body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
            return ast.get_source_segment(texto, nodo)
    raise AssertionError(f"no encontré {nombre}")


def _llamadas(nombre: str) -> set:
    """Los nombres de las funciones que `nombre` LLAMA.

    Se leen del árbol y no del texto: un comentario que menciona una función
    no es una llamada a esa función, y buscar la cadena a ojo confunde las dos
    cosas — este mismo test se rompió así.
    """
    llamadas = set()
    for nodo in ast.walk(ast.parse(_cuerpo(nombre))):
        if isinstance(nodo, ast.Call):
            f = nodo.func
            if isinstance(f, ast.Name):
                llamadas.add(f.id)
            elif isinstance(f, ast.Attribute):
                llamadas.add(f.attr)
    return llamadas


class ElDetalleTraeElPlazo(unittest.TestCase):

    def test_el_detalle_evalua_el_plazo(self):
        cuerpo = _cuerpo("get_case_detail")
        self.assertIn("sla_casos.evaluar(", cuerpo,
                      "el detalle tiene que calcular los campos del plazo")

    def test_devuelve_la_configuracion_del_plazo(self):
        """La lista la manda y el detalle también: sin eso el front igual
        tendría que pedir la lista para saber cuántas horas son."""
        cuerpo = _cuerpo("get_case_detail")
        self.assertIn("sla_config", cuerpo)
        self.assertIn("HORAS_RECONTACTO", cuerpo)
        self.assertIn("HORAS_CIERRE", cuerpo)

    def test_no_rompe_si_falta_el_modulo(self):
        """`sla_casos` se importa con un `try`. Si no está, el detalle tiene
        que seguir respondiendo el caso, sin plazo — como hace la lista."""
        cuerpo = _cuerpo("get_case_detail")
        i = cuerpo.index("sla_casos.evaluar(")
        antes = cuerpo[:i]
        self.assertIn("if sla_casos:", antes,
                      "la evaluación tiene que estar detrás de la guarda")


class LasDosRutasCuentanIgual(unittest.TestCase):
    """El criterio de «contacto» tiene que ser el mismo en la lista y en el
    detalle. Si se separan, el mismo caso muestra semáforos distintos según
    por dónde se lo mire, y nada falla: sólo discrepan."""

    def test_un_envio_fallido_no_cuenta_como_contacto(self):
        # En las dos: el cliente no recibió nada, así que el recontacto sigue
        # pendiente.
        lista = _cuerpo("_contactos_por_caso")
        detalle = _cuerpo("get_case_detail")
        self.assertIn('r.get("sent")', lista)
        self.assertIn('r.get("sent")', detalle)

    def test_el_ultimo_contacto_es_el_mas_reciente(self):
        lista = _cuerpo("_contactos_por_caso")
        detalle = _cuerpo("get_case_detail")
        for nombre, cuerpo in (("la lista", lista), ("el detalle", detalle)):
            self.assertRegex(cuerpo, r'cuando > (d\["ultimo"\]|ultimo_contacto)',
                             f"{nombre} tiene que quedarse con el más reciente")

    def test_los_dos_miran_si_el_cliente_respondio(self):
        detalle = _cuerpo("get_case_detail")
        lista = _cuerpo("get_cases")
        for nombre, cuerpo in (("la lista", lista), ("el detalle", detalle)):
            self.assertIn("_es_correo_recibido", cuerpo, nombre)


class SinLecturasDeMas(unittest.TestCase):
    """El agregado no puede costar otra pasada por la base.

    `document_requests` ya se recorría para el último pedido; los contactos
    salen de esa misma pasada. Un segundo `_crm_list` del mismo prefijo
    duplicaría las lecturas de cada apertura de caso.
    """

    def test_document_requests_se_recorre_una_sola_vez(self):
        cuerpo = _cuerpo("get_case_detail")
        veces = len(re.findall(r'_crm_list\("document_requests"\)', cuerpo))
        self.assertEqual(veces, 1,
                         f"se recorre {veces} veces; tiene que ser una sola")

    def test_no_llama_a_contactos_por_caso(self):
        """Esa función recorre TODOS los casos. Acá hace falta uno."""
        self.assertNotIn("_contactos_por_caso", _llamadas("get_case_detail"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
