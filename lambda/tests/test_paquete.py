# -*- coding: utf-8 -*-
"""Que todo módulo que la API importa viaje en el paquete de la Lambda.

POR QUÉ EXISTE. `build_lambda.sh` copia los archivos UNO POR UNO. Es
deliberado —no se quiere empaquetar tests ni scripts sueltos— pero tiene una
trampa: agregar un módulo nuevo y olvidar la línea del `cp`.

Cuando eso pasa, el import defensivo de `api_handler` lo atrapa y el endpoint
devuelve un 503 educado… que parece un problema de infraestructura y no un
archivo que no se copió. Se descubre en producción, mirando logs.

Este test lo descubre antes. Pasó de verdad con `ros.py`.
"""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LAMBDA = RAIZ / "lambda"
BUILD = RAIZ / "build_lambda.sh"


def _copiados():
    """Los módulos que el script mete en el paquete."""
    texto = BUILD.read_text(encoding="utf-8")
    sueltos = set(re.findall(r'cp lambda/(\w+)\.py', texto))
    # `cp -R lambda/relevo` y similares copian paquetes enteros.
    paquetes = set(re.findall(r'cp -R lambda/(\w+)', texto))
    return sueltos, paquetes


def _importados_por(archivo: Path):
    """Los módulos locales que un archivo importa, sean directos o
    defensivos dentro de un `try`."""
    texto = archivo.read_text(encoding="utf-8")
    nombres = set(re.findall(r"^\s*import (\w+)", texto, re.M))
    nombres |= set(re.findall(r"^\s*from (\w+) import", texto, re.M))
    # Sólo los que existen como archivo en lambda/: el resto es stdlib o pip.
    return {n for n in nombres if (LAMBDA / f"{n}.py").exists()}


class ElPaqueteLlevaTodo(unittest.TestCase):

    def test_la_api_no_importa_nada_que_se_quede_afuera(self):
        sueltos, paquetes = _copiados()
        faltan = _importados_por(LAMBDA / "api_handler.py") - sueltos - paquetes
        self.assertEqual(
            faltan, set(),
            f"api_handler importa módulos que build_lambda.sh no copia: {faltan}. "
            f"Agregá `cp lambda/<módulo>.py \"$BUILD_DIR/\"` al script.")

    def test_el_runner_tampoco(self):
        sueltos, paquetes = _copiados()
        faltan = _importados_por(LAMBDA / "handler.py") - sueltos - paquetes
        self.assertEqual(faltan, set(),
                         f"handler importa módulos que no se copian: {faltan}")

    def test_lo_que_se_copia_existe(self):
        """Una línea que copia un archivo borrado rompe el build entero."""
        sueltos, paquetes = _copiados()
        for m in sueltos:
            with self.subTest(m):
                self.assertTrue((LAMBDA / f"{m}.py").exists(),
                                f"build_lambda.sh copia lambda/{m}.py, que no existe")
        for p in paquetes:
            with self.subTest(p):
                self.assertTrue((LAMBDA / p).is_dir(),
                                f"build_lambda.sh copia lambda/{p}/, que no existe")

    def test_los_tests_no_viajan(self):
        """Empaquetarlos engorda la Lambda y mete dependencias de desarrollo
        en el runtime."""
        self.assertNotIn("tests", _copiados()[1])
