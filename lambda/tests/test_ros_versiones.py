# -*- coding: utf-8 -*-
"""Las versiones de un ROS.

LO QUE VIGILA ESTE ARCHIVO:

1. **Una versión no se pisa.** Lo que se aprueba y se manda al regulador es
   una versión específica. Si una edición pudiera sobrescribir la anterior, la
   frase «se aprobó esto» dejaría de poder probarse.

2. **El hash es reproducible.** Dos corridas sobre el mismo contenido tienen
   que dar el mismo hash, y sobre los MISMOS bytes que se escriben. Un hash
   que cambia según el orden de las claves no prueba nada.

3. **Un registro viejo se sigue leyendo.** Nada de esto puede obligar a
   migrar lo que ya está.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import ros_versiones as V  # noqa: E402

ROS = {"folio": "ROS-2026-0001", "regulador": "UAF-CL",
       "creado_at": "2026-10-12 11:00:00"}


class ElHashEsReproducible(unittest.TestCase):

    def test_el_orden_de_las_claves_no_cambia_el_hash(self):
        a = {"b": 2, "a": 1, "c": {"z": 1, "y": 2}}
        b = {"a": 1, "c": {"y": 2, "z": 1}, "b": 2}
        self.assertEqual(V.sha256_de(V.canonico(a)),
                         V.sha256_de(V.canonico(b)))

    def test_las_tildes_y_la_eñe_no_se_escapan(self):
        """Un ROS chileno viene lleno de tildes. Escaparlas cambiaría los
        bytes sin cambiar el contenido."""
        crudo = V.canonico({"x": "Año de constitución · señor"})
        self.assertIn("Año".encode(), crudo)
        self.assertNotIn(b"\\u", crudo)

    def test_los_bytes_del_hash_son_los_que_se_escriben(self):
        """El hash sobre el dict en memoria no sirve: se puede volver a
        serializar distinto y dejar de coincidir con el archivo."""
        doc = {"a": 1, "ñ": "x"}
        crudo = V.canonico(doc)
        self.assertEqual(json.loads(crudo.decode("utf-8")), doc)
        self.assertEqual(V.sha256_de(crudo), V.sha256_de(V.canonico(doc)))

    def test_sin_espacios_entre_los_separadores(self):
        self.assertEqual(V.canonico({"a": 1, "b": 2}), b'{"a":1,"b":2}')


class LaRutaJuntaLasVersionesDeUnMismoROS(unittest.TestCase):

    def test_la_forma_que_pide_la_especificacion(self):
        self.assertEqual(V.clave(ROS, 1, "pdf"),
                         "ros/CL/2026/10/ROS-2026-0001/v1.pdf")
        self.assertEqual(V.clave(ROS, 2, "json"),
                         "ros/CL/2026/10/ROS-2026-0001/v2.json")

    def test_el_año_y_el_mes_salen_del_ros_y_no_de_hoy(self):
        """Si salieran de hoy, la v2 de un ROS de octubre aterrizaría en la
        carpeta de noviembre y las versiones quedarían desparramadas."""
        self.assertTrue(V.prefijo(ROS).startswith("ros/CL/2026/10/"))

    def test_cada_regulador_tiene_su_pais(self):
        for regulador, pais in (("UAF-CL", "CL"), ("UIF-AR", "AR"),
                                ("UIAF-CO", "CO")):
            with self.subTest(regulador):
                self.assertEqual(V.pais_de({"regulador": regulador}), pais)

    def test_va_bajo_un_prefijo_sin_regla_de_borrado(self):
        """`ros/` no lo alcanza ninguna de las 28 reglas del bucket. Un ROS es
        información reservada: no se borra solo."""
        self.assertTrue(V.clave(ROS, 1, "json").startswith("ros/"))

    def test_un_folio_o_un_regulador_raros_no_arman_una_ruta(self):
        for malo in ({**ROS, "folio": "../../etc/passwd"},
                     {**ROS, "folio": "ROS-26-1"},
                     {**ROS, "regulador": "UAF-XX"},
                     {**ROS, "creado_at": ""}):
            with self.subTest(malo=malo.get("folio")), self.assertRaises(ValueError):
                V.prefijo(malo)

    def test_no_se_inventan_extensiones(self):
        for mala in ("exe", "html", "", "json/../x"):
            with self.subTest(mala), self.assertRaises(ValueError):
                V.clave(ROS, 1, mala)

    def test_no_hay_version_cero_ni_negativa(self):
        for n in (0, -1):
            with self.subTest(n), self.assertRaises(ValueError):
                V.clave(ROS, n, "json")


class UNA_VERSION_NO_SE_PISA(unittest.TestCase):
    """El control que sostiene todo el módulo."""

    def _desc(self, n, origen="gereo"):
        return V.descriptor(n, json_key=V.clave(ROS, n, "json"),
                            json_sha256="abc", origen=origen,
                            quien="analista@example.com", cuando="2026-10-12 11:00:00")

    def test_agregar_no_muta_el_reporte_que_recibe(self):
        r = dict(ROS)
        nuevo = V.agregar(r, self._desc(1))
        self.assertEqual(V.versiones_de(r), [], "mutó el original")
        self.assertEqual(len(V.versiones_de(nuevo)), 1)

    def test_repetir_un_numero_falla(self):
        """Dos ediciones simultáneas calculan el mismo `n`: que falle es lo
        correcto, la alternativa es que una pise a la otra en silencio."""
        r = V.agregar(dict(ROS), self._desc(1))
        with self.assertRaises(ValueError):
            V.agregar(r, self._desc(1))

    def test_las_versiones_se_acumulan_y_la_actual_es_la_ultima(self):
        r = dict(ROS)
        for n in (1, 2, 3):
            r = V.agregar(r, self._desc(n, "edicion" if n > 1 else "gereo"))
        self.assertEqual([v["version"] for v in V.versiones_de(r)], [1, 2, 3])
        self.assertEqual(r["version_actual"], 3)

    def test_lo_de_gereo_y_lo_editado_quedan_distinguibles(self):
        """En una auditoría la única pregunta que importa es qué puso la
        máquina y qué puso la persona."""
        r = V.agregar(dict(ROS), self._desc(1, "gereo"))
        r = V.agregar(r, self._desc(2, "edicion"))
        self.assertEqual([v["origen"] for v in V.versiones_de(r)],
                         ["gereo", "edicion"])

    def test_no_se_acepta_un_origen_inventado(self):
        with self.assertRaises(ValueError):
            V.descriptor(1, json_key="k", json_sha256="s", origen="magia",
                         quien="a@b.cl", cuando="x")


class UnRegistroViejoSeSigueLeyendo(unittest.TestCase):
    """Nada de esto puede obligar a migrar lo que ya está."""

    def test_sin_el_campo_son_cero_versiones(self):
        self.assertEqual(V.versiones_de({"folio": "ROS-2026-0001"}), [])

    def test_el_siguiente_numero_de_un_ros_sin_versiones_es_uno(self):
        self.assertEqual(V.siguiente_numero({"folio": "ROS-2026-0001"}), 1)

    def test_un_campo_con_basura_no_revienta(self):
        for basura in (None, "", 0, {"a": 1}, "[]"):
            with self.subTest(basura=basura):
                self.assertEqual(V.versiones_de({"versiones": basura}), [])

    def test_pedir_una_version_que_no_existe_devuelve_None(self):
        r = V.agregar(dict(ROS), V.descriptor(
            1, json_key="k", json_sha256="s", origen="gereo",
            quien="a@b.cl", cuando="x"))
        self.assertIsNone(V.version_de(r, 9))
        self.assertIsNone(V.version_de(r, "no es un número"))
        self.assertIsNone(V.version_de(r, None))
        self.assertIsNotNone(V.version_de(r, "1"))


class ElPDFEsOpcional(unittest.TestCase):
    """GEREO sólo lo manda si se pidió. Un ROS sin PDF es válido."""

    def test_sin_pdf_los_campos_quedan_vacios_y_no_None(self):
        d = V.descriptor(1, json_key="k", json_sha256="s", origen="gereo",
                         quien="a@b.cl", cuando="x")
        self.assertEqual(d["pdf_key"], "")
        self.assertEqual(d["pdf_sha256"], "")

    def test_con_pdf_viaja_su_hash(self):
        d = V.descriptor(1, json_key="k", json_sha256="s", origen="gereo",
                         quien="a@b.cl", cuando="x",
                         pdf_key="ros/CL/2026/10/ROS-2026-0001/v1.pdf",
                         pdf_sha256="deadbeef")
        self.assertEqual(d["pdf_sha256"], "deadbeef")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── El lado de S3, con dobles ──────────────────────────────────────────────

import api_handler as A  # noqa: E402


class LaEscrituraEsCondicional(unittest.TestCase):
    """`IfNoneMatch='*'` es lo que hace que una versión sea inmutable de
    verdad y no por convención: el registro es leer-modificar-escribir sin
    bloqueo, así que dos ediciones a la vez calculan el mismo número."""

    def _con_s3(self, puesto, falla_en=()):
        class _S3:
            def put_object(self, **kw):
                if kw["Key"] in falla_en:
                    e = Exception("ya existe")
                    e.response = {"Error": {"Code": "PreconditionFailed"}}
                    raise e
                puesto.append(kw)
        return _S3()

    def test_manda_IfNoneMatch(self):
        puesto = []
        orig = A.s3
        A.s3 = self._con_s3(puesto)
        try:
            A._s3_put_inmutable("ros/CL/2026/10/X/v1.json", b"{}", "application/json")
        finally:
            A.s3 = orig
        self.assertEqual(puesto[0]["IfNoneMatch"], "*")

    def test_un_choque_no_se_confunde_con_un_exito(self):
        orig = A.s3
        A.s3 = self._con_s3([], falla_en={"ros/CL/2026/10/X/v1.json"})
        try:
            with self.assertRaises(A.VersionYaExiste):
                A._s3_put_inmutable("ros/CL/2026/10/X/v1.json", b"{}",
                                    "application/json")
        finally:
            A.s3 = orig

    def test_otro_error_de_s3_no_se_disfraza_de_choque(self):
        class _Rota:
            def put_object(self, **kw):
                e = Exception("sin permisos")
                e.response = {"Error": {"Code": "AccessDenied"}}
                raise e
        orig = A.s3
        A.s3 = _Rota()
        try:
            with self.assertRaises(Exception) as c:
                A._s3_put_inmutable("k", b"{}", "application/json")
            self.assertNotIsInstance(c.exception, A.VersionYaExiste)
        finally:
            A.s3 = orig

    def test_el_hash_guardado_es_el_de_los_bytes_escritos(self):
        puesto = []
        orig = A.s3
        A.s3 = self._con_s3(puesto)
        try:
            r = A._crear_version_ros(dict(ROS), {"b": 2, "a": 1},
                                     "analista@example.com")
        finally:
            A.s3 = orig
        escrito = puesto[0]["Body"]
        self.assertEqual(V.versiones_de(r)[0]["json_sha256"],
                         V.sha256_de(escrito))

    def test_el_pdf_va_como_archivo_propio_y_no_adentro_del_json(self):
        puesto = []
        orig = A.s3
        A.s3 = self._con_s3(puesto)
        try:
            r = A._crear_version_ros(dict(ROS), {"a": 1}, "analista@example.com",
                                     pdf_bytes=b"%PDF-1.4 falso")
        finally:
            A.s3 = orig
        claves = [p["Key"] for p in puesto]
        self.assertIn("ros/CL/2026/10/ROS-2026-0001/v1.json", claves)
        self.assertIn("ros/CL/2026/10/ROS-2026-0001/v1.pdf", claves)
        v = V.versiones_de(r)[0]
        self.assertTrue(v["pdf_sha256"])
        self.assertNotIn(b"PDF", puesto[0]["Body"], "el PDF se coló en el JSON")

    def test_sin_pdf_solo_se_escribe_el_json(self):
        puesto = []
        orig = A.s3
        A.s3 = self._con_s3(puesto)
        try:
            A._crear_version_ros(dict(ROS), {"a": 1}, "analista@example.com")
        finally:
            A.s3 = orig
        self.assertEqual([p["Key"] for p in puesto],
                         ["ros/CL/2026/10/ROS-2026-0001/v1.json"])


class ElPDFSeSacaDelBorrador(unittest.TestCase):
    """Hoy viaja en `pdf_base64` DENTRO del JSON del borrador: no es un
    archivo, no está ligado al ROS y no se puede ni mirar."""

    def test_lo_decodifica(self):
        import base64
        crudo = base64.b64encode(b"%PDF-1.4 contenido").decode()
        self.assertEqual(A._pdf_del_borrador({"pdf_base64": crudo}),
                         b"%PDF-1.4 contenido")

    def test_sin_pdf_devuelve_vacio(self):
        """Sólo llega si se marcó «Traer también el PDF»."""
        for sin in ({}, {"pdf_base64": None}, {"pdf_base64": ""}):
            with self.subTest(sin=sin):
                self.assertEqual(A._pdf_del_borrador(sin), b"")

    def test_UN_PDF_ILEGIBLE_NO_VOLTEA_LA_CREACION_DEL_ROS(self):
        """El reporte vale por su JSON, que es lo que se manda al regulador."""
        self.assertEqual(A._pdf_del_borrador({"pdf_base64": "no es base64 %%%"}),
                         b"")


class UNA_VERSION_QUE_NO_SE_GUARDO_NO_ES_SILENCIOSA(unittest.TestCase):
    """El ROS se crea igual si falla S3 —el reporte es el dato, la versión es
    la prueba— pero si eso falla de forma sistemática TODOS los ROS de GEREO
    quedan sin versión. Un `print` no lo ve nadie; el registro sí."""

    def test_queda_marcado_en_el_registro(self):
        class _Rota:
            def put_object(self, **kw):
                raise RuntimeError("S3 caído")
        orig = A.s3
        A.s3 = _Rota()
        try:
            with self.assertRaises(RuntimeError):
                A._crear_version_ros(dict(ROS), {"a": 1}, "analista@example.com")
        finally:
            A.s3 = orig

    def _crear_ros_con_s3(self, s3_doble):
        """`crear_ros` de verdad, con dobles en todo lo que toca afuera."""
        import io
        borrador = json.dumps({"ros_doc": {"a": 1}, "opciones": {"pais": "Chile"},
                               "senales": [], "advertencias": []}).encode()

        class _S3(s3_doble):
            def get_object(self, **kw):
                return {"Body": io.BytesIO(borrador)}

        guardado = {}
        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_list", "_crm_put", "_safe_audit")}
        A.s3 = _S3()
        A._crm_get = lambda t, k: ({"case_id": "c-1", "entity_id": "9000001"}
                                   if t == "cases" else None)
        A._crm_list = lambda t: []
        A._crm_put = lambda t, k, v: guardado.update(ros=v)
        A._safe_audit = lambda **k: None
        try:
            r = A.crear_ros({"case_id": "c-1", "regulador": "UAF-CL",
                             "actor_email": "analista@example.com",
                             "gereo_run_id": "run-1"})
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return r, guardado.get("ros", {})

    def test_crear_ros_deja_la_marca_cuando_falla_S3(self):
        class _Rota:
            def put_object(self, **kw):
                raise RuntimeError("S3 caído")
        codigo, guardado = self._crear_ros_con_s3(_Rota)
        self.assertEqual(codigo["statusCode"], 201, "el ROS tenía que crearse igual")
        self.assertEqual(guardado["version_error"]["motivo"], "RuntimeError")
        self.assertTrue(guardado["version_error"]["cuando"])
        self.assertEqual(V.versiones_de(guardado), [])

    def test_el_motivo_no_lleva_el_mensaje_crudo_de_boto(self):
        """El mensaje de boto trae la clave del objeto, y la clave lleva el
        folio y el país. Sólo puede viajar el TIPO del error."""
        class _Rota:
            def put_object(self, **kw):
                raise RuntimeError("falló al escribir "
                                   "ros/CL/2026/10/ROS-2026-0001/v1.json")
        _, guardado = self._crear_ros_con_s3(_Rota)
        motivo = guardado["version_error"]["motivo"]
        self.assertEqual(motivo, "RuntimeError")
        self.assertNotIn("ros/", motivo)
        self.assertNotIn("ROS-", motivo)

    def test_cuando_S3_anda_no_hay_marca_de_error(self):
        class _Bien:
            def put_object(self, **kw):
                pass
        codigo, guardado = self._crear_ros_con_s3(_Bien)
        self.assertEqual(codigo["statusCode"], 201)
        self.assertNotIn("version_error", guardado)
        self.assertEqual(len(V.versiones_de(guardado)), 1)


# ── La edición: valores sí, estructura no ──────────────────────────────────

class LA_EDICION_NO_DEFORMA_EL_REPORTE(unittest.TestCase):
    """GEREO usa el JSON tal cual para completar el formulario del regulador.
    Un campo de más, uno de menos o uno que cambió de tipo y el reporte se cae
    del otro lado — o peor, entra mal, y nos enteramos por el regulador."""

    BASE = {"s": {"nombre": "X", "monto": 100, "pep": False,
                  "lista": ["a", "b"], "vacio": None,
                  "anidado": {"calle": "Falsa", "nro": 123}}}

    def test_cambiar_valores_esta_bien(self):
        otro = {"s": {"nombre": "Y", "monto": 200, "pep": True,
                      "lista": ["c", "d"], "vacio": None,
                      "anidado": {"calle": "Real", "nro": 456}}}
        self.assertEqual(V.diferencias_de_forma(self.BASE, otro), [])

    def test_UN_CAMPO_VACIO_SE_PUEDE_LLENAR(self):
        """Es el punto de editar: GEREO deja campos a criterio del analista."""
        lleno = {"s": {**self.BASE["s"], "vacio": "ahora dice algo"}}
        self.assertEqual(V.diferencias_de_forma(self.BASE, lleno), [])

    def test_y_uno_lleno_se_puede_vaciar(self):
        vacio = {"s": {**self.BASE["s"], "nombre": None}}
        self.assertEqual(V.diferencias_de_forma(self.BASE, vacio), [])

    def test_un_entero_y_un_decimal_son_el_mismo_tipo(self):
        """Un monto puede venir como 1000 o 1000.0 sin que eso cambie nada."""
        self.assertEqual(
            V.diferencias_de_forma(self.BASE,
                                   {"s": {**self.BASE["s"], "monto": 100.5}}),
            [])

    def test_un_campo_de_mas_se_rechaza(self):
        d = V.diferencias_de_forma(self.BASE,
                                   {"s": {**self.BASE["s"], "inventado": "x"}})
        self.assertEqual(d, ["sobra «s.inventado»"])

    def test_un_campo_de_menos_tambien(self):
        sin = {k: v for k, v in self.BASE["s"].items() if k != "pep"}
        self.assertEqual(V.diferencias_de_forma(self.BASE, {"s": sin}),
                         ["falta «s.pep»"])

    def test_un_tipo_cambiado_tambien(self):
        d = V.diferencias_de_forma(self.BASE,
                                   {"s": {**self.BASE["s"], "monto": "cien"}})
        self.assertEqual(d, ["«s.monto» era numero y llegó como texto"])

    def test_UN_BOOL_NO_ES_UN_NUMERO(self):
        """En Python `bool` ES `int`: sin cuidarlo, mandar 1 donde iba `true`
        pasaría el control y el regulador recibiría otra cosa."""
        d = V.diferencias_de_forma(self.BASE,
                                   {"s": {**self.BASE["s"], "pep": 1}})
        self.assertEqual(d, ["«s.pep» era bool y llegó como numero"])

    def test_EL_LARGO_DE_UNA_LISTA_ES_ESTRUCTURA(self):
        """Agregar un reportado no es editar un valor: cambia lo que el
        formulario del regulador va a recibir. Para eso se pide otra
        generación a GEREO."""
        mas = {"s": {**self.BASE["s"], "lista": ["a", "b", "c"]}}
        self.assertEqual(V.diferencias_de_forma(self.BASE, mas),
                         ["sobra «s.lista[2]»"])
        menos = {"s": {**self.BASE["s"], "lista": ["a"]}}
        self.assertEqual(V.diferencias_de_forma(self.BASE, menos),
                         ["falta «s.lista[1]»"])

    def test_tambien_mira_adentro_de_lo_anidado(self):
        d = V.diferencias_de_forma(
            self.BASE,
            {"s": {**self.BASE["s"], "anidado": {"calle": "Real"}}})
        self.assertEqual(d, ["falta «s.anidado.nro»"])


class SOLO_SE_EDITAN_LAS_SECCIONES_DEL_FORMULARIO(unittest.TestCase):
    """`meta` dice quién y cuándo generó el reporte; `reglas`, qué se evaluó.
    Son el registro de lo que hizo la máquina, y una persona editándolos
    borraría justo la parte que permite auditar."""

    DOC = {"meta": {"generado_con_ia": True}, "reglas": [{"id": "R1"}],
           "1_antecedentes_operaciones_sospechosas": {"monto": 1},
           "2_identificacion_reportados": {"nombre": "X"}}
    EDITABLES = ["1_antecedentes_operaciones_sospechosas",
                 "2_identificacion_reportados"]

    def test_lo_editado_pisa_y_lo_demas_se_arrastra(self):
        nuevo = V.fundir(self.DOC,
                         {"1_antecedentes_operaciones_sospechosas": {"monto": 99}},
                         self.EDITABLES)
        self.assertEqual(nuevo["1_antecedentes_operaciones_sospechosas"],
                         {"monto": 99})
        self.assertEqual(nuevo["meta"], self.DOC["meta"])
        self.assertEqual(nuevo["reglas"], self.DOC["reglas"])
        self.assertEqual(nuevo["2_identificacion_reportados"], {"nombre": "X"})

    def test_NO_SE_PUEDE_EDITAR_META_NI_REGLAS(self):
        for intruso in ("meta", "reglas"):
            with self.subTest(intruso), self.assertRaises(ValueError) as c:
                V.fundir(self.DOC, {intruso: {"lo que sea": 1}}, self.EDITABLES)
            self.assertIn(intruso, str(c.exception))

    def test_ni_una_seccion_de_otro_pais(self):
        with self.assertRaises(ValueError):
            V.fundir(self.DOC, {"4_detalle": {"descripcion": "x"}},
                     self.EDITABLES)

    def test_fundir_no_muta_el_documento_anterior(self):
        V.fundir(self.DOC, {"2_identificacion_reportados": {"nombre": "Z"}},
                 self.EDITABLES)
        self.assertEqual(self.DOC["2_identificacion_reportados"], {"nombre": "X"})


class GuardarUnaEdicion(unittest.TestCase):
    """El endpoint entero, con dobles."""

    DOC = {"meta": {"generado_con_ia": True}, "reglas": [],
           "1_antecedentes_operaciones_sospechosas": {"monto": 1, "txt": "a"},
           "2_identificacion_reportados": {"nombre": "X"}}

    def _guardar(self, secciones, *, etapa="recibido", estado="borrador",
                 sobre=None, version_actual=1):
        import io as _io
        import json as _json
        import ros_etapas as _E
        guardado, escrito = {}, []
        reporte = {"folio": "ROS-2026-0001", "regulador": "UAF-CL",
                   "estado": estado, "creado_at": "2026-10-13 11:00:00",
                   "etapa_gereo": etapa, "version_actual": version_actual,
                   "versiones": [{"version": 1, "origen": "gereo",
                                  "json_key": "ros/CL/2026/10/ROS-2026-0001/v1.json",
                                  "json_sha256": "x", "pdf_key": "",
                                  "pdf_sha256": "", "creada_por": "a@example.com",
                                  "creada_at": "x"}]}

        class _S3:
            def get_object(self, **kw):
                return {"Body": _io.BytesIO(_json.dumps(GuardarUnaEdicion.DOC).encode())}
            def put_object(self, **kw):
                escrito.append(kw)

        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_put", "_safe_audit")}
        A.s3 = _S3()
        A._crm_get = lambda t, k: reporte if t == "ros" else None
        A._crm_put = lambda t, k, v: guardado.update(ros=v)
        A._safe_audit = lambda **k: None
        try:
            # `sobre_version` es obligatorio: por defecto va el que el
            # cliente real mandaría.
            cuerpo = {"secciones": secciones,
                      "sobre_version": version_actual if sobre is None else sobre}
            r = A.guardar_version_ros("ROS-2026-0001", cuerpo,
                                      "oficial@example.com")
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return r, guardado.get("ros", {}), escrito

    def test_el_camino_normal_crea_la_version_2(self):
        r, guardado, escrito = self._guardar(
            {"1_antecedentes_operaciones_sospechosas": {"monto": 99, "txt": "b"}})
        self.assertEqual(r["statusCode"], 201)
        self.assertEqual(guardado["version_actual"], 2)
        self.assertEqual(V.versiones_de(guardado)[-1]["origen"], "edicion")
        self.assertEqual(V.versiones_de(guardado)[-1]["creada_por"],
                         "oficial@example.com")

    def test_la_version_1_no_se_toca(self):
        """Lo que se aprueba es una versión específica."""
        _, _, escrito = self._guardar(
            {"1_antecedentes_operaciones_sospechosas": {"monto": 99, "txt": "b"}})
        claves = [e["Key"] for e in escrito]
        self.assertEqual(claves, ["ros/CL/2026/10/ROS-2026-0001/v2.json"])
        self.assertTrue(all(e.get("IfNoneMatch") == "*" for e in escrito))

    def test_meta_y_reglas_se_arrastran(self):
        _, _, escrito = self._guardar(
            {"1_antecedentes_operaciones_sospechosas": {"monto": 99, "txt": "b"}})
        doc = json.loads(escrito[0]["Body"].decode("utf-8"))
        self.assertEqual(doc["meta"], self.DOC["meta"])
        self.assertEqual(doc["2_identificacion_reportados"], {"nombre": "X"})

    def test_UNA_EDICION_QUE_DEFORMA_SE_RECHAZA_ENTERA(self):
        r, guardado, escrito = self._guardar(
            {"1_antecedentes_operaciones_sospechosas": {"monto": 99}})
        self.assertEqual(r["statusCode"], 400)
        cuerpo = json.loads(r["body"])
        self.assertIn("estructura", cuerpo["error"])
        self.assertTrue(cuerpo["diferencias"])
        self.assertEqual(escrito, [], "escribió igual")
        self.assertEqual(guardado, {}, "guardó igual")

    def test_EDITAR_ANULA_LA_REVISION(self):
        """Lo revisado era la versión anterior; darla por buena sobre un
        contenido que cambió es lo que el control existe para evitar."""
        r, guardado, _ = self._guardar(
            {"1_antecedentes_operaciones_sospechosas": {"monto": 99, "txt": "b"}},
            etapa="revisado")
        self.assertEqual(r["statusCode"], 201)
        import ros_etapas as _E
        self.assertEqual(_E.etapa_de(guardado), "recibido")
        self.assertIn("revisión", _E.historial_de(guardado)[-1]["nota"])

    def test_un_reporte_enviado_no_se_edita(self):
        r, _, escrito = self._guardar(
            {"1_antecedentes_operaciones_sospechosas": {"monto": 99, "txt": "b"}},
            estado="enviado")
        self.assertEqual(r["statusCode"], 409)
        self.assertEqual(escrito, [])

    def test_mientras_gereo_procesa_tampoco(self):
        r, _, escrito = self._guardar(
            {"1_antecedentes_operaciones_sospechosas": {"monto": 99, "txt": "b"}},
            etapa="enviando")
        self.assertEqual(r["statusCode"], 409)
        self.assertEqual(escrito, [])

    def test_DOS_ANALISTAS_A_LA_VEZ_NO_SE_PISAN(self):
        """El cliente dice qué versión creía editar. Pisar el trabajo de otro
        en silencio es peor que hacerle repetir el suyo."""
        r, _, escrito = self._guardar(
            {"1_antecedentes_operaciones_sospechosas": {"monto": 99, "txt": "b"}},
            sobre=1, version_actual=3)
        self.assertEqual(r["statusCode"], 409)
        self.assertIn("mientras editabas", json.loads(r["body"])["error"])
        self.assertEqual(escrito, [])

    def test_sin_contenido_no_hace_nada(self):
        for vacio in ({}, None, "texto", []):
            with self.subTest(vacio=vacio):
                r, _, escrito = self._guardar(vacio)
                self.assertEqual(r["statusCode"], 400)
                self.assertEqual(escrito, [])


class LaFormaEsLaDeGEREO(unittest.TestCase):
    """Se compara contra la v1, no contra la versión anterior.

    Comparando contra la anterior, el comodín `nulo` deja lavar un tipo en
    dos saltos: v1 texto → v2 null (permitido) → v3 número (permitido). Queda
    un tipo que GEREO nunca devolvió, y el reporte entra mal al regulador.
    """

    def test_dos_saltos_no_lavan_un_tipo(self):
        v1 = {"s": {"rut": "76.123.456-7"}}
        v2 = {"s": {"rut": None}}            # vaciar: permitido
        v3 = {"s": {"rut": 76123456}}        # llenar con OTRO tipo
        # Contra la versión anterior, el salto pasa…
        self.assertEqual(V.diferencias_de_forma(v2, v3), [])
        # …y contra la v1, que es la forma de GEREO, no.
        self.assertEqual(V.diferencias_de_forma(v1, v3),
                         ["«s.rut» era texto y llegó como numero"])

    def test_vaciar_y_volver_a_llenar_con_el_mismo_tipo_si(self):
        v1 = {"s": {"rut": "76.123.456-7"}}
        self.assertEqual(V.diferencias_de_forma(v1, {"s": {"rut": "77.000.000-0"}}),
                         [])


class CadaReguladorEncuentraSusSecciones(unittest.TestCase):
    """Si el mapeo falla, el resultado son secciones vacías SIN error: el
    formulario sale en blanco y nadie sabe por qué. Por eso se verifica el
    camino entero, de regulador a secciones editables."""

    def test_los_tres(self):
        import ros_gereo as RG
        for regulador, pais in (("UAF-CL", "Chile"), ("UIAF-CO", "Colombia"),
                                ("UIF-AR", "Argentina")):
            with self.subTest(regulador):
                largo = V.pais_largo({"regulador": regulador})
                self.assertEqual(largo, pais)
                editables = [c for c, _ in RG.SECCIONES.get(largo, [])]
                self.assertTrue(editables,
                                f"{regulador} se queda sin secciones editables")

    def test_un_regulador_desconocido_no_devuelve_un_formulario_vacio(self):
        self.assertEqual(V.pais_largo({"regulador": "XXX-ZZ"}), "")


class LoQueGuardarRechaza(unittest.TestCase):
    """Los casos de borde del endpoint."""

    def _pedir(self, cuerpo, version_actual=2):
        import io as _io
        import json as _json
        reporte = {"folio": "ROS-2026-0001", "regulador": "UAF-CL",
                   "estado": "borrador", "creado_at": "2026-10-13 11:00:00",
                   "etapa_gereo": "recibido", "version_actual": version_actual,
                   "versiones": [{"version": n, "origen": "gereo",
                                  "json_key": f"k{n}", "json_sha256": "x",
                                  "pdf_key": "", "pdf_sha256": "",
                                  "creada_por": "a@example.com", "creada_at": "x"}
                                 for n in range(1, version_actual + 1)]}

        class _S3:
            def get_object(self, **kw):
                return {"Body": _io.BytesIO(_json.dumps(
                    GuardarUnaEdicion.DOC).encode())}
            def put_object(self, **kw):
                pass

        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_put", "_safe_audit")}
        A.s3 = _S3()
        A._crm_get = lambda t, k: reporte if t == "ros" else None
        A._crm_put = lambda t, k, v: None
        A._safe_audit = lambda **k: None
        try:
            return A.guardar_version_ros("ROS-2026-0001", cuerpo, "o@example.com")
        finally:
            for n, f in orig.items():
                setattr(A, n, f)

    def test_SIN_sobre_version_no_se_guarda(self):
        """Si fuera opcional, el cliente distraído se saltea el control — y el
        control existe justamente para el cliente distraído."""
        r = self._pedir({"secciones": {"1_antecedentes_operaciones_sospechosas":
                                       {"monto": 9, "txt": "b"}}})
        self.assertEqual(r["statusCode"], 400)
        self.assertIn("sobre_version", json.loads(r["body"])["error"])

    def test_un_sobre_version_que_no_es_numero_tampoco_revienta(self):
        for malo in ("x", None, [], {}, "2.5"):
            with self.subTest(malo=malo):
                r = self._pedir({"secciones": {"s": {}}, "sobre_version": malo})
                self.assertEqual(r["statusCode"], 400)

    def test_un_choque_en_S3_es_409_y_no_502(self):
        """Dos guardados a la vez con el mismo `sobre_version`: el segundo
        choca con el IfNoneMatch. Decir «reintentá» haría que reintente y
        vuelva a chocar."""
        import io as _io
        import json as _json
        reporte = {"folio": "ROS-2026-0001", "regulador": "UAF-CL",
                   "estado": "borrador", "creado_at": "2026-10-13 11:00:00",
                   "etapa_gereo": "recibido", "version_actual": 1,
                   "versiones": [{"version": 1, "origen": "gereo",
                                  "json_key": "k1", "json_sha256": "x",
                                  "pdf_key": "", "pdf_sha256": "",
                                  "creada_por": "a@example.com", "creada_at": "x"}]}

        class _S3Ocupado:
            def get_object(self, **kw):
                return {"Body": _io.BytesIO(_json.dumps(
                    GuardarUnaEdicion.DOC).encode())}
            def put_object(self, **kw):
                e = Exception("ya existe")
                e.response = {"Error": {"Code": "PreconditionFailed"}}
                raise e

        orig = {n: getattr(A, n) for n in
                ("s3", "_crm_get", "_crm_put", "_safe_audit")}
        A.s3 = _S3Ocupado()
        A._crm_get = lambda t, k: reporte if t == "ros" else None
        A._crm_put = lambda t, k, v: None
        A._safe_audit = lambda **k: None
        try:
            r = A.guardar_version_ros(
                "ROS-2026-0001",
                {"secciones": {"1_antecedentes_operaciones_sospechosas":
                               {"monto": 9, "txt": "b"}},
                 "sobre_version": 1},
                "o@example.com")
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        self.assertEqual(r["statusCode"], 409)
        self.assertIn("Recargá", json.loads(r["body"])["error"])
