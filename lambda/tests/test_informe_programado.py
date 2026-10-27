# -*- coding: utf-8 -*-
"""Las reglas de la corrida programada del informe de alertas.

Lo que se prueba acá es la decisión —a quién, si sale, y cuándo hay que
gritar—, no el armado del informe, que ya tiene sus propias pruebas.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import informe_programado as IP


# ── limpiar ─────────────────────────────────────────────────────────────────

def test_limpia_normaliza_y_saca_repetidos():
    assert IP.limpiar([" Ana@Global66.com ", "ana@global66.com", "", None,
                       "beto@global66.com"]) == ["ana@global66.com",
                                                 "beto@global66.com"]


def test_limpia_conserva_el_orden():
    # El orden es el del campo «Para» del correo: una lista que se reordena
    # sola cada semana se lee como si hubiera cambiado algo.
    assert IP.limpiar(["z@global66.com", "a@global66.com"]) == [
        "z@global66.com", "a@global66.com"]


def test_limpia_acepta_un_string_suelto():
    assert IP.limpiar("uno@global66.com") == ["uno@global66.com"]


def test_limpia_lo_que_no_es_lista_no_explota():
    assert IP.limpiar(None) == []
    assert IP.limpiar({}) == []


# ── plan: de dónde salen los destinatarios ──────────────────────────────────

def test_LA_CONFIG_DE_S3_LE_GANA_AL_HORARIO():
    # Es el punto de todo el diseño: cambiar la lista sin tocar el horario ni
    # redesplegar. Si esto se da vuelta, cambiar de equipo obliga a recrear el
    # horario, que es justo lo que nadie se acuerda de hacer.
    p = IP.plan({"para": ["nuevo@global66.com"]},
                {"para": ["viejo@global66.com"]})
    assert p["enviar"] is True
    assert p["para"] == ["nuevo@global66.com"]
    assert p["origen"] == "config"


def test_SIN_CONFIG_SALE_IGUAL_CON_LA_LISTA_DEL_HORARIO():
    # El salvavidas: que S3 no tenga el objeto no puede dejar al equipo sin
    # informe un lunes.
    p = IP.plan({}, {"para": ["kyt@global66.com"]})
    assert p["enviar"] is True
    assert p["para"] == ["kyt@global66.com"]
    assert p["origen"] == "horario"


def test_una_config_con_lista_vacia_cae_al_horario_y_NO_apaga():
    # "Se me borró la lista" y "no quiero que salga" no pueden terminar igual.
    p = IP.plan({"para": []}, {"para": ["kyt@global66.com"]})
    assert p["enviar"] is True
    assert p["origen"] == "horario"


def test_APAGADO_EXPLICITO_NO_MANDA_Y_NO_ES_FALLA():
    p = IP.plan({"activo": False}, {"para": ["kyt@global66.com"]})
    assert p["enviar"] is False
    assert p["para"] == []
    # El origen `config` es lo que el handler mira para NO disparar el aviso:
    # alguien lo apagó a propósito.
    assert p["origen"] == "config"
    assert "apagado" in p["motivo"]


def test_el_apagado_le_gana_hasta_a_su_propia_lista():
    p = IP.plan({"activo": False, "para": ["kyt@global66.com"]}, {})
    assert p["enviar"] is False


def test_activo_true_no_cambia_nada():
    p = IP.plan({"activo": True, "para": ["kyt@global66.com"]}, {})
    assert p["enviar"] is True and p["origen"] == "config"


def test_SIN_NADIE_A_QUIEN_MANDARLE_ES_FALLA_NO_APAGADO():
    # Origen vacío ⇒ el handler avisa. Llegar acá significa que el horario
    # perdió su lista, y eso hay que saberlo.
    p = IP.plan({}, {})
    assert p["enviar"] is False
    assert p["origen"] == ""
    assert "destinatarios" in p["motivo"]


def test_plan_tolera_basura_en_lugar_de_diccionarios():
    p = IP.plan(None, None)
    assert p["enviar"] is False
    p2 = IP.plan("roto", ["tambien roto"])
    assert p2["enviar"] is False


# ── cuerpo ──────────────────────────────────────────────────────────────────

def test_el_actor_de_la_auditoria_no_es_una_persona():
    # Nadie apretó nada: atribuirle el envío al último que tocó el horario
    # sería firmarle algo que no hizo.
    body = IP.cuerpo({"para": ["kyt@global66.com"]}, {})
    assert body["actor_email"] == "sistema:programado"
    assert body["para"] == ["kyt@global66.com"]


def test_los_filtros_del_horario_viajan_al_informe():
    body = IP.cuerpo({"para": ["a@global66.com"]},
                     {"regla": "PEP", "persona": "ana", "desde": "2026-10-01"})
    assert body["regla"] == "PEP"
    assert body["persona"] == "ana"
    assert body["desde"] == "2026-10-01"


def test_los_filtros_vacios_no_viajan():
    # Un `regla: ""` no es lo mismo que no mandar `regla`: el informe filtra
    # por string y un vacío de más cambia lo que sale.
    body = IP.cuerpo({"para": ["a@global66.com"]}, {"regla": "  ", "hasta": ""})
    assert "regla" not in body and "hasta" not in body


# ── leer_respuesta ──────────────────────────────────────────────────────────

def test_lee_la_respuesta_de_api_gateway():
    codigo, datos = IP.leer_respuesta(
        {"statusCode": 200, "body": json.dumps({"enviado": True, "alertas": 7})})
    assert codigo == 200 and datos["alertas"] == 7


def test_lee_un_body_que_ya_es_diccionario():
    codigo, datos = IP.leer_respuesta({"statusCode": 500, "body": {"error": "x"}})
    assert codigo == 500 and datos["error"] == "x"


def test_una_respuesta_rota_no_explota():
    assert IP.leer_respuesta(None) == (0, {})
    assert IP.leer_respuesta({"statusCode": "doscientos", "body": "{{"}) == (0, {})


# ── falla: el 200 que no mandó nada ─────────────────────────────────────────

def test_UN_200_CON_ENVIADO_FALSE_ES_UNA_FALLA():
    # ÉSTE es el modo de falla que importa: respuesta bien formada, correo que
    # no llegó a nadie. Es lo que dejó la escucha de respuestas ocho días
    # muerta sin que nadie lo notara.
    motivo = IP.falla(200, {"enviado": False, "aviso": "SMTP 535"})
    assert motivo
    assert "SMTP 535" in motivo


def test_un_200_enviado_no_avisa():
    assert IP.falla(200, {"enviado": True}) == ""


def test_un_codigo_distinto_de_200_es_falla_con_su_detalle():
    motivo = IP.falla(400, {"error": "El informe sólo se manda a correos @global66.com"})
    assert "400" in motivo
    assert "@global66.com" in motivo


def test_un_503_del_modulo_que_no_viajo_tambien_avisa():
    assert IP.falla(503, {"error": "api_handler no importable"})


def test_falla_tolera_datos_vacios():
    assert IP.falla(500, None)
    assert IP.falla(0, {})


# ── el contrato con el resto del sistema ────────────────────────────────────

def test_la_clave_de_config_vive_donde_la_otra_config_editable():
    # `config/auto_case_rules.json` ya vive ahí. Dos lugares distintos para
    # "configuración que se edita sin desplegar" es uno de más.
    assert IP.CLAVE_CONFIG.startswith("config/")


def test_el_handler_tiene_la_rama_y_el_build_se_lleva_el_modulo():
    # Un módulo que no viaja en el zip es una rama que devuelve 503 el lunes a
    # las nueve. `test_paquete.py` caza el `cp` olvidado; esto caza el otro
    # lado: que la rama exista y se llame como el horario la invoca.
    raiz = os.path.join(os.path.dirname(__file__), "..", "..")
    with open(os.path.join(raiz, "lambda", "handler.py"), encoding="utf-8") as f:
        handler = f.read()
    assert 'report_name == "informe_alertas"' in handler
    with open(os.path.join(raiz, "build_lambda.sh"), encoding="utf-8") as f:
        assert "informe_programado.py" in f.read()


def _handler_fuente():
    raiz = os.path.join(os.path.dirname(__file__), "..", "..")
    with open(os.path.join(raiz, "lambda", "handler.py"), encoding="utf-8") as f:
        return f.read()


def test_LA_FALLA_DEL_INFORME_AVISA_POR_SLACK():
    # El pedido era explícito: que una falla no se quede en el log. Las tres
    # llamadas del camino programado pasan por `_avisar_falla`.
    fuente = _handler_fuente()
    i = fuente.index("def _informe_alertas_programado(")
    cuerpo = fuente[i:i + 3000]
    assert cuerpo.count("_avisar_falla(") == 3


def test_EL_AVISO_DICE_QUE_EL_CORREO_NO_SALIO_NO_QUE_NO_ENTRO():
    # Los tres procesos que ya usaban el aviso LEEN correo; éste MANDA. Un
    # aviso que dice "ese correo no entra al sistema" cuando lo que pasó es
    # que no salió manda a buscar el problema al lado equivocado.
    fuente = _handler_fuente()
    i = fuente.index("def _informe_alertas_programado(")
    cuerpo = fuente[i:i + 3000]
    assert cuerpo.count("consecuencia=SIN_INFORME") == 3
    assert "sin el informe" in fuente[fuente.index("SIN_INFORME = ("):][:300]


def test_el_aviso_por_defecto_sigue_siendo_el_de_los_que_leen():
    # Agregar el parámetro no puede cambiar lo que ven los otros tres.
    fuente = _handler_fuente()
    assert "consecuencia: str = CONSECUENCIA_ENTRADA" in fuente
    assert "NO entra al sistema" in fuente


def test_APAGARLO_A_MANO_NO_DISPARA_EL_AVISO():
    # Si apagar el informe gritara, nadie lo apagaría — lo borrarían, y
    # entonces volver a prenderlo deja de ser un cambio de una línea.
    fuente = _handler_fuente()
    i = fuente.index("def _informe_alertas_programado(")
    cuerpo = fuente[i:i + 3000]
    assert "if not apagado:" in cuerpo


def test_el_horario_del_script_es_lunes_a_las_nueve_de_chile():
    # Una regla cron común sólo entiende UTC y Chile cambia de huso dos veces
    # al año: sin la zona, el informe llega a las 8 o a las 10 según el mes.
    raiz = os.path.join(os.path.dirname(__file__), "..", "..")
    with open(os.path.join(raiz, "horario_informe_alertas.sh"), encoding="utf-8") as f:
        script = f.read()
    assert "cron(0 9 ? * MON *)" in script
    assert "America/Santiago" in script
    assert "--schedule-expression-timezone" in script
    assert '"report_name\\":\\"informe_alertas' in script


def test_EL_SCRIPT_NO_LLEVA_LA_LISTA_DEL_EQUIPO():
    # Este repositorio es PÚBLICO y la lista es de personas. Vive en
    # config/informe_alertas.json, en el bucket, que es privado. Acá se cuenta
    # cuántas direcciones hay escritas: la única admitida es la de quien corre
    # la prueba, que ya figura en el repo como default de GMAIL_USER.
    import re
    raiz = os.path.join(os.path.dirname(__file__), "..", "..")
    with open(os.path.join(raiz, "horario_informe_alertas.sh"), encoding="utf-8") as f:
        script = f.read()
    correos = set(re.findall(r"[\w.+-]+@global66\.com", script))
    # `uno@` y `otro@` son los de los ejemplos de uso; no son de nadie.
    reales = correos - {"uno@global66.com", "otro@global66.com",
                        "benjamin.mackenna@global66.com"}
    assert not reales, f"direcciones de personas en un repo público: {reales}"
