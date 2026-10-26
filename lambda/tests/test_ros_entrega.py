# -*- coding: utf-8 -*-
"""`POST /ros/{folio}/entregar`: el camino completo, con GEREO y S3 simulados.

Lo que las funciones puras no pueden probar: que cada control esté CABLEADO,
en el orden correcto, y que cuando algo falla no quede un reporte a medio
mover. Un control que existe y no se llama es peor que no tenerlo.

Las tres que no son obvias:

1. **No se guarda `enviando` antes de llamar.** Guardarlo parece lo prolijo
   —nadie edita mientras GEREO procesa— y deja una trampa: `enviando` sólo
   sale hacia `enviado` o `error_envio`, y las dos las escribe esta función.
   Si la Lambda se muere en el medio, el reporte queda ahí para siempre: no
   editable, no reintentable, sin salida desde ninguna pantalla. Escribiendo
   una sola vez al final, una caída deja el registro intacto en `revisado` y
   el reintento es seguro porque GEREO deduplica por `ros_id + version`.

2. **La narrativa del registro la llena la entrega.** `ros.cambiar_estado`
   exige narrativa para pasar a `enviado`, pero el campo `narrativa` sólo lo
   escribe `POST /ros/{folio}/narrativa`. Un ROS de GEREO editado sólo por el
   formulario de versiones lo tiene vacío, así que ese control frenaría justo
   el camino nuevo. Se completa desde `narrativa_enviada.texto`, que es la
   narrativa de la versión que se firmó.

3. **El 502 con `entregado: False` no es lo mismo que un error.** La etapa se
   movió a `error_envio` y el reporte vuelve a ser editable: hay que poder
   distinguir «no salió y podés corregir» de «no pasó nada».

Ids y correos ficticios: el repo es público.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(_k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_handler as A  # noqa: E402
import gereo as G  # noqa: E402
import ros_versiones as V  # noqa: E402

DOC = {"meta": {"generado_en": "2026-10-20 10:00:00"},
       "secciones": {"1_identificacion": {"cliente": "NOMBRE APELLIDO"}}}
HASH = V.sha256_de(V.canonico(DOC))

CASO = {"case_id": "caso-0001", "entity_name": "NOMBRE APELLIDO",
        "entity_type": "customer", "entity_id": "9000001",
        "alert_data": {"email": "cliente@ejemplo.test"}}

ACTOR = "rocio.cerda@ejemplo.test"


def reporte(**cambios):
    """Un ROS aprobado, listo para entregar."""
    base = {
        "folio": "ROS-2026-0007",
        "case_id": "caso-0001",
        "regulador": "UAF-CL",
        "estado": "revision_legal",
        "etapa_gereo": "revisado",
        "narrativa": "",
        "version_actual": 3,
        "versiones": [{"version": 3, "origen": "edicion",
                       "json_key": "ros/CL/2026/10/ROS-2026-0007/v3.json",
                       "json_sha256": HASH, "pdf_key": "", "pdf_sha256": "",
                       "creada_por": "ana.perez@ejemplo.test",
                       "creada_at": "2026-10-23 15:00:00"}],
        # Con señales gatilladas y sin advertencias: un borrador que no deja
        # puntos pendientes. Es el caso en que no hace falta acuse.
        "borrador_gereo": {"opciones": {"pais": "Chile",
                                        "customer_id": "9000001"},
                           "senales": [{"codigo": "S1", "detalle": "x"}],
                           "advertencias": []},
        "aprobacion": {"version": 3, "json_sha256": HASH,
                       "quien": ACTOR, "cuando": "2026-10-23 15:40:00",
                       "acuse_gereo": False},
        "narrativa_enviada": {"version": 3, "json_sha256": HASH,
                              "texto": "El cliente operó por fuera de su perfil."},
        "historial": [{"estado": "revision_legal", "quien": "ana.perez@ejemplo.test",
                       "cuando": "2026-10-23 14:00:00", "nota": ""}],
        "historial_gereo": [
            {"etapa": "recibido", "quien": "ana.perez@ejemplo.test",
             "cuando": "2026-10-20 10:00:00", "nota": ""},
            {"etapa": "revisado", "quien": "ana.perez@ejemplo.test",
             "cuando": "2026-10-23 14:30:00", "nota": ""}],
    }
    base.update(cambios)
    return base


class Base(unittest.TestCase):

    def setUp(self):
        self.ros = {"ROS-2026-0007": reporte()}
        self.casos = {"caso-0001": dict(CASO)}
        self.puesto = []
        self.auditado = []
        self.llamadas = []
        self.respuesta = (202, {"estado": "RECIBIDO", "entrega_id": "e-0001"})
        self.excepcion = None

        self._orig = {n: getattr(A, n) for n in
                      ("_crm_get", "_crm_put", "_safe_audit",
                       "_leer_version_ros")}
        self._entregar = G.entregar

        def _get(tipo, k):
            if tipo == "ros":
                return self.ros.get(k)
            if tipo == "cases":
                return self.casos.get(k)
            return None

        def _entregar_falso(payload, abrir=None):
            self.llamadas.append(payload)
            if self.excepcion:
                raise self.excepcion
            return self.respuesta

        A._crm_get = _get
        A._crm_put = lambda tipo, k, v: self.puesto.append(v)
        A._safe_audit = lambda **k: self.auditado.append(k)
        A._leer_version_ros = lambda rep, n: DOC
        G.entregar = _entregar_falso

    def tearDown(self):
        for n, f in self._orig.items():
            setattr(A, n, f)
        G.entregar = self._entregar

    def entregar(self, folio="ROS-2026-0007", actor=ACTOR):
        r = A.entregar_ros(folio, {}, actor)
        return r["statusCode"], json.loads(r["body"])

    def guardado(self):
        self.assertTrue(self.puesto, "no guardó nada")
        return self.puesto[-1]


class ElCaminoFeliz(Base):

    def test_entrega_y_responde_200(self):
        codigo, d = self.entregar()
        self.assertEqual(codigo, 200)
        self.assertTrue(d["entrega"]["entregado"])
        self.assertEqual(d["entrega"]["entrega_id"], "e-0001")

    def test_el_payload_que_viaja_es_el_acordado(self):
        self.entregar()
        p = self.llamadas[0]
        self.assertEqual(p["pais"], "Chile")
        self.assertEqual(p["watchtower"]["ros_id"], "ROS-2026-0007")
        self.assertEqual(p["watchtower"]["version"], 3)
        self.assertEqual(p["watchtower"]["hash_json"], HASH)
        self.assertEqual(p["cliente"]["email"], "cliente@ejemplo.test")
        self.assertEqual(p["ros_doc"], DOC)

    def test_queda_en_enviado_en_los_dos_ejes(self):
        self.entregar()
        g = self.guardado()
        self.assertEqual(g["etapa_gereo"], "enviado")
        self.assertEqual(g["estado"], "enviado")
        self.assertTrue(g["enviado_at"])

    def test_el_historial_registra_el_paso_por_enviando(self):
        # Se persiste una sola vez, pero lo que pasó, pasó.
        self.entregar()
        etapas = [e.get("etapa") for e in self.guardado()["historial_gereo"]]
        self.assertEqual(etapas[-2:], ["enviando", "enviado"])

    def test_LA_NARRATIVA_SE_COMPLETA_DESDE_LA_VERSION_APROBADA(self):
        """Sin esto, `cambiar_estado` frena por «reporte sin narrativa» —y el
        campo lo llena una ruta que el camino de GEREO no usa."""
        self.assertEqual(self.ros["ROS-2026-0007"]["narrativa"], "")
        self.entregar()
        self.assertEqual(self.guardado()["narrativa"],
                         "El cliente operó por fuera de su perfil.")

    def test_una_narrativa_escrita_a_mano_no_se_pisa(self):
        self.ros["ROS-2026-0007"]["narrativa"] = "Texto propio del analista."
        self.entregar()
        self.assertEqual(self.guardado()["narrativa"], "Texto propio del analista.")

    def test_guarda_el_acuse_de_la_entrega(self):
        self.entregar()
        e = self.guardado()["entrega"]
        self.assertEqual(e["version"], 3)
        self.assertEqual(e["quien"], ACTOR)
        self.assertEqual(e["codigo"], 202)
        self.assertTrue(e["entregado"])

    def test_se_audita_sin_datos_del_cliente(self):
        self.entregar()
        self.assertEqual(len(self.auditado), 1)
        a = self.auditado[0]
        self.assertEqual(a["action"], "ros.entregado")
        plano = str(a)
        self.assertNotIn("9000001", plano)
        self.assertNotIn("cliente@ejemplo.test", plano)
        self.assertNotIn("NOMBRE APELLIDO", plano)

    def test_EL_200_DE_GEREO_TAMBIEN_BLOQUEA(self):
        """Reenvío de la misma versión: GEREO ya la tiene."""
        self.respuesta = (200, {"estado": "YA_ENTREGADO", "entrega_id": "e-0001"})
        codigo, d = self.entregar()
        self.assertEqual(codigo, 200)
        self.assertTrue(d["entrega"]["entregado"])
        self.assertEqual(self.guardado()["etapa_gereo"], "enviado")


class LoQueNoSale(Base):

    def test_un_folio_que_no_existe_es_404(self):
        codigo, _ = self.entregar(folio="ROS-2026-9999")
        self.assertEqual(codigo, 404)
        self.assertEqual(self.llamadas, [])

    def test_sin_aprobar_no_se_llama_a_gereo(self):
        self.ros["ROS-2026-0007"].pop("aprobacion")
        codigo, d = self.entregar()
        self.assertEqual(codigo, 409)
        self.assertEqual(self.llamadas, [], "llamó a GEREO igual")
        self.assertEqual(self.puesto, [], "escribió igual")

    def test_una_edicion_posterior_a_la_aprobacion_frena(self):
        self.ros["ROS-2026-0007"]["version_actual"] = 4
        codigo, _ = self.entregar()
        self.assertEqual(codigo, 409)
        self.assertEqual(self.llamadas, [])

    def test_sin_correo_del_cliente_frena_antes_de_llamar(self):
        self.casos["caso-0001"]["alert_data"] = {}
        codigo, d = self.entregar()
        self.assertEqual(codigo, 409)
        self.assertIn("correo", d["error"])
        self.assertEqual(self.llamadas, [])

    def test_un_ros_descartado_no_se_entrega(self):
        self.ros["ROS-2026-0007"]["estado"] = "descartado"
        codigo, _ = self.entregar()
        self.assertEqual(codigo, 409)
        self.assertEqual(self.llamadas, [])

    def test_sin_revision_no_se_entrega(self):
        self.ros["ROS-2026-0007"]["etapa_gereo"] = "recibido"
        codigo, _ = self.entregar()
        self.assertEqual(codigo, 409)
        self.assertEqual(self.llamadas, [])

    def test_EL_DOCUMENTO_QUE_NO_ES_EL_APROBADO_NO_SALE(self):
        """Control propio, además del de GEREO: si lo leído de S3 no hashea
        igual que lo firmado, entregar sería mandar algo que nadie aprobó."""
        A._leer_version_ros = lambda rep, n: {**DOC, "secciones": {"x": 1}}
        codigo, d = self.entregar()
        self.assertEqual(codigo, 409)
        self.assertEqual(self.llamadas, [])
        self.assertIn("no coincide", d["error"])

    def test_si_no_puede_leer_la_version_es_502_y_no_llama(self):
        def cae(rep, n):
            raise FileNotFoundError("sin json")
        A._leer_version_ros = cae
        codigo, _ = self.entregar()
        self.assertEqual(codigo, 502)
        self.assertEqual(self.llamadas, [])


class CuandoGereoDiceQueNo(Base):

    def test_un_422_deja_el_reporte_en_error_y_editable(self):
        self.respuesta = (422, {"estado": "INVALIDO", "mensaje": "falta la sección 4",
                                "campo": "ros_doc.secciones"})
        codigo, d = self.entregar()
        self.assertEqual(codigo, 502)
        self.assertFalse(d["entrega"]["entregado"])
        g = self.guardado()
        self.assertEqual(g["etapa_gereo"], "error_envio")
        self.assertEqual(g["estado"], "revision_legal", "movió el eje viejo igual")

    def test_un_422_no_se_marca_reintentable(self):
        self.respuesta = (422, {"estado": "INVALIDO"})
        _, d = self.entregar()
        self.assertFalse(d["entrega"]["reintentable"])

    def test_EL_503_DICE_QUE_NO_ES_UN_ERROR_NUESTRO(self):
        # El endpoint se publica apagado a propósito.
        self.respuesta = (503, {"estado": "DESHABILITADO"})
        _, d = self.entregar()
        self.assertFalse(d["entrega"]["reintentable"])
        self.assertIn("habilitada", d["entrega"]["mensaje"])

    def test_un_5xx_si_es_reintentable(self):
        self.respuesta = (502, {})
        _, d = self.entregar()
        self.assertTrue(d["entrega"]["reintentable"])
        self.assertEqual(self.guardado()["etapa_gereo"], "error_envio")

    def test_un_409_no_bloquea_ni_se_reintenta(self):
        self.respuesta = (409, {"estado": "YA_ENTREGADO",
                                "mensaje": "ya recibimos la v2"})
        _, d = self.entregar()
        self.assertFalse(d["entrega"]["entregado"])
        self.assertFalse(d["entrega"]["reintentable"])

    def test_un_corte_de_red_queda_registrado_como_reintentable(self):
        self.excepcion = G.ErrorGereo("No se pudo hablar con GEREO: timeout",
                                      codigo=0, reintentable=True)
        codigo, d = self.entregar()
        self.assertEqual(codigo, 502)
        self.assertTrue(d["entrega"]["reintentable"])
        self.assertEqual(self.guardado()["etapa_gereo"], "error_envio")

    def test_desde_error_envio_se_puede_reintentar(self):
        self.respuesta = (502, {})
        self.entregar()
        # El reporte quedó en `error_envio`, que sí puede volver a `enviando`.
        self.ros["ROS-2026-0007"] = self.guardado()
        self.puesto.clear()
        self.respuesta = (202, {"estado": "RECIBIDO", "entrega_id": "e-0002"})
        codigo, d = self.entregar()
        self.assertEqual(codigo, 200)
        self.assertEqual(self.guardado()["etapa_gereo"], "enviado")


class NoSeGuardaEnviandoAntesDeLlamar(Base):
    """Si la Lambda se muere entre el `put` y la respuesta, un `enviando`
    persistido deja el reporte sin salida: no editable, no reintentable."""

    def test_no_escribe_nada_antes_de_la_llamada(self):
        visto = {}

        def _entregar(payload, abrir=None):
            visto["escrituras"] = len(self.puesto)
            return (202, {"estado": "RECIBIDO"})
        G.entregar = _entregar
        self.entregar()
        self.assertEqual(visto["escrituras"], 0,
                         "guardó antes de llamar: una caída deja el ROS trabado")

    def test_escribe_una_sola_vez(self):
        self.entregar()
        self.assertEqual(len(self.puesto), 1)

    def test_una_caida_deja_el_registro_intacto(self):
        def revienta(payload, abrir=None):
            raise RuntimeError("la Lambda se murió")
        G.entregar = revienta
        with self.assertRaises(RuntimeError):
            self.entregar()
        self.assertEqual(self.puesto, [])
        self.assertEqual(self.ros["ROS-2026-0007"]["etapa_gereo"], "revisado")


class LaIdempotenciaLocal(Base):

    def test_el_segundo_clic_no_vuelve_a_llamar(self):
        self.entregar()
        self.ros["ROS-2026-0007"] = self.guardado()
        self.llamadas.clear()
        codigo, d = self.entregar()
        self.assertEqual(codigo, 200)
        self.assertEqual(self.llamadas, [], "volvió a entregar")
        self.assertIn("ya se entregó", d["mensaje"])

    def test_el_segundo_clic_no_reescribe(self):
        self.entregar()
        self.ros["ROS-2026-0007"] = self.guardado()
        self.puesto.clear()
        self.entregar()
        self.assertEqual(self.puesto, [])


class LosPendientesDeGereo(Base):
    """El bug que encontró la prueba de punta a punta.

    `bloqueos_para_aprobar` trataba los puntos pendientes del borrador como
    BLOQUEO SECO, y las advertencias vienen en todas las corridas —el reporte
    sale incompleto a propósito—, así que ningún ROS de GEREO se podía
    aprobar jamás. `ros.cambiar_estado` ya explicaba por qué en el camino
    viejo es un acuse y no un bloqueo; el camino nuevo copió el control y
    perdió esa parte.

    No se vio antes porque **no hay ningún ROS en producción**: el flujo
    entero nunca corrió sobre un registro real.
    """

    def con_advertencias(self):
        r = self.ros["ROS-2026-0007"]
        r["borrador_gereo"]["advertencias"] = [
            "La tipología quedó sin definir: la elige el analista."]
        return r

    def test_SIN_ACUSE_NO_SE_ENTREGA_Y_NO_SALE_A_GEREO(self):
        r = self.con_advertencias()
        r["aprobacion"]["acuse_gereo"] = False
        codigo, d = self.entregar()
        self.assertEqual(codigo, 409)
        self.assertEqual(self.llamadas, [])
        self.assertIn("pendientes", d["error"])

    def test_CON_EL_ACUSE_DE_LA_APROBACION_SI_SE_ENTREGA(self):
        r = self.con_advertencias()
        r["aprobacion"]["acuse_gereo"] = True
        codigo, _ = self.entregar()
        self.assertEqual(codigo, 200)
        self.assertEqual(self.guardado()["estado"], "enviado")

    def test_el_acuse_lo_lleva_la_aprobacion_y_no_quien_entrega(self):
        # Quien aprieta «Entregar» puede ser otra persona: hacerle firmar de
        # nuevo lo que ya se firmó sería pedir dos veces lo mismo.
        r = self.con_advertencias()
        r["aprobacion"]["acuse_gereo"] = True
        codigo, _ = self.entregar(actor="otra.persona@ejemplo.test")
        self.assertEqual(codigo, 200)

    def test_queda_registrado_QUE_se_acuso(self):
        r = self.con_advertencias()
        r["aprobacion"]["acuse_gereo"] = True
        self.entregar()
        acuse = self.guardado().get("acuse_gereo") or {}
        self.assertTrue(acuse.get("puntos"), "no dejó qué se acusó")

    def test_un_borrador_sin_senales_tambien_es_un_pendiente(self):
        self.ros["ROS-2026-0007"]["borrador_gereo"]["senales"] = []
        self.ros["ROS-2026-0007"]["aprobacion"]["acuse_gereo"] = False
        codigo, _ = self.entregar()
        self.assertEqual(codigo, 409)
        self.assertEqual(self.llamadas, [])

    def test_un_ros_escrito_a_mano_no_tiene_pendientes(self):
        # Sin `borrador_gereo` no hay nada que acusar: `listo_para_enviar({})`
        # diría «no se gatilló ninguna señal», que sobre un ROS escrito a mano
        # no significa nada y lo trabaría sin motivo.
        self.ros["ROS-2026-0007"]["borrador_gereo"] = None
        self.ros["ROS-2026-0007"]["borrador_gereo"] = None
        # Sin borrador tampoco hay `opciones`, así que falta el customer_id:
        # lo que se prueba es que el motivo NO es el de los pendientes.
        _, d = self.entregar()
        self.assertNotIn("pendientes", d.get("error", ""))


class LaRuta(unittest.TestCase):

    def _por_la_ruta(self, metodo="POST", ruta="/ros/ROS-2026-0007/entregar"):
        r = A.handler({"rawPath": ruta,
                       "requestContext": {"http": {"method": metodo}},
                       "headers": {}, "body": "{}"}, None)
        return r["statusCode"], json.loads(r["body"])

    def test_la_ruta_existe_y_exige_token(self):
        # 401 y no 404: prueba que está cableada. Llamar a `entregar_ros`
        # directo no lo prueba.
        codigo, _ = self._por_la_ruta()
        self.assertEqual(codigo, 401)

    def test_el_GET_no_entrega_nada(self):
        codigo, _ = self._por_la_ruta(metodo="GET")
        # Cae en `detalle_ros`… que también exige token. Lo que importa es que
        # no entregue: un GET no puede tener efectos.
        self.assertEqual(codigo, 401)


if __name__ == "__main__":
    unittest.main()
