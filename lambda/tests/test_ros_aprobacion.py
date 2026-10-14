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
                                          acuse_ia=False, narrativa_es_de_ia=False)
        self.assertTrue(any("marcaste" in f for f in faltan))

    def test_quien_edito_tampoco(self):
        r = reporte([v(1, "gereo", "ana@example.com"),
                     v(2, "edicion", "oficial@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False)
        self.assertTrue(any("editaste" in f for f in faltan))

    def test_EDITO_LA_v2_Y_OTRO_LA_v3__TAMPOCO_APRUEBA(self):
        """El contenido de la v3 sigue siendo en parte de quien hizo la v2."""
        r = reporte([v(1, "gereo", "ana@example.com"),
                     v(2, "edicion", "oficial@example.com"),
                     v(3, "edicion", "beto@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False)
        self.assertTrue(any("editaste" in f for f in faltan))

    def test_A_edita__B_revisa__A_aprueba__RECHAZADO(self):
        r = reporte([v(1, "gereo", "ana@example.com"),
                     v(2, "edicion", "oficial@example.com")],
                    [{"etapa": "revisado", "quien": "beto@example.com"}])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False)
        self.assertTrue(faltan)

    def test_PEDIR_EL_REPORTE_NO_ES_ESCRIBIRLO(self):
        """La v1 la generó GEREO a pedido de alguien. Si contara como edición,
        quien lo pidió quedaría inhabilitado sin haber tocado una letra."""
        r = reporte([v(1, "gereo", "oficial@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False)
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
                                          acuse_ia=False, narrativa_es_de_ia=False)
        self.assertTrue(any("editaste" in f for f in faltan))

    def test_se_devuelven_TODOS_los_motivos(self):
        """Arreglar uno y volver a chocar con otro hace que nadie confíe en lo
        que la pantalla dice."""
        r = reporte([v(1, "gereo", "a@example.com"),
                     v(2, "edicion", "x@example.com")],
                    [{"etapa": "revisado", "quien": "x@example.com"}])
        faltan = AP.bloqueos_para_aprobar(r, "x@example.com", [],
                                          acuse_ia=False, narrativa_es_de_ia=True)
        self.assertGreaterEqual(len(faltan), 3)


class EL_PADRON_FALLA_CERRADO(unittest.TestCase):

    def test_sin_padron_no_aprueba_nadie(self):
        """Un padrón que no se puede leer no significa «todos pueden»."""
        r = reporte([v(1, "gereo", "a@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "quien.sea@example.com", [],
                                          acuse_ia=False, narrativa_es_de_ia=False)
        self.assertTrue(any("Oficial de Cumplimiento designado" in f
                            for f in faltan))

    def test_alguien_fuera_del_padron_no_aprueba(self):
        r = reporte([v(1, "gereo", "a@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "otro@example.com", OFICIALES,
                                          acuse_ia=False, narrativa_es_de_ia=False)
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
                                          acuse_ia=False, narrativa_es_de_ia=True)
        self.assertTrue(any("redactó la IA" in f for f in faltan))

    def test_con_el_acuse_pasa(self):
        r = reporte([v(1, "gereo", "a@example.com")])
        faltan = AP.bloqueos_para_aprobar(r, "oficial@example.com", OFICIALES,
                                          acuse_ia=True, narrativa_es_de_ia=True)
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
