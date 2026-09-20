# -*- coding: utf-8 -*-
"""Los números del informe de gestión.

Este informe se usa para mirar la carga de trabajo de personas, así que un
error de cuenta no es un número feo: es un analista que aparece peor de lo que
trabajó. Lo que se cubre, en ese orden:

  1. **Que dos formas de escribir a la misma persona sean una sola.** En
     producción Diego figura como `diego armesto` y como
     `diego.armesto@global66.com`; sin normalizar, sus 18 casos se muestran
     como dos analistas de 10 y 8.
  2. **Qué cuenta como gestionado.** Estar asignado no alcanza.
  3. **Los bordes de los promedios**: sin cerrados, un solo caso, un caso con
     fechas al revés.
"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import informe_casos as I  # noqa: E402

AHORA = dt.datetime(2026, 9, 20, 12, 0, 0)


def caso(estado="open", asignado="ana@global66.com", notas=0,
         creado="2026-09-10 12:00:00", cerrado="", **extra):
    c = {"status": estado, "assigned_to": asignado, "note_count": notas,
         "created_at": creado, "closed_at": cerrado}
    c.update(extra)
    return c


class ElMismoAnalistaEsUnoSolo(unittest.TestCase):

    def test_normaliza_el_nombre_sin_arroba(self):
        self.assertEqual(I.normalizar_analista("diego armesto"),
                         "diego.armesto@global66.com")

    def test_el_correo_queda_igual(self):
        self.assertEqual(I.normalizar_analista("Diego.Armesto@Global66.com"),
                         "diego.armesto@global66.com")

    def test_las_dos_formas_caen_en_el_mismo_analista(self):
        """El caso real que motivó esto."""
        casos = ([caso(asignado="diego armesto")] * 10
                 + [caso(asignado="diego.armesto@global66.com")] * 8)
        filas = I.por_analista(casos, ahora=AHORA)
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["total"], 18)

    def test_vacio_es_sin_asignar(self):
        for v in ("", None, "   "):
            self.assertEqual(I.normalizar_analista(v), I.SIN_ASIGNAR)


class QueCuentaComoGestionado(unittest.TestCase):

    def test_abierto_y_sin_notas_no_esta_gestionado(self):
        self.assertFalse(I.fue_gestionado(caso()))

    def test_estar_asignado_no_alcanza(self):
        """Asignar es repartir, no gestionar. Es la distinción que el informe
        existe para poder mostrar."""
        self.assertFalse(I.fue_gestionado(caso(asignado="ana@global66.com")))

    def test_una_nota_alcanza(self):
        self.assertTrue(I.fue_gestionado(caso(notas=1)))

    def test_salir_de_abierto_alcanza(self):
        for e in ("in_progress", "under_review", "closed", "archived"):
            with self.subTest(e):
                self.assertTrue(I.fue_gestionado(caso(estado=e)))


class Promedios(unittest.TestCase):

    def cerrado(self, dias):
        ini = dt.datetime(2026, 9, 1, 12, 0, 0)
        return caso(estado="closed", creado=ini.strftime(I.FORMATO),
                    cerrado=(ini + dt.timedelta(days=dias)).strftime(I.FORMATO))

    def test_sin_cerrados_no_inventa_un_promedio(self):
        """Un analista sin cierres tiene que mostrar un guion, no un cero: cero
        días de cierre se lee como 'cierra todo al instante'."""
        ind = I.indicadores([caso(), caso()], ahora=AHORA)
        self.assertIsNone(ind["cierre_promedio"])
        self.assertIsNone(ind["cierre_mediana"])

    def test_promedio_y_mediana(self):
        ind = I.indicadores([self.cerrado(1), self.cerrado(2), self.cerrado(30)],
                            ahora=AHORA)
        self.assertEqual(ind["cierre_promedio"], 11.0)
        self.assertEqual(ind["cierre_mediana"], 2.0)   # la mediana no la arrastra
        self.assertEqual(ind["cierre_max"], 30.0)

    def test_un_caso_cerrado_el_mismo_dia_es_cero_no_none(self):
        self.assertEqual(I.indicadores([self.cerrado(0)], ahora=AHORA)["cierre_promedio"], 0.0)

    def test_fechas_al_reves_se_descartan(self):
        """Un cierre anterior a la creación es un dato malo; contarlo daría un
        promedio negativo que nadie sabría interpretar."""
        malo = caso(estado="closed", creado="2026-09-10 12:00:00",
                    cerrado="2026-09-01 12:00:00")
        self.assertIsNone(I.dias_de_cierre(malo))
        self.assertIsNone(I.indicadores([malo], ahora=AHORA)["cierre_promedio"])

    def test_sin_closed_at_no_se_promedia(self):
        self.assertIsNone(I.dias_de_cierre(caso(estado="closed", cerrado="")))


class Porcentajes(unittest.TestCase):

    def test_sin_casos_no_divide_por_cero(self):
        ind = I.indicadores([], ahora=AHORA)
        self.assertEqual(ind["total"], 0)
        self.assertEqual(ind["pct_gestionados"], 0.0)
        self.assertEqual(ind["pct_vencidos"], 0.0)

    def test_gestionados_y_sin_tocar_suman_el_total(self):
        casos = [caso(), caso(notas=2), caso(estado="closed", cerrado="2026-09-11 12:00:00")]
        ind = I.indicadores(casos, ahora=AHORA)
        self.assertEqual(ind["gestionados"] + ind["sin_tocar"], ind["total"])

    def test_el_porcentaje_de_vencidos_es_sobre_los_que_tienen_plazo(self):
        """Dividir sobre el total diluiría el número con casos que nunca
        tuvieron plazo."""
        casos = [caso(sla_aplica=True, sla_estado="vencido"),
                 caso(sla_aplica=True, sla_estado="en_plazo"),
                 caso()]                      # sin plazo
        self.assertEqual(I.indicadores(casos, ahora=AHORA)["pct_vencidos"], 50.0)


class Agrupacion(unittest.TestCase):

    EQUIPOS = {"ana@global66.com": "Monitoreo", "beto@global66.com": "Monitoreo",
               "cata@global66.com": "Onboarding"}

    def casos(self):
        return ([caso(asignado="ana@global66.com")] * 3
                + [caso(asignado="beto@global66.com")] * 2
                + [caso(asignado="cata@global66.com")]
                + [caso(asignado="")])

    def test_arma_los_equipos(self):
        eq = {e["equipo"]: e for e in I.por_equipo(self.casos(), self.EQUIPOS, AHORA)}
        self.assertEqual(eq["Monitoreo"]["total"], 5)
        self.assertEqual(eq["Onboarding"]["total"], 1)
        self.assertEqual(len(eq["Monitoreo"]["analistas"]), 2)

    def test_los_sin_asignar_no_se_reparten(self):
        """Esconderlos dentro de un equipo haría desaparecer justo lo que hay
        que ver."""
        eq = {e["equipo"]: e for e in I.por_equipo(self.casos(), self.EQUIPOS, AHORA)}
        self.assertEqual(eq[I.SIN_ASIGNAR]["total"], 1)
        self.assertNotIn(I.SIN_ASIGNAR, eq["Monitoreo"]["analistas"])

    def test_un_analista_sin_equipo_cargado_es_visible(self):
        """No se lo esconde: es la señal de que falta cargarlo."""
        eq = {e["equipo"]: e for e in
              I.por_equipo([caso(asignado="nuevo@global66.com")], self.EQUIPOS, AHORA)}
        self.assertIn(I.SIN_EQUIPO, eq)

    def test_los_sin_asignar_van_ultimos(self):
        orden = [e["equipo"] for e in I.por_equipo(self.casos(), self.EQUIPOS, AHORA)]
        self.assertEqual(orden[-1], I.SIN_ASIGNAR)

    def test_el_total_del_equipo_es_la_suma_de_sus_analistas(self):
        for e in I.por_equipo(self.casos(), self.EQUIPOS, AHORA):
            with self.subTest(e["equipo"]):
                self.assertEqual(e["total"], sum(a["total"] for a in e["analistas"]))


class Filtros(unittest.TestCase):

    def casos(self):
        return [caso(creado="2026-08-15 10:00:00", asignado="ana@global66.com"),
                caso(creado="2026-09-10 10:00:00", asignado="ana@global66.com"),
                caso(creado="2026-09-18 10:00:00", asignado="beto@global66.com")]

    def test_por_fecha(self):
        self.assertEqual(len(I.filtrar(self.casos(), desde="2026-09-01")), 2)
        self.assertEqual(len(I.filtrar(self.casos(), hasta="2026-09-01")), 1)
        self.assertEqual(len(I.filtrar(self.casos(), desde="2026-09-01",
                                       hasta="2026-09-15")), 1)

    def test_por_analista_normalizando(self):
        """Filtrar por 'ana armesto' o por su correo tiene que dar lo mismo."""
        self.assertEqual(len(I.filtrar(self.casos(), analista="ana@global66.com")), 2)
        self.assertEqual(len(I.filtrar(self.casos(), analista="ana")), 2)

    def test_por_equipo(self):
        eq = {"ana@global66.com": "Monitoreo", "beto@global66.com": "Onboarding"}
        self.assertEqual(len(I.filtrar(self.casos(), equipo="Monitoreo", equipos=eq)), 2)

    def test_el_filtro_de_fecha_incluye_los_bordes(self):
        self.assertEqual(len(I.filtrar(self.casos(), desde="2026-09-10",
                                       hasta="2026-09-10")), 1)


class FechasRaras(unittest.TestCase):
    """Un caso con la fecha mal no puede tumbar el informe entero."""

    def test_sin_fecha_de_creacion(self):
        self.assertIsNone(I.dias_abierto(caso(creado="")))
        I.indicadores([caso(creado="")], ahora=AHORA)   # no revienta

    def test_formatos_que_aparecen_en_el_crm(self):
        self.assertEqual(I.a_fecha("2026-09-10 12:00:00"),
                         dt.datetime(2026, 9, 10, 12, 0))
        self.assertEqual(I.a_fecha("2026-09-10T12:00:00Z"),
                         dt.datetime(2026, 9, 10, 12, 0))
        self.assertEqual(I.a_fecha("2026-09-10"), dt.datetime(2026, 9, 10))
        self.assertIsNone(I.a_fecha("ayer"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
