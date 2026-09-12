"""La ficha del cliente.

Lo que se protege acá no es el formateo: es que los totales no cuenten plata
que no se movió. La tabla `transaction` guarda también cotizaciones, errores y
devoluciones, y sumarlas junto a las transferencias exitosas da un volumen
inflado que después alguien usa para decidir si un cliente es de alto riesgo.
Verificado contra el cluster: un cliente con 64 filas tenía 63 transferencias
exitosas y 1 devuelta.

El otro invariante con test es la barrera de `entero()`: el id va interpolado
en el SQL porque la Data API no admite parámetros en todas las posiciones, así
que esa función es lo único que separa la ficha de una inyección.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ficha_cliente as F  # noqa: E402


class Entero(unittest.TestCase):
    """La única barrera entre el input y el SQL interpolado."""

    def test_acepta_un_id_normal(self):
        self.assertEqual(F.entero("4084605"), 4084605)
        self.assertEqual(F.entero(" 4084605 "), 4084605)

    def test_rechaza_cualquier_cosa_que_no_sea_numero(self):
        for malo in ("1 OR 1=1", "1; DROP TABLE x", "4084605'", "abc", "",
                     None, "1.5", "0x10"):
            self.assertIsNone(F.entero(malo), f"debería rechazar {malo!r}")

    def test_rechaza_cero_negativos_y_desbordes(self):
        """Un id fuera del rango de int no existe y Redshift lo rechazaría con
        un error críptico; mejor cortarlo acá."""
        self.assertIsNone(F.entero("0"))
        self.assertIsNone(F.entero("-5"))
        self.assertIsNone(F.entero("2147483648"))
        self.assertEqual(F.entero("2147483647"), 2147483647)

    def test_el_id_validado_es_lo_unico_que_entra_al_sql(self):
        sql = F.sql_resumen(F.entero("4084605"))
        self.assertIn("t.customer_id = 4084605", sql)
        self.assertNotIn("'", sql.split("customer_id =")[1])


class SoloCuentaLoQueSeMovio(unittest.TestCase):
    """El invariante que más cambia los números."""

    def test_los_totales_filtran_por_estado_efectivo(self):
        sql = F.sql_resumen(1)
        self.assertIn("TRANSFERENCIA_EXITOSA", sql)
        self.assertIn("TRANSFERENCIA_ENVIADA", sql)
        # total_usd nunca puede sumar una fila que no sea efectiva
        total = sql.split("AS total_usd")[0].rsplit("ROUND(SUM(", 1)[1]
        self.assertIn("tx_status IN ('TRANSFERENCIA_EXITOSA'", total)

    def test_devueltas_y_retenidas_se_informan_aparte_no_se_descartan(self):
        """Para AML una devolución es señal. Silenciarla sería peor que
        sumarla mal."""
        sql = F.sql_resumen(1)
        self.assertIn("AS n_devueltas", sql)
        self.assertIn("AS devuelto_usd", sql)
        self.assertIn("AS n_retenidas", sql)
        self.assertIn("UNDER_COMPLIANCE_REVIEW", sql)

    def test_un_estado_no_esta_en_dos_grupos_a_la_vez(self):
        grupos = [set(F.EFECTIVAS), set(F.DEVUELTAS), set(F.RETENIDAS)]
        for i, a in enumerate(grupos):
            for b in grupos[i + 1:]:
                self.assertEqual(a & b, set(), "un estado se contaría dos veces")

    def test_por_pais_y_por_mes_usan_el_mismo_filtro(self):
        """Si el detalle no filtra igual que el total, las sumas no cuadran y
        nadie sabe a cuál creerle."""
        for sql in (F.sql_por_pais(1), F.sql_por_mes(1)):
            self.assertIn("TRANSFERENCIA_EXITOSA", sql)


class Cripto(unittest.TestCase):
    def test_se_detecta_por_el_nombre_del_banco_no_por_payment_method(self):
        """Medido en producción: `payment_method` dice WALLET en 2.068.423 de
        2.069.828 filas de 3 meses. Buscar 'bridge' ahí no encuentra nada
        nunca; lo que sí aparece es outbound_bank_name = 'BRIDGE'."""
        self.assertIn("outbound_bank_name", F.CRIPTO)
        self.assertIn("inbound_bank_name", F.CRIPTO)
        self.assertNotIn("payment_method", F.CRIPTO)

    def test_remesas_y_cripto_particionan_las_efectivas(self):
        r = {"n_efectivas": 60, "n_cripto": 60, "n_remesas": 0,
             "usd_cripto": "16537.11", "usd_remesas": "0.00"}
        p = {x["producto"]: x for x in F.productos({}, r)}
        self.assertTrue(p["Cripto"]["tiene"])
        self.assertFalse(p["Remesas"]["tiene"])
        self.assertIn("16,537.11", p["Cripto"]["detalle"])


class Productos(unittest.TestCase):
    def test_cuenta_virtual_sale_del_perfil_kyc(self):
        p = {x["producto"]: x for x in F.productos(
            {"virtual_account_active": "true", "virtual_account_type": "LOCAL",
             "virtual_account_country_code": "US",
             "virtual_account_number": "9900123456"}, {})}
        self.assertTrue(p["Cuenta virtual"]["tiene"])
        self.assertIn("9900123456", p["Cuenta virtual"]["detalle"])

    def test_un_numero_de_cuenta_sin_flag_igual_cuenta(self):
        """`is_enabled` puede venir en null para cuentas viejas; tener número
        asignado ya es evidencia de que el producto existe."""
        p = {x["producto"]: x for x in F.productos(
            {"virtual_account_number": "9900123456"}, {})}
        self.assertTrue(p["Cuenta virtual"]["tiene"])

    def test_sin_datos_no_afirma_nada(self):
        for x in F.productos({}, {}):
            self.assertFalse(x["tiene"], f"{x['producto']} no debería afirmarse")

    def test_cada_producto_dice_de_donde_sale(self):
        """Una ficha de auditoría que afirma sin citar la fuente no se puede
        discutir, que es lo peor que puede pasarle a una."""
        for x in F.productos({}, {}):
            self.assertTrue(x["evidencia"].strip())


class Periodo(unittest.TestCase):
    def test_dice_de_cuando_a_cuando_y_cuanto(self):
        self.assertEqual(
            F.periodo({"primera": "2026-06-11 22:23:45",
                       "ultima": "2026-09-11 18:58:57"}),
            "2026-06-11 a 2026-09-11 (3 meses)")

    def test_un_solo_dia_no_dice_0_meses(self):
        """60 operaciones en un día es exactamente el caso que hay que ver;
        redondearlo a '0 meses' lo escondería."""
        self.assertIn("1 día", F.periodo({"primera": "2026-06-23 16:43:30",
                                          "ultima": "2026-06-24 18:27:30"}))

    def test_sin_transacciones_lo_dice_en_vez_de_inventar_fechas(self):
        self.assertIn("sin transacciones", F.periodo({}))


class Empaquetado(unittest.TestCase):
    """El build copia los archivos uno por uno, así que un módulo nuevo que
    nadie agrega a la lista se descubre recién en producción — y con un
    ImportError a nivel módulo que se lleva puesta la API entera, no sólo la
    ficha. Este test es el que cierra ese agujero."""

    def test_el_modulo_viaja_en_el_paquete(self):
        build = Path(__file__).resolve().parents[2] / "build_lambda.sh"
        self.assertIn("lambda/ficha_cliente.py", build.read_text(),
                      "falta copiar ficha_cliente.py en build_lambda.sh")


class Avisos(unittest.TestCase):
    def test_muchas_devoluciones_levantan_bandera_alta(self):
        a = F.alertas_del_resumen({"n_efectivas": 6, "n_devueltas": 4,
                                   "devuelto_usd": "1200"})
        self.assertTrue(any(x["tono"] == "alto" for x in a))

    def test_una_devolucion_aislada_se_informa_sin_alarmar(self):
        a = F.alertas_del_resumen({"n_efectivas": 63, "n_devueltas": 1,
                                   "devuelto_usd": "382.04"})
        self.assertEqual([x["tono"] for x in a], ["medio"])

    def test_retenidas_por_compliance_siempre_avisan(self):
        a = F.alertas_del_resumen({"n_efectivas": 100, "n_retenidas": 1})
        self.assertTrue(any("retenida" in x["texto"] for x in a))

    def test_un_cliente_limpio_no_genera_ruido(self):
        self.assertEqual(F.alertas_del_resumen(
            {"n_efectivas": 63, "n_remesas": 63}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
