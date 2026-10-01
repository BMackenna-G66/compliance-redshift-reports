# -*- coding: utf-8 -*-
"""Del borrador de GEREO al ROS de WatchTower.

LO QUE VIGILA ESTE ARCHIVO, y el primero es el que importa:

1. **El texto de GEREO no llega nunca al campo que firma el oficial.**
   `ros.py` existe con la regla de que la narrativa la escribe una persona —
   «un texto generado que alguien firma sin leer es exactamente el accidente
   que hay que evitar»—. Conectar un generador es justo el cambio que puede
   romper eso sin que nada falle: el ROS quedaría igual de completo, sólo que
   firmado por alguien que no lo escribió.

2. **Un campo ausente significa «no corresponde».** GEREO no manda los campos
   cuya condición no se cumple. Rellenarlos con vacío los convertiría en un
   dato que dice algo falso: «no es PEP» cuando en realidad es «no se
   preguntó».

3. **Gatilladas y descartadas son cosas distintas.** Un ROS que no dice qué
   se descartó no permite reconstruir el análisis, que es exactamente para lo
   que lo pide un regulador.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import ros as R  # noqa: E402
import ros_gereo as RG  # noqa: E402

RESPUESTA_CHILE = {
    "estado": "OK",
    "opciones": {"pais": "Chile", "customer_id": "2402916", "meses": 6},
    "advertencias": ["La 'Temática' queda sin seleccionar."],
    "senales": [],
    "ros_doc": {
        "meta": {"customer_id": "2402916", "generado_en": "22/09/2026 14:56",
                 "advertencias": ["La 'Temática' queda sin seleccionar."],
                 "generado_con_ia": False},
        "1_antecedentes_operaciones_sospechosas": {
            "tipo_reporte": "", "monto": "",
            "1_descripcion_hechos_orden_cronologico": "Durante el período…",
            "2_que_se_considero_sospechoso": "Del análisis de las operaciones…",
        },
        "2_identificacion_reportados": {"nombre_o_razon_social": "JUAN CARLOS"},
        "reglas": [
            {"id": "R01", "titulo": "Múltiples beneficiarios", "gatillada": False,
             "detalle": "Ningún mes alcanza 5 beneficiarios."},
            {"id": "R02", "titulo": "Fraccionamiento", "gatillada": True},
        ],
    },
}


class LaNarrativaDeGereoNoSeFirmaSola(unittest.TestCase):
    """La regla que sostiene todo el módulo."""

    def test_el_borrador_no_toca_el_campo_narrativa(self):
        b = RG.armar_borrador(RESPUESTA_CHILE, "run-1")
        caso = {"case_id": "C1", "entity_id": "2402916"}
        reporte = R.crear(
            {"case_id": "C1", "regulador": "UAF-CL", "creado_por": "ana@x.com",
             "borrador_gereo": b, "origen": "gereo"},
            caso, [], [])
        self.assertEqual(reporte["narrativa"], "",
                         "el texto de GEREO se filtró al campo que firma el "
                         "oficial de cumplimiento")
        self.assertTrue(reporte["borrador_gereo"]["narrativa_borrador"])

    def test_el_texto_de_gereo_queda_etiquetado_y_separado(self):
        """Dos respuestas a dos preguntas distintas del formulario. Pegarlas
        invita a copiarlas juntas a un campo que pide una."""
        n = RG.narrativa_borrador(RESPUESTA_CHILE["ros_doc"], "Chile")
        self.assertEqual(len(n), 2)
        self.assertEqual(n[0]["titulo"], "Descripción de los hechos")
        self.assertEqual(n[1]["titulo"], "Qué se consideró sospechoso")

    def test_un_ros_sin_narrativa_sigue_sin_poder_enviarse(self):
        """El control de `ros.py` no se ablanda porque ahora haya un borrador:
        tener un texto sugerido no es haberlo escrito."""
        b = RG.armar_borrador(RESPUESTA_CHILE, "run-1")
        reporte = R.crear(
            {"case_id": "C1", "regulador": "UAF-CL", "creado_por": "ana@x.com",
             "borrador_gereo": b},
            {"case_id": "C1"}, [], [])
        reporte = R.cambiar_estado(reporte, "revision_legal", "ana@x.com")
        with self.assertRaises(ValueError) as c:
            R.cambiar_estado(reporte, "enviado", "jefa@x.com")
        self.assertIn("narrativa", str(c.exception))


# Las dos respuestas que faltaban: mismo armado que la de Chile, con la forma
# que devuelve la API para esos países. Datos inventados.
RESPUESTA_ARGENTINA = {
    "estado": "OK",
    "opciones": {"pais": "Argentina", "customer_id": "9000001", "meses": 6},
    "advertencias": [],
    "senales": [],
    "ros_doc": {
        "meta": {"customer_id": "9000001", "generado_en": "01/10/2026 10:00",
                 "generado_con_ia": True},
        "1_datos_directos_ros": {"conoce_delito_precedente": "NO",
                                 "exteriorizacion_voluntaria": "NO"},
        "3_persona_fisica": {"aplica": True, "nombre": "NOMBRE DE PRUEBA"},
        "4_operaciones_y_productos": {
            "monto_pesos": "1000000",
            "descripcion_operatoria": "Durante el período analizado…",
            "descripcion_analisis": "Del análisis de las operaciones…",
            "conclusiones": "",
        },
        "reglas": [{"id": "R01", "titulo": "Fraccionamiento", "gatillada": True}],
    },
}

RESPUESTA_COLOMBIA = {
    "estado": "OK",
    "opciones": {"pais": "Colombia", "customer_id": "9000002", "meses": 6},
    "advertencias": [],
    "senales": [],
    "ros_doc": {
        "meta": {"customer_id": "9000002", "generado_en": "01/10/2026 10:00",
                 "generado_con_ia": True},
        "1_informacion_general_reporte": {"clase_reporte": "ROS"},
        "2_persona_juridica": {"aplica": False, "mensaje": "No aplica."},
        "3_persona_natural": {"aplica": True, "nombres": "NOMBRE DE PRUEBA"},
        "4_detalle": {"moneda": "COP",
                      "descripcion": "El cliente registra operaciones…"},
        "reglas": [{"id": "R01", "titulo": "Fraccionamiento", "gatillada": True}],
    },
}


class LaNarrativaNoEstaEnElMismoLugarEnLosTresPaises(unittest.TestCase):
    """La primera corrida real contra GEREO encontró esto.

    El mapeo buscaba los dos campos de Chile dentro de la sección de apertura
    de cada país. En Chile está ahí; en Argentina y Colombia la narrativa vive
    en la última sección y con otros nombres, así que el borrador llegaba a la
    pantalla con cero bloques de texto —sin el aviso de que era un borrador y
    sin el botón para copiarlo— mientras el texto seguía adentro del JSON.
    """

    def test_argentina_la_encuentra_en_operaciones_y_productos(self):
        n = RG.narrativa_borrador(RESPUESTA_ARGENTINA["ros_doc"], "Argentina")
        self.assertEqual([x["titulo"] for x in n],
                         ["Descripción de la operatoria", "Análisis de la operatoria"])

    def test_colombia_la_encuentra_en_detalle(self):
        n = RG.narrativa_borrador(RESPUESTA_COLOMBIA["ros_doc"], "Colombia")
        self.assertEqual([x["titulo"] for x in n], ["Descripción de la operación"])

    def test_chile_sigue_igual(self):
        n = RG.narrativa_borrador(RESPUESTA_CHILE["ros_doc"], "Chile")
        self.assertEqual(len(n), 2)

    def test_un_campo_de_narrativa_vacío_no_se_dibuja(self):
        """`conclusiones` viene vacío: GEREO lo deja al analista. Un título con
        nada abajo se lee como «GEREO no supo qué poner»."""
        n = RG.narrativa_borrador(RESPUESTA_ARGENTINA["ros_doc"], "Argentina")
        self.assertNotIn("Conclusiones", [x["titulo"] for x in n])

    def test_los_tres_países_tienen_mapeo_de_narrativa(self):
        """Un país en SECCIONES sin entrada acá vuelve a dar cero bloques."""
        self.assertEqual(set(RG.NARRATIVA), set(RG.SECCIONES))
        for pais, (seccion, campos) in RG.NARRATIVA.items():
            self.assertIn(seccion, [c for c, _ in RG.SECCIONES[pais]],
                          f"{pais}: la narrativa apunta a una sección que no existe")
            self.assertTrue(campos)


class ElAvisoDeIANoDependeDeQueGereoLoMande(unittest.TestCase):
    """GEREO manda `generado_con_ia: true` en los tres países, pero el texto de
    advertencia sólo en Chile. Es la advertencia que impide que alguien firme
    texto generado sin leerlo, así que la derivamos del flag."""

    def test_argentina_lo_recibe_aunque_gereo_no_lo_mande(self):
        b = RG.armar_borrador(RESPUESTA_ARGENTINA, "run-ar")
        self.assertTrue(any("IA" in a for a in b["advertencias"]))

    def test_y_frena_el_envío(self):
        b = RG.armar_borrador(RESPUESTA_COLOMBIA, "run-co")
        self.assertTrue(any("IA" in f for f in RG.listo_para_enviar(b)))

    def test_no_se_dice_dos_veces_cuando_gereo_ya_lo_dijo(self):
        r = dict(RESPUESTA_CHILE)
        r["advertencias"] = [RG.AVISO_IA]
        r["ros_doc"] = dict(RESPUESTA_CHILE["ros_doc"],
                            meta={"generado_con_ia": True})
        b = RG.armar_borrador(r, "run-cl")
        self.assertEqual(sum("IA" in a for a in b["advertencias"]), 1)

    def test_sin_ia_no_se_inventa_la_advertencia(self):
        b = RG.armar_borrador(RESPUESTA_CHILE, "run-1")   # generado_con_ia: False
        self.assertFalse(any("IA" in a for a in b["advertencias"]))

    def test_una_advertencia_con_la_palabra_transferencia_no_cuenta_como_aviso(self):
        """El de-duplicado busca «IA» como palabra, no como pedazo de otra."""
        r = dict(RESPUESTA_ARGENTINA)
        r["advertencias"] = ["Revisar la transferencia de mayor monto."]
        b = RG.armar_borrador(r, "run-ar")
        self.assertIn(RG.AVISO_IA, b["advertencias"])


class UnCampoAusenteSignificaNoCorresponde(unittest.TestCase):

    def test_una_seccion_que_no_vino_no_se_dibuja_vacia(self):
        doc = {"1_informacion_general_reporte": {"x": 1}}
        s = RG.secciones_de(doc, "Colombia")
        self.assertEqual([x["clave"] for x in s], ["1_informacion_general_reporte"])

    def test_en_argentina_las_dos_secciones_de_persona_son_excluyentes(self):
        """Viene la que corresponde al cliente; la otra no viaja."""
        doc = {"3_persona_fisica": {"nombre": "X"}}
        s = RG.secciones_de(doc, "Argentina")
        claves = [x["clave"] for x in s]
        self.assertIn("3_persona_fisica", claves)
        self.assertNotIn("3_persona_fisica_extranjera", claves)

    def test_sin_delito_precedente_esa_sección_no_viaja(self):
        """`conoce_delito_precedente: NO` ⇒ GEREO omite la sección 2 entera.
        Verificado contra la respuesta real: no es un hueco del mapeo."""
        s = RG.secciones_de(RESPUESTA_ARGENTINA["ros_doc"], "Argentina")
        self.assertNotIn("2_delito_precedente", [x["clave"] for x in s])
        self.assertEqual(
            RESPUESTA_ARGENTINA["ros_doc"]["1_datos_directos_ros"]
            ["conoce_delito_precedente"], "NO")

    def test_no_se_rellena_con_vacio(self):
        """Un campo vacío diría «no es PEP» donde el dato es «no se preguntó»."""
        s = RG.secciones_de({"1_datos_directos_ros": {}}, "Argentina")
        self.assertEqual(s, [])

    def test_las_secciones_van_en_el_orden_del_formulario(self):
        doc = {c: {"x": 1} for c, _ in RG.SECCIONES["Colombia"]}
        s = RG.secciones_de(doc, "Colombia")
        self.assertEqual([x["clave"] for x in s],
                         [c for c, _ in RG.SECCIONES["Colombia"]])

    def test_cada_seccion_trae_el_nombre_del_formulario(self):
        """El regulador cita por número y nombre de sección; mostrar la clave
        cruda obligaría a traducirla a mano."""
        s = RG.secciones_de(RESPUESTA_CHILE["ros_doc"], "Chile")
        self.assertEqual(s[0]["titulo"],
                         "Antecedentes de las operaciones sospechosas")


class GatilladasYDescartadasSonDistintas(unittest.TestCase):

    def test_se_separan(self):
        r = RG.reglas_de(RESPUESTA_CHILE["ros_doc"])
        self.assertEqual(len(r["gatilladas"]), 1)
        self.assertEqual(len(r["descartadas"]), 1)
        self.assertEqual(r["total_evaluadas"], 2)

    def test_lo_descartado_se_guarda_con_su_motivo(self):
        """«Se miró y no disparó» es parte del análisis que hay que poder
        reconstruir, no ruido que se tira."""
        r = RG.reglas_de(RESPUESTA_CHILE["ros_doc"])
        self.assertIn("Ningún mes", r["descartadas"][0]["detalle"])


class LoQueFaltaAntesDeEnviar(unittest.TestCase):

    def test_sin_senales_gatilladas_lo_dice(self):
        b = RG.armar_borrador(RESPUESTA_CHILE, "run-1")
        faltan = RG.listo_para_enviar(b)
        self.assertTrue(any("al menos una" in f for f in faltan))

    def test_las_advertencias_de_gereo_viajan_al_control(self):
        """La API avisa que el reporte sale incompleto a propósito; sin esto
        ese aviso queda en un texto que nadie relee al momento de enviar."""
        b = RG.armar_borrador(RESPUESTA_CHILE, "run-1")
        faltan = RG.listo_para_enviar(b)
        self.assertTrue(any("Temática" in f for f in faltan))


class ElOrigenQuedaRegistrado(unittest.TestCase):
    """`ros.py` dejó `origen` y `externo_id` esperando exactamente esto."""

    def test_el_identificador_dice_de_dónde_salió(self):
        i = RG.identificador(RESPUESTA_CHILE, "run-12345678")
        self.assertTrue(i.startswith("gereo:"))
        self.assertIn("2402916", i)

    def test_un_ros_de_gereo_se_distingue_de_uno_de_acá(self):
        b = RG.armar_borrador(RESPUESTA_CHILE, "run-1")
        de_gereo = R.crear({"case_id": "C1", "regulador": "UAF-CL",
                            "creado_por": "ana@x.com", "origen": "gereo",
                            "externo_id": RG.identificador(RESPUESTA_CHILE, "run-1"),
                            "borrador_gereo": b}, {"case_id": "C1"}, [], [])
        de_aca = R.crear({"case_id": "C2", "regulador": "UAF-CL",
                          "creado_por": "ana@x.com"}, {"case_id": "C2"}, [], [])
        self.assertEqual(de_gereo["origen"], "gereo")
        self.assertEqual(de_aca["origen"], "watchtower")
        self.assertEqual(de_aca["externo_id"], "")
        self.assertIsNone(de_aca["borrador_gereo"])

    def test_se_guarda_con_qué_parámetros_se_emitió(self):
        """El eco de `opciones` incluye el mes de término que GEREO resuelve
        solo: sin eso hay que reconstruir con qué período se pidió."""
        b = RG.armar_borrador(RESPUESTA_CHILE, "run-1")
        self.assertEqual(b["opciones"]["meses"], 6)


class LosPaisesCoincidenConLosReguladores(unittest.TestCase):
    """Si los mapas se separan, un ROS de Chile se armaría con las secciones
    del formulario argentino."""

    def test_cada_regulador_tiene_secciones(self):
        import gereo as G
        for codigo, pais in G.PAIS_POR_REGULADOR.items():
            self.assertIn(pais, RG.SECCIONES,
                          f"{codigo} ({pais}) no tiene secciones declaradas")

    def test_y_no_sobra_ninguno(self):
        import gereo as G
        self.assertEqual(set(RG.SECCIONES), set(G.PAISES))


if __name__ == "__main__":
    unittest.main(verbosity=2)
