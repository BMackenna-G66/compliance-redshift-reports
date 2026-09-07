"""Regresiones. Cada caso es una trampa documentada o un bug que ya ocurrio.

Corre con stdlib:   python3 -m unittest discover -s tests -v
(tambien corre bajo pytest si esta instalado)
"""
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ.parent))
sys.path.insert(0, str(RAIZ))

from relevo import cargar_reglas, procesar          # noqa: E402
from relevo.validar import normalizar               # noqa: E402

REGLAS = cargar_reglas()


def correr(asunto, cuerpo="", **headers):
    return procesar({"id": "t", "asunto": asunto, "cuerpo": cuerpo, "headers": headers}, REGLAS)


def valores(reg, llave):
    return sorted(h["valor_consulta"] for h in reg["ids"] if h["llave"] == llave and h["valido"])


class IdentificacionDePartner(unittest.TestCase):
    def test_el_header_manda_sobre_el_from_reescrito(self):
        """El From dice compliance@global66.com en los 2.430 correos. No separa nada."""
        r = correr("Cualquier cosa", **{"From": "compliance@global66.com",
                                        "X-Original-Sender": "no_reply@dlocal.com"})
        self.assertEqual(r["partner"], "dLocal")
        self.assertTrue(r["partner_via"].startswith("x_original_sender"))

    def test_mapa_de_dominios_completo(self):
        for direccion, esperado in [
            ("no_reply@dlocal.com", "dLocal"),
            ("kycrequests@currencycloud.com", "Currencycloud"),
            ("fraudreporting@currencycloud.com", "Currencycloud"),
            ("compliance@nium.com", "Nium"),
            ("payments@nium.com", "Nium"),
            ("qualquer@ozcambio.com.br", "OZ Câmbio"),
            ("support@bridge.xyz", "Bridge"),
            ("hola@cobre.co", "Cobre"),
            ("x@localpayment.com", "Localpayment"),
        ]:
            with self.subTest(direccion=direccion):
                self.assertEqual(correr("asunto", **{"X-Original-Sender": direccion})["partner"], esperado)

    def test_remitente_nuevo_se_loguea_crudo_y_no_se_pierde(self):
        r = correr("Novedad", **{"X-Original-Sender": "nuevo@partner-nuevo.com"})
        self.assertEqual(r["estado"], "partner_desconocido")
        self.assertEqual(r["x_original_sender_crudo"], "nuevo@partner-nuevo.com")

    def test_un_rmt_en_el_asunto_no_convierte_un_correo_de_nium_en_dlocal(self):
        """Regresion: 33 correos de Nium se atribuian a dLocal por traer RMT.
        RMT es un identificador NUESTRO: cualquier corresponsal puede citarlo."""
        r = correr("Additional Information Request - Alerts - PY74392606 - RMT023469123")
        self.assertEqual(r["partner"], "Nium")

    def test_la_etiqueta_estructural_gana_sobre_la_marca_mencionada(self):
        """Regresion: 3 correos de Currencycloud nombraban a NIUM como contraparte."""
        r = correr("[Currencycloud] Re: 1351577 - Compliance Query - NIUM * Yineth Perez")
        self.assertEqual(r["partner"], "Currencycloud")

    def test_currency_cloud_con_espacio(self):
        self.assertEqual(correr("RE: CURRENCY CLOUD compliance query")["partner"], "Currencycloud")


class Clasificacion(unittest.TestCase):
    def test_dlocal_informativo_vs_accionable(self):
        h = {"X-Original-Sender": "no_reply@dlocal.com"}
        self.assertTrue(correr("New RFI is requested - RMT025597309", **h)["accionable"])
        self.assertTrue(correr("RFI needs attention - RMT025597309", **h)["accionable"])
        for asunto in ("OTP code requested - RMT025597309",
                       "Payout ID 636254416 external ID RMT025641319 has been released",
                       "Your verification has been approved - RMT025646337"):
            with self.subTest(asunto=asunto):
                self.assertFalse(correr(asunto, **h)["accionable"])

    def test_asunto_desconocido_se_trata_como_accionable(self):
        r = correr("Formato nuevo que nadie vio", **{"X-Original-Sender": "no_reply@dlocal.com"})
        self.assertTrue(r["accionable"])
        self.assertTrue(any("cambio de formato" in a for a in r["alertas"]))


class DerivaObservadaEnVivo(unittest.TestCase):
    """Formatos que aparecieron en el buzon el 2026-09-03 y no estaban en la
    ventana analizada. Cada uno es una regla que se habria perdido."""
    H = {"X-Original-Sender": "kycrequests@currencycloud.com"}

    def test_el_cierre_de_ticket_es_informativo(self):
        """Mismo asunto que el requerimiento: la diferencia esta en el cuerpo.
        Sin esto, la mitad del trafico de un dia entra como accionable."""
        asunto = "[Currencycloud] Re: 1382588 - Urgent - Bank Compliance Query - Maria G"
        r = correr(asunto, "Your request (1382588) has been Solved.", **self.H)
        self.assertEqual(r["tipo"], "resuelto")
        self.assertFalse(r["accionable"])

    def test_el_mismo_asunto_con_updated_sigue_siendo_accionable(self):
        asunto = "[Currencycloud] Re: 1382588 - Urgent - Bank Compliance Query - Maria G"
        r = correr(asunto, "Your request (1382588) has been updated.", **self.H)
        self.assertEqual(r["tipo"], "consulta_compliance")
        self.assertTrue(r["accionable"])

    def test_tipo_tss_reconocido(self):
        r = correr("[Currencycloud] Re: 1379978 - TSS RT for the Compliance Check: BANK OF AMERICA",
                   "Your request (1379978) has been updated.", **self.H)
        self.assertEqual(r["partner"], "Currencycloud")
        self.assertEqual(r["tipo"], "verificacion_tss")

    def test_ticket_sin_la_etiqueta_entre_corchetes(self):
        """El primer mensaje de un hilo llega sin '[Currencycloud]' adelante."""
        r = correr("1373096 - Compliance Query - APEX LEGAL IMMIG", "", **self.H)
        self.assertEqual(r["partner"], "Currencycloud")
        self.assertEqual(r["caso_partner"], "1373096")


class OZCambio(unittest.TestCase):
    H = {"X-Original-Sender": "ops@ozcambio.com.br"}

    def test_dos_ids_en_un_asunto(self):
        """5 mensajes con formato 'IDs A / B'. Un regex de primera coincidencia
        pierde la segunda transaccion."""
        r = correr("OZ NOTIFICACIÓN - LÍMITE - IDs 14630283 / 14630102", **self.H)
        self.assertEqual(valores(r, "transfer_no"), ["14630102", "14630283"])

    def test_id_corrupto_fuera_de_rango_no_se_consulta(self):
        """Aparecio un 1385384 de siete digitos. Si se consulta, devuelve vacio
        y el caso queda «sin match» sin que nadie entienda por que."""
        r = correr("Re: OZ NOTIFICATION - ID 1385384", **self.H)
        self.assertEqual(r["estado"], "en_conciliacion")
        self.assertEqual(r["valor_consulta"], "")
        self.assertIn("fuera de rango", r["ids"][0]["motivo"])

    def test_no_captura_numeros_sueltos_sin_la_etiqueta_id(self):
        r = correr("OZ NOTIFICATION - transferencia 14185258 monto 99999999", **self.H)
        self.assertEqual(valores(r, "transfer_no"), [])


class Nium(unittest.TestCase):
    H = {"X-Original-Sender": "compliance@nium.com"}

    def test_captura_todos_los_py_del_cuerpo_no_el_primero(self):
        r = correr("Reminder: Additional Information Request",
                   "PY77289097/PY77335966/PY77396838/PY77401001", **self.H)
        self.assertEqual(valores(r, "nium_payout_id"),
                         ["77289097", "77335966", "77396838", "77401001"])
        self.assertEqual(r["n_transacciones"], 4)

    def test_un_caso_cubre_varias_transacciones(self):
        """El Request ID de Nium agrupa por CLIENTE, no por operacion."""
        r = correr("Reminder: Additional Information Request – COMERCIAL Y ASESORA",
                   "Request ID: 1069816\nPY59130209/PY60245047/PY60995055", **self.H)
        self.assertEqual(r["caso_partner"], "1069816")
        self.assertEqual(r["n_transacciones"], 3)

    def test_prioridad_rmt_sobre_py(self):
        r = correr("Additional Information Request", "PY77289097 RMT027773217", **self.H)
        self.assertEqual(r["llave_consulta"], "rmt")
        self.assertEqual(r["valor_consulta"], "27773217")

    def test_py_sin_rmt_usa_la_llave_de_nium(self):
        """28 de 71: la consulta tiene que aceptar PY ademas de RMT."""
        r = correr("Additional Information Request", "PY77289097", **self.H)
        self.assertEqual(r["llave_consulta"], "nium_payout_id")
        self.assertEqual(r["valor_consulta"], "77289097")

    def test_el_cuerpo_es_obligatorio(self):
        """25 de 71 PY solo estan en el cuerpo: sin leerlo se pierde el 35%."""
        asunto = "Reminder: Additional Information Request – Alerts – COMERCIAL Y ASESORA"
        self.assertEqual(correr(asunto, "", **self.H)["valor_consulta"], "")
        self.assertEqual(correr(asunto, "PY59130209", **self.H)["valor_consulta"], "59130209")


class Currencycloud(unittest.TestCase):
    H = {"X-Original-Sender": "kycrequests@currencycloud.com"}

    def test_ticket_del_asunto_es_del_partner_no_llave_de_consulta(self):
        r = correr("[Currencycloud] Re: 1308101 - Compliance Query", **self.H)
        self.assertEqual(r["caso_partner"], "1308101")
        self.assertEqual(r["llave_consulta"], "")
        self.assertEqual(r["estado"], "sin_llave")

    def test_el_if_del_cuerpo_si_es_llave(self):
        r = correr("[Currencycloud] Re: 1317951 - Bank RFI",
                   "Transaction ID: IF-20260424-S1B6BR", **self.H)
        self.assertEqual(r["llave_consulta"], "cc_transaction_id")
        self.assertEqual(r["valor_consulta"], "IF-20260424-S1B6BR")

    def test_external_id_solo_acepta_un_formato_de_los_cuatro(self):
        """Los otros tres formatos no son nuestros: consultarlos es consultar
        el identificador de otro sistema."""
        bueno = correr("[Currencycloud] Re: 1317951 - Bank RFI",
                       "External ID: 20260805_1031027169921_8338601597", **self.H)
        self.assertEqual(valores(bueno, "cc_external_id"), ["20260805_1031027169921_8338601597"])
        for malo in ("External ID: 135449", "External ID: ECM CASE #126540", "External ID: SAV 30663 LAB"):
            with self.subTest(malo=malo):
                self.assertEqual(valores(correr("[Currencycloud] Re: 1317951 - Bank RFI", malo, **self.H),
                                         "cc_external_id"), [])


class ColaDeExtraccion(unittest.TestCase):
    """La ingesta incremental lee toda la casilla. Separar «no es corresponsal»
    de «corresponsal sin regla» es lo que mantiene util la cola de
    descubrimiento: sin esto, 93 respuestas de clientes tapaban 3 senales."""

    def test_respuesta_de_cliente_se_aparta(self):
        r = correr("Re: Solicitud de información envió detenido - Global66", "",
                   **{"X-Original-Sender": "alguien@gmail.com"})
        self.assertEqual(r["estado"], "no_corresponsal")
        self.assertEqual(r["partner_via"], "no_corresponsal")

    def test_dominio_personal_no_es_corresponsal_nuevo(self):
        r = correr("Consulta cualquiera", "", **{"X-Original-Sender": "cliente@hotmail.com"})
        self.assertEqual(r["estado"], "no_corresponsal")

    def test_dominio_corporativo_desconocido_si_va_a_descubrimiento(self):
        """Asi aparecio Cobre. Esta cola tiene que seguir viva."""
        r = correr("Requerimiento de informacion", "",
                   **{"X-Original-Sender": "compliance@corresponsal-nuevo.com"})
        self.assertEqual(r["estado"], "partner_desconocido")
        self.assertEqual(r["x_original_sender_crudo"], "compliance@corresponsal-nuevo.com")

    def test_un_partner_conocido_no_se_aparta_nunca(self):
        r = correr("New RFI is requested - RMT025597309", "",
                   **{"X-Original-Sender": "no_reply@dlocal.com"})
        self.assertEqual(r["partner"], "dLocal")
        self.assertEqual(r["estado"], "listo_para_consulta")


class Normalizacion(unittest.TestCase):
    def test_prefijo_y_ceros_a_la_izquierda(self):
        self.assertEqual(normalizar("rmt", "RMT027773217", REGLAS), "27773217")
        self.assertEqual(normalizar("rmt", "027773217", REGLAS), "27773217")
        self.assertEqual(normalizar("nium_payout_id", "PY59130209", REGLAS), "59130209")
        self.assertEqual(normalizar("transfer_no", "13739614", REGLAS), "13739614")

    def test_el_if_conserva_su_forma(self):
        self.assertEqual(normalizar("cc_transaction_id", "if-20260424-s1b6br", REGLAS), "IF-20260424-S1B6BR")


class GoldenSet(unittest.TestCase):
    """Test de regresion contra los 963 registros del consolidado.

    No es una verdad de campo: el consolidado lo produjo el mismo tipo de
    extraccion. Sirve para que un cambio de reglas no rompa lo que ya andaba.
    """
    # El consolidado no vive en el repo (tiene datos de cliente). Se busca en
    # varios lugares: si el proyecto se mueve, el test no se apaga en silencio.
    CANDIDATOS = [
        RAIZ / "corpus" / "Consolidado_IDs_corresponsales.xlsx",
        RAIZ.parent / "Consolidado_IDs_corresponsales.xlsx",
        Path.home() / "Downloads" / "Consolidado_IDs_corresponsales.xlsx",
    ]

    def setUp(self):
        self.XLSX = next((c for c in self.CANDIDATOS if c.exists()), None)
        if self.XLSX is None:
            self.skipTest("no se encontro el consolidado en: "
                          + " · ".join(str(c) for c in self.CANDIDATOS))

    def test_captura_y_atribucion(self):
        from relevo.evaluar import evaluar, resumir
        from relevo.fuentes import desde_consolidado
        ms = desde_consolidado(self.XLSX)
        regs = [evaluar(procesar(m, REGLAS), m, REGLAS) for m in ms]
        _, t = resumir(regs)
        self.assertEqual(t["total"], 963)
        self.assertEqual(t["no_coincide"], 0, "ninguna extraccion debe entregar un valor distinto del esperado")
        self.assertEqual(t["capturado_invalido"], 0)
        self.assertGreaterEqual(t["tasa_captura"], 99.0)
        self.assertGreaterEqual(t["partner_ok"] / t["total"] * 100, 99.0)
        self.assertEqual(t["requiere_cuerpo"], 25, "los 25 PY que solo viven en el cuerpo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
