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
#
# ACTUALIZADO el 2026-09-13, con motivo. Dos archivos bajaron en un registro
# válido cada uno (35.028→35.027 y 1.652→1.651) al mapear los tipos de
# documento que los oficios traen y el mapa no reconocía. No es una regresión:
# el tipo determina la regla de longitud, y sin mapear caían en la regla laxa
# por defecto (3-15 dígitos). Los dos registros son:
#
#   EMBARGO DE CUENTAS, fila 2150: "Cédula Extranjeria" de 3 dígitos.
#       Ahora es CE, regla (5,10) → descartado.
#   EMBARGO DE CTA, fila 907: "Permiso Protección Temporal" de 6 dígitos.
#       Ahora es PPT, regla (7,10) → descartado.
#
# Son documentos inválidos de verdad; antes pasaban por un tipo no reconocido.
# No se pierden: van a la hoja "Descartados y revisión" con el motivo.
GOLDEN = {
    "Embargo con varias hojas.xlsx":        (5725, 5725,  0,  4691),
    "EMBARGO DE CUENTAS - 16-04-26.xlsx":   (35089, 35027, 62, 14907),
    "EMBARGO DE CTA 09-04-2026.xlsx":       (1663, 1651,  12, 1600),
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
        # Lo que define el criterio es el WHERE, no el SELECT. Traer columnas
        # extra para poder MIRAR un cruce está bien; filtrar por ellas cambia
        # en silencio quién cuenta como cliente.
        where = sql.split("where", 1)[1]
        for colado in ("status", "country", "is_company", "active", "document_type"):
            self.assertNotIn(colado, where,
                             f"el WHERE no debería filtrar por {colado}")

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


class ElTipoDeDocumentoTambienTieneQueCoincidir(unittest.TestCase):
    """Ser cliente son dos condiciones: el número Y el tipo.

    Encontrado sobre un oficio real: de 7 personas marcadas como clientes por
    número, 2 lo eran porque una cédula colombiana coincide con un DNI
    argentino y con un RUT chileno — gente distinta. Decirle a un juzgado que
    embargue a la persona equivocada es el error más caro de este módulo.

    Se rechaza pero NO se esconde: la coincidencia por número queda marcada,
    porque en un expediente judicial "hubo coincidencia y se descartó por
    esto" es información.
    """

    def _validador(self, tipo_base, pais="CO"):
        def ejecutor(sql):
            return [{"dni": "41888857", "nombre_completo": "OTRA PERSONA",
                     "tipo_dni": tipo_base, "customer_id": 1640224,
                     "pais_cliente": pais, "dni_normalizado": "41888857"}]
        return ValidadorRedshift(ejecutor=ejecutor)

    def _persona(self, tipo_oficio):
        return [{"numero_documento": "41888857", "tipo_documento": tipo_oficio,
                 "nombre_completo": "MARIA ELENA ZULUAGA URIBE", "flags": ""}]

    def test_mismo_numero_distinto_tipo_NO_es_cliente(self):
        p = self._persona("CC")
        marcar_clientes(p, self._validador("DNI", "AR"))
        self.assertFalse(p[0]["es_cliente"], "una CC colombiana no es un DNI argentino")
        self.assertTrue(p[0]["coincide_numero"], "el número sí coincidía")
        self.assertIn("REVISAR:coincide_numero_pero_no_tipo", p[0]["flags"])
        self.assertIn("AR", p[0]["flags"])

    def test_el_rechazado_no_se_lleva_un_customer_id(self):
        """Si no es cliente, no puede quedar con el id de otro: alguien lo
        copiaría al expediente."""
        p = self._persona("CC")
        marcar_clientes(p, self._validador("RUT", "CL"))
        self.assertEqual(p[0]["customer_id"], "")

    def test_mismo_numero_y_mismo_tipo_SI_es_cliente(self):
        p = self._persona("CC")
        marcar_clientes(p, self._validador("CC", "CO"))
        self.assertTrue(p[0]["es_cliente"])
        self.assertEqual(p[0]["customer_id"], 1640224)
        self.assertNotIn("REVISAR", p[0]["flags"])

    def test_sin_tipo_en_el_oficio_sigue_siendo_cliente_pero_marcado(self):
        """Rechazarlo sería perder un cliente real por un dato que el juzgado
        no mandó — el error en la dirección contraria, y también caro."""
        p = self._persona("")
        marcar_clientes(p, self._validador("CC", "CO"))
        self.assertTrue(p[0]["es_cliente"])
        self.assertIn("REVISAR:no_se_pudo_comparar_el_tipo", p[0]["flags"])

    def test_no_pisa_las_alertas_que_ya_traia(self):
        p = self._persona("CC")
        p[0]["flags"] = "AVISO:nombre_con_caracteres_perdidos"
        marcar_clientes(p, self._validador("DNI", "AR"))
        self.assertIn("AVISO:nombre_con_caracteres_perdidos", p[0]["flags"])
        self.assertIn("REVISAR:coincide_numero_pero_no_tipo", p[0]["flags"])


class TiposDeDocumentoDeLosOficios(unittest.TestCase):
    """El mapeo tiene que reconocer lo que los juzgados realmente escriben.

    Con el tipo formando parte del criterio, un sinónimo sin mapear deja de ser
    cosmético: `Cédula Extranjeria` salía como el literal "CEDULA EXT" y nunca
    iba a coincidir con el "CE" de la base. Medido sobre los cuatro oficios
    reales: 1.043 cédulas venezolanas, 253 tarjetas de identidad, 47 cédulas de
    extranjería y 21 permisos de protección temporal quedaban sin mapear.
    """

    def test_reconoce_lo_que_aparece_en_los_oficios_reales(self):
        from embargos.normalize import normalize_doc_type
        for crudo, esperado in [
            ("Cédula", "CC"), ("Cédula de Ciudadanía", "CC"), ("CC", "CC"),
            ("Tarjeta Identidad", "TI"), ("Tarjeta de Identidad", "TI"),
            ("Cédula Extranjeria", "CE"), ("Cédula de Extranjería", "CE"),
            ("Pasaporte", "PA"), ("NIT", "NIT"), ("Nit", "NIT"),
            ("Permiso Proteccion Temporal", "PPT"),
        ]:
            self.assertEqual(normalize_doc_type(crudo), esperado, f"con {crudo!r}")

    def test_un_tipo_desconocido_no_se_hace_pasar_por_uno_conocido(self):
        """Devuelve algo distinto a los códigos canónicos, así que no va a
        coincidir por accidente con el tipo de la base."""
        from embargos.normalize import normalize_doc_type
        self.assertNotIn(normalize_doc_type("Otro - Extranjero"),
                         ("CC", "CE", "TI", "PA", "NIT", "PPT"))


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
