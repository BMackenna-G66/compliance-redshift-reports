"""Paso 9, parte B: el espejo analítico.

No se prueba Redshift: se prueba lo que se le manda. Que las columnas del DDL
sean exactamente las claves que se suben, que las cuatro formas de fecha que
conviven en el módulo caigan en un solo formato, y que un valor demasiado largo
o un diccionario suelto no lleguen a la tabla.
"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from relevo import espejo  # noqa: E402


class FalsoDeposito:
    def __init__(self):
        self.datos = {}
        self.BUCKET = "bucket-de-prueba"
        self.PREFIJO = "relevo"

    def activo(self):
        return True

    def clave_segura(self, v):
        return str(v).replace("/", "_")

    def obtener(self, col, clave):
        return self.datos.get((col, clave))

    def poner(self, col, clave, dato, solo_si_falta=False):
        self.datos[(col, clave)] = dato
        return True

    def todos(self, col, sub=""):
        pref = col.strip("/") + "/"
        return [v for (c, _), v in self.datos.items()
                if c == col or c.startswith(pref)]


VISTA = {"casos": [{
    "id": "nium:caso:1088170",
    "partner": "Nium", "caso_partner": "1088170",
    "estado": "devuelto", "etapa": 3, "accionable": True,
    "n_transacciones": 1, "n_correos": 2,
    "primera": "2026-09-01 10:00", "ultima": "2026-09-04 15:30",
    "plazo": "2026-09-08",
    "items": [{"item": "origen_fondos", "es": "Origen de los fondos"}],
    "transacciones": [{"llave": "py", "valor": "PY75795516", "n_correos": 2,
                       "ultima": "2026-09-04 15:30",
                       "datos": {"monto": {"es": "Monto", "valor": "1500.00"},
                                 "moneda": "USD", "beneficiario": "ACME LTD"}}],
    "cliente": {"cliente_id": 3950037, "cliente_nombre": "Maria Paula",
                "cliente_correo": "maria@example.com", "cliente_pais": "CL"},
    "seguimiento": {"intentos": 1, "ultimo_contacto": "2026-09-02T09:00:00+00:00",
                    "proximo_contacto": "2026-09-05T09:00:00+00:00",
                    "vencido": False, "agotado": False},
    "acciones": [
        {"accion": "pedido_enviado", "quien": "ana", "cuando": "2026-09-02T09:00:00+00:00",
         "detalle": {"ref": "abc12345"}},
        {"accion": "respuesta_recibida", "quien": "sistema",
         "cuando": "2026-09-03T09:00:00+00:00", "detalle": {}},
        {"accion": "devuelto", "quien": "ana", "cuando": "2026-09-04T09:00:00+00:00",
         "detalle": {"parcial": False, "archivos": ["cedula.pdf"]}},
    ],
}]}


class DDLyFilasCoinciden(unittest.TestCase):
    def test_toda_clave_subida_existe_como_columna(self):
        """El bug más caro posible acá: COPY con 'auto' ignora en silencio una
        clave que no matchea ninguna columna, y la fila entra incompleta."""
        dep = FalsoDeposito()
        real, espejo.deposito = espejo.deposito, dep
        try:
            filas = espejo.construir(VISTA, ahora="2026-09-09 12:00:00")
        finally:
            espejo.deposito = real
        for tabla, lista in filas.items():
            columnas = {c for c, _ in espejo.TABLAS[tabla]}
            for f in lista:
                sobrantes = set(f) - columnas
                self.assertEqual(sobrantes, set(),
                                 f"{tabla}: claves que no son columna: {sobrantes}")

    def test_el_ddl_declara_las_mismas_tablas(self):
        sentencias = espejo.ddl()
        self.assertTrue(sentencias[0].startswith("CREATE SCHEMA IF NOT EXISTS"))
        declaradas = set()
        for s in sentencias[1:]:
            m = re.match(r"CREATE TABLE IF NOT EXISTS \w+\.(\w+) \(", s)
            self.assertIsNotNone(m, s[:80])
            declaradas.add(m.group(1))
        self.assertEqual(declaradas, set(espejo.TABLAS))

    def test_cada_tabla_lleva_snapshot_en(self):
        for tabla, cols in espejo.TABLAS.items():
            self.assertIn("snapshot_en", {c for c, _ in cols}, tabla)


class Fechas(unittest.TestCase):
    def test_iso_con_offset_va_a_utc(self):
        self.assertEqual(espejo._ts("2026-09-08T22:10:03-03:00"), "2026-09-09 01:10:03")

    def test_fecha_corta_de_transacciones_se_completa(self):
        self.assertEqual(espejo._ts("2026-09-04 15:30"), "2026-09-04 15:30:00")

    def test_gmtime_del_deposito_pasa_igual(self):
        self.assertEqual(espejo._ts("2026-09-04 15:30:22"), "2026-09-04 15:30:22")

    def test_internaldate_en_milisegundos(self):
        # 1757000000000 ms = 2025-09-04 15:33:20 UTC
        self.assertEqual(espejo._ts("1757000000000"), "2025-09-04 15:33:20")

    def test_lo_ilegible_va_null_y_no_una_fecha_inventada(self):
        for basura in ("", None, "ayer", "2026-13-45", "n/d"):
            self.assertIsNone(espejo._ts(basura), repr(basura))

    def test_horas_entre_marcas(self):
        self.assertEqual(espejo._horas("2026-09-02 09:00:00", "2026-09-03 09:00:00"), 24.0)
        self.assertIsNone(espejo._horas(None, "2026-09-03 09:00:00"))
        self.assertIsNone(espejo._horas("2026-09-02 09:00:00", None))


class Valores(unittest.TestCase):
    def test_recorta_al_largo_declarado(self):
        largo = "x" * 5000
        f = espejo._fila("solicitudes", {"caso_id": "c", "asunto": largo})
        self.assertEqual(len(f["asunto"]), 1000)

    def test_el_vacio_se_omite_para_que_quede_null(self):
        f = espejo._fila("casos", {"caso_id": "c", "cliente_nombre": "",
                                   "cliente_correo": None})
        self.assertNotIn("cliente_nombre", f)
        self.assertNotIn("cliente_correo", f)

    def test_desenvuelve_los_datos_con_forma_es_valor(self):
        self.assertEqual(espejo._plano({"es": "Monto", "valor": "1500.00"}), "1500.00")
        self.assertEqual(espejo._plano(["a", "b"]), "a, b")
        self.assertIsNone(espejo._plano(""))
        self.assertIsNone(espejo._plano({}))

    def test_el_monto_no_llega_como_diccionario_serializado(self):
        dep = FalsoDeposito()
        real, espejo.deposito = espejo.deposito, dep
        try:
            filas = espejo.construir(VISTA, ahora="2026-09-09 12:00:00")
        finally:
            espejo.deposito = real
        tx = filas["transacciones"][0]
        self.assertEqual(tx["monto"], "1500.00")
        # Ningún valor de la fila puede ser un dict o una lista: COPY los
        # cargaría serializados en una columna de texto.
        for col, v in tx.items():
            self.assertIsInstance(v, (str, int, float, bool), f"{col} = {v!r}")


class Contenido(unittest.TestCase):
    def setUp(self):
        self.dep = FalsoDeposito()
        self.real = espejo.deposito
        espejo.deposito = self.dep

    def tearDown(self):
        espejo.deposito = self.real

    def _filas(self):
        return espejo.construir(VISTA, ahora="2026-09-09 12:00:00")

    def test_una_fila_por_caso_y_una_por_accion(self):
        f = self._filas()
        self.assertEqual(len(f["casos"]), 1)
        self.assertEqual(len(f["acciones"]), 3)
        self.assertEqual(len(f["transacciones"]), 1)

    def test_los_tiempos_del_ciclo_se_calculan(self):
        c = self._filas()["casos"][0]
        self.assertEqual(c["horas_pedido_a_respuesta"], 24.0)
        self.assertEqual(c["horas_respuesta_a_devolucion"], 24.0)
        self.assertEqual(c["devuelto_en"], "2026-09-04 09:00:00")
        self.assertEqual(c["devuelto_por"], "ana")

    def test_sin_checklist_el_item_queda_marcado_como_tal(self):
        """No se le inventa 'pendiente' a un ítem que nadie registró."""
        i = self._filas()["items"][0]
        self.assertEqual(i["item"], "origen_fondos")
        self.assertEqual(i["estado"], "sin_checklist")

    def _con_checklist(self):
        """El checklist se lee de la colección completa, no caso por caso.
        Si la indexación por caso_id se rompe, TODOS los casos parecen no
        tener checklist y nada falla a la vista: de ahí este test."""
        self.dep.datos[("checklist", "k1")] = {
            "caso_id": "nium:caso:1088170", "ref": "abc12345",
            "documentos": {
                "origen_fondos": {"etiqueta": "Origen de los fondos",
                                  "estado": "entregado", "quien": "ana@global66.com",
                                  "cuando": "2026-09-04 10:00:00"},
                "documento_identidad": {"etiqueta": "Documento de identidad",
                                        "estado": "pendiente", "quien": "",
                                        "cuando": "2026-09-02 09:00:00"},
            },
        }
        return self._filas()

    def test_el_checklist_se_indexa_por_caso(self):
        items = self._con_checklist()["items"]
        self.assertEqual(len(items), 2)
        por_clave = {i["item"]: i for i in items}
        self.assertEqual(por_clave["origen_fondos"]["estado"], "entregado")
        self.assertEqual(por_clave["origen_fondos"]["quien"], "ana@global66.com")
        self.assertEqual(por_clave["documento_identidad"]["estado"], "pendiente")
        self.assertNotIn("sin_checklist", {i["estado"] for i in items})

    def test_los_conteos_del_checklist_llegan_al_caso(self):
        c = self._con_checklist()["casos"][0]
        self.assertEqual(c["ck_total"], 2)
        self.assertEqual(c["ck_entregado"], 1)
        self.assertEqual(c["ck_pendiente"], 1)
        # El 0 SÍ va: "cero documentos en recibido" es un hecho, no una
        # ausencia. Sólo None y "" se omiten para que queden NULL.
        self.assertEqual(c["ck_recibido"], 0)

    def test_un_booleano_falso_se_guarda_como_falso_y_no_como_null(self):
        """`vencido: False` omitido sería un caso vencido en el reporte."""
        c = self._filas()["casos"][0]
        self.assertIs(c["vencido"], False)
        self.assertIs(c["agotado"], False)
        self.assertIs(c["devolucion_parcial"], False)

    def test_un_checklist_de_otro_caso_no_se_mezcla(self):
        self.dep.datos[("checklist", "k9")] = {
            "caso_id": "dlocal:rmt:99999",
            "documentos": {"domicilio": {"etiqueta": "Domicilio", "estado": "recibido"}},
        }
        items = self._con_checklist()["items"]
        self.assertEqual({i["caso_id"] for i in items}, {"nium:caso:1088170"})
        self.assertNotIn("domicilio", {i["item"] for i in items})

    def test_las_solicitudes_van_completas_no_por_caso(self):
        """Una solicitud fallida puede no tener caso en la vista; perderla
        sería perder justo el intento que hay que revisar."""
        self.dep.datos[("solicitudes", "s1")] = {
            "request_id": "s1", "caso_id": "caso-que-ya-no-esta",
            "correo": "x@example.com", "asunto": "Solicitud",
            "enviado": False, "error": "403 sin scope de envío",
            "quien": "ana", "documentos": ["a", "b"], "cuando": "2026-09-02 09:00:00",
        }
        f = self._filas()
        self.assertEqual(len(f["solicitudes"]), 1)
        s = f["solicitudes"][0]
        self.assertEqual(s["caso_id"], "caso-que-ya-no-esta")
        self.assertEqual(s["n_documentos"], 2)
        self.assertNotIn("enviado", {k for k, v in s.items() if v is None})

    def test_la_devolucion_registrada_llega_al_espejo(self):
        self.dep.datos[("devoluciones", "d1")] = {
            "caso_id": "nium:caso:1088170", "quien": "ana", "cuando": "2026-09-04 09:00:00",
            "medio": "correo_manual", "para": "payments@nium.com", "idioma": "en",
            "referencia": "1088170", "archivos": ["cedula.pdf"], "pendientes": [],
            "parcial": False,
        }
        d = self._filas()["devoluciones"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["n_archivos"], 1)
        self.assertEqual(d[0]["para"], "payments@nium.com")

    def test_de_dos_devoluciones_del_mismo_caso_gana_la_ultima(self):
        for i, cuando in enumerate(("2026-09-04 09:00:00", "2026-09-06 09:00:00")):
            self.dep.datos[("devoluciones", f"d{i}")] = {
                "caso_id": "nium:caso:1088170", "quien": f"a{i}", "cuando": cuando,
                "archivos": [], "pendientes": [], "parcial": False}
        d = self._filas()["devoluciones"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["cuando"], "2026-09-06 09:00:00")


class SinDeposito(unittest.TestCase):
    def test_sin_bucket_no_intenta_escribir(self):
        class Apagado(FalsoDeposito):
            def activo(self):
                return False
        real, espejo.deposito = espejo.deposito, Apagado()
        try:
            r = espejo.correr()
        finally:
            espejo.deposito = real
        self.assertIn("RELEVO_BUCKET", r["error"])
        self.assertEqual(r["tablas"], {})


if __name__ == "__main__":
    unittest.main()
