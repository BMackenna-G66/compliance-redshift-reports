# -*- coding: utf-8 -*-
"""Revisar y aprobar un ROS.

LO QUE VIGILA ESTE ARCHIVO:

1. **Cuatro ojos de verdad.** No alcanza con que el que aprueba no sea el que
   revisó: tampoco puede ser ninguno de los que editaron el contenido. Si A
   edita la v2 y B la v3, el contenido sigue siendo en parte de A.

2. **El padrón falla cerrado.** Si no se puede leer, no aprueba nadie. Un
   padrón ilegible no significa «todos pueden».

3. **Se aprueba una versión, con su hash.** Si no, «lo aprobó Fulana» no se
   puede probar: el documento aprobado y el que se manda serían dos cosas
   distintas.

4. **El texto de la IA sin tocar se acusa expresamente.** Es la pregunta que
   va a hacer una auditoría.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import ros_aprobacion as AP  # noqa: E402

OFICIALES = ["oficial@example.com"]


def reporte(versiones=(), historial=(), **extra):
    return {
        "folio": "ROS-2026-0001", "regulador": "UAF-CL", "estado": "revision_legal",
        "etapa_gereo": "revisado", "version_actual": len(versiones) or 1,
        "versiones": [dict(v) for v in versiones],
        "historial_gereo": [dict(h) for h in historial],
        **extra,
    }


def v(n, origen, quien):
    return {"version": n, "origen": origen, "creada_por": quien,
            "json_key": f"k{n}", "json_sha256": f"sha{n}", "pdf_key": "",
            "pdf_sha256": "", "creada_at": "2026-10-14 10:00:00"}


class CUATRO_OJOS(unittest.TestCase):
    """El control central, y sin forma de relevarlo."""

    def test_quien_reviso_no_aprueba(self):
        r = reporte([v(1, "gereo", "ana@example.com")],
                    [{"etapa": "revisado", "quien": "oficial@example.com"}])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("marcaste" in f for f in faltan))

    def test_quien_edito_tampoco(self):
        r = reporte([v(1, "gereo", "ana@example.com"),
                     v(2, "edicion", "oficial@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("editaste" in f for f in faltan))

    def test_EDITO_LA_v2_Y_OTRO_LA_v3__TAMPOCO_APRUEBA(self):
        """El contenido de la v3 sigue siendo en parte de quien hizo la v2."""
        r = reporte([v(1, "gereo", "ana@example.com"),
                     v(2, "edicion", "oficial@example.com"),
                     v(3, "edicion", "beto@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("editaste" in f for f in faltan))

    def test_A_edita__B_revisa__A_aprueba__RECHAZADO(self):
        r = reporte([v(1, "gereo", "ana@example.com"),
                     v(2, "edicion", "oficial@example.com")],
                    [{"etapa": "revisado", "quien": "beto@example.com"}])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(faltan)

    def test_PEDIR_EL_REPORTE_NO_ES_ESCRIBIRLO(self):
        """La v1 la generó GEREO a pedido de alguien. Si contara como edición,
        quien lo pidió quedaría inhabilitado sin haber tocado una letra."""
        r = reporte([v(1, "gereo", "oficial@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertEqual(faltan, [])

    def test_todos_los_revisores_cuentan_no_solo_el_ultimo(self):
        """Si A revisó, se editó y B revisó de nuevo, los dos miraron ese
        contenido: ninguno es el par de ojos independiente."""
        r = reporte([v(1, "gereo", "ana@example.com")],
                    [{"etapa": "revisado", "quien": "oficial@example.com"},
                     {"etapa": "recibido", "quien": "beto@example.com"},
                     {"etapa": "revisado", "quien": "beto@example.com"}])
        self.assertEqual(AP.revisores_de(r),
                         {"oficial@example.com", "beto@example.com"})

    def test_el_correo_no_distingue_mayusculas(self):
        r = reporte([v(1, "gereo", "a@example.com"),
                     v(2, "edicion", "Oficial@Example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "OFICIAL@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("editaste" in f for f in faltan))

    def test_se_devuelven_TODOS_los_motivos(self):
        """Arreglar uno y volver a chocar con otro hace que nadie confíe en lo
        que la pantalla dice."""
        r = reporte([v(1, "gereo", "a@example.com"),
                     v(2, "edicion", "x@example.com")],
                    [{"etapa": "revisado", "quien": "x@example.com"}])
        faltan = AP.bloqueos_para_aprobar(r, "x@example.com", [],
                                          acuse_ia=False, narrativa_es_de_ia=True,
                                          acuse_gereo=False)
        self.assertGreaterEqual(len(faltan), 3)


class EL_PADRON_FALLA_CERRADO(unittest.TestCase):

    def test_sin_padron_no_aprueba_nadie(self):
        """Un padrón que no se puede leer no significa «todos pueden»."""
        r = reporte([v(1, "gereo", "a@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "quien.sea@example.com", [],
                                          acuse_ia=False, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("Oficial de Cumplimiento designado" in f
                            for f in faltan))

    def test_alguien_fuera_del_padron_no_aprueba(self):
        r = reporte([v(1, "gereo", "a@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "otro@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("reservada" in f or "reservado" in f for f in faltan))

    def test_lee_las_dos_formas_del_documento(self):
        self.assertEqual(AP.oficiales_de({"oficiales": ["A@x.com"]}), ["a@x.com"])
        self.assertEqual(AP.oficiales_de({"emails": ["A@x.com"]}), ["a@x.com"])
        self.assertEqual(AP.oficiales_de(["A@x.com"]), ["a@x.com"])

    def test_un_documento_con_basura_deja_el_padron_vacio(self):
        for basura in (None, "", 0, "[]", {"otra_cosa": ["a@x.com"]}, []):
            with self.subTest(basura=basura):
                self.assertEqual(AP.oficiales_de(basura), [])

    def test_no_repite_ni_deja_vacios(self):
        self.assertEqual(
            AP.oficiales_de({"oficiales": ["a@x.com", " A@X.com ", "", None]}),
            ["a@x.com"])


class EL_TEXTO_DE_LA_IA_SE_ACUSA(unittest.TestCase):
    """La pregunta que va a hacer una auditoría: ¿esto lo escribió una
    persona? Hoy nadie la podría contestar."""

    V1 = {"1_antecedentes_operaciones_sospechosas": {
        "1_descripcion_hechos_orden_cronologico": "Lo escribió la IA.",
        "2_que_se_considero_sospechoso": "Esto también."}}

    def test_sin_tocar_el_texto_hay_que_acusarlo(self):
        self.assertTrue(AP.narrativa_sin_tocar(self.V1, self.V1, "Chile"))
        r = reporte([v(1, "gereo", "a@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=True,
                                          acuse_gereo=False)
        self.assertTrue(any("redactó la IA" in f for f in faltan))

    def test_con_el_acuse_pasa(self):
        r = reporte([v(1, "gereo", "a@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=True, narrativa_es_de_ia=True,
                                          acuse_gereo=False)
        self.assertEqual(faltan, [])

    def test_si_alguien_lo_reescribio_no_se_pide(self):
        tocado = {"1_antecedentes_operaciones_sospechosas": {
            "1_descripcion_hechos_orden_cronologico": "Lo reescribí yo.",
            "2_que_se_considero_sospechoso": "Esto también."}}
        self.assertFalse(AP.narrativa_sin_tocar(self.V1, tocado, "Chile"))

    def test_CORREGIR_UN_MONTO_NO_CONVIERTE_EL_TEXTO_EN_HUMANO(self):
        """Se compara sólo la narrativa: cambiar un dato duro no cambia quién
        escribió el texto."""
        otro_monto = {
            "1_antecedentes_operaciones_sospechosas": {
                **self.V1["1_antecedentes_operaciones_sospechosas"],
                "monto": 999},
        }
        self.assertTrue(AP.narrativa_sin_tocar(self.V1, otro_monto, "Chile"))

    def test_sin_narrativa_no_se_acusa_nada(self):
        self.assertFalse(AP.narrativa_sin_tocar({}, {}, "Chile"))


class LO_QUE_TOCO_UNA_PERSONA(unittest.TestCase):

    V1 = {"s": {"rut": "11.111.111-1", "monto": 1000, "nota": "",
                "nombre": "Original"}}

    def test_marca_los_campos_vaciados(self):
        """Borrar un dato que GEREO sí trajo es la consecuencia del comodín
        `nulo`, y el documento va a salir sin ese dato."""
        sin_rut = {"s": {**self.V1["s"], "rut": None}}
        d = AP.diferencias_contra_v1(self.V1, sin_rut)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["ruta"], "s.rut")
        self.assertTrue(d[0]["vaciado"])

    def test_llenar_un_campo_vacio_NO_es_vaciarlo(self):
        lleno = {"s": {**self.V1["s"], "nota": "algo"}}
        d = AP.diferencias_contra_v1(self.V1, lleno)
        self.assertFalse(d[0]["vaciado"])

    def test_un_cambio_normal_no_se_marca(self):
        otro = {"s": {**self.V1["s"], "nombre": "Corregido"}}
        d = AP.diferencias_contra_v1(self.V1, otro)
        self.assertEqual(d[0]["antes"], "Original")
        self.assertEqual(d[0]["despues"], "Corregido")
        self.assertFalse(d[0]["vaciado"])

    def test_sin_cambios_no_hay_diff(self):
        self.assertEqual(AP.diferencias_contra_v1(self.V1, self.V1), [])

    def test_un_espacio_en_blanco_cuenta_como_vaciado(self):
        """«   » es un campo borrado con otra forma."""
        d = AP.diferencias_contra_v1(self.V1, {"s": {**self.V1["s"],
                                                     "nombre": "   "}})
        self.assertTrue(d[0]["vaciado"])


class LA_NARRATIVA_SALE_DE_LA_VERSION(unittest.TestCase):
    """Si fuera un campo aparte, el registro podría decir una cosa y el
    regulador recibir otra — peor que un campo vacío, porque nadie lo nota."""

    def test_se_arma_con_los_titulos_del_formulario(self):
        doc = {"1_antecedentes_operaciones_sospechosas": {
            "1_descripcion_hechos_orden_cronologico": "Los hechos.",
            "2_que_se_considero_sospechoso": "Lo sospechoso."}}
        texto = AP.narrativa_para_el_registro(doc, "Chile")
        self.assertIn("Descripción de los hechos", texto)
        self.assertIn("Los hechos.", texto)
        self.assertIn("Qué se consideró sospechoso", texto)

    def test_sin_narrativa_devuelve_vacio(self):
        self.assertEqual(AP.narrativa_para_el_registro({}, "Chile"), "")


class RevisarTambienTieneControles(unittest.TestCase):

    def test_no_se_revisa_un_reporte_sin_version(self):
        self.assertTrue(AP.bloqueos_para_revisar(reporte([])))

    def test_con_version_si(self):
        self.assertEqual(
            AP.bloqueos_para_revisar(reporte([v(1, "gereo", "a@example.com")])),
            [])


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── Los endpoints, con dobles ──────────────────────────────────────────────

import io  # noqa: E402
import json  # noqa: E402

import api_handler as A  # noqa: E402

DOC_V1 = {"meta": {"generado_con_ia": True}, "reglas": [],
          "1_antecedentes_operaciones_sospechosas": {
              "1_descripcion_hechos_orden_cronologico": "Lo escribió la IA.",
              "2_que_se_considero_sospechoso": "Esto también.",
              "monto": 1000},
          "2_identificacion_reportados": {"nombre_o_razon_social": "EJEMPLO SPA"}}


class ElPadronSeLeeDeS3(unittest.TestCase):

    def _con(self, cuerpo=None, explota=False):
        class _S3:
            def get_object(self, **kw):
                if explota:
                    raise RuntimeError("S3 caído")
                return {"Body": io.BytesIO(json.dumps(cuerpo).encode())}
        orig = A.s3
        A.s3 = _S3()
        self.addCleanup(lambda: setattr(A, "s3", orig))

    def test_lee_el_padron(self):
        self._con({"oficiales": ["Oficial@Global66.com"]})
        self.assertEqual(A._oficiales_cumplimiento(), ["oficial@global66.com"])

    def test_SI_NO_SE_PUEDE_LEER_NO_APRUEBA_NADIE(self):
        """Un padrón ilegible no significa «todos pueden»: significa que no
        sabemos quién puede."""
        self._con(explota=True)
        self.assertEqual(A._oficiales_cumplimiento(), [])

    def test_un_padron_vacio_tambien_deja_a_todos_afuera(self):
        self._con({"oficiales": []})
        self.assertEqual(A._oficiales_cumplimiento(), [])


class AprobarDePuntaAPunta(unittest.TestCase):

    def _aprobar(self, cuerpo, actor="oficial@example.com", *, padron=None,
                 versiones=None, historial=None, doc=None, version_actual=1):
        guardado = {}
        vs = versiones if versiones is not None else [v(1, "gereo", "ana@example.com")]
        r = reporte(vs, historial or [], version_actual=version_actual)

        class _S3:
            def get_object(self, **kw):
                clave = kw["Key"]
                if clave == AP.CLAVE_PADRON:
                    if padron is None:
                        raise RuntimeError("sin padrón")
                    return {"Body": io.BytesIO(json.dumps(
                        {"oficiales": padron}).encode())}
                # Por versión: la v1 es lo que generó GEREO y el resto puede
                # estar editado. Si las dos devolvieran lo mismo, el diff
                # saldría vacío y no probaría nada.
                cuerpo = DOC_V1 if clave == "k1" else (doc or DOC_V1)
                return {"Body": io.BytesIO(json.dumps(cuerpo).encode())}

        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_put", "_safe_audit")}
        A.s3 = _S3()
        A._crm_get = lambda t, k: r if t == "ros" else None
        A._crm_put = lambda t, k, x: guardado.update(ros=x)
        A._safe_audit = lambda **k: None
        try:
            res = A.aprobar_ros("ROS-2026-0001", cuerpo, actor)
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return res, guardado.get("ros", {})

    def test_sin_padron_devuelve_403(self):
        res, guardado = self._aprobar({"version": 1, "acuse_ia": True})
        self.assertEqual(res["statusCode"], 403)
        self.assertEqual(guardado, {})

    def test_SIN_EL_ACUSE_DE_IA_NO_APRUEBA(self):
        res, guardado = self._aprobar({"version": 1},
                                      padron=["oficial@example.com"])
        self.assertEqual(res["statusCode"], 403)
        self.assertIn("redactó la IA", json.loads(res["body"])["error"])
        self.assertEqual(guardado, {})

    def test_GUARDA_QUE_SE_APROBO_TEXTO_DE_IA(self):
        """Es lo que contesta una auditoría."""
        res, guardado = self._aprobar({"version": 1, "acuse_ia": True},
                                      padron=["oficial@example.com"])
        self.assertEqual(res["statusCode"], 200)
        ap = guardado["aprobacion"]
        self.assertTrue(ap["texto_de_ia_sin_modificar"])
        self.assertTrue(ap["acuse_ia"])
        self.assertEqual(ap["quien"], "oficial@example.com")
        self.assertEqual(ap["version"], 1)
        self.assertEqual(ap["json_sha256"], "sha1")

    def test_la_narrativa_enviada_sale_de_la_version(self):
        _, guardado = self._aprobar({"version": 1, "acuse_ia": True},
                                    padron=["oficial@example.com"])
        ne = guardado["narrativa_enviada"]
        self.assertEqual(ne["version"], 1)
        self.assertEqual(ne["json_sha256"], "sha1")
        self.assertIn("Lo escribió la IA.", ne["texto"])

    def test_APRUEBA_LA_VERSION_QUE_MIRO_Y_NO_LA_ULTIMA(self):
        """Si alguien guardó entremedio, lo revisado ya no es lo que se
        aprobaría."""
        res, guardado = self._aprobar(
            {"version": 1, "acuse_ia": True}, padron=["oficial@example.com"],
            versiones=[v(1, "gereo", "a@example.com"),
                       v(2, "edicion", "beto@example.com")],
            version_actual=2)
        self.assertEqual(res["statusCode"], 409)
        self.assertIn("mientras revisabas", json.loads(res["body"])["error"])
        self.assertEqual(guardado, {})

    def test_sin_decir_que_version_no_aprueba(self):
        for malo in ({}, {"version": "x"}, {"version": None}):
            with self.subTest(malo=malo):
                res, _ = self._aprobar({**malo, "acuse_ia": True},
                                       padron=["oficial@example.com"])
                self.assertEqual(res["statusCode"], 400)

    def test_el_cuatro_ojos_tambien_corre_en_el_endpoint(self):
        res, guardado = self._aprobar(
            {"version": 2, "acuse_ia": True}, actor="beto@example.com",
            padron=["beto@example.com"],
            versiones=[v(1, "gereo", "a@example.com"),
                       v(2, "edicion", "beto@example.com")],
            version_actual=2)
        self.assertEqual(res["statusCode"], 403)
        self.assertEqual(guardado, {})

    def test_guarda_los_campos_vaciados(self):
        """Quien firma ya los vio; que queden anotados es lo que permite
        auditarlo después."""
        editado = {**DOC_V1, "2_identificacion_reportados": {
            "nombre_o_razon_social": ""}}
        res, guardado = self._aprobar(
            {"version": 2, "acuse_ia": True}, padron=["oficial@example.com"],
            versiones=[v(1, "gereo", "a@example.com"),
                       v(2, "edicion", "beto@example.com")],
            version_actual=2, doc=editado)
        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(guardado["aprobacion"]["campos_vaciados"],
                         ["2_identificacion_reportados.nombre_o_razon_social"])


class DONDE_TIENE_QUE_ESTAR_EL_REPORTE(unittest.TestCase):
    """Sin estos controles se podía aprobar un ROS en «recibido» que NADIE
    revisó: el oficial aprobando solo, sin segundo par de ojos — que es justo
    lo que el cuatro ojos existe para impedir."""

    def _faltan(self, **extra):
        r = reporte([v(1, "gereo", "ana@example.com")], **extra)
        return AP.bloqueos_para_aprobar(
            r, "oficial@example.com", OFICIALES, acuse_ia=True,
            narrativa_es_de_ia=False,
                                          acuse_gereo=False)

    def test_SIN_REVISAR_NO_SE_APRUEBA(self):
        faltan = self._faltan(etapa_gereo="recibido")
        self.assertTrue(any("revisado" in f for f in faltan))

    def test_un_ros_descartado_tampoco(self):
        faltan = self._faltan(estado="descartado")
        self.assertTrue(any("descartado" in f for f in faltan))

    def test_fuera_de_revision_legal_tampoco(self):
        for estado in ("borrador", "enviado", ""):
            with self.subTest(estado=estado):
                faltan = self._faltan(estado=estado)
                self.assertTrue(any("revisión legal" in f for f in faltan))

    def test_ya_enviado_o_enviando_tampoco(self):
        for etapa in ("enviando", "enviado"):
            with self.subTest(etapa=etapa):
                self.assertTrue(self._faltan(etapa_gereo=etapa))

    def _con_pendientes(self):
        r = reporte([v(1, "gereo", "ana@example.com")])
        # Los pendientes salen del `borrador_gereo` del propio reporte.
        r["borrador_gereo"] = {
            "senales": [{"id": "R1"}],
            "advertencias": ["Textos narrativos redactados con IA (borrador)."]}
        return r

    def test_LOS_PENDIENTES_DE_GEREO_SE_ACUSAN_Y_SIN_ACUSE_BLOQUEAN(self):
        """Es el control del PR #97; el camino nuevo no puede esquivarlo.

        CAMBIÓ LA REGLA, NO EL CONTROL. Estaba como bloqueo seco y hacía que
        ningún ROS de GEREO se pudiera aprobar jamás: las advertencias vienen
        en TODAS las corridas, porque el reporte sale incompleto a propósito.
        `ros.cambiar_estado` ya explicaba por qué, en el camino viejo, esto es
        un acuse y no un bloqueo; el camino nuevo copió el control y perdió
        esa parte. Lo encontró la prueba de punta a punta de la entrega.

        Sin el acuse sigue bloqueando, que es lo que este test afirmaba.
        """
        faltan = AP.bloqueos_para_aprobar(
            self._con_pendientes(), "oficial@example.com", OFICIALES,
            acuse_ia=True, narrativa_es_de_ia=False, acuse_gereo=False)
        self.assertTrue(any("IA" in f for f in faltan))

    def test_CON_EL_ACUSE_SE_PUEDE_APROBAR(self):
        """Lo que falta no es que las advertencias desaparezcan: es que
        alguien se haga cargo de haberlas leído, con nombre y hora."""
        faltan = AP.bloqueos_para_aprobar(
            self._con_pendientes(), "oficial@example.com", OFICIALES,
            acuse_ia=True, narrativa_es_de_ia=False, acuse_gereo=True)
        self.assertEqual(faltan, [])

    def test_el_acuse_de_gereo_no_tapa_el_de_la_IA(self):
        # Son dos acuses distintos sobre dos cosas distintas.
        faltan = AP.bloqueos_para_aprobar(
            self._con_pendientes(), "oficial@example.com", OFICIALES,
            acuse_ia=False, narrativa_es_de_ia=True, acuse_gereo=True)
        self.assertTrue(any("expresamente" in f for f in faltan))

    def test_en_revisado_y_revision_legal_pasa(self):
        self.assertEqual(self._faltan(), [])


class UNA_VERSION_NO_SE_APRUEBA_DOS_VECES(unittest.TestCase):
    """La segunda pisaría la primera y la firma original desaparecería."""

    def _con_aprobacion(self, version=1, sha="sha1"):
        return reporte([v(1, "gereo", "ana@example.com")],
                       aprobacion={"version": version, "json_sha256": sha,
                                   "quien": "otro@example.com"})

    def test_la_segunda_se_rechaza(self):
        faltan = AP.bloqueos_para_aprobar(
            self._con_aprobacion(), "oficial@example.com", OFICIALES,
            acuse_ia=True, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("ya está aprobada" in f for f in faltan))

    def test_NADIE_LEE_APROBACION_A_PELO(self):
        """Una aprobación de otra versión no vale para la actual."""
        r = self._con_aprobacion(version=1)
        r["version_actual"] = 2
        r["versiones"].append(v(2, "edicion", "beto@example.com"))
        self.assertIsNone(AP.aprobacion_vigente(r))

    def test_ni_una_con_otro_hash(self):
        """Si el contenido cambió, la firma no lo alcanza."""
        self.assertIsNone(AP.aprobacion_vigente(self._con_aprobacion(sha="otro")))

    def test_la_de_la_version_actual_con_su_hash_si(self):
        self.assertIsNotNone(AP.aprobacion_vigente(self._con_aprobacion()))

    def test_sin_aprobacion_no_inventa_una(self):
        for basura in (None, "", 0, [], "sí"):
            with self.subTest(basura=basura):
                r = reporte([v(1, "gereo", "a@example.com")], aprobacion=basura)
                self.assertIsNone(AP.aprobacion_vigente(r))


class EL_ACUSE_DE_IA_NO_SE_ESQUIVA_CON_UN_ESPACIO(unittest.TestCase):
    """Agregar un punto final o un salto de línea volvía el texto «distinto»
    y el control desaparecía. Nadie lo haría a propósito — y justamente por
    eso: pasaría sin que nadie lo note."""

    V1 = {"1_antecedentes_operaciones_sospechosas": {
        "1_descripcion_hechos_orden_cronologico": "Lo escribió la IA.",
        "2_que_se_considero_sospechoso": "Esto también."}}

    def _con(self, a, b):
        return {"1_antecedentes_operaciones_sospechosas": {
            "1_descripcion_hechos_orden_cronologico": a,
            "2_que_se_considero_sospechoso": b}}

    def test_un_espacio_de_mas_no_lo_convierte_en_humano(self):
        casi = self._con("Lo escribió la IA. ", " Esto también.")
        self.assertTrue(AP.narrativa_sin_tocar(self.V1, casi, "Chile"))

    def test_un_salto_de_linea_tampoco(self):
        casi = self._con("Lo escribió\nla IA.", "Esto  también.")
        self.assertTrue(AP.narrativa_sin_tocar(self.V1, casi, "Chile"))

    def test_una_reescritura_de_verdad_si(self):
        otro = self._con("Esto lo escribí yo, a mano.", "Y esto también.")
        self.assertFalse(AP.narrativa_sin_tocar(self.V1, otro, "Chile"))

    def test_UN_REPORTE_SIN_NARRATIVA_NO_SE_APRUEBA(self):
        """Es lo que lee el regulador: lo que se aprobaría es un documento
        que no dice nada."""
        self.assertFalse(AP.hay_narrativa({}, "Chile"))
        self.assertFalse(AP.hay_narrativa(self._con("", ""), "Chile"))
        self.assertTrue(AP.hay_narrativa(self.V1, "Chile"))


class EDITAR_INVALIDA_LA_APROBACION(unittest.TestCase):
    """La spec es explícita: si alguien edita después de aprobar, la
    aprobación se pierde. Sin esto el ROS seguía llevando la firma de la
    versión anterior sobre un contenido que ya cambió."""

    DOC = {"meta": {}, "reglas": [],
           "1_antecedentes_operaciones_sospechosas": {"monto": 1, "txt": "a"},
           "2_identificacion_reportados": {"nombre": "X"}}

    def _editar(self):
        guardado = {}
        r = {"folio": "ROS-2026-0001", "regulador": "UAF-CL",
             "estado": "revision_legal", "creado_at": "2026-10-14 11:00:00",
             "etapa_gereo": "revisado", "version_actual": 1,
             "versiones": [v(1, "gereo", "ana@example.com")],
             "historial_gereo": [{"etapa": "revisado", "quien": "beto@example.com",
                                  "cuando": "x", "nota": ""}],
             "aprobacion": {"version": 1, "json_sha256": "sha1",
                            "quien": "oficial@example.com", "cuando": "antes"},
             "narrativa_enviada": {"version": 1, "texto": "lo firmado"}}

        class _S3:
            def get_object(self, **kw):
                return {"Body": io.BytesIO(json.dumps(
                    EDITAR_INVALIDA_LA_APROBACION.DOC).encode())}
            def put_object(self, **kw):
                pass

        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_put", "_safe_audit")}
        A.s3 = _S3()
        A._crm_get = lambda t, k: r if t == "ros" else None
        A._crm_put = lambda t, k, x: guardado.update(ros=x)
        A._safe_audit = lambda **k: None
        try:
            res = A.guardar_version_ros(
                "ROS-2026-0001",
                {"secciones": {"1_antecedentes_operaciones_sospechosas":
                               {"monto": 99, "txt": "b"}},
                 "sobre_version": 1},
                "beto@example.com")
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return res, guardado.get("ros", {})

    def test_LA_APROBACION_SE_VA_DEL_REGISTRO(self):
        res, guardado = self._editar()
        self.assertEqual(res["statusCode"], 201)
        self.assertNotIn("aprobacion", guardado)
        self.assertNotIn("narrativa_enviada", guardado)

    def test_y_queda_anotado_QUE_se_invalidó(self):
        """Un campo que desaparece sin rastro es peor que no haberlo tenido."""
        _, guardado = self._editar()
        eventos = [h for h in guardado["historial_gereo"]
                   if h.get("evento") == "aprobacion_invalidada"]
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["version_invalidada"], 1)
        self.assertEqual(eventos[0]["aprobada_por"], "oficial@example.com")

    def test_aprobacion_vigente_lo_confirma(self):
        _, guardado = self._editar()
        self.assertIsNone(AP.aprobacion_vigente(guardado))

    def test_sin_aprobacion_previa_no_anota_nada(self):
        guardado = {}
        r = {"folio": "ROS-2026-0001", "regulador": "UAF-CL",
             "estado": "revision_legal", "creado_at": "2026-10-14 11:00:00",
             "etapa_gereo": "recibido", "version_actual": 1,
             "versiones": [v(1, "gereo", "ana@example.com")]}

        class _S3:
            def get_object(self, **kw):
                return {"Body": io.BytesIO(json.dumps(
                    EDITAR_INVALIDA_LA_APROBACION.DOC).encode())}
            def put_object(self, **kw):
                pass

        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_put", "_safe_audit")}
        A.s3 = _S3()
        A._crm_get = lambda t, k: r if t == "ros" else None
        A._crm_put = lambda t, k, x: guardado.update(ros=x)
        A._safe_audit = lambda **k: None
        try:
            A.guardar_version_ros(
                "ROS-2026-0001",
                {"secciones": {"1_antecedentes_operaciones_sospechosas":
                               {"monto": 99, "txt": "b"}},
                 "sobre_version": 1},
                "beto@example.com")
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        self.assertEqual(
            [h for h in guardado.get("historial_gereo", [])
             if h.get("evento") == "aprobacion_invalidada"], [])


class LaFirmaQuedaEnElRegistro(unittest.TestCase):
    """Aprobar no mueve la etapa, pero es el hecho más importante del
    reporte. Sin esto la única traza era la auditoría general, y el campo
    `aprobacion` se pisa."""

    def test_queda_el_evento_con_la_version_y_el_hash(self):
        caso = AprobarDePuntaAPunta()
        res, guardado = caso._aprobar({"version": 1, "acuse_ia": True},
                                      padron=["oficial@example.com"])
        self.assertEqual(res["statusCode"], 200)
        eventos = [h for h in guardado["historial_gereo"]
                   if h.get("evento") == "aprobado"]
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["quien"], "oficial@example.com")
        self.assertEqual(eventos[0]["json_sha256"], "sha1")
        self.assertTrue(eventos[0]["texto_de_ia_sin_modificar"])


class UNA_EDICION_EN_EL_MEDIO_NO_SE_PISA(unittest.TestCase):
    """Entre la lectura del principio y el `put` se lee S3 dos veces. Si una
    edición entra ahí, escribir sin releer pisaría la versión nueva y el
    registro volvería a apuntar a la vieja — con una firma sobre un contenido
    que ya no es el actual."""

    def test_se_rechaza_con_409(self):
        lecturas = []
        r1 = reporte([v(1, "gereo", "ana@example.com")], version_actual=1)
        # La segunda lectura ve que alguien guardó la v2 entremedio.
        r2 = reporte([v(1, "gereo", "ana@example.com"),
                      v(2, "edicion", "beto@example.com")], version_actual=2)
        guardado = {}

        class _S3:
            def get_object(self, **kw):
                if kw["Key"] == AP.CLAVE_PADRON:
                    return {"Body": io.BytesIO(json.dumps(
                        {"oficiales": ["oficial@example.com"]}).encode())}
                return {"Body": io.BytesIO(json.dumps(DOC_V1).encode())}

        def _get(tipo, clave):
            if tipo != "ros":
                return None
            lecturas.append(1)
            return r1 if len(lecturas) == 1 else r2

        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_put", "_safe_audit")}
        A.s3 = _S3()
        A._crm_get = _get
        A._crm_put = lambda t, k, x: guardado.update(ros=x)
        A._safe_audit = lambda **k: None
        try:
            res = A.aprobar_ros("ROS-2026-0001",
                                {"version": 1, "acuse_ia": True},
                                "oficial@example.com")
        finally:
            for n, f in orig.items():
                setattr(A, n, f)

        self.assertEqual(res["statusCode"], 409)
        self.assertIn("mientras aprobabas", json.loads(res["body"])["error"])
        self.assertEqual(guardado, {}, "pisó la versión nueva")


class NINGUN_DEFAULT_FALLA_ABIERTO(unittest.TestCase):
    """La etapa y los pendientes se calculan DENTRO de la función.

    Como parámetros con default, un llamador que no los pasara saltearía el
    control en silencio — y el próximo que use esta función sin ese kwarg
    reabriría exactamente lo que cierra. Un control que depende de que lo
    invoquen bien no es un control.
    """

    def test_llamada_minima_sobre_un_ros_sin_revisar__BLOQUEA(self):
        r = reporte([v(1, "gereo", "ana@example.com")], etapa_gereo="recibido")
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=True, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("revisado" in f for f in faltan))

    def test_llamada_minima_con_pendientes__BLOQUEA(self):
        r = reporte([v(1, "gereo", "ana@example.com")])
        r["borrador_gereo"] = {"senales": [{"id": "R1"}],
                               "advertencias": ["Falta la temática."]}
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=True, narrativa_es_de_ia=False,
                                          acuse_gereo=False)
        self.assertTrue(any("temática" in f for f in faltan))

    def test_la_firma_ya_no_acepta_esos_kwargs(self):
        """Si alguien los vuelve a agregar, esto lo dice."""
        import inspect
        params = inspect.signature(AP.bloqueos_para_aprobar).parameters
        self.assertNotIn("etapa", params)
        self.assertNotIn("pendientes", params)

    def test_NINGUN_ACUSE_TIENE_DEFAULT(self):
        """Misma regla para `acuse_gereo` que para los otros dos.

        Un acuse con default es un acuse que el próximo llamador omite sin
        enterarse — y omitir un acuse es firmar en nombre de otro.
        """
        import inspect
        params = inspect.signature(AP.bloqueos_para_aprobar).parameters
        for nombre in ("acuse_ia", "narrativa_es_de_ia", "acuse_gereo"):
            self.assertIn(nombre, params)
            self.assertIs(params[nombre].default, inspect.Parameter.empty,
                          f"{nombre} tiene default: se puede saltear")


class NI_LA_PUNTUACION_NI_LAS_MAYUSCULAS_SON_AUTORIA(unittest.TestCase):
    """Un punto final o una letra capital no convierten texto de IA en texto
    humano: es la misma evasión que el espacio, con otra ropa."""

    V1 = {"1_antecedentes_operaciones_sospechosas": {
        "1_descripcion_hechos_orden_cronologico": "El cliente operó fuera de perfil",
        "2_que_se_considero_sospechoso": "Los montos no cuadran"}}

    def _con(self, a, b):
        return {"1_antecedentes_operaciones_sospechosas": {
            "1_descripcion_hechos_orden_cronologico": a,
            "2_que_se_considero_sospechoso": b}}

    def test_un_punto_final(self):
        casi = self._con("El cliente operó fuera de perfil.",
                         "Los montos no cuadran.")
        self.assertTrue(AP.narrativa_sin_tocar(self.V1, casi, "Chile"))

    def test_mayusculas(self):
        casi = self._con("EL CLIENTE OPERÓ FUERA DE PERFIL",
                         "los montos no cuadran")
        self.assertTrue(AP.narrativa_sin_tocar(self.V1, casi, "Chile"))

    def test_comas_y_comillas(self):
        casi = self._con("El cliente, operó fuera de perfil",
                         "«Los montos» no cuadran")
        self.assertTrue(AP.narrativa_sin_tocar(self.V1, casi, "Chile"))

    def test_PERO_CAMBIAR_UNA_PALABRA_SI_ES_REESCRIBIR(self):
        otro = self._con("El cliente operó dentro de perfil",
                         "Los montos no cuadran")
        self.assertFalse(AP.narrativa_sin_tocar(self.V1, otro, "Chile"))

    def test_y_las_tildes_siguen_contando(self):
        """`operó` y `opero` son dos palabras distintas."""
        otro = self._con("El cliente opero fuera de perfil",
                         "Los montos no cuadran")
        self.assertFalse(AP.narrativa_sin_tocar(self.V1, otro, "Chile"))
