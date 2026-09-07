"""Paso 4: validar antes de consultar.

Regla general: si el identificador no pasa la validacion, NO se consulta -- se
encola. Un ID corrupto devuelve vacio y el caso queda como «sin match» sin que
nadie entienda por que. Asi aparecio el 1385384 de OZ, siete digitos fuera del
rango de transaccion.

La normalizacion vive SOLO aca. Hoy se asume que Redshift guarda los IDs sin
prefijo y sin ceros a la izquierda (RMT027773217 -> 27773217). Verificar como
estan guardados de verdad es la pregunta 2 de fase 0, y cambiarla es cambiar
este archivo y nada mas.
"""


def normalizar(llave, valor_crudo, reglas):
    """Devuelve el valor tal como se le manda a la consulta."""
    cfg = reglas.get("normalizacion", {}).get(llave, {})
    v = str(valor_crudo).strip()

    pref = cfg.get("quitar_prefijo") or ""
    if pref and v.upper().startswith(pref.upper()):
        v = v[len(pref):]

    if cfg.get("tipo") == "entero":
        v = "".join(ch for ch in v if ch.isdigit())
        if cfg.get("quitar_ceros_izquierda"):
            v = v.lstrip("0") or "0"
        return v
    if cfg.get("mayusculas"):
        v = v.upper()
    return v


def validar(hallazgo, reglas):
    """Enriquece el hallazgo con valor_consulta, valido y motivo. Muta y devuelve."""
    llave, crudo = hallazgo["llave"], hallazgo["valor_crudo"]
    hallazgo["valor_consulta"] = normalizar(llave, crudo, reglas)
    hallazgo["valido"] = True
    hallazgo["motivo"] = ""

    # formato -- se aplica al valor crudo, antes de normalizar
    fmt = reglas.get("formatos", {}).get(llave)
    if fmt and not fmt["_re"].match(str(crudo)):
        hallazgo["valido"] = False
        hallazgo["motivo"] = f"formato no aceptado para {llave}"
        return hallazgo

    # rango -- se aplica al valor normalizado
    rango = reglas.get("rangos", {}).get(llave)
    if rango:
        try:
            n = int(hallazgo["valor_consulta"])
        except (TypeError, ValueError):
            hallazgo["valido"] = False
            hallazgo["motivo"] = "no es numerico"
            return hallazgo
        if not (rango["min"] <= n <= rango["max"]):
            hallazgo["valido"] = False
            hallazgo["motivo"] = (
                f"fuera de rango {rango['min']:,}-{rango['max']:,} (valor {n:,})".replace(",", ".")
            )
    return hallazgo
