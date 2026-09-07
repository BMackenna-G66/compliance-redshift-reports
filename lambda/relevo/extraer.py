"""Paso 3: extraer el identificador.

Dos cosas que las reglas resuelven de forma declarativa:

  `global: true`   captura TODAS las coincidencias, no la primera. Sin esto se
                   pierde la segunda transaccion de los asuntos "IDs A / B" de
                   OZ (5 mensajes) y se pierden los PY encadenados de Nium
                   ("PY77289097/PY77335966/PY77396838/...").

  `ancla`          el patron se aplica solo despues de una etiqueta y dentro de
                   una ventana de caracteres. Asi el "\\b(\\d{7,9})\\b" de OZ no
                   captura cualquier numero del asunto, solo los que siguen a
                   "ID" o "IDs".
"""
VENTANA_ANCLA_POR_DEFECTO = 120


def _coincidencias(regla, texto):
    if not texto:
        return []
    fuera = []
    if regla.get("_re_ancla") is not None:
        ventana = regla.get("ventana", VENTANA_ANCLA_POR_DEFECTO)
        for m in regla["_re_ancla"].finditer(texto):
            resto = texto[m.end():m.end() + ventana]
            for mm in regla["_re"].finditer(resto):
                fuera.append(mm.group(1))
                if not regla.get("global"):
                    break
            if not regla.get("global") and fuera:
                break
    else:
        for mm in regla["_re"].finditer(texto):
            fuera.append(mm.group(1))
            if not regla.get("global"):
                break
    return fuera


def extraer(mensaje, partner):
    """Devuelve una lista de hallazgos crudos, en orden de aparicion y sin repetir.

    Cada hallazgo: {llave, rol, de_quien, valor_crudo, ambito, regla}
    `ambito` dice de donde salio -- asunto o cuerpo. Es lo que permite medir
    cuantas transacciones se habrian perdido sin leer el cuerpo.
    """
    textos = {
        "asunto": mensaje.get("asunto") or "",
        # el cuerpo incluye el texto citado a proposito: 25 de los 71 PY de Nium
        # solo aparecen ahi.
        "cuerpo": mensaje.get("cuerpo") or "",
        "adjuntos": "\n".join(mensaje.get("texto_adjuntos") or []),
    }

    hallazgos, vistos = [], set()
    for regla in partner.get("extraccion", []):
        for ambito in regla.get("ambito", []):
            for valor in _coincidencias(regla, textos.get(ambito, "")):
                clave = (regla["llave"], valor)
                if clave in vistos:
                    continue
                vistos.add(clave)
                hallazgos.append({
                    "llave": regla["llave"],
                    "rol": regla.get("rol", "llave_consulta"),
                    "de_quien": regla.get("de_quien", "?"),
                    "valor_crudo": valor,
                    "ambito": ambito,
                    "regla": regla["patron"],
                })
    return hallazgos
