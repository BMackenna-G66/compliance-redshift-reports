# -*- coding: utf-8 -*-
"""El preflight. SIN ESTO LA APLICACIÓN ENTERA SE CAE, v1 y v2.

Este archivo existe por una caída de quince horas.

El 13-10-2026 se borró el handler de `OPTIONS` del `api_handler`, con el
argumento —razonable y equivocado— de que era código muerto porque el CORS lo
contesta API Gateway. Todo WatchTower dejó de funcionar para todo el equipo:
«Error de red al conectar con la API», listas vacías, ninguna pantalla.

POR QUÉ EL HANDLER SÍ CORRE. La API tiene una ruta `$default` (ANY → Lambda),
así que API Gateway le pasa TAMBIÉN el OPTIONS a la Lambda, y recién después
le agrega sus headers CORS encima. Si la Lambda no contesta un 2xx, el
preflight termina en 404 — **con los headers CORS correctos**, que es
exactamente lo que engaña al mirarlo— y el navegador bloquea la llamada.

Y bloquea TODAS: v1 manda `Content-Type: application/json` en cada request,
incluidos los GET, así que ninguna es una «simple request» que se saltee el
preflight.

LO QUE HABÍA QUE SACAR ERA LA POLÍTICA, NO LA RESPUESTA. El handler viejo
declaraba su propio `Access-Control-Allow-*`, que no regía y que escondió
durante meses que editar una configuración documental estaba roto en v1.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_handler as A  # noqa: E402


class ElPreflightContesta2xx(unittest.TestCase):

    def _options(self, ruta):
        return A.handler({
            "requestContext": {"http": {"method": "OPTIONS", "path": ruta}},
            "rawPath": ruta,
            "headers": {"origin": "https://bmackenna-g66.github.io"},
            "body": None}, None)

    def test_en_las_rutas_que_usa_la_aplicacion(self):
        for ruta in ("/cases", "/ros", "/alerts", "/reports", "/users",
                     "/alert-document-config/x", "/ros/ROS-2026-0001/aprobar"):
            with self.subTest(ruta=ruta):
                r = self._options(ruta)
                self.assertTrue(200 <= r["statusCode"] < 300,
                                f"{ruta} devolvió {r['statusCode']}: el "
                                "navegador bloquea la llamada")

    def test_Y_TAMBIEN_EN_UNA_RUTA_QUE_NO_EXISTE(self):
        """El preflight se contesta ANTES de rutear. Un 404 ahí bloquea la
        llamada igual que en una ruta válida — y es el modo en que esto se
        rompió: el OPTIONS caía al final del ruteo y salía 404."""
        for ruta in ("/una-ruta-que-no-existe", "/", "/cases/x/y/z"):
            with self.subTest(ruta=ruta):
                r = self._options(ruta)
                self.assertTrue(200 <= r["statusCode"] < 300)

    def test_NO_DECLARA_POLITICA_PROPIA(self):
        """Los headers los pone API Gateway. Declararlos acá crea una política
        que no rige y que engaña a quien la lee: el handler viejo permitía
        `PUT` y `Authorization` cuando API Gateway no, y así nadie vio durante
        meses que editar una configuración documental estaba roto."""
        r = self._options("/cases")
        self.assertEqual(
            [k for k in (r.get("headers") or {})
             if k.lower().startswith("access-control")], [],
            "volvió a declarar una política CORS que no rige")

    def test_el_preflight_no_mira_la_sesion(self):
        """Un OPTIONS no lleva el token: el navegador lo manda sin headers de
        autorización. Exigirlo ahí rompería todo de otra manera."""
        r = self._options("/ros")
        self.assertTrue(200 <= r["statusCode"] < 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
