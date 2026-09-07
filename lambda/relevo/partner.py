"""Paso 1: identificar QUIEN escribio.

El From no sirve: compliance@global66.com es una lista de Google Groups que
reescribe el remitente, asi que los 2.430 correos llegan con la misma direccion.
El header que Google Groups conserva es X-Original-Sender, y resolvio el 100%
de los mensajes que lo traen.

Orden de intento -- el primero que resuelve gana:
  1. X-Original-Sender   (el bueno)
  2. X-Original-From     (respaldo)
  3. Reply-To            (respaldo)
  4. display name del From  ("'d·Local' via Compliance")
  5. pista en el asunto  (ultimo recurso, y se marca como tal)
"""
import re

HEADERS_PEDIDOS = (
    "From", "Reply-To", "X-Original-Sender", "X-Original-From", "List-ID",
    "Message-ID", "In-Reply-To", "References", "Subject", "Date",
)

_RE_DIR = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _direcciones(valor):
    return [d.lower() for d in _RE_DIR.findall(valor or "")]


def _buscar_header(headers, nombre):
    """Los headers de correo no distinguen mayusculas."""
    n = nombre.lower()
    for k, v in (headers or {}).items():
        if k.lower() == n:
            return v
    return None


def _match_direccion(reglas, direccion):
    for p in reglas["partners"]:
        if direccion in [r.lower() for r in p.get("remitentes", [])]:
            return p, "remitente_exacto"
    dominio = direccion.split("@")[-1] if "@" in direccion else ""
    for p in reglas["partners"]:
        for d in p.get("dominios", []):
            if dominio == d.lower() or dominio.endswith("." + d.lower()):
                return p, "dominio"
    return None, None


def es_no_corresponsal(mensaje, reglas):
    """¿Este correo simplemente no es de un corresponsal?

    Hace falta porque la ingesta incremental lee toda la casilla. Distinguirlo
    de «corresponsal desconocido» es lo que mantiene util la cola de
    descubrimiento: ahi solo tienen que caer remitentes que PARECEN partner y
    no tienen regla, no las respuestas de nuestros propios clientes.
    """
    cfg = reglas.get("no_corresponsal") or {}
    asunto = mensaje.get("asunto") or ""
    for a in cfg.get("asunto", []):
        if a["_re"].search(asunto):
            return True, f"asunto de correo nuestro: {a['patron']}"

    headers = mensaje.get("headers") or {}
    crudo = _buscar_header(headers, "X-Original-Sender") or ""
    for d in _direcciones(crudo):
        dominio = d.split("@")[-1]
        if dominio in [x.lower() for x in cfg.get("dominios_personales", [])]:
            return True, f"remitente de correo personal: {dominio}"
    return False, ""


def identificar(mensaje, reglas):
    """Devuelve (partner|None, via, valor_crudo_del_header).

    `valor_crudo` se devuelve SIEMPRE, resuelva o no: es como uno se entera de
    un corresponsal nuevo sin que nadie escriba una regla. Asi aparecieron
    payments@nium.com y fraudreporting@currencycloud.com.
    """
    headers = mensaje.get("headers") or {}
    crudo = _buscar_header(headers, "X-Original-Sender")

    for nombre, via in (("X-Original-Sender", "x_original_sender"),
                        ("X-Original-From", "x_original_from"),
                        ("Reply-To", "reply_to")):
        valor = _buscar_header(headers, nombre)
        for d in _direcciones(valor):
            p, como = _match_direccion(reglas, d)
            if p:
                return p, f"{via}:{como}", crudo or valor

    # display name del From, para el caso "'d·Local' via Compliance"
    frm = _buscar_header(headers, "From") or ""
    display = _RE_DIR.sub("", frm)
    if display.strip(" <>\"'"):
        p, _ = _puntuar(reglas, display)
        if p:
            return p, "display_name", crudo or frm

    # ultimo recurso: pistas del asunto, por peso.
    asunto = mensaje.get("asunto") or ""
    p, empate = _puntuar(reglas, asunto)
    if p:
        return p, ("pista_asunto:ambigua" if empate else "pista_asunto"), crudo

    return None, "desconocido", crudo or frm or None


def _puntuar(reglas, texto):
    """Gana el partner con la pista de mayor peso, no el primero de la lista.

    Sin esto, tres correos de Currencycloud que nombran a NIUM como contraparte
    se atribuian a Nium. La etiqueta estructural [Currencycloud] pesa mas que
    una marca mencionada suelta.
    """
    if not texto:
        return None, False
    marcador = []
    for p in reglas["partners"]:
        aciertos = [pi for pi in p.get("pistas_asunto", []) if pi["_re"].search(texto)]
        if aciertos:
            marcador.append((max(pi["peso"] for pi in aciertos), len(aciertos), p))
    if not marcador:
        return None, False
    marcador.sort(key=lambda t: (-t[0], -t[1]))
    empate = len(marcador) > 1 and marcador[0][:2] == marcador[1][:2]
    return marcador[0][2], empate
