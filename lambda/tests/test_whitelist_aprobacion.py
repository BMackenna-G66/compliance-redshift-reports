# -*- coding: utf-8 -*-
"""Que silenciar a un cliente necesite dos personas, y desde cuándo cuenta.

El control entero es: no aplica hasta que lo apruebe un Oficial que no sea el
que lo pidió. Cada prueba de acá es una forma de romperlo.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import whitelist_aprobacion as W

OFICIALES = ["oficial@global66.com", "otra.oficial@global66.com"]
AHORA = dt.datetime(2026, 10, 27, 12, 0, 0)
TS = int(AHORA.timestamp())


def pendiente(**extra):
    e = {"whitelist_id": "w1", "entity_field": "customer_id",
         "entity_value": "123", "duration_days": 90, "scope": "global",
         "estado": "pendiente", "solicitado_por": "analista@global66.com"}
    e.update(extra)
    return e


# ── estado_de ───────────────────────────────────────────────────────────────

def test_sin_estado_Y_ANTERIOR_AL_CORTE_es_heredada():
    # Las que ya estaban no tienen el campo, pero sí fecha anterior al corte.
    assert W.estado_de({"whitelist_id": "vieja",
                        "created_at": "2026-08-04 13:51:51"}) == "heredada"


def test_SIN_ESTADO_Y_POSTERIOR_AL_CORTE_NO_APLICA():
    """El agujero que esto cierra.

    Mientras «sin estado» significaba «heredada» a secas, cualquier camino que
    escribiera una entrada sin pasar por el control —la migración desde
    Redshift, una carga a mano en S3, un cliente de la API desactualizado—
    silenciaba un cliente sin que nadie firmara. Por la puerta de atrás, pero
    silenciaba igual.
    """
    nueva = {"whitelist_id": "colada", "created_at": "2026-11-01 10:00:00",
             "expires_at": 9999999999}
    assert W.estado_de(nueva) == "desconocida"
    assert W.aplica(nueva, 1800000000) is False


def test_SIN_FECHA_LEGIBLE_NO_HAY_HERENCIA():
    """Falla cerrado: sin saber cuándo se creó, no se hereda nada."""
    for sin_fecha in ({"whitelist_id": "x"},
                      {"whitelist_id": "x", "created_at": ""},
                      {"whitelist_id": "x", "created_at": "ayer"},
                      {"whitelist_id": "x", "created_at": "04/08/2026"}):
        assert W.estado_de(sin_fecha) == "desconocida", sin_fecha


def test_UN_ESTADO_INVENTADO_NUNCA_ES_HERENCIA():
    # El campo está y dice cualquier cosa: alguien lo escribió. No se adivina,
    # ni siquiera si la fecha es vieja.
    assert W.estado_de({"estado": "aprobadisima"}) == "desconocida"
    assert W.estado_de({"estado": "pending",
                        "created_at": "2026-08-04 13:51:51"}) == "desconocida"


def test_una_desconocida_se_marca_para_ir_a_mirarla():
    # No silencia nada, pero que exista es una pista de que algo escribió por
    # fuera del control.
    r = W.resumen({"whitelist_id": "colada", "created_at": "2026-11-01 10:00:00"})
    assert r["fuera_del_control"] is True
    assert r["aplica"] is False


def test_el_estado_no_distingue_mayusculas():
    assert W.estado_de({"estado": "APROBADA"}) == "aprobada"


# ── aplica: la única respuesta a "¿silencia algo?" ──────────────────────────

def test_UNA_PENDIENTE_NO_SILENCIA_NADA():
    # Es la regla entera del PR. Si esto se cae, el control no existe.
    assert W.aplica(pendiente(), TS) is False


def test_una_rechazada_no_silencia_nada():
    assert W.aplica(pendiente(estado="rechazada"), TS) is False


def test_una_aprobada_vigente_si_silencia():
    e = W.aprobar(pendiente(), "oficial@global66.com", AHORA)
    assert W.aplica(e, TS) is True


def test_LAS_QUE_YA_ESTABAN_SIGUEN_APLICANDO():
    # Ponerlas en pendiente habría devuelto a los reportes, de golpe, a cada
    # cliente que estaba silenciado. Se respetan y se marcan; vencen solas.
    # La más nueva de las que había en producción es del 15-10-2026.
    vieja = {"entity_field": "customer_id", "entity_value": "9",
             "created_at": "2026-10-15 22:04:16", "expires_at": TS + 86400}
    assert W.aplica(vieja, TS) is True
    assert W.resumen(vieja)["sin_aprobacion"] is True


def test_EL_CORTE_ES_EL_MOMENTO_DEL_DESPLIEGUE():
    # Una constante y no una fecha calculada: tiene que significar lo mismo
    # dentro de un año, cuando nadie se acuerde de por qué está.
    assert W.CORTE == "2026-10-27 15:55:21"
    justo_antes = {"created_at": "2026-10-27 15:55:20", "expires_at": TS + 86400}
    justo_despues = {"created_at": "2026-10-27 15:55:22", "expires_at": TS + 86400}
    assert W.estado_de(justo_antes) == "heredada"
    assert W.estado_de(justo_despues) == "desconocida"


def test_una_aprobada_vencida_deja_de_silenciar():
    e = W.aprobar(pendiente(), "oficial@global66.com", AHORA)
    assert W.aplica(e, TS + 91 * 86400) is False


def test_UNA_PENDIENTE_NO_VENCE():
    # Todavía no empezó a contar: si venciera, una entrada pedida y no
    # aprobada se volvería inaprobable sola, en silencio.
    assert W.vencida(pendiente(expires_at=1), TS) is False


def test_una_entrada_sin_fecha_no_vence_por_las_dudas():
    assert W.vencida({"estado": "aprobada"}, TS) is False


def test_una_fecha_rota_no_rompe_la_corrida():
    assert W.vencida({"estado": "aprobada", "expires_at": "ayer"}, TS) is False


# ── bloqueos_para_aprobar ───────────────────────────────────────────────────

def test_un_oficial_distinto_del_que_pidio_puede_aprobar():
    assert W.bloqueos_para_aprobar(pendiente(), "oficial@global66.com",
                                   OFICIALES) == []


def test_EL_QUE_LA_PIDIO_NO_PUEDE_APROBARLA():
    # Cuatro ojos. Sin esto el paso de aprobación se completa solo.
    e = pendiente(solicitado_por="oficial@global66.com")
    faltan = W.bloqueos_para_aprobar(e, "oficial@global66.com", OFICIALES)
    assert any("pediste vos" in f for f in faltan)


def test_el_cuatro_ojos_mira_tambien_created_by():
    # Las pantallas viejas mandan `created_by` y no `solicitado_por`.
    e = pendiente(solicitado_por="", created_by="OFICIAL@global66.com")
    faltan = W.bloqueos_para_aprobar(e, "oficial@global66.com", OFICIALES)
    assert any("pediste vos" in f for f in faltan)


def test_QUIEN_NO_ESTA_EN_EL_PADRON_NO_APRUEBA():
    faltan = W.bloqueos_para_aprobar(pendiente(), "cualquiera@global66.com",
                                     OFICIALES)
    assert any("Oficial de Cumplimiento" in f for f in faltan)


def test_EL_PADRON_VACIO_FALLA_CERRADO():
    # Vacío no es "cualquiera puede": es "no sabemos quién puede".
    faltan = W.bloqueos_para_aprobar(pendiente(), "oficial@global66.com", [])
    assert any("sin padrón no aprueba nadie" in f for f in faltan)


def test_una_ya_aprobada_no_se_aprueba_de_nuevo():
    e = W.aprobar(pendiente(), "oficial@global66.com", AHORA)
    faltan = W.bloqueos_para_aprobar(e, "otra.oficial@global66.com", OFICIALES)
    assert any("ya está aprobada" in f for f in faltan)


def test_una_rechazada_no_se_puede_aprobar():
    e = W.rechazar(pendiente(), "oficial@global66.com", "no corresponde", AHORA)
    faltan = W.bloqueos_para_aprobar(e, "otra.oficial@global66.com", OFICIALES)
    assert any("rechazada" in f for f in faltan)


def test_una_heredada_no_se_aprueba():
    faltan = W.bloqueos_para_aprobar(
        {"entity_value": "9", "created_at": "2026-08-04 13:51:51"},
        "oficial@global66.com", OFICIALES)
    assert any("anterior al control" in f for f in faltan)


def test_UNA_DESCONOCIDA_TAMPOCO_SE_APRUEBA():
    """No se blanquea firmándola: hay que entender de dónde salió.

    Aprobarla sería convertir «alguien escribió esto por fuera del control»
    en «un Oficial lo revisó», que es precisamente la confusión que no puede
    quedar en el expediente.
    """
    faltan = W.bloqueos_para_aprobar(
        {"entity_value": "9", "created_at": "2026-11-01 10:00:00"},
        "oficial@global66.com", OFICIALES)
    assert faltan


def test_sin_quien_no_se_aprueba():
    assert W.bloqueos_para_aprobar(pendiente(), "  ", OFICIALES)


def test_LOS_MOTIVOS_VIENEN_TODOS_JUNTOS():
    # Descubrirlos de a uno apretando el botón cuatro veces es caro.
    e = pendiente(solicitado_por="colado@global66.com")
    faltan = W.bloqueos_para_aprobar(e, "colado@global66.com", OFICIALES)
    assert len(faltan) == 2


# ── aprobar: el reloj ───────────────────────────────────────────────────────

def test_EL_RELOJ_ARRANCA_AL_APROBAR_NO_AL_PEDIR():
    # Una entrada aprobada cinco días después tiene que valer 90, no 85: el
    # que la pide no paga la demora del que la firma.
    e = W.aprobar(pendiente(), "oficial@global66.com", AHORA + dt.timedelta(days=5))
    esperado = int((AHORA + dt.timedelta(days=95)).timestamp())
    assert e["expires_at"] == esperado


def test_aprobar_deja_quien_y_cuando():
    e = W.aprobar(pendiente(), "Oficial@Global66.com", AHORA)
    assert e["aprobacion"]["por"] == "oficial@global66.com"
    assert e["aprobacion"]["en"] == "2026-10-27 12:00:00"
    assert e["estado"] == "aprobada"


def test_aprobar_no_muta_la_entrada_original():
    orig = pendiente()
    W.aprobar(orig, "oficial@global66.com", AHORA)
    assert orig["estado"] == "pendiente"
    assert "aprobacion" not in orig


def test_aprobar_sin_quien_explota():
    try:
        W.aprobar(pendiente(), "")
    except ValueError:
        return
    raise AssertionError("aprobar sin quién tiene que fallar")


def test_UN_PLAZO_INVENTADO_CAE_AL_MAS_CORTO():
    # 90 es el máximo, no el default cómodo.
    e = W.aprobar(pendiente(duration_days=365), "oficial@global66.com", AHORA)
    assert e["duration_days"] == 30


def test_un_plazo_valido_se_respeta():
    e = W.aprobar(pendiente(duration_days=60), "oficial@global66.com", AHORA)
    assert e["duration_days"] == 60


# ── rechazar ────────────────────────────────────────────────────────────────

def test_rechazar_guarda_el_motivo_y_no_borra():
    e = W.rechazar(pendiente(), "oficial@global66.com", "el cliente sigue operando", AHORA)
    assert e["estado"] == "rechazada"
    assert e["rechazo"]["motivo"] == "el cliente sigue operando"
    assert e["rechazo"]["por"] == "oficial@global66.com"


def test_una_rechazada_no_queda_con_fecha_de_vencimiento():
    e = W.rechazar(pendiente(expires_at=TS + 999), "oficial@global66.com", "", AHORA)
    assert e["expires_at"] == 0


def test_el_motivo_del_rechazo_se_corta():
    e = W.rechazar(pendiente(), "oficial@global66.com", "x" * 900, AHORA)
    assert len(e["rechazo"]["motivo"]) == 500


def test_rechazar_no_muta_la_original():
    orig = pendiente()
    W.rechazar(orig, "oficial@global66.com", "no", AHORA)
    assert orig["estado"] == "pendiente"


# ── el padrón es el mismo de los ROS ────────────────────────────────────────

def test_EL_PADRON_ES_EL_MISMO_QUE_FIRMA_LOS_ROS():
    # Dos padrones para dos decisiones de compliance se desincronizan, y
    # "¿quién puede firmar?" pasa a tener dos respuestas.
    import ros_aprobacion
    assert W.CLAVE_PADRON == ros_aprobacion.CLAVE_PADRON
    assert W.oficiales_de is ros_aprobacion.oficiales_de
