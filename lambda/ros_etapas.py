# -*- coding: utf-8 -*-
"""La etapa del ROS en el camino a GEREO. Un eje aparte de `estado`.

═══════════════════════════════════════════════════════════════════════════
POR QUÉ UN EJE NUEVO Y NO MÁS ESTADOS
═══════════════════════════════════════════════════════════════════════════

Lo natural parecía ampliar `ros.ESTADOS` con las seis etapas del documento, y
rompe el modelo, porque las dos listas no contestan la misma pregunta:

  `estado`      ¿en qué punto del trabajo de compliance está este reporte?
  `etapa_gereo` ¿en qué punto del camino al regulador está el documento?

Un ROS puede estar en `revision_legal` —alguien está escribiendo— mientras el
payload de GEREO apenas llegó y está en `recibido`. Con un solo campo hay que
elegir cuál de las dos verdades se guarda, y la otra se pierde.

Cuatro cosas que salen gratis de separarlos:

  · Un registro viejo se lee sin migrar: sin el campo, la etapa es `sin_ros`.
  · `descartado` sigue existiendo, porque vive en `estado` y nadie lo tocó.
  · Un ROS escrito a mano nunca entra acá. No todo ROS nace en GEREO.
  · La pantalla actual no se entera: sólo aparecen campos nuevos.

═══════════════════════════════════════════════════════════════════════════
EL PUENTE VA EN UN SOLO SENTIDO
═══════════════════════════════════════════════════════════════════════════

`etapa_gereo = enviado` **dispara** `estado = enviado`, nunca al revés. Un ROS
reportado por fuera de GEREO llega a `enviado` por el camino de siempre, con
su acuse. Y el puente NO fuerza transiciones del eje viejo: si el ROS no está
en `revision_legal`, no se aprueba — no se lo empuja hasta ahí.
"""
from __future__ import annotations

# El nombre de cada etapa, para la pantalla. Las dos últimas no estaban en la
# propuesta original del analista: se agregaron para cubrir la espera y los
# fallos, que es donde un flujo sin etapa propia se queda mudo.
#
# LAS CLAVES SE QUEDAN COMO ESTÁN. Desde el acuerdo con GEREO del 23-10-2026
# el paso final es «entregado a GEREO» y no «subido al regulador» —la carga
# la autoriza un Oficial en Slack y WatchTower no se entera—, así que los
# TEXTOS cambiaron. Las claves no: están guardadas en `etapa_gereo` y en cada
# entrada de `historial_gereo`, y renombrarlas obligaría a migrar registros
# para arreglar un nombre interno que no se muestra en ningún lado.
ETAPAS = {
    "sin_ros":     "El caso no tiene ROS generado.",
    "recibido":    "GEREO devolvió el JSON y el PDF; están guardados.",
    "revisado":    "Un analista revisó el contenido.",
    "enviando":    "La versión aprobada se está entregando a GEREO.",
    "enviado":     ("Entregado a GEREO. La autorización para cargarlo al "
                    "regulador se decide en Slack, fuera de WatchTower."),
    "error_envio": "La entrega no salió.",
}

# De dónde se puede pasar a dónde.
#
# `revisado → recibido` es la regla de la especificación: editar después de
# revisar invalida la revisión. No es un retroceso raro, es el control.
#
# `enviado` no tiene salida. Un ROS que el regulador ya recibió no se
# desdice desde una pantalla: si hay que corregirlo, se gestiona por el
# procedimiento del regulador, que es de otro mundo.
TRANSICIONES = {
    "sin_ros":     ["recibido"],
    "recibido":    ["revisado"],
    "revisado":    ["recibido", "enviando"],
    "enviando":    ["enviado", "error_envio"],
    "error_envio": ["enviando", "recibido"],
    "enviado":     [],
}

INICIAL = "sin_ros"

# Las etapas donde todavía se puede tocar el contenido. `enviando` NO está:
# mientras GEREO procesa, el payload tiene que quedarse quieto.
EDITABLES = ("recibido", "revisado", "error_envio")


def etapa_de(reporte: dict) -> str:
    """La etapa actual. Un ROS sin el campo nunca pasó por GEREO."""
    e = str((reporte or {}).get("etapa_gereo") or "").strip()
    return e if e in ETAPAS else INICIAL


def puede_pasar(desde: str, hasta: str) -> bool:
    return hasta in TRANSICIONES.get(desde, [])


def historial_de(reporte: dict) -> list:
    h = (reporte or {}).get("historial_gereo")
    return list(h) if isinstance(h, list) else []


def bloqueos(reporte: dict, hasta: str) -> list:
    """Por qué NO se puede mover a esa etapa. Lista vacía = se puede.

    Acá viven las reglas del puente con el eje viejo, y existen porque las dos
    máquinas corren en paralelo: sin esto se podría aprobar para enviar un ROS
    que alguien ya decidió no reportar.
    """
    faltan = []
    desde = etapa_de(reporte)
    estado = str((reporte or {}).get("estado") or "").strip()

    if hasta not in ETAPAS:
        return [f"La etapa {hasta!r} no existe."]
    if not puede_pasar(desde, hasta):
        posibles = TRANSICIONES.get(desde, [])
        faltan.append(
            f"No se puede pasar de {desde!r} a {hasta!r}"
            + (f"; desde {desde!r} sólo se puede ir a {posibles}." if posibles
               else f"; {desde!r} es una etapa final."))

    # REGLA 1 — UN ROS DESCARTADO NO SIGUE EL CAMINO. Se evaluó y se decidió
    # no reportar: moverlo hacia el regulador sería contradecir esa decisión
    # desde otra pantalla.
    if estado == "descartado":
        faltan.append("Este ROS está descartado: se decidió no reportarlo. "
                      "Para retomarlo hay que volverlo a borrador primero.")

    # REGLA 2 — APROBAR EXIGE QUE EL EJE VIEJO ESTÉ EN REVISIÓN. Y el puente
    # no fuerza la transición: si el ROS no llegó a `revision_legal`, se
    # frena, no se lo empuja. Aprobar un reporte que nadie puso en revisión
    # saltearía el paso que existe justamente para que lo mire otra persona.
    if hasta == "enviando" and estado != "revision_legal":
        faltan.append("Para aprobar el envío, el reporte tiene que estar en "
                      f"revisión legal (hoy está en {estado or 'sin estado'}).")

    return faltan


def cambiar(reporte: dict, nueva: str, quien: str, nota: str = "",
            momento: str = "", datos: dict | None = None) -> dict:
    """Mueve la etapa dejando rastro. NO muta el reporte que recibe.

    El historial de este eje va aparte del de `estado`: mezclarlos daría una
    lista donde «revisado» y «revision_legal» se leen como lo mismo y nadie
    podría reconstruir qué pasó con el documento.
    """
    quien = str(quien or "").strip()
    if not quien:
        raise ValueError("falta quién hace el cambio")
    problemas = bloqueos(reporte, nueva)
    if problemas:
        raise ValueError("; ".join(problemas))

    salida = dict(reporte)
    salida["etapa_gereo"] = nueva
    entrada = {"etapa": nueva, "quien": quien, "cuando": str(momento or ""),
               "nota": str(nota or "")}
    # Qué versión era la que estaba en juego: una etapa sin eso no dice nada
    # cuando el ROS tiene cinco versiones.
    if reporte.get("version_actual"):
        entrada["version"] = reporte["version_actual"]
    if datos:
        entrada.update(datos)
    salida["historial_gereo"] = historial_de(reporte) + [entrada]
    return salida


def editable(reporte: dict) -> bool:
    """Si se puede tocar el contenido del ROS en esta etapa.

    Mientras GEREO procesa (`enviando`) el payload se queda quieto, y un
    `enviado` no se toca nunca más.
    """
    return etapa_de(reporte) in EDITABLES or etapa_de(reporte) == INICIAL


def anotar(reporte: dict, evento: str, quien: str, momento: str = "",
           nota: str = "", datos: dict | None = None) -> dict:
    """Un hecho que NO es un cambio de etapa, en el mismo historial.

    Aprobar no mueve la etapa —el reporte sigue «revisado» hasta que se
    envíe— pero es el hecho más importante del reporte: alguien firmó. Sin
    esto, la única traza era la auditoría general, que no vive con el registro
    y donde el campo `aprobacion` se pisa sin dejar rastro de lo anterior.

    NO muta el reporte que recibe.
    """
    if not str(quien or "").strip():
        raise ValueError("falta quién")
    entrada = {"evento": str(evento), "quien": str(quien).strip(),
               "cuando": str(momento or ""), "nota": str(nota or "")}
    if reporte.get("version_actual"):
        entrada["version"] = reporte["version_actual"]
    if datos:
        entrada.update(datos)
    salida = dict(reporte)
    salida["historial_gereo"] = historial_de(reporte) + [entrada]
    return salida
