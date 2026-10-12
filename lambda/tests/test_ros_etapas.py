# -*- coding: utf-8 -*-
"""La etapa del ROS en el camino a GEREO.

LO QUE VIGILA ESTE ARCHIVO:

1. **Los dos ejes no se pisan.** `estado` dice en qué punto del trabajo de
   compliance está el reporte; `etapa_gereo`, en qué punto del camino al
   regulador está el documento. Meterlos en una sola lista obligaba a elegir
   cuál de las dos verdades se guarda.

2. **El puente va en un sentido y respeta las reglas del eje viejo.** Un ROS
   descartado no sigue camino, y aprobar exige que alguien lo haya puesto en
   revisión. El puente frena; no empuja.

3. **Un registro viejo se lee sin migrar.** Sin el campo, la etapa es
   `sin_ros` y nada explota.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import ros as R          # noqa: E402
import ros_etapas as E   # noqa: E402

CUANDO = "2026-10-12 11:00:00"


def ros(etapa=None, estado="borrador", **extra):
    r = {"folio": "ROS-2026-0001", "regulador": "UAF-CL", "estado": estado,
         "narrativa": "x", **extra}
    if etapa:
        r["etapa_gereo"] = etapa
    return r


class LOS_DOS_EJES_NO_SE_PISAN(unittest.TestCase):
    """La decisión que ordena el módulo."""

    def test_el_unico_nombre_compartido_es_el_del_puente(self):
        """`enviado` está en los dos ejes A PROPÓSITO: es el punto donde se
        tocan, porque significan el mismo hecho del mundo —se reportó al
        regulador— y `etapa_gereo = enviado` dispara `estado = enviado`.

        Cualquier OTRO nombre repetido sería una fusión empezando, que es lo
        que este módulo existe para evitar."""
        self.assertEqual(set(E.ETAPAS) & set(R.ESTADOS), {"enviado"})

    def test_los_dos_enviado_son_finales_en_su_eje(self):
        """Si uno se pudiera desandar y el otro no, el puente dejaría al ROS
        diciendo dos cosas distintas sobre el mismo hecho."""
        self.assertEqual(E.TRANSICIONES["enviado"], [])
        self.assertEqual(R.TRANSICIONES["enviado"], [])

    def test_el_eje_viejo_quedo_intacto(self):
        self.assertEqual(sorted(R.ESTADOS),
                         ["borrador", "descartado", "enviado", "revision_legal"])
        self.assertEqual(R.TRANSICIONES["revision_legal"],
                         ["borrador", "enviado", "descartado"])

    def test_un_ros_puede_estar_en_revision_y_recien_recibido(self):
        """El caso que un solo campo no puede representar."""
        r = ros("recibido", estado="revision_legal")
        self.assertEqual(E.etapa_de(r), "recibido")
        self.assertEqual(r["estado"], "revision_legal")

    def test_descartado_sigue_existiendo(self):
        """Vive en `estado` y el documento del analista no lo nombraba. Era
        una omisión, no una baja."""
        self.assertIn("descartado", R.ESTADOS)
        self.assertNotIn("descartado", E.ETAPAS)

    def test_el_historial_de_cada_eje_va_aparte(self):
        """Mezclarlos daría una lista donde «revisado» y «revision_legal» se
        leen como lo mismo."""
        r = E.cambiar(ros("recibido"), "revisado", "a@example.com", momento=CUANDO)
        self.assertEqual(len(E.historial_de(r)), 1)
        self.assertEqual(r.get("historial", []), [])


class ELPUENTERESPETAELEJEVIEJO(unittest.TestCase):

    def test_un_ros_descartado_no_sigue_camino(self):
        """Se evaluó y se decidió no reportar: moverlo hacia el regulador
        sería contradecir esa decisión desde otra pantalla."""
        r = ros("recibido", estado="descartado")
        self.assertTrue(any("descartado" in b for b in E.bloqueos(r, "revisado")))
        with self.assertRaises(ValueError):
            E.cambiar(r, "revisado", "a@example.com", momento=CUANDO)

    def test_aprobar_exige_revision_legal(self):
        r = ros("revisado", estado="borrador")
        self.assertTrue(any("revisión legal" in b for b in E.bloqueos(r, "enviando")))

    def test_con_revision_legal_se_puede_aprobar(self):
        r = ros("revisado", estado="revision_legal")
        self.assertEqual(E.bloqueos(r, "enviando"), [])

    def test_EL_PUENTE_NO_FUERZA_LA_TRANSICION_DEL_EJE_VIEJO(self):
        """Se frena, no se empuja. Aprobar un reporte que nadie puso en
        revisión saltearía el paso que existe para que lo mire otra persona."""
        r = ros("revisado", estado="borrador")
        with self.assertRaises(ValueError):
            E.cambiar(r, "enviando", "a@example.com", momento=CUANDO)
        self.assertEqual(r["estado"], "borrador", "le tocó el estado")

    def test_las_otras_etapas_no_piden_revision_legal(self):
        """Sólo aprobar. Revisar es justamente lo que se hace antes."""
        self.assertEqual(E.bloqueos(ros("recibido", estado="borrador"),
                                    "revisado"), [])


class LasTransicionesSonLasDeLaEspecificacion(unittest.TestCase):

    def test_el_camino_feliz(self):
        r = ros()
        for etapa in ("recibido", "revisado", "enviando", "enviado"):
            if etapa == "enviando":
                r["estado"] = "revision_legal"
            r = E.cambiar(r, etapa, "a@example.com", momento=CUANDO)
        self.assertEqual(E.etapa_de(r), "enviado")
        self.assertEqual([h["etapa"] for h in E.historial_de(r)],
                         ["recibido", "revisado", "enviando", "enviado"])

    def test_EDITAR_DESPUES_DE_REVISAR_INVALIDA_LA_REVISION(self):
        """No es un retroceso raro: es el control de la especificación."""
        self.assertTrue(E.puede_pasar("revisado", "recibido"))

    def test_un_enviado_no_vuelve_atras(self):
        """Lo que el regulador ya recibió no se desdice desde una pantalla."""
        self.assertEqual(E.TRANSICIONES["enviado"], [])
        for destino in ("recibido", "revisado", "enviando", "error_envio"):
            with self.subTest(destino):
                self.assertFalse(E.puede_pasar("enviado", destino))

    def test_un_error_se_reintenta_o_se_edita(self):
        self.assertEqual(sorted(E.TRANSICIONES["error_envio"]),
                         ["enviando", "recibido"])

    def test_no_se_saltea_la_revision(self):
        self.assertFalse(E.puede_pasar("recibido", "enviando"))

    def test_mientras_gereo_procesa_el_payload_se_queda_quieto(self):
        self.assertFalse(E.editable(ros("enviando")))
        self.assertFalse(E.editable(ros("enviado")))
        for etapa in ("recibido", "revisado", "error_envio"):
            with self.subTest(etapa):
                self.assertTrue(E.editable(ros(etapa)))

    def test_una_etapa_inventada_no_entra(self):
        r = ros("recibido")
        self.assertTrue(E.bloqueos(r, "magia"))
        with self.assertRaises(ValueError):
            E.cambiar(r, "magia", "a@example.com", momento=CUANDO)

    def test_sin_autor_no_hay_cambio(self):
        """Es un registro regulatorio: quién lo movió es lo que se audita."""
        for vacio in ("", "   ", None):
            with self.subTest(vacio=vacio), self.assertRaises(ValueError):
                E.cambiar(ros("recibido"), "revisado", vacio, momento=CUANDO)


class UnRegistroViejoSeLeeSinMigrar(unittest.TestCase):

    def test_sin_el_campo_la_etapa_es_sin_ros(self):
        self.assertEqual(E.etapa_de({"folio": "ROS-2026-0001"}), "sin_ros")

    def test_un_campo_con_basura_no_revienta(self):
        for basura in (None, "", 0, "magia", {"a": 1}, []):
            with self.subTest(basura=basura):
                self.assertEqual(E.etapa_de({"etapa_gereo": basura}), "sin_ros")

    def test_un_historial_con_basura_tampoco(self):
        for basura in (None, "", 0, {"a": 1}, "[]"):
            with self.subTest(basura=basura):
                self.assertEqual(E.historial_de({"historial_gereo": basura}), [])

    def test_un_ros_escrito_a_mano_nunca_entra_acá(self):
        """No todo ROS nace en GEREO, y el que no nace ahí se mueve por el
        camino de siempre sin tocar este eje."""
        r = ros()
        self.assertEqual(E.etapa_de(r), "sin_ros")
        movido = R.cambiar_estado(r, "revision_legal", "a@example.com")
        self.assertEqual(E.etapa_de(movido), "sin_ros")

    def test_cambiar_no_muta_el_reporte_que_recibe(self):
        r = ros("recibido")
        E.cambiar(r, "revisado", "a@example.com", momento=CUANDO)
        self.assertEqual(E.etapa_de(r), "recibido", "mutó el original")


class LaEtapaDiceDeQueVersionHabla(unittest.TestCase):
    """Una etapa sin versión no dice nada cuando el ROS tiene cinco."""

    def test_anota_la_version_en_juego(self):
        r = E.cambiar(ros("recibido", version_actual=3), "revisado",
                      "a@example.com", momento=CUANDO)
        self.assertEqual(E.historial_de(r)[-1]["version"], 3)

    def test_sin_versiones_no_inventa_el_campo(self):
        r = E.cambiar(ros("recibido"), "revisado", "a@example.com", momento=CUANDO)
        self.assertNotIn("version", E.historial_de(r)[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class LaEtapaYLaVersionNoSeConfundenAlFallar(unittest.TestCase):
    """Observación de la auditoría sobre el #101.

    Si el cambio de etapa viviera en el mismo `try` que el guardado de la
    versión, un fallo al mover la etapa dejaría el ROS marcado con
    `version_error` aunque la v1 SÍ se haya guardado. El registro mentiría
    sobre qué falló, que es peor que no decir nada.
    """

    def _crear(self, s3_clase, etapas_rotas=False):
        import io
        import json as _json
        import api_handler as A
        import ros_etapas as _E
        borrador = _json.dumps({"ros_doc": {"a": 1},
                                "opciones": {"pais": "Chile"},
                                "senales": [], "advertencias": []}).encode()

        class _S3(s3_clase):
            def get_object(self, **kw):
                return {"Body": io.BytesIO(borrador)}

        class _EtapasRotas:
            def cambiar(self, *a, **k):
                raise RuntimeError("etapa rota")
            etapa_de = staticmethod(_E.etapa_de)

        guardado = {}
        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_list", "_crm_put", "_safe_audit",
                 "ros_etapas")}
        A.s3 = _S3()
        A._crm_get = lambda t, k: ({"case_id": "c-1"} if t == "cases" else None)
        A._crm_list = lambda t: []
        A._crm_put = lambda t, k, v: guardado.update(ros=v)
        A._safe_audit = lambda **k: None
        if etapas_rotas:
            A.ros_etapas = _EtapasRotas()
        try:
            A.crear_ros({"case_id": "c-1", "regulador": "UAF-CL",
                         "actor_email": "analista@example.com",
                         "gereo_run_id": "run-1"})
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return guardado.get("ros", {})

    def test_si_falla_la_etapa_NO_se_marca_un_error_de_version(self):
        class _Bien:
            def put_object(self, **kw):
                pass
        guardado = self._crear(_Bien, etapas_rotas=True)
        self.assertNotIn("version_error", guardado,
                         "el registro miente: la v1 se guardó bien")
        self.assertEqual(len(guardado.get("versiones", [])), 1)

    def test_si_falla_la_version_la_etapa_no_avanza(self):
        """Sin versión guardada no hay nada «recibido»."""
        class _Rota:
            def put_object(self, **kw):
                raise RuntimeError("S3 caído")
        guardado = self._crear(_Rota)
        self.assertEqual(E.etapa_de(guardado), "sin_ros")
        self.assertEqual(guardado["version_error"]["motivo"], "RuntimeError")

    def test_el_camino_normal_deja_la_v1_y_la_etapa(self):
        class _Bien:
            def put_object(self, **kw):
                pass
        guardado = self._crear(_Bien)
        self.assertEqual(E.etapa_de(guardado), "recibido")
        self.assertEqual(len(guardado["versiones"]), 1)
        self.assertEqual(E.historial_de(guardado)[-1]["version"], 1)
