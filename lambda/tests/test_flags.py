# -*- coding: utf-8 -*-
"""`GET /flags` — la matriz de banderas del análisis individual.

POR QUÉ EXISTE ESTE ENDPOINT. El front nuevo tiene una pantalla "Flags y
pesos". Sin un endpoint tendría que copiar `FLAG_WEIGHTS` y `FLAG_LABELS`, y
el día que alguien cambie un peso la pantalla seguiría mostrando el viejo sin
que nadie se entere — hasta que un analista defienda un caso con un número
que no es.

LO QUE MÁS IMPORTA DE ESTE ARCHIVO es el último test: que los cortes de nivel
tengan UNA sola definición. Estaban escritos como literales dentro del `if`
de `aml_individual`, y al exponerlos acá era tentador repetirlos.
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

import aml_individual as AML  # noqa: E402
import api_handler as A  # noqa: E402


def llamar():
    r = A.get_flags()
    return r["statusCode"], json.loads(r["body"])


class Respuesta(unittest.TestCase):

    def test_devuelve_las_diez_banderas(self):
        codigo, d = llamar()
        self.assertEqual(codigo, 200)
        self.assertEqual(len(d["flags"]), 10)

    def test_son_exactamente_las_de_aml_individual(self):
        _, d = llamar()
        claves = {f["clave"] for f in d["flags"]}
        self.assertEqual(claves, set(AML.FLAG_WEIGHTS))

    def test_cada_peso_es_el_del_módulo(self):
        _, d = llamar()
        for f in d["flags"]:
            with self.subTest(f["clave"]):
                self.assertEqual(f["peso"], AML.FLAG_WEIGHTS[f["clave"]])

    def test_el_maximo_se_calcula_y_no_se_escribe(self):
        """Un score sólo se entiende contra su máximo: "12" no dice nada,
        "12 de 19" sí. Y el 19 tiene que salir de sumar, no de escribirlo."""
        _, d = llamar()
        self.assertEqual(d["maximo"], sum(AML.FLAG_WEIGHTS.values()))
        self.assertEqual(d["maximo"], 19)

    def test_la_etiqueta_se_parte_en_codigo_y_nombre(self):
        _, d = llamar()
        por_clave = {f["clave"]: f for f in d["flags"]}
        f1 = por_clave["flag_structuring"]
        self.assertEqual(f1["codigo"], "F1")
        self.assertEqual(f1["nombre"], "Estructuración")
        self.assertEqual(f1["etiqueta"], "F1 Estructuración")

    def test_una_etiqueta_sin_espacio_no_deja_el_nombre_vacio(self):
        """Si alguien renombra una bandera a una sola palabra, la pantalla
        tiene que mostrar algo igual."""
        original = dict(AML.FLAG_LABELS)
        try:
            A.FLAG_LABELS["flag_redondos"] = "Redondos"
            _, d = llamar()
            f = next(x for x in d["flags"] if x["clave"] == "flag_redondos")
            self.assertEqual(f["nombre"], "Redondos")
        finally:
            A.FLAG_LABELS.clear()
            A.FLAG_LABELS.update(original)

    def test_vienen_ordenadas_por_peso(self):
        _, d = llamar()
        pesos = [f["peso"] for f in d["flags"]]
        self.assertEqual(pesos, sorted(pesos, reverse=True))

    def test_a_igual_peso_ordena_por_NUMERO_y_no_por_texto(self):
        """F6 antes que F10.

        Ordenando el código como texto, "F10" cae antes que "F6" porque
        '1' < '6'. Con diez banderas eso deja F10 en el medio de la lista y
        hace dudar de si falta alguna.
        """
        def numero(c):
            return int("".join(x for x in c if x.isdigit()) or 99)

        _, d = llamar()
        for a, b in zip(d["flags"], d["flags"][1:]):
            if a["peso"] == b["peso"]:
                with self.subTest(f'{a["codigo"]} antes que {b["codigo"]}'):
                    self.assertLess(numero(a["codigo"]), numero(b["codigo"]))

    def test_las_de_peso_1_salen_en_orden_numerico(self):
        _, d = llamar()
        peso1 = [f["codigo"] for f in d["flags"] if f["peso"] == 1]
        self.assertEqual(peso1, ["F6", "F8", "F10"])


class LosCortesTienenUnaSolaDefinicion(unittest.TestCase):
    """El test que justifica el refactor de `aml_individual`.

    Los cortes estaban escritos como literales dentro del `if` que clasifica
    el score. Al exponerlos en `GET /flags` era tentador repetirlos acá, y
    entonces habría DOS definiciones del mismo corte: la pantalla diría
    "crítico desde 10" mientras el scoring usa otro número.
    """

    def test_el_endpoint_los_lee_del_modulo_de_scoring(self):
        _, d = llamar()
        self.assertEqual(d["cortes"], AML.CORTES_NIVEL)

    def test_cambiar_el_corte_en_el_modulo_cambia_lo_que_ve_el_front(self):
        original = dict(AML.CORTES_NIVEL)
        try:
            A.CORTES_NIVEL["critico"] = 99
            _, d = llamar()
            self.assertEqual(d["cortes"]["critico"], 99)
        finally:
            A.CORTES_NIVEL.clear()
            A.CORTES_NIVEL.update(original)

    def test_el_scoring_sigue_clasificando_igual_que_antes(self):
        """El refactor cambió literales por la constante: la clasificación
        tiene que dar exactamente lo mismo que con los números escritos."""
        def nivel(score):
            if score >= AML.CORTES_NIVEL['critico']:
                return 'CRÍTICO'
            if score >= AML.CORTES_NIVEL['alto']:
                return 'ALTO'
            if score >= AML.CORTES_NIVEL['medio']:
                return 'MEDIO'
            return 'BAJO'

        esperado = {0: 'BAJO', 2: 'BAJO', 3: 'MEDIO', 5: 'MEDIO',
                    6: 'ALTO', 9: 'ALTO', 10: 'CRÍTICO', 19: 'CRÍTICO'}
        for score, nombre in esperado.items():
            with self.subTest(score=score):
                self.assertEqual(nivel(score), nombre)

    def test_los_cortes_caben_en_la_escala(self):
        """Un corte por encima del máximo alcanzable sería un nivel al que
        nadie puede llegar nunca."""
        maximo = sum(AML.FLAG_WEIGHTS.values())
        for nombre, corte in AML.CORTES_NIVEL.items():
            with self.subTest(nombre):
                self.assertLessEqual(corte, maximo)
                self.assertGreater(corte, 0)


class SiElModuloNoViaja(unittest.TestCase):
    """El paquete de la Lambda se arma con un script; si `aml_individual` no
    entrara, el endpoint tiene que decirlo y no romper el resto de la API."""

    def test_devuelve_503_y_no_revienta(self):
        guardados = (A.FLAG_WEIGHTS, A.FLAG_LABELS, A.CORTES_NIVEL)
        try:
            A.FLAG_WEIGHTS = A.FLAG_LABELS = A.CORTES_NIVEL = None
            codigo, d = llamar()
            self.assertEqual(codigo, 503)
            self.assertIn("error", d)
        finally:
            A.FLAG_WEIGHTS, A.FLAG_LABELS, A.CORTES_NIVEL = guardados


if __name__ == "__main__":
    unittest.main(verbosity=1)
