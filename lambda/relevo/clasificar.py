"""Paso 2: clasificar QUE pide el correo.

El paso 1 dice quien, este dice que. Los dos son necesarios, y este es el que
saca el ruido de la bandeja: de los 580 correos de dLocal solo 248 requieren
accion, y en Currencycloud la mitad del trafico de un dia son avisos de que un
ticket se cerro.

Una regla puede mirar el asunto, el cuerpo o los dos (`ambito`). Hace falta:
Currencycloud manda el aviso de cierre con el MISMO asunto que el requerimiento
--"[Currencycloud] Re: 1382588 - Urgent - Bank Compliance Query - ..."-- y la
diferencia esta en el cuerpo: "has been Solved" contra "has been updated".
Clasificar solo por asunto los mezcla.
"""


def clasificar(asunto, cuerpo, partner):
    """Devuelve (tipo, accionable). Gana la primera regla que matchea, asi que
    el orden en reglas.json es la prioridad."""
    textos = {"asunto": asunto or "", "cuerpo": cuerpo or ""}
    for c in partner.get("clasificacion", []):
        for ambito in c.get("ambito", ["asunto"]):
            if c["_re"].search(textos.get(ambito, "")):
                return c["tipo"], bool(c["accionable"])
    return "sin_clasificar", True  # sin clasificar se trata como accionable: es mas seguro
