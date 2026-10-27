# -*- coding: utf-8 -*-
"""Qué decide una corrida programada del informe de alertas.

═══════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO EXISTE SEPARADO DEL ENVÍO
═══════════════════════════════════════════════════════════════════════════

Mandar el informe ya funciona: `enviar_informe_alertas` lo arma y lo manda, y
esa función no cambia. Lo que faltaba era quién decide, cada lunes y sin una
persona al teclado, **a quién** se le manda y **si** se manda.

Esa decisión vive acá, sin boto3 ni red, porque es la parte que hay que poder
probar sin mandar un correo. El `handler` pone S3 y el envío; este módulo
pone las reglas.

═══════════════════════════════════════════════════════════════════════════
DE DÓNDE SALEN LOS DESTINATARIOS — Y POR QUÉ DE DOS LADOS
═══════════════════════════════════════════════════════════════════════════

Dos fuentes, en este orden:

  1. `config/informe_alertas.json` en S3. **Manda sobre todo lo demás.** Es la
     forma de cambiar la lista sin tocar código, sin redesplegar la Lambda y
     sin recrear el horario: se edita un objeto en S3 y el lunes siguiente ya
     sale a quien corresponde.
  2. La lista que trae el propio horario de EventBridge, que la pone el
     script del repo. Es el valor de arranque y el salvavidas: si el objeto
     de S3 no existe, está roto o quedó vacío, el informe **sale igual** a la
     lista con la que se creó el horario.

Las dos son fuentes autorizadas —una la escribe quien administra el bucket,
la otra quien corre el script— así que ninguna necesita más validación que la
que ya hace `_destinatarios` en el envío: sólo correos internos, y no más de
los que entran en un correo. Si alguien escribe mal una dirección en la
config, el envío la rechaza con 400 y eso **dispara el aviso de falla**, que
es exactamente lo que tiene que pasar.

El orden importa y es a propósito. Al revés —el horario pisando la config— un
cambio de equipo obligaría a recrear el horario, que es justo lo que nadie se
acuerda de hacer.

═══════════════════════════════════════════════════════════════════════════
APAGARLO NO ES LO MISMO QUE FALLAR
═══════════════════════════════════════════════════════════════════════════

`{"activo": false}` en la config para el envío sin borrar el horario, y eso
**no es una falla**: no avisa, no grita, queda en el log y listo. Una lista
vacía, en cambio, no apaga nada: cae al salvavidas del punto 2. Son dos cosas
distintas y se dicen distinto, porque "no quiero que salga" y "se me borró la
lista" no pueden tener el mismo resultado.
"""
from __future__ import annotations

import json

# El objeto de S3 que manda. Va en `config/`, al lado de
# `config/auto_case_rules.json`, que es donde ya vive la configuración que se
# edita sin desplegar.
CLAVE_CONFIG = "config/informe_alertas.json"

# Quién figura en la auditoría. No es un correo de persona a propósito: nadie
# apretó nada, y poner al último que tocó el horario sería atribuirle un envío
# que no hizo.
ACTOR = "sistema:programado"

# El nombre con el que el aviso de falla se presenta. Tiene que decir qué se
# rompió sin que haya que abrir el código para entenderlo.
PROCESO = "Informe de alertas programado"


def limpiar(crudos) -> list:
    """Correos normalizados, sin vacíos y sin repetidos, en orden.

    El orden se conserva porque es el del campo «Para» del correo que le llega
    a la gente, y una lista que se reordena sola cada semana se lee como si
    hubiera cambiado algo.
    """
    if isinstance(crudos, str):
        crudos = [crudos]
    fuera, vistos = [], set()
    for x in (crudos or []):
        c = str(x or "").strip().lower()
        if c and c not in vistos:
            vistos.add(c)
            fuera.append(c)
    return fuera


def plan(config: dict | None, evento: dict | None) -> dict:
    """Qué hay que hacer en esta corrida.

    Devuelve `{enviar, para, origen, motivo}`:

      · `enviar`  si sale o no.
      · `para`    a quiénes (vacío si no sale).
      · `origen`  `"config"` o `"horario"` — de dónde salió la lista. Va al
                  log y al resultado: cuando alguien pregunte "¿por qué le
                  llegó a esta persona?", la respuesta tiene que estar ahí.
      · `motivo`  por qué no sale, cuando no sale. Vacío si sale.
    """
    config = config if isinstance(config, dict) else {}
    evento = evento if isinstance(evento, dict) else {}

    # El apagado primero: si está apagado no importa a quién le tocaba.
    if config.get("activo") is False:
        return {"enviar": False, "para": [], "origen": "config",
                "motivo": f"apagado en {CLAVE_CONFIG} (\"activo\": false)"}

    de_config = limpiar(config.get("para"))
    if de_config:
        return {"enviar": True, "para": de_config, "origen": "config",
                "motivo": ""}

    del_horario = limpiar(evento.get("para"))
    if del_horario:
        return {"enviar": True, "para": del_horario, "origen": "horario",
                "motivo": ""}

    # Ni config ni horario. No hay a quién mandarle, y esto SÍ es una falla:
    # el horario se creó con una lista, así que llegar acá significa que algo
    # la perdió.
    return {"enviar": False, "para": [], "origen": "",
            "motivo": f"no hay destinatarios: ni {CLAVE_CONFIG} ni el horario "
                      "traen una lista"}


def cuerpo(plan_: dict, evento: dict | None = None) -> dict:
    """El `body` que espera `enviar_informe_alertas`.

    Los filtros (`desde`, `hasta`, `persona`, `regla`) se pasan si el horario
    los trae. Hoy no los trae ninguno —el informe es de todas las alertas
    abiertas— pero dejarlos pasar permite armar un segundo horario con otro
    recorte sin tocar esto.
    """
    evento = evento if isinstance(evento, dict) else {}
    body = {"para": list(plan_.get("para") or []), "actor_email": ACTOR}
    for k in ("desde", "hasta", "persona", "regla"):
        v = str(evento.get(k) or "").strip()
        if v:
            body[k] = v
    return body


def leer_respuesta(respuesta) -> tuple:
    """`(código, datos)` de lo que devolvió el envío.

    `enviar_informe_alertas` contesta en formato de API Gateway —el `body` es
    un string JSON— porque también la llama la pantalla. Acá no hay HTTP: hay
    que abrirla.
    """
    if not isinstance(respuesta, dict):
        return 0, {}
    try:
        codigo = int(respuesta.get("statusCode") or 0)
    except (TypeError, ValueError):
        codigo = 0
    crudo = respuesta.get("body")
    if isinstance(crudo, dict):
        return codigo, crudo
    try:
        datos = json.loads(crudo or "{}")
    except (TypeError, ValueError):
        datos = {}
    return codigo, (datos if isinstance(datos, dict) else {})


def falla(codigo: int, datos: dict | None) -> str:
    """Por qué hay que avisar, o `""` si salió bien.

    **Un 200 no alcanza.** `enviar_informe_alertas` devuelve 200 con
    `enviado: false` cuando el SMTP rechazó el correo: la respuesta está bien
    formada y el informe no llegó a nadie. Ése es el modo de falla que dejó la
    escucha de respuestas ocho días muerta sin que nadie lo notara, y es el
    que esta función existe para cazar.
    """
    datos = datos if isinstance(datos, dict) else {}
    if codigo != 200:
        detalle = str(datos.get("error") or "").strip()
        return f"el envío contestó {codigo}" + (f": {detalle}" if detalle else "")
    if not datos.get("enviado"):
        aviso = str(datos.get("aviso") or "").strip()
        return ("el informe se armó pero el correo NO salió"
                + (f": {aviso}" if aviso else ""))
    return ""
