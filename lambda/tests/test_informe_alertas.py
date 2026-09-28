# -*- coding: utf-8 -*-
"""El informe de alertas.

LO QUE VIGILA, además de que las cuentas den:

**Que no invente lo que no se puede medir.** La spec propone columnas de
«gestionadas», «cerradas» y «cumplimiento de SLA». Ninguna se puede calcular:
medido el 28-09-2026, las 122 alertas de producción están en `active` y
`reviewed_at` está vacío en las 122. Una columna en cero se lee como «nadie
gestionó nada», que no es lo que dice el dato — dice que no lo registramos.
Por eso el correo lo aclara, y hay un test de que esa aclaración esté.

**Que «con caso» mire las dos señales.** `case_id` es el vínculo real y
`tiene_caso` la bandera que arma la API. Con una sola, 7 de 67 quedaban
afuera.
"""
import datetime as dt
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import informe_alertas as C  # noqa: E402
import informe_email as E  # noqa: E402

AHORA = dt.datetime(2026, 9, 28, 12, 0, 0)


def alerta(**kw):
    base = {"alert_id": "a1", "report_name": "structuring_detection",
            "entity_value": "1234567", "priority": "high",
            "assigned_to": "ana.perez@global66.com", "status": "active",
            "created_at": "2026-09-20 10:00:00", "case_id": "", "tiene_caso": False}
    base.update(kw)
    return base


class ConCasoMiraLasDosSeniales(unittest.TestCase):

    def test_el_vinculo_real(self):
        self.assertTrue(C.tiene_caso(alerta(case_id="CASO-1")))

    def test_la_bandera_de_la_api(self):
        """Con `case_id` solo, 7 de 67 quedaban afuera."""
        self.assertTrue(C.tiene_caso(alerta(tiene_caso=True)))

    def test_sin_ninguna_no_tiene(self):
        self.assertFalse(C.tiene_caso(alerta()))


class LasCuentas(unittest.TestCase):

    ALERTAS = [
        alerta(case_id="C1"),
        alerta(alert_id="a2", tiene_caso=True),
        alerta(alert_id="a3", created_at="2026-06-01 10:00:00"),   # 119 d, sin caso
        alerta(alert_id="a4", priority="low", assigned_to=""),
    ]

    def test_reparte_con_caso_y_sin_caso(self):
        g = C.indicadores(self.ALERTAS, AHORA)
        self.assertEqual(g["total"], 4)
        self.assertEqual(g["con_caso"], 2)
        self.assertEqual(g["sin_caso"], 2)
        self.assertEqual(g["pct_con_caso"], 50.0)

    def test_cuenta_las_viejas_sin_caso(self):
        """Lo accionable: sin caso y con semanas encima es trabajo que no
        empezó, no trabajo atrasado."""
        g = C.indicadores(self.ALERTAS, AHORA)
        self.assertEqual(g["sin_caso_viejas"], 1)

    def test_una_vieja_con_caso_no_cuenta_como_pendiente(self):
        vieja = alerta(created_at="2026-01-01 10:00:00", case_id="C9")
        self.assertEqual(C.indicadores([vieja], AHORA)["sin_caso_viejas"], 0)

    def test_los_sin_asignar_van_ultimos_y_aparte(self):
        """No son de nadie: meterlos dentro de una persona haría desaparecer
        la fila que hay que mirar."""
        filas = C.por_persona(self.ALERTAS, AHORA)
        self.assertEqual(filas[-1]["persona"], C.SIN_ASIGNAR)
        self.assertEqual(filas[-1]["total"], 1)

    def test_por_regla_ordena_por_volumen(self):
        muchas = ([alerta(report_name="regla_a") for _ in range(3)]
                  + [alerta(report_name="regla_b")])
        filas = C.por_regla(muchas, AHORA)
        self.assertEqual([f["regla"] for f in filas], ["regla_a", "regla_b"])

    def test_el_filtro_por_fecha_mira_la_creacion(self):
        sel = C.filtrar(self.ALERTAS, desde="2026-09-01")
        self.assertEqual(len(sel), 3)


class NoInventaLoQueNoSeMide(unittest.TestCase):

    def test_no_hay_columna_de_gestionadas_ni_de_sla(self):
        claves = set(C.indicadores([alerta()], AHORA))
        for inventada in ("gestionadas", "cerradas", "sla", "qsla",
                          "primera_respuesta"):
            self.assertNotIn(inventada, claves)

    def test_el_correo_dice_que_no_lo_mide(self):
        datos = C.armar([alerta(), alerta(alert_id="a2")], ahora=AHORA)
        h = E.construir_alertas(datos, url_bandeja="https://ejemplo/", ahora=AHORA)
        self.assertIn("no mide", h)
        self.assertIn("gestionadas", h)
        # El «2» va dentro de un <strong>, así que se busca el texto de al lado.
        self.assertIn("de 2 alertas están en estado", h,
                      "tiene que decir sobre cuántas habla")


class ElCorreoDeAlertas(unittest.TestCase):

    DATOS = None

    def setUp(self):
        self.DATOS = C.armar(
            [alerta(), alerta(alert_id="a2", case_id="C1"),
             alerta(alert_id="a3", created_at="2026-05-01 10:00:00")],
            ahora=AHORA)

    def html(self):
        return E.construir_alertas(self.DATOS, url_bandeja="https://ejemplo/",
                                   ahora=AHORA,
                                   generado_por="jefa@global66.com")

    def test_es_correo_y_no_pagina(self):
        h = self.html()
        self.assertNotIn("<style", h)
        self.assertNotIn("class=", h)
        self.assertNotIn("<script", h)

    def test_ninguna_direccion_queda_suelta(self):
        """Mismo problema que en el informe de casos: Gmail las repinta."""
        h = self.html()
        self.assertEqual(h.count("@global66.com"), h.count("mailto:") * 2)

    def test_tiene_el_tramo_de_mas_de_treinta_dias(self):
        h = self.html()
        self.assertIn("30d+", h)

    def test_el_asunto_dice_de_que_es(self):
        self.assertIn("Reporte de alertas", E.asunto_alertas("28-09-2026"))

    def test_el_texto_plano_no_va_vacio(self):
        t = E.texto_plano_alertas(self.DATOS, "28-09-2026")
        self.assertIn("Alertas: 3", t)
        self.assertIn("no registra", t)


# ── El endpoint ──────────────────────────────────────────────────────────

import api_handler as A  # noqa: E402


class _Correo:
    def __init__(self):
        self.enviados = []

    def __call__(self, to, subject, html, from_addr=None, attachments=None):
        self.enviados.append({"to": to, "subject": subject})
        return {"sent": True, "error": ""}


def llamar(cuerpo):
    correo = _Correo()
    orig = {"_send_email": A._send_email, "get_alerts": A.get_alerts,
            "_safe_audit": A._safe_audit}
    A._send_email = correo
    A.get_alerts = lambda *a, **k: {"statusCode": 200,
                                    "body": json.dumps({"alerts": [alerta()]})}
    A._safe_audit = lambda **k: None
    try:
        r = A.enviar_informe_alertas(cuerpo)
    finally:
        for n, f in orig.items():
            setattr(A, n, f)
    return r["statusCode"], json.loads(r["body"]), correo


class ElCorreoNoSaleDelDominio(unittest.TestCase):
    """El informe lista ids de clientes: la misma regla que el de casos."""

    def test_un_destinatario_de_afuera_se_rechaza(self):
        codigo, d, correo = llamar({"para": ["alguien@gmail.com"]})
        self.assertEqual(codigo, 400)
        self.assertEqual(correo.enviados, [])
        self.assertIn("alguien@gmail.com", d["rechazados"])

    def test_sin_destinatarios_no_hace_nada(self):
        codigo, _, correo = llamar({})
        self.assertEqual(codigo, 400)
        self.assertEqual(correo.enviados, [])

    def test_un_solo_correo_con_todos(self):
        _, d, correo = llamar({"para": ["ana@global66.com", "luis@global66.com"]})
        self.assertEqual(len(correo.enviados), 1, "tiene que ser un solo envío")
        self.assertEqual(d["destinatarios"],
                         ["ana@global66.com", "luis@global66.com"])

    def test_la_respuesta_dice_cuantas_alertas_y_cuantas_sin_caso(self):
        _, d, _ = llamar({"para": ["ana@global66.com"]})
        self.assertEqual(d["alertas"], 1)
        self.assertEqual(d["sin_caso"], 1)


class ElModuloViajaEnElPaquete(unittest.TestCase):
    """`build_lambda.sh` copia los módulos uno por uno. El que se olvida no
    falla en los tests: falla en producción con un 503."""

    def test_informe_alertas_esta_en_el_build(self):
        raiz = Path(__file__).resolve().parents[2]
        build = (raiz / "build_lambda.sh").read_text(encoding="utf-8")
        self.assertIn("informe_alertas.py", build)


if __name__ == "__main__":
    unittest.main(verbosity=2)
