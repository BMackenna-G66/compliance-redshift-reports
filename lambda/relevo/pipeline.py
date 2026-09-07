"""Orquesta los pasos 1 a 4 y emite un registro por mensaje.

Lo que este modulo NO hace, a proposito: consultar Redshift. Las validaciones de
unicidad (LIMIT 2) y completitud (que la transaccion tenga correo de cliente)
necesitan la base, y quedan como estado `listo_para_consulta`. El corte esta
puesto ahi para que todo lo de arriba se pueda correr y medir sin red.
"""
from .clasificar import clasificar
from .extraer import extraer
from .partner import es_no_corresponsal, identificar
from .validar import validar

ESTADOS = {
    "no_corresponsal":       "No es correo de un corresponsal. Apartado; se procesa en una etapa futura.",
    "partner_desconocido":   "Remitente que parece de corresponsal y no tiene regla. Cola de descubrimiento.",
    "archivado_informativo": "Clasificado como notificacion: no requiere accion.",
    "listo_para_consulta":   "Hay al menos una llave valida. Sigue el paso 5 (Redshift).",
    "sin_llave":             "Se identifico el caso del partner pero ninguna llave nuestra.",
    "en_conciliacion":       "Se extrajo un identificador pero no paso la validacion. NO se consulta.",
    "sin_id":                "No se extrajo ningun identificador.",
}


def _crudo(mensaje):
    from .partner import _buscar_header
    return _buscar_header(mensaje.get("headers") or {}, "X-Original-Sender")


def procesar(mensaje, reglas):
    reg = {
        "id": mensaje.get("id"),
        "asunto": mensaje.get("asunto") or "",
        "tiene_cuerpo": bool(mensaje.get("cuerpo")),
        "alertas": [],
    }

    # 0. ¿es siquiera correo de corresponsal?
    fuera, motivo = es_no_corresponsal(mensaje, reglas)
    if fuera:
        reg.update(partner="", partner_id="", partner_via="no_corresponsal", tipo="",
                   accionable=None, ids=[], llave_consulta="", valor_consulta="",
                   caso_partner="", estado="no_corresponsal",
                   x_original_sender_crudo=_crudo(mensaje))
        reg["alertas"].append(motivo)
        return reg

    # 1. quien
    partner, via, crudo = identificar(mensaje, reglas)
    reg["x_original_sender_crudo"] = crudo          # se loguea siempre, resuelva o no
    reg["partner_via"] = via
    if partner is None:
        reg.update(partner="", partner_id="", tipo="", accionable=None, ids=[],
                   llave_consulta="", valor_consulta="", caso_partner="",
                   estado="partner_desconocido")
        reg["alertas"].append(f"remitente sin regla: {crudo or 'sin header'}")
        return reg
    reg["partner"] = partner["nombre"]
    reg["partner_id"] = partner["id"]
    if via.startswith("pista_asunto"):
        reg["alertas"].append("partner resuelto por el asunto, no por header")
    if via.endswith(":ambigua"):
        reg["alertas"].append("mas de un partner coincide con el asunto")

    # 2. que
    reg["tipo"], reg["accionable"] = clasificar(reg["asunto"], mensaje.get("cuerpo"), partner)
    if reg["tipo"] == "sin_clasificar":
        reg["alertas"].append("asunto no coincide con ningun tipo conocido: posible cambio de formato")

    # 3. extraer + 4. validar
    ids = [validar(h, reglas) for h in extraer(mensaje, partner)]
    reg["ids"] = ids

    llaves = [h for h in ids if h["rol"] == "llave_consulta"]
    casos = [h for h in ids if h["rol"] == "caso_partner"]
    validas = [h for h in llaves if h["valido"]]

    # una regla con espera_uno que trae varias es senal de cambio de formato
    for regla in partner.get("extraccion", []):
        if regla.get("espera_uno"):
            n = len([h for h in ids if h["llave"] == regla["llave"]])
            if n > 1:
                reg["alertas"].append(f"{n} valores de {regla['llave']} en un correo que deberia traer uno")

    reg["caso_partner"] = casos[0]["valor_consulta"] if casos else ""

    # la llave se elige por la prioridad declarada del partner, no por orden de aparicion
    elegida = None
    for llave in partner.get("prioridad_llave", []):
        cands = [h for h in validas if h["llave"] == llave]
        if cands:
            elegida = cands[0]
            break
    if elegida is None and validas:
        elegida = validas[0]

    reg["llave_consulta"] = elegida["llave"] if elegida else ""
    reg["valor_consulta"] = elegida["valor_consulta"] if elegida else ""
    reg["n_transacciones"] = len({h["valor_consulta"] for h in validas})

    if not reg["accionable"]:
        reg["estado"] = "archivado_informativo"
    elif elegida is not None:
        reg["estado"] = "listo_para_consulta"
    elif llaves and not validas:
        reg["estado"] = "en_conciliacion"
        reg["alertas"] += [f"{h['llave']} {h['valor_crudo']}: {h['motivo']}" for h in llaves if not h["valido"]]
    elif casos:
        reg["estado"] = "sin_llave"
    else:
        reg["estado"] = "sin_id"
    return reg


def procesar_lote(mensajes, reglas):
    return [procesar(m, reglas) for m in mensajes]
