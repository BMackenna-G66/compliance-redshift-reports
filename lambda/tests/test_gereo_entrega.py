# -*- coding: utf-8 -*-
"""La entrega del ROS aprobado a GEREO: el payload y cómo se lee la respuesta.

Cuatro cosas que, si se rompen, rompen la integración entera y no de a poco:

1. **El hash.** GEREO valida que `hash_json` sea el SHA-256 de `ros_doc`. El
   SHA-256 de un objeto JSON no existe: existe el de unos bytes, y los bytes
   dependen de cómo se serialice. Si las dos partes serializan distinto,
   **todas** las entregas son 422. Acá se fija que nuestro hash es el de
   `ros_versiones.canonico` y que el documento que se manda es el que se
   firmó al aprobar.

2. **El 503 significa lo contrario que en la generación.** Allá es «la fuente
   no responde» y se reintenta; acá es «el endpoint está apagado» y no. Si se
   compartiera la tabla, el reintento haría exactamente lo contrario de lo
   que corresponde en los dos casos.

3. **El 200 es un éxito, no un «nada pasó».** Es el reenvío de la misma
   versión: GEREO ya la tiene, así que el ROS se bloquea igual que con un 202.
   Tratarlo como no-entregado dejaría un ROS editable que el regulador ya
   recibió.

4. **El correo del cliente.** GEREO nombra la carpeta de Drive con él, y uno
   de los casos reales tiene el correo de NUESTRO analista en
   `client_profile.compliance_agent`. Buscar «el primer campo que parezca un
   correo» crearía una carpeta a nombre de un empleado.

Los ids y correos son ficticios: el repo es público.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(_k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import gereo_entrega as E  # noqa: E402
import ros_versiones as V  # noqa: E402

DOC = {
    "meta": {"generado_en": "2026-10-20 10:00:00"},
    "secciones": {"1_identificacion": {"cliente": "NOMBRE APELLIDO"}},
}
HASH = V.sha256_de(V.canonico(DOC))

CASO = {
    "case_id": "a1b2c3d4-0000-0000-0000-000000000001",
    "entity_name": "NOMBRE APELLIDO",
    "alert_data": {"email": "cliente@ejemplo.test", "monto": 1000},
}


def reporte(**cambios):
    base = {
        "folio": "ROS-2026-0007",
        "case_id": "a1b2c3d4-0000-0000-0000-000000000001",
        "regulador": "UAF-CL",
        "version_actual": 3,
        "borrador_gereo": {"opciones": {"pais": "Chile",
                                        "customer_id": "9000001",
                                        "fecha_inicio": "01/2026"}},
        "aprobacion": {"version": 3, "json_sha256": HASH,
                       "quien": "ana.perez@ejemplo.test",
                       "cuando": "2026-10-23 15:40:00"},
    }
    base.update(cambios)
    return base


class ElCorreoDelCliente(unittest.TestCase):

    def test_sale_de_alert_data_email(self):
        c, de = E.correo_del_cliente(CASO)
        self.assertEqual(c, "cliente@ejemplo.test")
        self.assertEqual(de, "alert_data.email")

    def test_cae_a_customer_email(self):
        caso = {"alert_data": {"customer_email": "otro@ejemplo.test"}}
        self.assertEqual(E.correo_del_cliente(caso)[0], "otro@ejemplo.test")

    def test_cae_a_client_profile(self):
        caso = {"client_profile": {"email": "tercero@ejemplo.test"}}
        self.assertEqual(E.correo_del_cliente(caso)[0], "tercero@ejemplo.test")

    def test_NO_usa_el_correo_de_nuestro_analista(self):
        """`client_profile.compliance_agent` es un correo válido y es NUESTRO.

        Un caso real lo tiene. Buscar «el primer campo que parezca correo» lo
        tomaría y GEREO crearía la carpeta del cliente a nombre de un
        empleado de Global66, dentro del expediente de un reporte regulatorio.
        """
        caso = {"client_profile": {"compliance_agent": "analista@global66.test"}}
        self.assertEqual(E.correo_del_cliente(caso), ("", ""))

    def test_el_orden_es_el_de_la_frecuencia_real(self):
        # 189 casos tienen `email` y 56 `customer_email`. Con los dos, gana el
        # primero: es el del cliente reportado en la alerta.
        caso = {"alert_data": {"email": "primero@ejemplo.test",
                               "customer_email": "segundo@ejemplo.test"}}
        self.assertEqual(E.correo_del_cliente(caso)[0], "primero@ejemplo.test")

    def test_un_valor_que_no_es_correo_no_cuenta(self):
        caso = {"alert_data": {"email": "no tiene arroba"}}
        self.assertEqual(E.correo_del_cliente(caso), ("", ""))

    def test_sin_bloques_no_rompe(self):
        self.assertEqual(E.correo_del_cliente({}), ("", ""))
        self.assertEqual(E.correo_del_cliente(None), ("", ""))

    def test_un_bloque_que_no_es_dict_no_rompe(self):
        # `alert_data` viene como string JSON en algunos registros.
        self.assertEqual(E.correo_del_cliente({"alert_data": "{...}"}), ("", ""))


class ElPayload(unittest.TestCase):

    def setUp(self):
        self.p = E.payload(reporte(), CASO, DOC,
                           url_base="https://watchtower.ejemplo.test/app")

    def test_tiene_la_forma_acordada(self):
        self.assertEqual(sorted(self.p),
                         ["cliente", "opciones", "pais", "ros_doc", "watchtower"])

    def test_el_pais_sale_del_regulador(self):
        self.assertEqual(self.p["pais"], "Chile")

    def test_los_datos_de_watchtower(self):
        w = self.p["watchtower"]
        self.assertEqual(w["ros_id"], "ROS-2026-0007")
        self.assertEqual(w["version"], 3)
        self.assertEqual(w["hash_json"], HASH)
        self.assertEqual(w["aprobado_por"], "ana.perez@ejemplo.test")
        self.assertEqual(w["aprobado_en"], "2026-10-23 15:40:00")

    def test_el_enlace_abre_el_caso_y_no_la_bandeja(self):
        self.assertTrue(self.p["watchtower"]["url"].endswith(
            "/#/cases/a1b2c3d4-0000-0000-0000-000000000001"))

    def test_NO_lleva_el_pdf(self):
        # GEREO lo regenera desde `ros_doc` (4.2), así el PDF siempre dice lo
        # mismo que el JSON aprobado. Mandar el nuestro abriría la puerta a
        # que digan cosas distintas.
        plano = str(self.p)
        self.assertNotIn("pdf", plano.lower())

    def test_las_opciones_van_tal_cual(self):
        self.assertEqual(self.p["opciones"]["customer_id"], "9000001")
        self.assertEqual(self.p["opciones"]["pais"], "Chile")

    def test_el_cliente_se_arma_de_las_tres_fuentes(self):
        self.assertEqual(self.p["cliente"], {
            "customer_id": "9000001",
            "nombre": "NOMBRE APELLIDO",
            "email": "cliente@ejemplo.test"})

    def test_el_customer_id_sale_de_opciones_no_del_caso(self):
        # Es lo que GEREO cruza contra `cliente.customer_id` en 4.1, y es con
        # lo que se emitió ESTE reporte.
        caso = {**CASO, "entity_id": "7777777"}
        p = E.payload(reporte(), caso, DOC)
        self.assertEqual(p["cliente"]["customer_id"], "9000001")

    def test_sin_url_base_no_arma_un_enlace_roto(self):
        p = E.payload(reporte(), CASO, DOC, url_base="")
        self.assertEqual(p["watchtower"]["url"], "")

    def test_sin_caso_id_devuelve_la_base_y_no_una_url_rota(self):
        self.assertEqual(E.url_del_caso("https://x.test/app", ""),
                         "https://x.test/app")


class ElHash(unittest.TestCase):

    def test_el_documento_aprobado_coincide(self):
        self.assertEqual(E.desajuste_de_hash(reporte(), DOC), "")

    def test_UN_DOCUMENTO_DISTINTO_NO_SE_ENTREGA(self):
        """Si lo leído de S3 no hashea igual que lo firmado, entregar sería
        mandarle al regulador algo que nadie aprobó."""
        otro = {**DOC, "secciones": {"1_identificacion": {"cliente": "OTRO"}}}
        self.assertNotEqual(E.desajuste_de_hash(reporte(), otro), "")

    def test_sin_hash_firmado_tampoco_se_entrega(self):
        r = reporte(aprobacion={"version": 3, "quien": "a@b.test"})
        self.assertIn("hash", E.desajuste_de_hash(r, DOC))

    def test_el_motivo_no_lleva_los_hashes(self):
        otro = {**DOC, "extra": 1}
        texto = E.desajuste_de_hash(reporte(), otro)
        self.assertNotIn(HASH, texto)

    def test_nuestro_hash_es_el_de_la_forma_canonica(self):
        """EL ACUERDO CON GEREO, ESCRITO. Si GEREO serializa distinto, ningún
        hash va a coincidir nunca y todas las entregas van a ser 422."""
        import hashlib
        import json as _json
        esperado = hashlib.sha256(_json.dumps(
            DOC, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()
        self.assertEqual(HASH, esperado)

    def test_el_orden_de_las_claves_no_cambia_el_hash(self):
        al_reves = {"secciones": DOC["secciones"], "meta": DOC["meta"]}
        self.assertEqual(V.sha256_de(V.canonico(al_reves)), HASH)

    def test_los_acentos_no_se_escapan(self):
        # `ensure_ascii=False`: un ROS en castellano está lleno de acentos y
        # la diferencia cambia el hash de punta a punta.
        doc = {"a": "operación"}
        self.assertIn("operación".encode("utf-8"), V.canonico(doc))


class LoQueFrenaLaEntrega(unittest.TestCase):

    def test_un_reporte_aprobado_y_completo_pasa(self):
        self.assertEqual(E.faltantes_para_entregar(reporte(), CASO), [])

    def test_sin_aprobar_no_se_entrega(self):
        r = reporte(); r.pop("aprobacion")
        self.assertTrue(any("aprobado" in f for f in
                            E.faltantes_para_entregar(r, CASO)))

    def test_UNA_EDICION_POSTERIOR_INVALIDA_LA_APROBACION(self):
        # Se aprobó la v3 y después alguien guardó la v4: entregar mandaría
        # una versión que nadie firmó.
        r = reporte(version_actual=4)
        self.assertTrue(any("editó" in f for f in
                            E.faltantes_para_entregar(r, CASO)))

    def test_un_pais_fuera_del_acuerdo_no_se_entrega(self):
        r = reporte(regulador="SBS-PE")
        self.assertTrue(any("país" in f for f in
                            E.faltantes_para_entregar(r, CASO)))

    def test_sin_customer_id_no_se_entrega(self):
        r = reporte(borrador_gereo={"opciones": {}})
        self.assertTrue(any("customer_id" in f for f in
                            E.faltantes_para_entregar(r, CASO)))

    def test_sin_nombre_del_cliente_no_se_entrega(self):
        caso = {**CASO, "entity_name": ""}
        self.assertTrue(any("nombre" in f for f in
                            E.faltantes_para_entregar(reporte(), caso)))

    def test_SIN_CORREO_NO_SE_ENTREGA(self):
        """73 de los 328 casos no tienen el correo del cliente. GEREO nombra
        la carpeta de Drive `ID - NOMBRE - email`: entregar sin correo deja
        una carpeta mal nombrada en el expediente de un ROS."""
        caso = {**CASO, "alert_data": {}}
        self.assertTrue(any("correo" in f for f in
                            E.faltantes_para_entregar(reporte(), caso)))

    def test_se_devuelven_TODOS_los_motivos(self):
        r = reporte(regulador="", borrador_gereo={})
        r.pop("aprobacion")
        self.assertGreaterEqual(len(E.faltantes_para_entregar(r, {})), 4)


class LaRespuesta(unittest.TestCase):

    def test_202_es_entregado_y_no_se_reintenta(self):
        l = E.leer_respuesta(202, {"estado": "RECIBIDO", "entrega_id": "e-1"})
        self.assertTrue(l["entregado"])
        self.assertFalse(l["reintentable"])
        self.assertEqual(l["entrega_id"], "e-1")

    def test_EL_200_TAMBIEN_ES_ENTREGADO(self):
        """Reenvío de la misma versión: GEREO ya la tiene. Tratarlo como no
        entregado dejaría editable un ROS que el regulador ya recibió."""
        l = E.leer_respuesta(200, {"estado": "RECIBIDO", "entrega_id": "e-1"})
        self.assertTrue(l["entregado"])
        self.assertFalse(l["reintentable"])

    def test_409_no_se_reintenta_ni_cuenta_como_entregado(self):
        l = E.leer_respuesta(409, {"estado": "YA_ENTREGADO"})
        self.assertFalse(l["entregado"])
        self.assertFalse(l["reintentable"])

    def test_422_no_se_reintenta(self):
        l = E.leer_respuesta(422, {"estado": "INVALIDO", "campo": "ros_doc.meta"})
        self.assertFalse(l["reintentable"])
        self.assertEqual(l["campo"], "ros_doc.meta")

    def test_EL_503_DE_LA_ENTREGA_NO_SE_REINTENTA(self):
        """Al revés que en la generación: acá 503 es «el endpoint está
        publicado apagado» y no cambia hasta la fecha acordada."""
        l = E.leer_respuesta(503, {"estado": "DESHABILITADO"})
        self.assertFalse(l["reintentable"])
        self.assertFalse(l["entregado"])

    def test_el_503_de_la_GENERACION_si_se_reintenta(self):
        # La otra tabla, la de `gereo`, no se tocó. Las dos conviven.
        import gereo as G
        self.assertTrue(G._traducir(503, {}).reintentable)

    def test_los_5xx_si_se_reintentan(self):
        for c in (500, 502, 504):
            self.assertTrue(E.leer_respuesta(c, {})["reintentable"], c)

    def test_un_401_no_se_reintenta(self):
        # La clave rotada no mejora insistiendo.
        self.assertFalse(E.leer_respuesta(401, {})["reintentable"])

    def test_el_estado_del_cuerpo_manda_sobre_el_del_codigo(self):
        l = E.leer_respuesta(200, {"estado": "YA_ENTREGADO"})
        self.assertEqual(l["estado"], "YA_ENTREGADO")

    def test_un_cuerpo_vacio_no_rompe(self):
        l = E.leer_respuesta(202, None)
        self.assertEqual(l["estado"], "RECIBIDO")
        self.assertTrue(l["entregado"])


class LoQueSeLeDiceALaPersona(unittest.TestCase):

    def test_el_202_dice_que_queda_bloqueado(self):
        t = E.explicacion(E.leer_respuesta(202, {}))
        self.assertIn("bloquead", t)

    def test_el_503_explica_que_no_es_un_error_nuestro(self):
        t = E.explicacion(E.leer_respuesta(503, {}))
        self.assertIn("habilitada", t)
        self.assertIn("editable", t)

    def test_el_422_dice_el_campo(self):
        t = E.explicacion(E.leer_respuesta(422, {"campo": "ros_doc.meta"}))
        self.assertIn("ros_doc.meta", t)

    def test_el_mensaje_de_gereo_se_usa_cuando_viene(self):
        t = E.explicacion(E.leer_respuesta(422, {"mensaje": "falta la sección 4"}))
        self.assertIn("falta la sección 4", t)

    def test_un_5xx_invita_a_reintentar_la_misma_version(self):
        t = E.explicacion(E.leer_respuesta(502, {}))
        self.assertIn("misma versión", t)


if __name__ == "__main__":
    unittest.main()
