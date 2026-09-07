"""Tests del paso 5. Ninguno toca la red: el driver se reemplaza por un doble.

Lo que se prueba de verdad son las tres reglas de negocio que hacen que este
paso sea seguro: sólo lectura, dos filas es `ambiguo` y sin correo de cliente
es `incompleto`. Lo demás es plomería.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from relevo import cliente as C                    # noqa: E402
from relevo import redshift as R                   # noqa: E402

CONSULTAS = {"consultas": {
    "rmt": {"activa": True, "sql": "SELECT 1 AS cliente_id WHERE x = :valor LIMIT 2"},
    "transfer_no": {"activa": False, "sql": "SELECT 1 LIMIT 2"},
}}

FILA = {"cliente_id": 42, "cliente_nombre": "ACME SpA", "cliente_correo": "pagos@acme.cl",
        "tx_monto": 1234.56, "tx_beneficiario": "JUAN PEREZ GOMEZ", "sucursal": "Santiago"}


class Doble:
    """Se hace pasar por Redshift. Devuelve lo que le dijeron, o levanta."""

    def __init__(self, filas=(), error=None):
        self.filas, self.error, self.llamadas = list(filas), error, []

    def dicts(self, sql, params=None, timeout=None):
        self.llamadas.append((sql, params))
        if self.error:
            raise R.ErrorRedshift(self.error)
        return [dict(f) for f in self.filas], 7

    def cerrar(self):
        pass


class GuardaSoloLectura(unittest.TestCase):
    def test_rechaza_escrituras(self):
        for mala in ("DELETE FROM t", "UPDATE t SET a=1", "DROP TABLE t", "TRUNCATE t",
                     "INSERT INTO t VALUES (1)", "COPY t FROM 's3://x'", "UNLOAD ('x') TO 's3://y'"):
            with self.assertRaises(R.ErrorRedshift, msg=mala):
                R._solo_lectura(mala)

    def test_rechaza_sentencias_encadenadas(self):
        with self.assertRaises(R.ErrorRedshift):
            R._solo_lectura("SELECT 1; DROP TABLE t")

    def test_rechaza_escritura_escondida_en_un_select(self):
        # El comentario no la salva: la palabra sigue en el cuerpo.
        with self.assertRaises(R.ErrorRedshift):
            R._solo_lectura("SELECT * FROM t WHERE x = (DELETE FROM y RETURNING 1)")

    def test_rechaza_vacia(self):
        with self.assertRaises(R.ErrorRedshift):
            R._solo_lectura("   ")

    def test_acepta_lecturas(self):
        self.assertTrue(R._solo_lectura("SELECT a FROM t LIMIT 2"))
        self.assertTrue(R._solo_lectura("WITH x AS (SELECT 1) SELECT * FROM x"))
        self.assertTrue(R._solo_lectura("-- comentario\nSELECT 1;"))

    def test_el_punto_y_coma_final_no_molesta(self):
        self.assertNotIn(";", R._solo_lectura("SELECT 1;"))


class Config(unittest.TestCase):
    """La Data API no tiene host ni clave: casi todo tiene default y las
    credenciales las resuelve boto3. Lo que puede faltar es el cluster."""

    def test_defaults_del_cluster(self):
        c = R.config({})
        self.assertEqual(c["cluster"], "compliance-redshift-cluster")
        self.assertEqual(c["base"], "dev")
        self.assertEqual(c["region"], "us-east-1")
        self.assertEqual(R.faltantes(c), [])

    def test_sin_cluster_ni_workgroup_falta_algo(self):
        self.assertIn("REDSHIFT_CLUSTER", R.faltantes({"base": "dev"}))

    def test_serverless_usa_workgroup_en_vez_de_cluster(self):
        rs = R.Redshift(R.config({"REDSHIFT_WORKGROUP": "wg"}))
        self.assertEqual(rs._destino(), {"WorkgroupName": "wg"})
        self.assertIn("DbUser", R.Redshift(R.config({}))._destino())

    def test_diagnostico_distingue_permisos_de_sesion(self):
        cfg = R.config({"AWS_PROFILE": "compliance-admin"})
        self.assertIn("GetClusterCredentials",
                      R._diagnostico(cfg, Exception("User is not authorized ... GetClusterCredentials")))
        self.assertIn("aws sso login", R._diagnostico(cfg, Exception("Token has expired")))
        self.assertIn("permisos", R._diagnostico(cfg, Exception("AccessDeniedException")))
        self.assertIn("boto3", R._diagnostico(cfg, Exception("Unable to locate credentials")))

    def test_el_error_de_tres_partes_se_explica(self):
        m = R._error_sql('Relation "transaction" does not exist')
        self.assertIn("db_prod", m)
        self.assertIn("tres partes", m)

    def test_el_error_de_cast_se_explica(self):
        self.assertIn("::bigint", R._error_sql("operator does not exist: bigint = text"))


class LecturaDeCeldas(unittest.TestCase):
    """La Data API devuelve cada celda como {tipoValue: x} o {isNull: True}."""

    def test_tipos(self):
        self.assertEqual(R._valor({"longValue": 42}), 42)
        self.assertEqual(R._valor({"stringValue": "IF-1"}), "IF-1")
        self.assertIsNone(R._valor({"isNull": True}))
        self.assertIsNone(R._valor({}))


class Comparacion(unittest.TestCase):
    def test_nombres_parecidos(self):
        self.assertTrue(C._parecen("JUAN PEREZ GOMEZ", "Juan Pérez"))
        self.assertTrue(C._parecen("Comercial ACME SpA", "ACME"))
        self.assertFalse(C._parecen("ACME SpA", "Distribuidora Otra Ltda"))

    def test_nombre_vacio_no_es_comparable(self):
        self.assertIsNone(C._parecen("", "Juan"))

    def test_montos_en_los_dos_formatos(self):
        self.assertEqual(C._numero("USD 1.234,56"), 1234.56)
        self.assertEqual(C._numero("1,234.56"), 1234.56)
        self.assertEqual(C._numero("5.000"), 5000.0)       # es, miles
        self.assertEqual(C._numero("1.234.567"), 1234567.0)
        self.assertEqual(C._numero("12,5"), 12.5)
        self.assertEqual(C._numero("1.50"), 1.5)
        self.assertIsNone(C._numero("n/a"))

    def test_tolerancia_de_monto(self):
        self.assertTrue(C._mismo_monto("USD 1.234,56", 1234.56))
        self.assertTrue(C._mismo_monto(1000, 1005))          # 0,5%: comisión
        self.assertFalse(C._mismo_monto(1000, 1200))

    def test_verificar_marca_la_discrepancia(self):
        v = C.verificar(FILA, {"beneficiario": "Otro Nombre Distinto", "monto": "1.234,56"})
        self.assertFalse(v["beneficiario"]["coincide"])
        self.assertTrue(v["monto"]["coincide"])

    def test_verificar_acepta_los_datos_como_los_guarda_la_transaccion(self):
        """La transacción guarda {es, valor}, no texto suelto. Pasarle esa forma
        reventaba con TypeError y se llevaba puesta la resolución entera."""
        v = C.verificar(FILA, {"beneficiario": {"es": "Beneficiario", "valor": "Juan Perez Gomez"},
                               "monto": {"es": "Monto", "valor": "USD 1.234,56"}})
        self.assertTrue(v["beneficiario"]["coincide"])
        self.assertTrue(v["monto"]["coincide"])

    def test_beneficiario_partido_en_nombre_y_apellido(self):
        v = C.verificar(FILA, {"beneficiario": {"valor": "Juan"},
                               "beneficiario_apellido": {"valor": "Perez Gomez"}})
        self.assertTrue(v["beneficiario"]["coincide"])


class Resolver(unittest.TestCase):
    def tx(self, llave="rmt", valor="28172225", datos=None):
        return {"llave": llave, "valor": valor, "datos": datos or {}}

    def test_sin_consulta_activa_no_consulta(self):
        d = Doble([FILA])
        r = C.resolver(self.tx("transfer_no"), d, CONSULTAS)
        self.assertEqual(r["estado"], "sin_consulta")
        self.assertEqual(d.llamadas, [])

    def test_llave_desconocida_tampoco(self):
        r = C.resolver(self.tx("inventada"), Doble([FILA]), CONSULTAS)
        self.assertEqual(r["estado"], "sin_consulta")

    def test_una_fila_con_correo_es_encontrado(self):
        r = C.resolver(self.tx(), Doble([FILA]), CONSULTAS)
        self.assertEqual(r["estado"], "encontrado")
        self.assertEqual(r["cliente"]["cliente_correo"], "pagos@acme.cl")

    def test_el_valor_viaja_como_parametro(self):
        d = Doble([FILA])
        C.resolver(self.tx(valor="28172225"), d, CONSULTAS)
        self.assertEqual(d.llamadas[0][1], {"valor": "28172225"})

    def test_columnas_fuera_del_contrato_van_a_extra(self):
        r = C.resolver(self.tx(), Doble([FILA]), CONSULTAS)
        self.assertEqual(r["cliente"]["extra"], {"sucursal": "Santiago"})

    def test_dos_filas_es_ambiguo_y_no_se_acciona(self):
        r = C.resolver(self.tx(), Doble([FILA, {**FILA, "cliente_id": 43}]), CONSULTAS)
        self.assertEqual(r["estado"], "ambiguo")
        self.assertEqual(r["filas"], 2)

    def test_sin_correo_de_cliente_es_incompleto(self):
        r = C.resolver(self.tx(), Doble([{**FILA, "cliente_correo": None}]), CONSULTAS)
        self.assertEqual(r["estado"], "incompleto")

    def test_cero_filas_es_sin_match(self):
        self.assertEqual(C.resolver(self.tx(), Doble([]), CONSULTAS)["estado"], "sin_match")

    def test_el_error_es_un_estado_no_una_excepcion(self):
        r = C.resolver(self.tx(), Doble(error="no se pudo conectar a h:5439"), CONSULTAS)
        self.assertEqual(r["estado"], "error")
        self.assertIn("conectar", r["motivo"])

    def test_avisa_cuando_el_beneficiario_no_coincide(self):
        r = C.resolver(self.tx(datos={"beneficiario": "Persona Completamente Otra"}),
                       Doble([FILA]), CONSULTAS)
        self.assertEqual(r["estado"], "encontrado")
        self.assertIn("OJO", r["motivo"])


class Cache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name) / "clientes.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_ida_y_vuelta(self):
        C.guardar_cache([{"llave": "rmt", "valor": "1", "estado": "encontrado"}], self.ruta)
        self.assertEqual(C.leer_cache(self.ruta)["rmt|1"]["estado"], "encontrado")

    def test_deduplica_por_llave_y_valor(self):
        C.guardar_cache([{"llave": "rmt", "valor": "1", "estado": "sin_match"}], self.ruta)
        C.guardar_cache([{"llave": "rmt", "valor": "1", "estado": "encontrado"}], self.ruta)
        cache = C.leer_cache(self.ruta)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache["rmt|1"]["estado"], "encontrado")

    def test_ignora_una_linea_a_medio_escribir(self):
        self.ruta.write_text('{"llave":"rmt","valor":"1"}\n{"llave":"rmt","va\n', encoding="utf-8")
        self.assertEqual(len(C.leer_cache(self.ruta)), 1)

    def test_adjuntar_pega_el_resultado_a_la_transaccion(self):
        tx = [{"llave": "rmt", "valor": "1"}, {"llave": "rmt", "valor": "2"}]
        C.adjuntar(tx, {"rmt|1": {"estado": "encontrado"}})
        self.assertEqual(tx[0]["cliente"]["estado"], "encontrado")
        self.assertIsNone(tx[1]["cliente"])


class Lote(unittest.TestCase):
    def test_no_repregunta_lo_ya_resuelto(self):
        d = Doble([FILA])
        txs = [{"llave": "rmt", "valor": "1"}, {"llave": "rmt", "valor": "2"}]
        C.resolver_muchas(txs, CONSULTAS, rs=d, cache=False)
        self.assertEqual(len(d.llamadas), 2)

    def test_el_limite_corta(self):
        d = Doble([FILA])
        txs = [{"llave": "rmt", "valor": str(i)} for i in range(10)]
        r = C.resolver_muchas(txs, CONSULTAS, rs=d, cache=False, limite=3)
        self.assertEqual(len(d.llamadas), 3)
        self.assertEqual(len(r), 3)

    def test_si_la_conexion_se_cae_no_sigue_golpeando(self):
        d = Doble(error="no se pudo conectar a h:5439 (timeout)")
        txs = [{"llave": "rmt", "valor": str(i)} for i in range(10)]
        C.resolver_muchas(txs, CONSULTAS, rs=d, cache=False)
        self.assertEqual(len(d.llamadas), 1)


class ArchivoDeConsultas(unittest.TestCase):
    """El archivo que se edita a mano: que sea válido y que respete el contrato."""

    def setUp(self):
        self.c = C.cargar_consultas()

    def test_toda_llave_de_consulta_tiene_su_sql(self):
        """Si alguien agrega una llave nueva a reglas.json, este test avisa.

        Sólo las de rol `llave_consulta`: `cc_ticket` y `nium_request_id` son el
        número de caso DEL PARTNER, no sirven para buscar en nuestra base.
        """
        reglas = json.loads((Path(__file__).resolve().parent.parent / "reglas.json")
                            .read_text(encoding="utf-8"))
        llaves = {e["llave"] for p in reglas["partners"] for e in p.get("extraccion", [])
                  if e.get("rol") == "llave_consulta"}
        faltan = llaves - set(self.c["consultas"])
        self.assertFalse(faltan, f"sin consulta definida en consultas.json: {faltan}")

    def test_toda_consulta_es_de_lectura_parametrizada_y_acotada(self):
        for llave, cfg in self.c["consultas"].items():
            with self.subTest(llave=llave):
                R._solo_lectura(cfg["sql"])                      # levanta si no es lectura
                self.assertIn(":valor", cfg["sql"], "el valor tiene que ir como parámetro con nombre")
                self.assertRegex(cfg["sql"], r"LIMIT\s+2\s*$", "falta LIMIT 2 (unicidad)")

    def test_toda_consulta_devuelve_los_alias_minimos(self):
        for llave, cfg in self.c["consultas"].items():
            with self.subTest(llave=llave):
                for alias in ("cliente_id", "cliente_nombre", "cliente_correo"):
                    self.assertIn(f"AS {alias}", cfg["sql"])


if __name__ == "__main__":
    unittest.main()
