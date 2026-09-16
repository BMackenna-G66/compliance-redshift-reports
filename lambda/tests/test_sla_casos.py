# -*- coding: utf-8 -*-
"""El reloj de los casos de alerta: los bordes del plazo y lo que apaga el aviso."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sla_casos as S  # noqa: E402

CREADO = dt.datetime(2026, 9, 10, 12, 0, 0)
T = "%Y-%m-%d %H:%M:%S"


def caso(horas_abierto=0, status="open", report="structuring_detection", **extra):
    c = {"case_id": "c1", "status": status, "report_name": report,
         "created_at": CREADO.strftime(T)}
    c.update(extra)
    return c, CREADO + dt.timedelta(hours=horas_abierto)


class Umbrales(unittest.TestCase):
    """Los tres tramos y, sobre todo, sus bordes exactos."""

    def _estado(self, horas, **kw):
        c, ref = caso(horas)
        return S.evaluar(c, ref, **kw)["sla_estado"]

    def test_recien_creado(self):
        self.assertEqual(self._estado(0), S.EN_PLAZO)

    def test_justo_antes_del_recontacto(self):
        self.assertEqual(self._estado(35.9), S.EN_PLAZO)

    def test_en_el_recontacto_exacto(self):
        """36 h es 1,5 días: el borde entra en amarillo, no se queda en verde."""
        self.assertEqual(self._estado(36.0), S.POR_CONTACTAR)

    def test_justo_antes_del_cierre(self):
        self.assertEqual(self._estado(71.9), S.POR_CONTACTAR)

    def test_en_el_cierre_exacto(self):
        self.assertEqual(self._estado(72.0), S.VENCIDO)

    def test_muy_pasado(self):
        self.assertEqual(self._estado(24 * 59), S.VENCIDO)

    def test_las_constantes_son_los_dias_pedidos(self):
        self.assertEqual(S.HORAS_RECONTACTO / 24, 1.5)
        self.assertEqual(S.HORAS_CIERRE / 24, 3.0)


class ApagaElAviso(unittest.TestCase):
    """El amarillo es un pendiente; cuando el pendiente está hecho, se apaga."""

    def test_sin_contactos_pide_contactar(self):
        c, ref = caso(40)
        r = S.evaluar(c, ref, contactos=0)
        self.assertEqual(r["sla_estado"], S.POR_CONTACTAR)
        self.assertEqual(r["sla_accion"], "contactar")

    def test_con_un_contacto_previo_pide_recontactar(self):
        c, ref = caso(40)
        # El correo inicial, mandado antes de la marca de las 36 h.
        r = S.evaluar(c, ref, contactos=1,
                      ultimo_contacto=(CREADO + dt.timedelta(hours=2)).strftime(T))
        self.assertEqual(r["sla_estado"], S.POR_RECONTACTAR)
        self.assertEqual(r["sla_accion"], "recontactar")

    def test_recontactado_despues_de_la_marca_vuelve_a_verde(self):
        c, ref = caso(40)
        r = S.evaluar(c, ref, contactos=2,
                      ultimo_contacto=(CREADO + dt.timedelta(hours=37)).strftime(T))
        self.assertEqual(r["sla_estado"], S.EN_PLAZO)
        self.assertEqual(r["sla_accion"], "")

    def test_si_el_cliente_respondio_no_se_le_insiste(self):
        c, ref = caso(40)
        self.assertEqual(S.evaluar(c, ref, contactos=1, respondio=True)["sla_estado"],
                         S.EN_PLAZO)

    def test_pero_responder_no_frena_el_vencimiento(self):
        """Contestar saca el pendiente de recontacto; no cierra el caso solo."""
        c, ref = caso(80)
        self.assertEqual(S.evaluar(c, ref, contactos=1, respondio=True)["sla_estado"],
                         S.VENCIDO)


class QuienTieneReloj(unittest.TestCase):

    def test_caso_manual_no_tiene_plazo(self):
        c, ref = caso(100, report="")
        r = S.evaluar(c, ref)
        self.assertFalse(r["sla_aplica"])
        self.assertEqual(r["sla_estado"], S.SIN_RELOJ)
        self.assertIsNone(r["sla_dias"])

    def test_caso_manual_con_datos_de_alerta_si(self):
        """Hay casos sin report_name que igual nacieron de una alerta."""
        c, ref = caso(100, report="", alert_data={"customer_id": "123"})
        self.assertTrue(S.evaluar(c, ref)["sla_aplica"])

    def test_alert_data_vacio_no_alcanza(self):
        c, ref = caso(100, report="", alert_data={})
        self.assertFalse(S.evaluar(c, ref)["sla_aplica"])

    def test_cerrado_detiene_el_reloj(self):
        c, ref = caso(200, status="closed",
                      closed_at=(CREADO + dt.timedelta(hours=50)).strftime(T))
        r = S.evaluar(c, ref)
        self.assertEqual(r["sla_estado"], S.CERRADO)
        self.assertEqual(r["sla_horas"], 50.0)          # lo que tardó, no lo que pasó
        self.assertIsNone(r["sla_horas_restantes"])
        self.assertEqual(r["sla_accion"], "")

    def test_archivado_tambien(self):
        c, ref = caso(200, status="archived")
        self.assertEqual(S.evaluar(c, ref)["sla_estado"], S.CERRADO)


class FechasRaras(unittest.TestCase):
    """Un caso con la fecha mal no puede tumbar el listado entero."""

    def test_sin_fecha_de_creacion(self):
        r = S.evaluar({"status": "open", "report_name": "x", "created_at": ""})
        self.assertFalse(r["sla_aplica"])

    def test_fecha_ilegible(self):
        r = S.evaluar({"status": "open", "report_name": "x", "created_at": "ayer"})
        self.assertFalse(r["sla_aplica"])

    def test_formato_iso_con_z(self):
        self.assertEqual(S.a_fecha("2026-09-10T12:00:00Z"), CREADO)

    def test_formato_iso_con_microsegundos(self):
        self.assertEqual(S.a_fecha("2026-09-10 12:00:00.123456"), CREADO)

    def test_solo_fecha(self):
        self.assertEqual(S.a_fecha("2026-09-10"), dt.datetime(2026, 9, 10))


class Salida(unittest.TestCase):

    def test_los_hitos_y_el_restante(self):
        c, ref = caso(12)
        r = S.evaluar(c, ref)
        self.assertEqual(r["sla_recontacto_at"], "2026-09-12 00:00:00")
        self.assertEqual(r["sla_cierre_at"], "2026-09-13 12:00:00")
        self.assertEqual(r["sla_horas_restantes"], 60.0)
        self.assertEqual(r["sla_dias"], 0.5)

    def test_el_restante_es_negativo_cuando_ya_venció(self):
        c, ref = caso(80)
        self.assertEqual(S.evaluar(c, ref)["sla_horas_restantes"], -8.0)

    def test_resumen_cuenta_por_estado(self):
        casos = [{"sla_estado": S.VENCIDO}, {"sla_estado": S.VENCIDO},
                 {"sla_estado": S.EN_PLAZO}, {"sla_estado": S.SIN_RELOJ}]
        r = S.resumen(casos)
        self.assertEqual(r[S.VENCIDO], 2)
        self.assertEqual(r[S.EN_PLAZO], 1)
        self.assertEqual(r[S.SIN_RELOJ], 1)
        self.assertEqual(r[S.POR_RECONTACTAR], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
