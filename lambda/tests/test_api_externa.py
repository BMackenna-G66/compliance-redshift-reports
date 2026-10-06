# -*- coding: utf-8 -*-
"""La API externa de casos: quién entra, qué puede hacer y qué llega a la base.

Los tres riesgos que cubre, en orden de lo que costaría que salieran mal:

  1. **Que entre quien no debe.** Sin clave, con clave inventada o con una
     clave revocada. Y que un error leyendo el secreto NO abra la puerta.
  2. **Que haga más de lo que le corresponde.** Una clave de lectura no
     escribe; una que gestiona casos no le escribe al cliente sin su permiso.
  3. **Que el código de regla entre crudo al SQL.** El WHERE se arma por
     interpolación de texto contra Redshift, así que el filtro del parámetro
     es lo único que separa una consulta de una inyección.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_externa as X  # noqa: E402

CLAVE_LECTOR = "k-lector-0000000000000000"
CLAVE_GESTOR = "k-gestor-1111111111111111"
CLAVE_MUDA = "k-muda-22222222222222222"
CLAVE_BAJA = "k-baja-33333333333333333"

CONSUMIDORES = {
    "sistema-casos": {"clave": CLAVE_GESTOR,
                      "permisos": [X.LEER, X.ESCRIBIR, X.COMUNICAR]},
    "tablero-lectura": {"clave": CLAVE_LECTOR, "permisos": [X.LEER]},
    # Gestiona el caso pero no le escribe al cliente.
    "sin-voz": {"clave": CLAVE_MUDA, "permisos": [X.LEER, X.ESCRIBIR]},
    "revocado": {"clave": CLAVE_BAJA, "permisos": [X.LEER], "activo": False},
}


def evento(clave=None, extra=None):
    h = dict(extra or {})
    if clave:
        h["x-api-key"] = clave
    return {"headers": h}


class Base(unittest.TestCase):
    def setUp(self):
        X._cache = dict(CONSUMIDORES)
        # Normaliza como lo haría `_consumidores()` al leer el secreto.
        for cfg in X._cache.values():
            cfg["permisos"] = set(cfg["permisos"])
            cfg.setdefault("activo", True)

    def tearDown(self):
        X._cache = None


class QuienEntra(Base):

    def test_sin_header_no_entra(self):
        self.assertIsNone(X.identificar(evento()))

    def test_clave_inventada_no_entra(self):
        self.assertIsNone(X.identificar(evento("no-soy-una-clave")))

    def test_clave_correcta_entra(self):
        self.assertEqual(X.identificar(evento(CLAVE_GESTOR))["nombre"], "sistema-casos")

    def test_el_header_no_distingue_mayusculas(self):
        """API Gateway puede entregar los headers con otra capitalización."""
        e = {"headers": {"X-Api-Key": CLAVE_LECTOR}}
        self.assertEqual(X.identificar(e)["nombre"], "tablero-lectura")

    def test_una_clave_revocada_no_entra(self):
        self.assertIsNone(X.identificar(evento(CLAVE_BAJA)))

    def test_la_clave_no_se_acepta_por_prefijo(self):
        """Comparación completa, no 'empieza con'."""
        self.assertIsNone(X.identificar(evento(CLAVE_GESTOR[:10])))
        self.assertIsNone(X.identificar(evento(CLAVE_GESTOR + "x")))

    def test_espacios_alrededor_no_rompen(self):
        self.assertEqual(X.identificar(evento(f"  {CLAVE_GESTOR}  "))["nombre"],
                         "sistema-casos")


class SiElSecretoFalla(unittest.TestCase):
    """Falla cerrada: un problema leyendo el secreto no puede abrir la puerta."""

    def setUp(self):
        X._cache = None

    def tearDown(self):
        X._cache = None

    def test_sin_secreto_legible_no_autoriza_a_nadie(self):
        import boto3
        original = boto3.client

        def revienta(*a, **k):
            raise RuntimeError("Secrets Manager caído")

        boto3.client = revienta
        try:
            self.assertEqual(X._consumidores(), {})
            self.assertIsNone(X.identificar(evento(CLAVE_GESTOR)))
        finally:
            boto3.client = original


class QuePuedeHacer(Base):

    def test_el_lector_lee(self):
        c, motivo = X.autorizar(evento(CLAVE_LECTOR), X.LEER)
        self.assertIsNone(motivo)
        self.assertEqual(c["nombre"], "tablero-lectura")

    def test_el_lector_no_escribe(self):
        c, motivo = X.autorizar(evento(CLAVE_LECTOR), X.ESCRIBIR)
        self.assertIsNone(c)
        self.assertEqual(motivo[0], 403)

    def test_gestionar_no_alcanza_para_escribirle_al_cliente(self):
        """El permiso de comunicar es aparte a propósito: mandarle un correo a
        una persona real es el riesgo más alto del módulo."""
        c, motivo = X.autorizar(evento(CLAVE_MUDA), X.COMUNICAR)
        self.assertIsNone(c)
        self.assertEqual(motivo[0], 403)
        # Pero sí puede mover el caso.
        self.assertIsNone(X.autorizar(evento(CLAVE_MUDA), X.ESCRIBIR)[1])

    def test_401_y_403_son_distintos(self):
        """'No sé quién sos' y 'no podés' mandan a revisar cosas distintas."""
        self.assertEqual(X.autorizar(evento(), X.LEER)[1][0], 401)
        self.assertEqual(X.autorizar(evento(CLAVE_LECTOR), X.ESCRIBIR)[1][0], 403)

    def test_un_permiso_inventado_en_el_secreto_se_ignora(self):
        X._cache = {"raro": {"clave": "k-raro", "permisos": {"casos:borrar-todo"},
                             "activo": True}}
        self.assertEqual(X.autorizar(evento("k-raro"), X.LEER)[1][0], 403)


class ComoQuedaFirmado(Base):

    def test_el_actor_lleva_prefijo_api(self):
        """En una auditoría hay que poder separar lo que hizo una persona en la
        pantalla de lo que hizo un sistema por la API."""
        c = X.identificar(evento(CLAVE_GESTOR))
        self.assertEqual(X.actor(c), "api:sistema-casos")


class LaReglaNoEntraCrudaAlSQL(unittest.TestCase):
    """El WHERE se arma interpolando texto contra Redshift."""

    def test_acepta_el_codigo_real(self):
        self.assertTrue(X.regla_valida("PSP-C-AMT-J9H7"))
        self.assertIn("PSP-C-AMT-J9H7", X.sql_alertas_por_regla("PSP-C-AMT-J9H7"))

    def test_rechaza_comillas_y_punto_y_coma(self):
        for veneno in ("PSP'--", "a'; DROP TABLE compliance.bbdd_delitos; --",
                       "x' OR '1'='1", "a b", "", None, "a%", "'"):
            with self.subTest(veneno=veneno):
                self.assertFalse(X.regla_valida(veneno))
                with self.assertRaises(ValueError):
                    X.sql_alertas_por_regla(veneno)

    def test_rechaza_un_codigo_larguisimo(self):
        self.assertFalse(X.regla_valida("A" * 200))

    def test_el_pais_tambien_se_valida(self):
        self.assertIn("'AR'", X.sql_alertas_por_regla("PSP-C-AMT-J9H7", "ar"))
        with self.assertRaises(ValueError):
            X.sql_alertas_por_regla("PSP-C-AMT-J9H7", "AR' OR 1=1 --")

    def test_el_limite_se_topea(self):
        sql = X.sql_alertas_por_regla("PSP-C-AMT-J9H7", "", 99999)
        self.assertIn(f"LIMIT {X.MAX_POR_PAGINA}", sql)

    def test_un_limite_absurdo_no_revienta(self):
        self.assertIn("LIMIT 1", X.sql_alertas_por_regla("PSP-C-AMT-J9H7", "", -5))


class LaConsultaLePideALaBaseColumnasQueExisten(unittest.TestCase):
    """La regresión.

    La SQL leía `compliance.priority_queue_b2c` pidiéndole nueve columnas que
    esa vista no tiene —la vista expone customer_id, email, name, last_name,
    country_code, los scores y poco más—, así que el endpoint fallaba SIEMPRE
    con `column "nombre" does not exist`. No lo rompió ningún cambio reciente:
    nunca anduvo, y ningún test lo veía porque todos miraban el texto del SQL
    y no contra qué tabla iba.
    """

    # Lo que la vista expone de verdad, leído de Redshift el 06-10-2026.
    VISTA = ("customer_id", "email", "name", "last_name", "country_code",
             "nationality_code", "is_pep", "profession", "cant_beneficiarios",
             "country_risk", "nationality_risk", "pep_score", "profession_score",
             "benef_score", "risk_score")

    def test_no_le_pide_a_la_vista_columnas_que_no_tiene(self):
        sql = X.sql_alertas_por_regla("PSP-C-AMT-J9H7")
        # De la vista sólo puede salir el score, y por un LEFT JOIN explícito:
        # nunca como tabla principal.
        self.assertNotIn("FROM compliance.priority_queue_b2c", sql)
        self.assertIn("LEFT JOIN compliance.priority_queue_b2c", sql)
        for inexistente in ("nombre", "dni", "tipo_dni", "agent_comment",
                            "compliance_agent", "status_created_at",
                            "pais_cliente", "compliance_status"):
            with self.subTest(columna=inexistente):
                self.assertNotIn(f"q.{inexistente}", sql,
                                 f"{inexistente} no existe en priority_queue_b2c")

    def test_los_datos_duros_salen_de_customer(self):
        sql = X.sql_alertas_por_regla("PSP-C-AMT-J9H7")
        self.assertIn('"db_prod"."customer"."compliance"', sql)
        self.assertIn('"db_prod"."customer"."customer_v2"', sql)
        self.assertIn('"db_prod"."customer"."kyc_document"', sql)

    def test_el_score_entra_por_LEFT_join(self):
        """Un INNER dejaría afuera al cliente que no está en la cola de
        priorización, que es justo el que nadie miró todavía."""
        sql = X.sql_alertas_por_regla("PSP-C-AMT-J9H7")
        self.assertIn("LEFT JOIN compliance.priority_queue_b2c", sql)
        self.assertNotIn("INNER JOIN compliance.priority_queue_b2c", sql)

    def test_busca_el_codigo_en_las_DOS_columnas(self):
        """Hoy los bloqueos de fraude llegan por `observation`. Buscar sólo en
        `comment` devolvía cero sin error, que es la peor forma de fallar."""
        sql = X.sql_alertas_por_regla("PSP-C-AMT-J9H7")
        self.assertIn("u.comment LIKE '%PSP-C-AMT-J9H7%'", sql)
        self.assertIn("u.observation LIKE '%PSP-C-AMT-J9H7%'", sql)

    def test_solo_los_que_siguen_bloqueados(self):
        """Devolver uno ya desbloqueado hace que un analista abra un caso
        sobre algo resuelto."""
        self.assertIn("u.compliance_status IN ('BLOCKED', 'FULLY_BLOCKED')",
                      X.sql_alertas_por_regla("PSP-C-AMT-J9H7"))

    def test_se_queda_con_el_estado_mas_nuevo_de_cada_cliente(self):
        sql = X.sql_alertas_por_regla("PSP-C-AMT-J9H7")
        self.assertIn("ROW_NUMBER() OVER", sql)
        self.assertIn("u.rn = 1", sql)

    def test_el_pais_filtra_por_la_columna_de_customer(self):
        """`pais_cliente` es un alias del SELECT: en el WHERE no existe."""
        sql = X.sql_alertas_por_regla("PSP-C-AMT-J9H7", "ar")
        self.assertIn("UPPER(c.country_code) = 'AR'", sql)


class LaReglaSaleDeDondeVengaEscrita(unittest.TestCase):

    def test_prefiere_observation(self):
        a = X.alerta_publica({"customer_id": "9000001",
                              "observation": "operation-alert - FRAUD - PSP-C-AMT-J9H7",
                              "comment": "otra cosa"})
        self.assertEqual(a["regla"], "operation-alert - FRAUD - PSP-C-AMT-J9H7")

    def test_cae_en_comment_si_no_hay_observation(self):
        a = X.alerta_publica({"customer_id": "9000001", "observation": "",
                              "comment": "operation-alert - PSP_SUM_30"})
        self.assertEqual(a["regla"], "operation-alert - PSP_SUM_30")

    def test_sin_ninguna_de_las_dos_no_revienta(self):
        self.assertEqual(X.alerta_publica({"customer_id": "9000001"})["regla"], "")


class ElContrato(unittest.TestCase):
    """La proyección es el contrato: si cambia el objeto interno, acá no pasa
    nada hasta que alguien lo decida."""

    CASO = {
        "case_id": "abc-123", "title": "Caso: 4171334", "description": "",
        "status": "open", "priority": "high", "entity_type": "customer",
        "entity_id": "4171334", "entity_name": "Jaqueline Cipres",
        "report_name": "operation-alert_-_psp_sum_30", "alert_priority": "P2",
        "assigned_to": "ana@global66.com", "created_by": "api:sistema-casos",
        "created_at": "2026-09-08 13:00:13", "updated_at": "2026-09-08 13:00:13",
        "closed_at": "", "note_count": 2,
        "sla_aplica": True, "sla_estado": "vencido", "sla_dias": 12.0,
        "sla_horas_restantes": -216.0, "sla_cierre_at": "2026-09-11 13:00:13",
        "sla_accion": "cerrar",
        # Un campo interno que NO tiene que salir al contrato.
        "alert_data": {"email": "jaquelin@ejemplo.com", "dni": "38699180"},
    }

    def test_expone_lo_que_corresponde(self):
        p = X.caso_publico(self.CASO)
        self.assertEqual(p["id"], "abc-123")
        self.assertEqual(p["cliente"]["id"], "4171334")
        self.assertEqual(p["origen"]["reporte"], "operation-alert_-_psp_sum_30")
        self.assertEqual(p["plazo"]["estado"], "vencido")
        self.assertEqual(p["plazo"]["accion"], "cerrar")

    def test_no_filtra_datos_personales_del_listado(self):
        """El listado sale a un sistema externo: el DNI y el correo del cliente
        se piden en el detalle, no viajan en cada fila de una página de 200."""
        p = X.caso_publico(self.CASO)
        plano = repr(p)
        self.assertNotIn("38699180", plano)
        self.assertNotIn("jaquelin@ejemplo.com", plano)
        self.assertNotIn("alert_data", p)

    def test_un_caso_sin_plazo_lo_dice(self):
        p = X.caso_publico({"case_id": "x", "status": "open"})
        self.assertEqual(p["plazo"], {"aplica": False})

    def test_no_revienta_con_un_caso_incompleto(self):
        p = X.caso_publico({})
        self.assertEqual(p["id"], "")
        self.assertEqual(p["cliente"]["id"], "")

    def test_estados_y_prioridades_validos(self):
        self.assertTrue(X.valida_estado("open"))
        self.assertTrue(X.valida_estado("CLOSED"))
        self.assertFalse(X.valida_estado("inventado"))
        self.assertTrue(X.valida_prioridad("high"))
        self.assertFalse(X.valida_prioridad("urgentisimo"))


class FormaCortaDelSecreto(unittest.TestCase):
    """{"nombre": "clave"} da sólo lectura: escribir tiene que ser explícito."""

    def tearDown(self):
        X._cache = None

    def test_la_forma_corta_es_solo_lectura(self):
        import boto3, json as _json

        class SM:
            def get_secret_value(self, SecretId):
                return {"SecretString": _json.dumps({"rapido": "k-rapido-123"})}

        original = boto3.client
        boto3.client = lambda *a, **k: SM()
        X._cache = None
        try:
            c = X.identificar(evento("k-rapido-123"))
            self.assertEqual(c["nombre"], "rapido")
            self.assertEqual(c["permisos"], {X.LEER})
            self.assertEqual(X.autorizar(evento("k-rapido-123"), X.ESCRIBIR)[1][0], 403)
        finally:
            boto3.client = original


class LaNotaGuardaSuAutor(unittest.TestCase):
    """El bug que esto cubre no rompe nada: el endpoint devolvía 201 y la nota
    quedaba guardada, pero SIN autor, porque el cuerpo se armaba con
    `actor_email` y el caso guarda `author_email`. Justo el dato que este
    módulo existe para garantizar."""

    def test_el_cuerpo_usa_el_nombre_que_espera_el_caso(self):
        cuerpo = X.cuerpo_nota("hola", "api:sistema-casos")
        self.assertEqual(cuerpo, {"content": "hola", "author_email": "api:sistema-casos"})
        self.assertNotIn("actor_email", cuerpo)

    def test_ida_y_vuelta(self):
        """Lo que se escribe es lo que después se lee: si los dos nombres se
        separan, esto falla."""
        cuerpo = X.cuerpo_nota("texto", "api:x")
        guardada = {**cuerpo, "created_at": "2026-09-20 10:00:00"}
        self.assertEqual(X.nota_publica(guardada),
                         {"texto": "texto", "autor": "api:x",
                          "cuando": "2026-09-20 10:00:00"})

    def test_una_nota_vieja_sin_autor_no_revienta(self):
        self.assertEqual(X.nota_publica({"content": "x"})["autor"], "")


if __name__ == "__main__":
    unittest.main(verbosity=1)
