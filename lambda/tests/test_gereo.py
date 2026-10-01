# -*- coding: utf-8 -*-
"""El cliente de la API de GEREO.

LO QUE VIGILA, en orden de qué duele más si se rompe:

1. **Que la clave no termine en el repo.** Es público. Una clave escrita en
   el código hay que rotarla el mismo día y la integración se corta.

2. **Que no se loguee la respuesta.** Trae nombre, documento, dirección y
   teléfono de personas reales más el detalle de sus operaciones. Un `print`
   del response completo queda en CloudWatch por años.

3. **Que `es_detencion` no se trate como error.** GEREO responde 200 cuando
   el cliente existe pero es de otro país. Es la regla de negocio
   funcionando; contarlo como falla llenaría el tablero de errores que no lo
   son, y reintentarlo da exactamente lo mismo.

4. **Que sólo el 503 se reintente.** Un 404 y un 422 no mejoran insistiendo.

5. **Que la matriz por país se valide antes de salir a la red.** GEREO
   rechaza igual, pero con un viaje a su base de datos —la misma que atiende
   la pantalla de sus analistas— para decirnos algo que ya sabíamos.
"""
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(_k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import gereo as G  # noqa: E402


def _respuesta(cuerpo):
    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return _R(json.dumps(cuerpo).encode())


def abrir_con(cuerpo):
    visto = {}

    def abrir(req, timeout=None):
        visto["url"] = req.full_url
        visto["headers"] = dict(req.headers)
        visto["cuerpo"] = json.loads(req.data) if req.data else None
        visto["timeout"] = timeout
        return _respuesta(cuerpo)
    abrir.visto = visto
    return abrir


def abrir_error(codigo, cuerpo):
    def abrir(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, codigo, "err", {},
            io.BytesIO(json.dumps(cuerpo).encode()))
    return abrir


class LaClaveNoVaEnElCodigo(unittest.TestCase):

    def test_el_modulo_no_trae_ninguna_clave_escrita(self):
        fuente = Path(G.__file__).read_text(encoding="utf-8")
        self.assertIn("get_secret_value", fuente,
                      "la clave sale de Secrets Manager")
        # Nada con pinta de clave: el repo es público.
        for sospechoso in ("X-API-Key: ", "wt_", "gereo_key ="):
            self.assertNotIn(sospechoso + "e", fuente)

    def test_viaja_en_el_header_y_no_en_la_url(self):
        G._clave_cache = "clave-de-prueba"
        abrir = abrir_con({"estado": "ok"})
        G.salud(abrir=abrir)
        self.assertEqual(abrir.visto["headers"].get("X-api-key"), "clave-de-prueba")
        self.assertNotIn("clave-de-prueba", abrir.visto["url"])

    def test_sin_clave_no_sale_a_la_red(self):
        G._clave_cache = ""
        os.environ.pop("GEREO_API_KEY", None)

        def no_llamar(req, timeout=None):
            raise AssertionError("no tenía que haber salido a la red")
        with self.assertRaises(G.ErrorGereo):
            G.salud(abrir=no_llamar)


class NoSeLogueaLaRespuesta(unittest.TestCase):
    """Un `print` del response completo vive años en CloudWatch."""

    def test_no_se_imprime_el_cuerpo_en_ningun_lado(self):
        fuente = Path(G.__file__).read_text(encoding="utf-8")
        for linea in fuente.splitlines():
            if "print(" not in linea:
                continue
            for prohibido in ("{d}", "{crudo}", "{cuerpo}", "{doc}", "{resp"):
                self.assertNotIn(prohibido, linea,
                                 f"esta línea loguea el cuerpo: {linea.strip()}")


class LaDetencionNoEsUnError(unittest.TestCase):

    def test_un_cliente_de_otro_pais_devuelve_detenido(self):
        G._clave_cache = "k"
        abrir = abrir_con({
            "estado": "DETENIDO_PAIS_NO_CHILE", "es_detencion": True,
            "mensaje": "El país de origen del cliente '9999999' es 'PE'."})
        d = G.generar_ros({"pais": "Chile", "customer_id": "9999999",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                          abrir=abrir)
        self.assertTrue(d["detenido"])
        self.assertIn("PE", d["mensaje"])

    def test_no_levanta_excepcion(self):
        """Si fuera excepción, el tablero lo contaría como falla de la API."""
        G._clave_cache = "k"
        abrir = abrir_con({"estado": "DETENIDO_PAIS_NO_CHILE",
                           "es_detencion": True, "mensaje": "x"})
        G.generar_ros({"pais": "Chile", "customer_id": "1",
                       "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                      abrir=abrir)   # no tiene que tirar


class SoloElQuinientosTresSeReintenta(unittest.TestCase):

    def _error(self, codigo, cuerpo=None):
        G._clave_cache = "k"
        try:
            G.salud(abrir=abrir_error(codigo, cuerpo or {}))
        except G.ErrorGereo as e:
            return e
        raise AssertionError("tenía que fallar")

    def test_el_503_si(self):
        self.assertTrue(self._error(503).reintentable)

    def test_el_404_no(self):
        """«Ese cliente no existe» no mejora insistiendo."""
        self.assertFalse(self._error(404).reintentable)

    def test_el_422_no_y_dice_qué_campo(self):
        e = self._error(422, {"estado": "OPCION_INVALIDA",
                              "campo": "clientes_asociados",
                              "mensaje": "no admite clientes asociados."})
        self.assertFalse(e.reintentable)
        self.assertEqual(e.campo, "clientes_asociados")

    def test_el_401_avisa_que_es_la_clave(self):
        e = self._error(401)
        self.assertIn("clave", e.mensaje.lower())

    def test_un_corte_de_red_si_se_reintenta(self):
        G._clave_cache = "k"

        def cae(req, timeout=None):
            raise TimeoutError("se cortó")
        with self.assertRaises(G.ErrorGereo) as c:
            G.salud(abrir=cae)
        self.assertTrue(c.exception.reintentable)


class LaMatrizPorPaisSeValidaAntes(unittest.TestCase):
    """GEREO lo rechaza igual, pero con un viaje a su base de datos."""

    def base(self, **kw):
        d = {"pais": "Chile", "customer_id": "1", "tipo_cliente": "B2C",
             "fecha_inicio": "01/2025"}
        d.update(kw)
        return d

    def test_argentina_no_admite_b2b(self):
        faltan = G.validar(self.base(pais="Argentina", tipo_cliente="B2B"))
        self.assertTrue(any("B2C" in f for f in faltan))

    def test_argentina_no_admite_asociados(self):
        faltan = G.validar(self.base(pais="Argentina",
                                     clientes_asociados=["2"]))
        self.assertTrue(any("asociados" in f for f in faltan))

    def test_colombia_no_admite_asociados(self):
        faltan = G.validar(self.base(pais="Colombia",
                                     clientes_asociados=["2"]))
        self.assertTrue(any("único cliente" in f for f in faltan))

    def test_chile_admite_hasta_quince(self):
        self.assertEqual(
            G.validar(self.base(clientes_asociados=[str(i) for i in range(15)])),
            [])
        self.assertTrue(
            G.validar(self.base(clientes_asociados=[str(i) for i in range(16)])))

    def test_un_pais_de_fuera_se_rechaza(self):
        self.assertTrue(G.validar(self.base(pais="Perú")))

    def test_la_fecha_tiene_que_ser_mes_y_anio(self):
        self.assertTrue(G.validar(self.base(fecha_inicio="2025-01")))
        self.assertTrue(G.validar(self.base(fecha_inicio="13/2025")))
        self.assertEqual(G.validar(self.base(fecha_inicio="12/2025")), [])

    def test_no_sale_a_la_red_si_el_pedido_esta_mal(self):
        G._clave_cache = "k"

        def no_llamar(req, timeout=None):
            raise AssertionError("no tenía que salir")
        with self.assertRaises(G.ErrorGereo):
            G.generar_ros(self.base(pais="Colombia",
                                    clientes_asociados=["2"]), abrir=no_llamar)


class ElCuerpoQueSeManda(unittest.TestCase):

    def test_natural_y_juridica_se_normalizan(self):
        self.assertEqual(G.normalizar_tipo("natural"), "B2C")
        self.assertEqual(G.normalizar_tipo("juridica"), "B2B")
        self.assertEqual(G.normalizar_tipo("b2b"), "B2B")

    def test_los_campos_opcionales_no_viajan_vacios(self):
        c = G.cuerpo_para({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"})
        self.assertNotIn("fecha_fin", c)
        self.assertNotIn("clientes_asociados", c)
        self.assertNotIn("incluir_pdf", c)

    def test_el_pdf_solo_si_se_pide(self):
        """Armarlo le suma segundos a cada llamada."""
        c = G.cuerpo_para({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025",
                           "incluir_pdf": True})
        self.assertTrue(c["incluir_pdf"])

    def test_los_asociados_aceptan_texto_separado_por_coma(self):
        c = G.cuerpo_para({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025",
                           "clientes_asociados": "2, 3 ,4"})
        self.assertEqual(c["clientes_asociados"], ["2", "3", "4"])

    def test_el_timeout_es_generoso(self):
        """El documento pide 60 s o más: un ROS consulta, evalúa y redacta."""
        self.assertGreaterEqual(G.TIMEOUT_ROS, 60)


class LoQueSeDevuelve(unittest.TestCase):

    RESPUESTA = {
        "estado": "OK",
        "opciones": {"pais": "Chile", "meses": 6},
        "ros_doc": {
            "meta": {"advertencias": ["La 'Temática' queda sin seleccionar."]},
            "reglas": [{"id": "R01", "gatillada": False}],
        },
        "senales": [],
        "pdf_base64": None,
    }

    def test_las_advertencias_suben_al_primer_nivel(self):
        """Es lo que el analista tiene que ver primero, no una nota al pie
        escondida en meta."""
        G._clave_cache = "k"
        d = G.generar_ros({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                          abrir=abrir_con(self.RESPUESTA))
        self.assertEqual(len(d["advertencias"]), 1)
        self.assertIn("Temática", d["advertencias"][0])

    def test_se_guarda_el_eco_de_las_opciones(self):
        """Es el registro de con qué parámetros se emitió, incluido el mes de
        término que GEREO resuelve solo."""
        G._clave_cache = "k"
        d = G.generar_ros({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                          abrir=abrir_con(self.RESPUESTA))
        self.assertEqual(d["opciones"]["meses"], 6)

    def test_senales_y_reglas_son_cosas_distintas(self):
        """`senales` son las gatilladas; `ros_doc.reglas`, todas las
        evaluadas. La diferencia entre «esto disparó» y «esto se miró y no
        disparó» es justo lo que se audita."""
        G._clave_cache = "k"
        d = G.generar_ros({"pais": "Chile", "customer_id": "1",
                           "tipo_cliente": "B2C", "fecha_inicio": "01/2025"},
                          abrir=abrir_con(self.RESPUESTA))
        self.assertEqual(d["senales"], [])
        self.assertEqual(len(d["ros_doc"]["reglas"]), 1)


class ElPaisYElReguladorSonLoMismo(unittest.TestCase):
    """`ros.py` trabaja con reguladores y GEREO con países. Si los dos mapas
    se separan, un ROS de Chile terminaría pidiéndose a la UIF argentina."""

    def test_los_tres_reguladores_de_ros_tienen_pais(self):
        import ros as R
        for codigo in R.REGULADORES:
            self.assertIn(codigo, G.PAIS_POR_REGULADOR,
                          f"{codigo} no tiene país en el cliente de GEREO")

    def test_y_los_paises_coinciden(self):
        import ros as R
        for codigo, pais in G.PAIS_POR_REGULADOR.items():
            self.assertEqual(R.REGULADORES[codigo]["pais"], pais)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── La fase 2: la generación asíncrona ───────────────────────────────────

import api_handler as A  # noqa: E402


class LaGeneracionEsAsincronica(unittest.TestCase):
    """Un ROS tarda decenas de segundos. El API Gateway corta a los 29 y la
    Lambda de la API a los 60: si se llamara ahí, fallaría siempre y el
    analista vería un timeout sin saber si el análisis corrió."""

    def _llamar(self, cuerpo):
        visto = {}
        orig = {n: getattr(A, n) for n in
                ("runs_table", "lambda_client", "_safe_audit")}

        class _Tabla:
            def put_item(self, Item):
                visto["run"] = Item

        class _Lambda:
            def invoke(self, **kw):
                visto["invoke"] = kw
                return {}

        A.runs_table, A.lambda_client = _Tabla(), _Lambda()
        A._safe_audit = lambda **k: visto.setdefault("audit", k)
        try:
            r = A.generar_borrador_ros(cuerpo)
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return r["statusCode"], json.loads(r["body"]), visto

    BUENO = {"pais": "Chile", "customer_id": "2402916", "tipo_cliente": "B2C",
             "fecha_inicio": "01/2025", "actor_email": "ana@global66.com"}

    def test_devuelve_202_y_una_corrida(self):
        codigo, d, visto = self._llamar(dict(self.BUENO))
        self.assertEqual(codigo, 202)
        self.assertTrue(d["run_id"])
        self.assertEqual(visto["run"]["report_name"], "gereo_ros")

    def test_delega_en_la_lambda_larga_y_no_espera(self):
        _, _, visto = self._llamar(dict(self.BUENO))
        self.assertEqual(visto["invoke"]["InvocationType"], "Event")
        carga = json.loads(visto["invoke"]["Payload"])
        self.assertEqual(carga["report_name"], "gereo_ros")
        self.assertEqual(carga["pedido"]["customer_id"], "2402916")

    def test_un_pedido_invalido_no_lanza_nada(self):
        """La matriz por país se valida acá: si no, se gasta una corrida y un
        viaje a la base de GEREO para que nos diga lo que ya sabíamos."""
        malo = dict(self.BUENO, pais="Colombia", clientes_asociados=["9"])
        codigo, d, visto = self._llamar(malo)
        self.assertEqual(codigo, 422)
        self.assertNotIn("invoke", visto, "no tenía que lanzar la corrida")
        self.assertIn("único cliente", d["error"])

    def test_queda_registrado_quien_lo_pidio(self):
        """GEREO anota la llamada como «nuestro sistema»: si detrás hubo una
        persona, la constancia tiene que quedar de este lado."""
        _, _, visto = self._llamar(dict(self.BUENO))
        self.assertEqual(visto["audit"]["user_email"], "ana@global66.com")
        self.assertEqual(visto["audit"]["action"], "gereo.ros.generar")

    def test_el_pedido_que_viaja_ya_viene_normalizado(self):
        _, _, visto = self._llamar(dict(self.BUENO, tipo_cliente="natural"))
        carga = json.loads(visto["invoke"]["Payload"])
        self.assertEqual(carga["pedido"]["tipo_cliente"], "B2C")


class ElBorradorNoSeLogueaNiSeGuardaEnDynamo(unittest.TestCase):
    """El borrador trae nombre, documento, dirección y teléfono de personas
    reales. Va a S3, bajo el mismo estándar que los casos. En DynamoDB —que
    es lo que sondea la pantalla— va sólo el estado y dónde quedó."""

    def _fuente(self):
        return (Path(A.__file__).parent / "handler.py").read_text(encoding="utf-8")

    def test_la_corrida_no_guarda_el_documento(self):
        fuente = self._fuente()
        i = fuente.index("def _gereo_ros(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        self.assertIn("s3.put_object", cuerpo)
        # Lo que va a Dynamo son claves de estado, nunca el documento.
        for prohibido in ("ros_doc=", "documento=", "borrador=d"):
            self.assertNotIn(prohibido, cuerpo)

    def test_el_log_no_imprime_el_documento(self):
        fuente = self._fuente()
        i = fuente.index("def _gereo_ros(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        for linea in cuerpo.splitlines():
            if "logger." not in linea:
                continue
            for prohibido in ("%s\", d", "d)", "{d}", "ros_doc"):
                if prohibido == "d)" and "d.get(" in linea:
                    continue
                self.assertNotIn(prohibido, linea,
                                 f"esta línea loguea el documento: {linea.strip()}")

    def test_una_detencion_termina_en_done_y_no_en_error(self):
        """Contarla como fallida llenaría el tablero de errores que son la
        regla de negocio funcionando."""
        fuente = self._fuente()
        i = fuente.index("def _gereo_ros(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        # El único ERROR es el de `ErrorGereo`; la detención sigue de largo.
        self.assertEqual(cuerpo.count('status="ERROR"'), 1)
        j = cuerpo.index('status="ERROR"')
        self.assertIn("except gereo.ErrorGereo", cuerpo[:j])


# ── La fase 5: proteger el backend de GEREO ──────────────────────────────

class NoSeLeCaeEncimaAGereo(unittest.TestCase):
    """«El mismo backend atiende la pantalla de los analistas; un loop sin
    freno se la degrada», dice el documento. Un ROS consulta la base, evalúa
    reglas y redacta: dos o tres en paralelo ya se sienten del otro lado."""

    def _con_corridas(self, items, por_pagina=1):
        visto = {}

        class _Tabla:
            # PAGINA, como la tabla real. Un `scan` de DynamoDB lee hasta 1 MB
            # y deja el resto en `LastEvaluatedKey`; la tabla de corridas ya
            # pasa de 1 MB. El doble que devolvía todo de una vez daba los
            # tests en verde con el tope roto en producción: tres corridas
            # simultáneas pasaron las tres. Una página por ítem, para que
            # cualquier versión que no pagine cuente de menos.
            def scan(self, **kw):
                visto["paginas"] = visto.get("paginas", 0) + 1
                desde = int((kw.get("ExclusiveStartKey") or {}).get("i", 0))
                trozo = items[desde:desde + por_pagina]
                fuera = {"Items": trozo}
                if desde + por_pagina < len(items):
                    fuera["LastEvaluatedKey"] = {"i": desde + por_pagina}
                return fuera

            def put_item(self, Item):
                visto["run"] = Item

        class _Lambda:
            def invoke(self, **kw):
                visto["invoke"] = kw
                return {}

        orig = {n: getattr(A, n) for n in
                ("runs_table", "lambda_client", "_safe_audit")}
        A.runs_table, A.lambda_client = _Tabla(), _Lambda()
        A._safe_audit = lambda **k: None
        try:
            r = A.generar_borrador_ros(
                {"pais": "Chile", "customer_id": "1", "tipo_cliente": "B2C",
                 "fecha_inicio": "01/2025"})
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return r["statusCode"], json.loads(r["body"]), visto

    def _hace(self, minutos):
        import datetime as _dt
        return (_dt.datetime.utcnow() - _dt.timedelta(minutes=minutos)).isoformat()

    def test_con_el_tope_lleno_no_lanza_otra(self):
        items = [{"run_id": str(i), "started_at": self._hace(2)}
                 for i in range(A.GEREO_MAX_EN_CURSO)]
        codigo, d, visto = self._con_corridas(items)
        self.assertEqual(codigo, 429)
        self.assertNotIn("invoke", visto, "no tenía que lanzar la corrida")
        self.assertEqual(d["en_curso"], A.GEREO_MAX_EN_CURSO)

    def test_por_debajo_del_tope_sí(self):
        codigo, _, visto = self._con_corridas(
            [{"run_id": "1", "started_at": self._hace(2)}])
        self.assertEqual(codigo, 202)
        self.assertIn("invoke", visto)

    def test_una_corrida_muerta_no_bloquea_para_siempre(self):
        """`RUNNING` se escribe ANTES de empezar a trabajar: si la Lambda
        muere, nadie escribe DONE ni ERROR y la corrida queda con cara de
        estar avanzando. Sin la ventana, dos corridas muertas dejarían el
        módulo trabado sin que nadie entienda por qué."""
        viejas = [{"run_id": str(i), "started_at": self._hace(600)}
                  for i in range(A.GEREO_MAX_EN_CURSO + 3)]
        codigo, _, visto = self._con_corridas(viejas)
        self.assertEqual(codigo, 202)
        self.assertIn("invoke", visto)

    def test_cuenta_las_corridas_que_quedaron_en_otra_página(self):
        """La regresión. Las corridas en curso no están todas en la primera
        página del `scan`: con la tabla real caen donde las ponga el hash de
        la clave. Contar sólo la primera dejaba pasar todo."""
        relleno = [{"run_id": f"otro-{i}", "started_at": self._hace(600)}
                   for i in range(40)]
        en_curso = [{"run_id": str(i), "started_at": self._hace(2)}
                    for i in range(A.GEREO_MAX_EN_CURSO)]
        codigo, d, visto = self._con_corridas(relleno + en_curso, por_pagina=10)
        self.assertEqual(codigo, 429, "el tope no vio las corridas del final")
        self.assertNotIn("invoke", visto)

    def test_deja_de_leer_apenas_llega_al_tope(self):
        """Seguir recorriendo la tabla para afinar un número que ya no cambia
        la decisión es gasto en cada POST."""
        items = [{"run_id": str(i), "started_at": self._hace(2)}
                 for i in range(500)]
        _, _, visto = self._con_corridas(items, por_pagina=1)
        self.assertLessEqual(visto["paginas"], A.GEREO_MAX_EN_CURSO)

    def test_una_tabla_que_no_termina_nunca_no_cuelga_el_post(self):
        class _Infinita:
            def scan(self, **kw):
                return {"Items": [], "LastEvaluatedKey": {"i": 1}}
        orig = A.runs_table
        A.runs_table = _Infinita()
        try:
            self.assertEqual(A._gereo_en_curso(), 0)
        finally:
            A.runs_table = orig

    def test_si_no_se_puede_contar_se_deja_pasar(self):
        """Bloquear por no poder mirar sería peor que dejar correr una de
        más: nadie podría generar un ROS por un problema de la tabla."""
        class _Rota:
            def scan(self, **kw):
                raise RuntimeError("DynamoDB caído")
        orig = A.runs_table
        A.runs_table = _Rota()
        try:
            self.assertEqual(A._gereo_en_curso(), 0)
        finally:
            A.runs_table = orig


class SoloElQuinientosTresSeReintentaEnLaLambdaLarga(unittest.TestCase):

    def _cuerpo(self):
        fuente = (Path(A.__file__).parent / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def _gereo_ros(")
        return fuente[i:fuente.index("\ndef ", i + 10)]

    def test_hay_reintento_con_esperas_crecientes(self):
        cuerpo = self._cuerpo()
        self.assertIn("ESPERAS", cuerpo)
        self.assertIn("time.sleep", cuerpo)

    def test_lo_que_no_es_reintentable_corta_al_primer_intento(self):
        """Un 404 y un 422 no mejoran insistiendo, y reintentarlos esconde el
        error real detrás de tres intentos."""
        cuerpo = self._cuerpo()
        self.assertIn("if not e.reintentable:", cuerpo)
        i = cuerpo.index("if not e.reintentable:")
        self.assertIn("break", cuerpo[i:i + 120])

    def test_las_esperas_caben_en_el_tiempo_de_la_lambda(self):
        """Si la suma pasara los 900 s, el último reintento moriría por
        timeout y la corrida quedaría en RUNNING para siempre."""
        import re
        m = re.search(r"ESPERAS = \(([^)]*)\)", self._cuerpo())
        esperas = [int(x) for x in m.group(1).replace(" ", "").split(",") if x]
        # 90 s de timeout por intento, más las esperas entre ellos.
        self.assertLess(sum(esperas) + 90 * (len(esperas) + 1), 900)
