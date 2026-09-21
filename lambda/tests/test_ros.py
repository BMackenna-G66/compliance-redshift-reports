# -*- coding: utf-8 -*-
"""El registro de Reportes de Operación Sospechosa.

Es un registro regulatorio, así que lo que se prueba acá no son detalles de
implementación: son las propiedades que hacen que el registro sirva como
prueba de qué se decidió y cuándo.

  · Un ROS enviado no vuelve atrás. Fingir que no salió es falsear.
  · No se envía sin narrativa: lo reportado sería un documento vacío.
  · Todo cambio deja rastro con autor. Un registro sin autor no prueba nada.
  · Los montos de reportes distintos NO se suman.
"""
import datetime as dt
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import ros  # noqa: E402

CUANDO = dt.datetime(2026, 9, 21, 15, 0, 0)

CASO = {
    "case_id": "c-1", "entity_id": "9000001", "entity_name": "Ejemplo SpA",
    "entity_type": "customer", "title": "Caso de prueba",
    "created_at": "2026-09-01 10:00:00", "report_name": "structuring_detection",
}
ALERTAS = [
    {"alert_id": "a-1", "reason": "Estructuración", "report_name": "structuring_detection",
     "created_at": "2026-09-05 10:00:00",
     "row_data": {"total_usd_7d": "3290.00", "total_trx_7d": 37}},
    {"alert_id": "a-2", "reason": "Dispersión", "report_name": "beneficiary_dispersion",
     "created_at": "2026-09-02 10:00:00",
     "row_data": {"total_payout_usd_7d": "81072.00", "customer_id": 9000001}},
]


def nuevo(**extra):
    datos = {"case_id": "c-1", "regulador": "UAF-CL",
             "creado_por": "oficial@global66.com", **extra}
    return ros.crear(datos, CASO, ALERTAS, momento=CUANDO)


class LosReguladores(unittest.TestCase):

    def test_son_los_tres_donde_se_reporta(self):
        """El prototipo dibujaba cinco —sumaba México y Brasil— pero eso era
        relleno del diseño."""
        self.assertEqual(set(ros.REGULADORES), {"UIF-AR", "UAF-CL", "UIAF-CO"})

    def test_cada_uno_dice_su_país_y_su_nombre_completo(self):
        for clave, d in ros.REGULADORES.items():
            with self.subTest(clave):
                self.assertTrue(d["pais"] and d["nombre"] and d["completo"])

    def test_uno_que_no_existe_no_se_acepta(self):
        falta = ros.validar_creacion({"case_id": "c-1", "regulador": "UIF-MX",
                                      "creado_por": "x@y.cl"})
        self.assertTrue(any("regulador" in f for f in falta))


class ElFolio(unittest.TestCase):

    def test_arranca_en_uno(self):
        self.assertEqual(ros.siguiente_folio([], CUANDO), "ROS-2026-0001")

    def test_sigue_al_ultimo_del_año(self):
        self.assertEqual(
            ros.siguiente_folio(["ROS-2026-0001", "ROS-2026-0002"], CUANDO),
            "ROS-2026-0003")

    def test_los_años_no_se_mezclan(self):
        """El correlativo es por año: los de 2025 no cuentan para 2026."""
        self.assertEqual(ros.siguiente_folio(["ROS-2025-0099"], CUANDO), "ROS-2026-0001")

    def test_llena_un_hueco_en_vez_de_saltarlo(self):
        """Si el 2 no existe —se creó y se borró— el siguiente lo usa. En un
        registro correlativo, un hueco obliga a explicar qué pasó ahí."""
        self.assertEqual(
            ros.siguiente_folio(["ROS-2026-0001", "ROS-2026-0003"], CUANDO),
            "ROS-2026-0002")

    def test_la_basura_en_la_lista_no_lo_rompe(self):
        for sucio in (["", None, "cualquier cosa", "ROS-XX-0001", "ROS-2026-1"],):
            self.assertEqual(ros.siguiente_folio(sucio, CUANDO), "ROS-2026-0001")

    def test_no_repite_uno_que_ya_existe(self):
        falta = ros.validar_creacion(
            {"case_id": "c-1", "regulador": "UAF-CL", "creado_por": "x@y.cl",
             "folio": "ROS-2026-0001"}, ["ROS-2026-0001"])
        self.assertTrue(any("ya existe" in f for f in falta))


class LaEvidencia(unittest.TestCase):
    """Los hechos los arma el sistema; la narrativa la escribe una persona."""

    def test_recoge_el_sujeto_y_el_caso(self):
        e = ros.evidencia_de(CASO, ALERTAS)
        self.assertEqual(e["sujeto"]["entity_id"], "9000001")
        self.assertEqual(e["caso"]["case_id"], "c-1")

    def test_lista_todas_las_alertas_vinculadas(self):
        e = ros.evidencia_de(CASO, ALERTAS)
        self.assertEqual(e["n_alertas"], 2)
        self.assertEqual({a["alert_id"] for a in e["alertas"]}, {"a-1", "a-2"})

    def test_el_periodo_va_de_la_alerta_mas_vieja_a_la_mas_nueva(self):
        e = ros.evidencia_de(CASO, ALERTAS)
        self.assertEqual(e["periodo"]["desde"], "2026-09-02 10:00:00")
        self.assertEqual(e["periodo"]["hasta"], "2026-09-05 10:00:00")

    def test_LOS_MONTOS_NO_SE_SUMAN(self):
        """Cada reporte mide una cosa distinta: lo girado en 7 días, el
        acumulado de depósitos chicos. Sumarlos daría un total sin significado
        y terminaría escrito en un documento legal."""
        e = ros.evidencia_de(CASO, ALERTAS)
        self.assertNotIn("total", e)
        campos = {m["campo"] for m in e["montos"]}
        self.assertEqual(campos, {"total_usd_7d", "total_payout_usd_7d"})
        # Cada monto dice de qué alerta y de qué campo salió.
        for m in e["montos"]:
            self.assertTrue(m["alerta"] and m["campo"] and m["valor"])

    def test_los_campos_que_no_son_montos_no_entran(self):
        e = ros.evidencia_de(CASO, ALERTAS)
        self.assertNotIn("total_trx_7d", {m["campo"] for m in e["montos"]})
        self.assertNotIn("customer_id", {m["campo"] for m in e["montos"]})

    def test_un_caso_sin_alertas_no_rompe(self):
        e = ros.evidencia_de(CASO, [])
        self.assertEqual(e["n_alertas"], 0)
        self.assertEqual(e["periodo"], {"desde": "", "hasta": ""})

    def test_el_sistema_no_escribe_la_narrativa(self):
        """Un ROS es una afirmación legal firmada. Un texto generado que
        alguien firma sin leer es el accidente que hay que evitar."""
        r = nuevo()
        self.assertEqual(r["narrativa"], "")


class Crear(unittest.TestCase):

    def test_nace_en_borrador(self):
        self.assertEqual(nuevo()["estado"], "borrador")

    def test_exige_autor(self):
        falta = ros.validar_creacion({"case_id": "c-1", "regulador": "UAF-CL"})
        self.assertTrue(any("autor" in f or "quién" in f for f in falta))

    def test_exige_caso(self):
        falta = ros.validar_creacion({"regulador": "UAF-CL", "creado_por": "x@y.cl"})
        self.assertTrue(any("caso" in f for f in falta))

    def test_sin_los_datos_no_se_crea(self):
        with self.assertRaises(ValueError):
            ros.crear({}, CASO, ALERTAS)

    def test_el_plazo_viaja_vacío_pero_existe(self):
        """Se decidió no llevar cuenta regresiva por ahora; el campo queda
        para que agregarla después no obligue a rehacer el modelo."""
        self.assertIn("vence_at", nuevo())
        self.assertEqual(nuevo()["vence_at"], "")

    def test_marca_de_dónde_salió(self):
        """Cuando exista el servicio externo, los de allá se van a distinguir
        de los de acá sin migrar nada."""
        self.assertEqual(nuevo()["origen"], "watchtower")
        self.assertEqual(nuevo(origen="servicio-externo")["origen"], "servicio-externo")
        self.assertEqual(nuevo()["externo_id"], "")

    def test_el_historial_empieza_con_la_creación(self):
        h = nuevo()["historial"]
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["estado"], "borrador")
        self.assertEqual(h[0]["quien"], "oficial@global66.com")


class ElCicloDeVida(unittest.TestCase):

    def test_el_camino_normal(self):
        r = nuevo(narrativa="Se detectó…")
        r = ros.cambiar_estado(r, "revision_legal", "oficial@global66.com", momento=CUANDO)
        self.assertEqual(r["estado"], "revision_legal")
        r = ros.cambiar_estado(r, "enviado", "legal@global66.com", momento=CUANDO)
        self.assertEqual(r["estado"], "enviado")
        self.assertTrue(r["enviado_at"])

    def test_UN_ROS_ENVIADO_NO_VUELVE_ATRAS(self):
        """Ya salió al regulador. Fingir que no sería falsear el registro:
        para corregirlo se emite otro, que es como funciona con las UIF."""
        r = ros.cambiar_estado(nuevo(narrativa="x"), "revision_legal", "a@b.cl", momento=CUANDO)
        r = ros.cambiar_estado(r, "enviado", "a@b.cl", momento=CUANDO)
        for destino in ("borrador", "revision_legal", "descartado"):
            with self.subTest(destino), self.assertRaises(ValueError):
                ros.cambiar_estado(r, destino, "a@b.cl")

    def test_NO_SE_ENVIA_SIN_NARRATIVA(self):
        """Lo reportado sería un documento vacío."""
        r = ros.cambiar_estado(nuevo(), "revision_legal", "a@b.cl", momento=CUANDO)
        with self.assertRaises(ValueError) as e:
            ros.cambiar_estado(r, "enviado", "a@b.cl")
        self.assertIn("narrativa", str(e.exception))

    def test_no_se_salta_la_revision(self):
        with self.assertRaises(ValueError):
            ros.cambiar_estado(nuevo(narrativa="x"), "enviado", "a@b.cl")

    def test_descartar_es_una_decisión_registrable(self):
        """Decidir que algo NO se reporta es tan registrable como decidir que
        sí; sin dónde anotarlo, el caso desaparecería sin rastro."""
        r = ros.cambiar_estado(nuevo(), "descartado", "a@b.cl",
                               nota="Operación justificada", momento=CUANDO)
        self.assertEqual(r["estado"], "descartado")
        self.assertEqual(r["historial"][-1]["nota"], "Operación justificada")

    def test_un_descartado_se_puede_reabrir(self):
        r = ros.cambiar_estado(nuevo(), "descartado", "a@b.cl", momento=CUANDO)
        self.assertEqual(ros.cambiar_estado(r, "borrador", "a@b.cl", momento=CUANDO)["estado"],
                         "borrador")

    def test_TODO_CAMBIO_DEJA_RASTRO_CON_AUTOR(self):
        r = nuevo(narrativa="x")
        r = ros.cambiar_estado(r, "revision_legal", "uno@global66.com", momento=CUANDO)
        r = ros.cambiar_estado(r, "enviado", "otro@global66.com", momento=CUANDO)
        self.assertEqual([h["quien"] for h in r["historial"]],
                         ["oficial@global66.com", "uno@global66.com", "otro@global66.com"])
        for h in r["historial"]:
            self.assertTrue(h["cuando"])

    def test_sin_autor_no_se_mueve(self):
        with self.assertRaises(ValueError):
            ros.cambiar_estado(nuevo(), "revision_legal", "")

    def test_un_estado_inventado_se_rechaza(self):
        with self.assertRaises(ValueError):
            ros.cambiar_estado(nuevo(), "en_tramite", "a@b.cl")

    def test_el_error_dice_qué_sí_se_puede(self):
        """Un «no se puede» sin alternativas obliga a leer el código."""
        with self.assertRaises(ValueError) as e:
            ros.cambiar_estado(nuevo(), "enviado", "a@b.cl")
        self.assertIn("revision_legal", str(e.exception))

    def test_no_muta_el_original(self):
        r = nuevo()
        ros.cambiar_estado(r, "descartado", "a@b.cl", momento=CUANDO)
        self.assertEqual(r["estado"], "borrador")
        self.assertEqual(len(r["historial"]), 1)

    def test_un_enviado_ya_no_es_editable(self):
        r = ros.cambiar_estado(nuevo(narrativa="x"), "revision_legal", "a@b.cl", momento=CUANDO)
        self.assertTrue(ros.editable(r))
        r = ros.cambiar_estado(r, "enviado", "a@b.cl", momento=CUANDO)
        self.assertFalse(ros.editable(r))

    def test_todos_los_estados_se_explican(self):
        for e in ros.ESTADOS:
            with self.subTest(e):
                self.assertGreater(len(ros.ESTADOS[e]), 20)
                self.assertIn(e, ros.TRANSICIONES)


class Indicadores(unittest.TestCase):

    def test_en_curso_es_lo_que_falta_trabajar(self):
        r = [{"estado": "borrador", "regulador": "UAF-CL"},
             {"estado": "revision_legal", "regulador": "UAF-CL"},
             {"estado": "enviado", "regulador": "UIAF-CO"},
             {"estado": "descartado", "regulador": "UIF-AR"}]
        i = ros.indicadores(r)
        self.assertEqual(i["total"], 4)
        self.assertEqual(i["en_curso"], 2)
        self.assertEqual(i["por_regulador"], {"UIF-AR": 1, "UAF-CL": 2, "UIAF-CO": 1})

    def test_los_estados_suman_el_total(self):
        r = [{"estado": e} for e in ("borrador", "enviado", "enviado")]
        i = ros.indicadores(r)
        self.assertEqual(sum(i["por_estado"].values()), i["total"])

    def test_una_lista_vacía_no_rompe(self):
        self.assertEqual(ros.indicadores([])["total"], 0)
        self.assertEqual(ros.indicadores(None)["total"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)


class LosPromediosNoSonMontos(unittest.TestCase):
    """Un ROS lista lo que el cliente MOVIÓ.

    Se vio en la pantalla: entre los montos aparecía `avg_ticket_usd_7d` con
    USD 9,15, al lado de un total de USD 704. Los dos en una lista titulada
    «montos» invitan a leerlos como cosas del mismo orden — y esto va en un
    documento que lee un regulador.
    """

    def _campos(self, fila):
        e = ros.evidencia_de(CASO, [{"alert_id": "a", "row_data": fila}])
        return {m["campo"] for m in e["montos"]}

    def test_los_totales_entran(self):
        self.assertEqual(
            self._campos({"total_usd_7d": "704", "total_payout_usd_7d": "81072"}),
            {"total_usd_7d", "total_payout_usd_7d"})

    def test_los_promedios_no(self):
        self.assertEqual(self._campos({"avg_ticket_usd_7d": "9.15"}), set())
        self.assertEqual(self._campos({"promedio_usd": "10"}), set())

    def test_los_máximos_y_mínimos_tampoco(self):
        self.assertEqual(self._campos({"max_ticket_usd_7d": "529"}), set())

    def test_los_ratios_tampoco(self):
        self.assertEqual(self._campos({"payout_vs_payin_ratio_usd": "3.2"}), set())

    def test_lo_que_no_es_en_dólares_sigue_afuera(self):
        self.assertEqual(self._campos({"total_trx_7d": 37, "customer_id": 1}), set())

    def test_un_total_conserva_su_nombre_de_campo(self):
        """Sin el nombre, «USD 704» no dice de qué: el campo es lo que lo
        vuelve verificable contra la alerta."""
        e = ros.evidencia_de(CASO, [{"alert_id": "a-9", "row_data": {"total_usd_7d": "704"}}])
        self.assertEqual(e["montos"][0], {"alerta": "a-9", "campo": "total_usd_7d",
                                          "valor": "704"})
