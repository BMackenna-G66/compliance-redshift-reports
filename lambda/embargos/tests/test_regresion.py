"""Regresión del extractor de oficios de embargo.

Los números de abajo salen de una corrida verificada sobre los cuatro archivos
reales. El plan de automatización los fija como *golden values* con una regla
explícita: **si un refactor mueve cualquiera de estos números, el refactor está
mal**. La lógica de normalización está calibrada contra datos sucios de verdad
—encabezados corruptos, apóstrofes de Excel, nombres partidos en dos líneas— y
"mejorarla" sin un caso que lo justifique es romperla.

**Por qué los nombres van hasheados.** Este repositorio es público y las
personas de esos archivos son ciudadanos reales requeridos en un proceso
judicial. La aserción del PDF es valiosa —el propio oficio declara en su texto
quién es el primero y quién el último de los 190, así que comparar contra eso
verifica el extractor contra el documento mismo— pero no hace falta publicar
sus nombres para conservarla: alcanza con el hash.

**Por qué los tests se saltan solos.** Las muestras tampoco pueden estar en el
repo (están en `.gitignore`), así que en CI estos tests no corren. Es
deliberado: mejor un test que se salta y lo dice, que muestras con datos
personales publicadas para que el test pase.
"""
import hashlib
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from embargos import extract  # noqa: E402
from embargos.redshift import ValidadorRedshift, clave_sql, marcar_clientes  # noqa: E402

MUESTRAS = RAIZ / "embargos" / "muestras"

# archivo -> (filas, válidos, descartados, personas únicas)
GOLDEN = {
    "Embargo con varias hojas.xlsx":        (5725, 5725,  0,  4691),
    "EMBARGO DE CUENTAS - 16-04-26.xlsx":   (35089, 35028, 61, 14908),
    "EMBARGO DE CTA 09-04-2026.xlsx":       (1663, 1652,  11, 1601),
    "Oficio_DEAJGCC26-4272.pdf":            (190,  190,   0,  190),
}

# sha256[:16] de los nombres que el propio oficio declara como el primero y el
# último de sus 190 demandados.
PDF_PRIMERO = "7e0ac8987c5609c5"
PDF_ULTIMO = "93c2370b1f86721e"


def _huella(texto: str) -> str:
    return hashlib.sha256(texto.strip().upper().encode("utf-8")).hexdigest()[:16]


def _hay(nombre: str) -> bool:
    return (MUESTRAS / nombre).exists()


class Extraccion(unittest.TestCase):
    """Los cuatro archivos, contra los conteos verificados."""

    def _corrida(self, nombre):
        if not _hay(nombre):
            self.skipTest(f"falta la muestra {nombre} (no viaja en el repo: datos personales)")
        return extract.extraer(MUESTRAS / nombre)

    def test_los_conteos_no_se_mueven(self):
        vistos = 0
        for nombre, (filas, validos, descartados, personas) in GOLDEN.items():
            if not _hay(nombre):
                continue
            vistos += 1
            with self.subTest(archivo=nombre):
                r = self._corrida(nombre)
                self.assertEqual(len(r.registros) + len(r.descartados), filas, "filas leídas")
                self.assertEqual(len(r.registros), validos, "registros válidos")
                self.assertEqual(len(r.descartados), descartados, "descartados")
                self.assertEqual(len(extract.consolidar_por_persona(r.registros)), personas,
                                 "personas únicas")
        if not vistos:
            self.skipTest("no hay muestras locales; correr con la carpeta de insumos")

    def test_el_pdf_coincide_con_lo_que_el_propio_oficio_declara(self):
        """El oficio dice en su cuerpo quién es el nº 1 y quién el nº 190. Es
        la verificación más fuerte que hay: contrasta el extractor contra el
        documento, no contra otra corrida del extractor."""
        r = self._corrida("Oficio_DEAJGCC26-4272.pdf")
        self.assertEqual(len(r.registros), 190)
        self.assertEqual(_huella(r.registros[0].nombre_completo), PDF_PRIMERO,
                         "cambió el primer demandado extraído del PDF")
        self.assertEqual(_huella(r.registros[-1].nombre_completo), PDF_ULTIMO,
                         "cambió el último demandado extraído del PDF")


class NormalizacionDelCruce(unittest.TestCase):
    """`clave_sql` tiene que normalizar EXACTAMENTE igual que el SQL.

    Si los dos lados divergen, el cruce no falla con error: devuelve que nadie
    es cliente. Es el modo de falla más caro de todo el módulo, porque produce
    una respuesta plausible y equivocada para un juzgado.
    """

    def test_replica_el_regexp_del_sql(self):
        for crudo, esperado in [
            ("  85200359 ", "85200359"),
            ("800165941-6", "8001659416"),
            ("'85200359", "85200359"),
            ("ab123456", "AB123456"),      # conserva letras, como el SQL
            ("085200359", "085200359"),    # NO quita ceros a la izquierda
            ("12.345.678", "12345678"),
            ("", ""),
            (None, ""),
        ]:
            self.assertEqual(clave_sql(crudo), esperado, f"con {crudo!r}")


class CruceContraRedshift(unittest.TestCase):
    """El validador, con el ejecutor inyectado — sin cluster."""

    def setUp(self):
        self.sql_vistos = []

        def ejecutor(sql):
            self.sql_vistos.append(sql)
            # Simula que 111 y 222 están en la base; 333 no.
            filas = []
            for doc, cid, nom in (("111", 9001, "ANA PEREZ"), ("222", 9002, "LUIS GOMEZ")):
                if f"'{doc}'" in sql:
                    filas.append({"dni": doc, "nombre_completo": nom, "tipo_dni": "CC",
                                  "customer_id": cid, "dni_normalizado": doc})
            return filas

        self.v = ValidadorRedshift(ejecutor=ejecutor)

    def test_distingue_cliente_de_no_cliente(self):
        r = self.v.validar(["111", "222", "333"])
        self.assertTrue(r["111"])
        self.assertTrue(r["222"])
        self.assertEqual(r["333"], {}, "333 no está en la base: no es cliente")
        self.assertEqual(r["111"]["customer_id"], 9001)
        self.assertEqual(r["222"]["nombre_en_sistema"], "LUIS GOMEZ")

    def test_la_consulta_no_agrega_criterios_propios(self):
        """La definición de cliente es la consulta. Un filtro de estado o de
        país metido acá cambiaría esa definición sin que nadie lo decidiera."""
        self.v.validar(["111"])
        sql = self.sql_vistos[0].lower()
        self.assertIn("kyc_document", sql)
        self.assertIn("customer_v2", sql)
        self.assertIn("inner join", sql)
        for colado in ("status", "country", "is_company", "active"):
            self.assertNotIn(colado, sql, f"la consulta no debería filtrar por {colado}")

    def test_lotea_en_vez_de_una_consulta_por_persona(self):
        """Una consulta por persona serían 15.000 viajes al cluster."""
        v = ValidadorRedshift(ejecutor=lambda sql: [], lote=100)
        v.validar([str(i) for i in range(1, 451)])
        self.assertEqual(v.consultas, 5, "450 documentos en lotes de 100")

    def test_un_documento_vacio_no_rompe_ni_viaja(self):
        v = ValidadorRedshift(ejecutor=lambda sql: [])
        r = v.validar(["", "  ", "111"])
        self.assertEqual(r[""], {})
        self.assertEqual(v.consultas, 1)

    def test_marcar_clientes_no_pisa_el_nombre_del_oficio(self):
        """El nombre del oficio es lo que pidió el juzgado; el del sistema es
        contraste. Cuál va en el Word lo decide el área, no este código."""
        personas = [{"numero_documento": "111", "nombre_completo": "ANA P. CORRUPTO"},
                    {"numero_documento": "333", "nombre_completo": "NO CLIENTE"}]
        marcar_clientes(personas, self.v)
        self.assertTrue(personas[0]["es_cliente"])
        self.assertEqual(personas[0]["nombre_completo"], "ANA P. CORRUPTO")
        self.assertEqual(personas[0]["nombre_en_sistema"], "ANA PEREZ")
        self.assertFalse(personas[1]["es_cliente"])
        self.assertEqual(personas[1]["nombre_en_sistema"], "")


class Empaquetado(unittest.TestCase):
    def test_el_modulo_y_las_plantillas_viajan_en_el_paquete(self):
        """`build_lambda.sh` copia archivo por archivo: un módulo que nadie
        agrega ahí se descubre recién en producción."""
        build = (RAIZ.parent / "build_lambda.sh").read_text()
        self.assertIn("lambda/embargos", build)

    def test_las_muestras_estan_ignoradas_por_git(self):
        """El repo es público y las muestras traen 42.667 personas reales."""
        ignore = (RAIZ.parent / ".gitignore").read_text()
        self.assertIn("lambda/embargos/muestras/", ignore)


if __name__ == "__main__":
    unittest.main(verbosity=2)
