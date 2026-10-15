# -*- coding: utf-8 -*-
"""Qué puede entrar a la lista blanca.

EL AGUJERO QUE ESTO CIERRA. El valor de una entrada se interpola en el SQL de
**todos** los reportes. El escape doblaba las comillas simples, pero Redshift
acepta también la barra invertida, así que

    \\') AND (1=0) --

cierra el literal y lo que sigue entra como SQL: el reporte sale vacío **para
todos los clientes**, no sólo para el de la entrada. Y la API interna no
autentica, así que alcanzaba un POST.

LA LISTA ES CERRADA, no de prohibidos. Prohibir la comilla y la barra es una
carrera que se pierde: siempre queda una forma de escapar que nadie pensó.
"""
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import whitelist_validacion as V  # noqa: E402

# El payload que vacía todos los reportes. Va acá para que, si alguien
# "simplifica" la validación, este test lo diga.
ATAQUE = "\\') AND (1=0) --"


class EL_PAYLOAD_DE_INYECCION_SE_RECHAZA(unittest.TestCase):

    def test_el_de_verdad(self):
        self.assertFalse(V.es_valida("customer_id", ATAQUE))

    def test_y_sus_variantes(self):
        for malo in ("1' OR '1'='1", "1); DROP TABLE x; --", "1\\", "1'",
                     "1 UNION SELECT 1", "1--", "1/*", "' OR 1=1 --",
                     "1\\') --", "1 OR TRUE"):
            with self.subTest(malo=malo):
                self.assertFalse(V.es_valida("customer_id", malo), malo)

    def test_tambien_por_el_CAMPO(self):
        """El campo también entra al SQL, sin comillas alrededor: ahí una
        inyección no necesita ni cerrar un literal."""
        for malo in ("customer_id) OR (1=1", "1=1 --", "customer_id;DROP",
                     "", "   ", "cualquier_cosa"):
            with self.subTest(malo=malo):
                self.assertFalse(V.es_valida(malo, "123"))

    def test_el_motivo_NO_lleva_el_valor(self):
        """El motivo va al cliente y al log. Si el valor es un intento de
        inyección, copiarlo lo mete en CloudWatch."""
        motivo = V.motivo_de_rechazo("customer_id", ATAQUE)
        self.assertTrue(motivo)
        self.assertNotIn(ATAQUE, motivo)
        self.assertNotIn("1=0", motivo)


class LO_QUE_SI_ENTRA(unittest.TestCase):
    """Las 49 entradas vigentes al 14-10-2026 son todas `customer_id` con
    dígitos. Nada de lo que hay hoy se rompe."""

    def test_un_id_normal(self):
        for bueno in ("123", "9000001", "1", "9" * 20):
            with self.subTest(bueno=bueno):
                self.assertTrue(V.es_valida("customer_id", bueno), bueno)

    def test_los_cinco_campos(self):
        self.assertEqual(V.CAMPOS, ("customer_id", "company_id",
                                    "beneficiary_id", "email", "customer_email"))
        for campo in ("customer_id", "company_id", "beneficiary_id"):
            with self.subTest(campo=campo):
                self.assertTrue(V.es_valida(campo, "123"))

    def test_CUSTOMER_EMAIL_TAMBIEN(self):
        """Casi se pierde. Lo ofrecen los dos formularios manuales de v1 y lo
        devuelven 23 de los 41 reportes: dejarlo afuera habría roto una
        opción que hoy funciona."""
        self.assertTrue(V.es_valida("customer_email", "alguien@example.com"))
        self.assertFalse(V.es_valida("customer_email", "a'b@x.com"))

    def test_LA_LISTA_CUBRE_TODO_LO_QUE_LOS_FRONTS_OFRECEN(self):
        """La regresión. La primera versión salió del inventario de lo que
        hay GUARDADO (todo `customer_id`) y no de lo que puede LLEGAR, así
        que dejaba afuera opciones que las pantallas ofrecen y nadie usó
        todavía. Esto lee los fronts de verdad."""
        raiz = Path(__file__).resolve().parents[2]
        ofrecidos = set()

        v1 = (raiz / "frontend" / "index.html").read_text(encoding="utf-8")
        # Los <option> del selector de campo del formulario de whitelist.
        for m in re.finditer(r'value="(customer_id|company_id|beneficiary_id'
                             r'|email|customer_email)"', v1):
            ofrecidos.add(m.group(1))

        for arch in (raiz / "frontend" / "v2" / "src").rglob("*.js*"):
            for m in re.finditer(r"entity_field:\s*'([a-z_]+)'",
                                 arch.read_text(encoding="utf-8")):
                ofrecidos.add(m.group(1))

        faltan = sorted(ofrecidos - set(V.CAMPOS))
        self.assertEqual(faltan, [], (
            "los fronts ofrecen campos que la validación rechaza, así que "
            f"elegirlos daría 400: {faltan}"))

    def test_un_correo_normal(self):
        for bueno in ("alguien@example.com", "a.b+c@sub.dominio.cl"):
            with self.subTest(bueno=bueno):
                self.assertTrue(V.es_valida("email", bueno), bueno)

    def test_un_correo_con_comillas_no(self):
        for malo in ("a'b@x.com", "a\\b@x.com", "a b@x.com", "a@x", "@x.com",
                     "a@x.com; DROP", "a@x.com'"):
            with self.subTest(malo=malo):
                self.assertFalse(V.es_valida("email", malo), malo)

    def test_un_id_con_letras_no(self):
        """No hay ninguno así en producción, y un id no numérico abre la
        puerta a todo lo demás."""
        for malo in ("abc", "12a", "1 2", "1.5", "-1", "+1", "1e3"):
            with self.subTest(malo=malo):
                self.assertFalse(V.es_valida("customer_id", malo), malo)

    def test_un_valor_larguisimo_no(self):
        self.assertFalse(V.es_valida("customer_id", "9" * 300))


class AL_APLICAR_SE_DESCARTA_Y_LA_CORRIDA_SIGUE(unittest.TestCase):
    """Un reporte que no corre es peor que un reporte con una exclusión de
    menos."""

    def test_separa_lo_bueno_de_lo_malo(self):
        buenas, malas = V.filtrar([
            {"whitelist_id": "a", "entity_field": "customer_id", "entity_value": "123"},
            {"whitelist_id": "b", "entity_field": "customer_id", "entity_value": ATAQUE},
            {"whitelist_id": "c", "entity_field": "inventado", "entity_value": "123"},
        ])
        self.assertEqual([e["whitelist_id"] for e in buenas], ["a"])
        self.assertEqual([w for w, _ in malas], ["b", "c"])

    def test_lo_descartado_viaja_sin_el_valor(self):
        _, malas = V.filtrar([{"whitelist_id": "b", "entity_field": "customer_id",
                               "entity_value": ATAQUE}])
        self.assertNotIn(ATAQUE, malas[0][1])

    def test_una_lista_vacia_o_rara_no_revienta(self):
        for basura in (None, [], [{}], [{"entity_field": None}]):
            with self.subTest(basura=basura):
                buenas, _ = V.filtrar(basura)
                self.assertEqual(buenas, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── Los endpoints ──────────────────────────────────────────────────────────

import json  # noqa: E402

import api_handler as A  # noqa: E402


class ElAltaIndividual(unittest.TestCase):

    def _agregar(self, cuerpo):
        puesto, auditado = {}, []
        orig = {n: getattr(A, n) for n in ("_crm_put", "_safe_audit")}
        A._crm_put = lambda t, k, v: puesto.update(entrada=v)
        A._safe_audit = lambda **k: auditado.append(k)
        try:
            r = A.add_to_whitelist(cuerpo)
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return r, puesto.get("entrada", {}), auditado

    def test_EL_ATAQUE_NO_ENTRA(self):
        r, puesto, _ = self._agregar({"entity_field": "customer_id",
                                      "entity_value": ATAQUE,
                                      "duration_days": 30})
        self.assertEqual(r["statusCode"], 400)
        self.assertEqual(puesto, {}, "lo guardó igual")
        self.assertNotIn(ATAQUE, json.loads(r["body"])["error"])

    def test_un_campo_inventado_tampoco(self):
        r, puesto, _ = self._agregar({"entity_field": "lo_que_sea",
                                      "entity_value": "123",
                                      "duration_days": 30})
        self.assertEqual(r["statusCode"], 400)
        self.assertEqual(puesto, {})

    def test_el_alta_normal_sigue_andando(self):
        r, puesto, _ = self._agregar({"entity_field": "customer_id",
                                      "entity_value": "9000001",
                                      "duration_days": 90, "reason": "revisado",
                                      "scope": "global"})
        self.assertEqual(r["statusCode"], 201)
        self.assertEqual(puesto["entity_value"], "9000001")
        self.assertEqual(puesto["duration_days"], 90)
        self.assertEqual(puesto["scope"], "global")

    def test_GUARDA_QUIEN_LO_AGREGO(self):
        """El backend lo descartaba, así que 49 entradas vigentes no tienen
        autor: no se puede saber quién silenció a esos clientes."""
        _, puesto, _ = self._agregar({"entity_field": "customer_id",
                                      "entity_value": "9000001",
                                      "duration_days": 30,
                                      "created_by": "analista@example.com"})
        self.assertEqual(puesto["created_by"], "analista@example.com")

    def test_NO_SE_EXIGE_EL_AUTOR(self):
        """Dos pantallas todavía no lo mandan. Exigirlo las rompería hasta
        que se renueve el bundle, que tarda hasta un día."""
        r, puesto, _ = self._agregar({"entity_field": "customer_id",
                                      "entity_value": "9000001",
                                      "duration_days": 30})
        self.assertEqual(r["statusCode"], 201)
        self.assertEqual(puesto["created_by"], "")

    def test_se_audita(self):
        """Dejar de alertar sobre un cliente es una decisión de compliance."""
        _, _, auditado = self._agregar({"entity_field": "customer_id",
                                        "entity_value": "9000001",
                                        "duration_days": 30,
                                        "created_by": "analista@example.com"})
        self.assertEqual(len(auditado), 1)
        self.assertEqual(auditado[0]["action"], "whitelist.add")
        self.assertEqual(auditado[0]["user_email"], "analista@example.com")

    def test_la_auditoria_NO_lleva_el_valor_del_cliente(self):
        _, _, auditado = self._agregar({"entity_field": "customer_id",
                                        "entity_value": "9000001",
                                        "duration_days": 30})
        self.assertNotIn("9000001", json.dumps(auditado[0]))


class LaBajaTambienSeAudita(unittest.TestCase):
    """Volver a alertar sobre un cliente es tan registrable como dejar de
    hacerlo, y antes esto borraba sin dejar rastro de quién."""

    def _quitar(self, cuerpo=None, previa=None):
        auditado, borrado = [], []
        orig = {n: getattr(A, n) for n in
                ("_crm_get", "_crm_delete", "_safe_audit")}
        A._crm_get = lambda t, k: previa
        A._crm_delete = lambda t, k: borrado.append(k)
        A._safe_audit = lambda **k: auditado.append(k)
        try:
            r = A.remove_from_whitelist("w-1", cuerpo)
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return r, borrado, auditado

    def test_borra_y_audita(self):
        r, borrado, auditado = self._quitar(
            {"actor_email": "analista@example.com"},
            {"entity_field": "customer_id", "scope": "global", "reason": "x"})
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(borrado, ["w-1"])
        self.assertEqual(auditado[0]["action"], "whitelist.remove")
        self.assertEqual(auditado[0]["user_email"], "analista@example.com")

    def test_LEE_LA_ENTRADA_ANTES_DE_BORRARLA(self):
        """Después no hay de dónde sacar sobre qué cliente era, y una línea
        de auditoría que sólo dice un uuid no reconstruye nada."""
        _, _, auditado = self._quitar(
            {}, {"entity_field": "customer_id", "scope": "report",
                 "reason": "falso positivo"})
        self.assertEqual(auditado[0]["new_value"]["entity_field"], "customer_id")
        self.assertEqual(auditado[0]["new_value"]["scope"], "report")

    def test_sin_la_entrada_no_revienta(self):
        r, borrado, auditado = self._quitar({}, None)
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(borrado, ["w-1"])
        self.assertEqual(len(auditado), 1)


class ElAutorLlegaALaPantalla(unittest.TestCase):
    """Se guardaba y no se devolvía: el dato quedaba en S3 sin llegar a
    ninguna pantalla, así que seguía sin poder saberse quién silenció a ese
    cliente — que era el punto de guardarlo."""

    def test_get_whitelist_devuelve_created_by(self):
        entradas = [{"whitelist_id": "w1", "entity_field": "customer_id",
                     "entity_value": "9000001", "duration_days": 30,
                     "reason": "x", "scope": "global", "report_name": "",
                     "created_by": "analista@example.com",
                     "created_at": "2026-10-15 10:00:00",
                     "expires_at": 9999999999, "expires_at_str": "2027-01-01"}]
        orig = A._crm_list
        A._crm_list = lambda t: entradas
        try:
            r = A.get_whitelist()
        finally:
            A._crm_list = orig
        w = json.loads(r["body"])["whitelist"][0]
        self.assertEqual(w["created_by"], "analista@example.com")

    def test_una_entrada_vieja_sin_autor_no_revienta(self):
        """Las 49 vigentes no lo tienen."""
        entradas = [{"whitelist_id": "w1", "entity_field": "customer_id",
                     "entity_value": "9000001", "duration_days": 30,
                     "reason": "", "scope": "global", "report_name": "",
                     "created_at": "2026-09-01 10:00:00",
                     "expires_at": 9999999999, "expires_at_str": "2027-01-01"}]
        orig = A._crm_list
        A._crm_list = lambda t: entradas
        try:
            r = A.get_whitelist()
        finally:
            A._crm_list = orig
        self.assertEqual(json.loads(r["body"])["whitelist"][0]["created_by"], "")
