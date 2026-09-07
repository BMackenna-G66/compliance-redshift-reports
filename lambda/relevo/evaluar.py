"""Compara lo que extrajo el motor contra el consolidado de 963 registros.

Que puede y que no puede medir esta comparacion, dicho de frente:

  SI mide   la extraccion de identificadores desde el ASUNTO, que es lo unico
            que el Excel guarda, y la clasificacion accionable/informativo.
  NO mide   la identificacion de partner por X-Original-Sender (el Excel no
            tiene headers) ni la extraccion desde el cuerpo. Para eso hacen
            falta correos reales: --eml, --mbox o --json.

Y una advertencia que conviene no perder: el consolidado lo produjo el mismo
tipo de extraccion que estamos midiendo. Esto es un test de REGRESION, no una
verdad de campo. La verdad de campo sale de revisar a mano una muestra.
"""
from .validar import normalizar

VEREDICTOS = {
    "coincide":           "El identificador esperado salio del asunto y paso validacion.",
    "requiere_cuerpo":    "El Excel dice que solo vive en el cuerpo. No salir del asunto es lo correcto.",
    "capturado_invalido": "Se extrajo el valor esperado pero no paso validacion: iria a conciliacion.",
    "no_coincide":        "Se extrajo algo distinto de lo esperado.",
    "sin_captura":        "Deberia haber salido del asunto y no salio.",
}
ORDEN_VEREDICTO = ["coincide", "requiere_cuerpo", "sin_captura", "no_coincide", "capturado_invalido"]


def evaluar(registro, mensaje, reglas):
    """Anota el registro con el veredicto contra el golden set. Muta y devuelve."""
    esp = mensaje.get("esperado")
    if not esp:
        registro["veredicto"] = ""
        return registro

    registro["esperado"] = esp
    registro["partner_ok"] = (registro.get("partner") or "") == esp["partner"]

    llave = esp["llave"]
    objetivo = normalizar(llave, esp["valor"], reglas) if llave else ""

    validos, invalidos = [], []
    for h in registro.get("ids", []):
        (validos if h["valido"] else invalidos).append(h)

    hallados_llave = [h["valor_consulta"] for h in validos if h["llave"] == llave]
    invalidos_llave = [h["valor_consulta"] for h in invalidos if h["llave"] == llave]

    if objetivo and objetivo in hallados_llave:
        registro["veredicto"] = "coincide"
    elif objetivo and objetivo in invalidos_llave:
        registro["veredicto"] = "capturado_invalido"
    elif not esp["en_asunto"]:
        registro["veredicto"] = "requiere_cuerpo"
    elif hallados_llave or invalidos_llave:
        registro["veredicto"] = "no_coincide"
    else:
        registro["veredicto"] = "sin_captura"

    registro["esperado_normalizado"] = objetivo
    registro["hallado_para_llave"] = hallados_llave + [f"{v} (invalido)" for v in invalidos_llave]
    return registro


def resumir(registros):
    """Agrega por partner y total. Solo cuenta veredictos: los registros sin
    golden set (correos reales) quedan fuera del denominador."""
    def vacio():
        return {v: 0 for v in ORDEN_VEREDICTO} | {
            "total": 0, "evaluados": 0, "partner_ok": 0, "accionables": 0,
            "informativos": 0, "con_llave": 0, "sin_llave": 0,
            "en_conciliacion": 0, "sin_id": 0, "desconocidos": 0,
        }

    por_partner, total = {}, vacio()
    for r in registros:
        nombre = r.get("partner") or (r.get("esperado", {}) or {}).get("partner") or "(sin partner)"
        d = por_partner.setdefault(nombre, vacio())
        for caja in (d, total):
            caja["total"] += 1
            if r.get("veredicto"):
                caja["evaluados"] += 1
                caja[r["veredicto"]] += 1
            if r.get("partner_ok"):
                caja["partner_ok"] += 1
            if r.get("accionable") is True:
                caja["accionables"] += 1
            elif r.get("accionable") is False:
                caja["informativos"] += 1
            if r.get("llave_consulta"):
                caja["con_llave"] += 1
            est = r.get("estado")
            if est == "sin_llave":
                caja["sin_llave"] += 1
            elif est == "en_conciliacion":
                caja["en_conciliacion"] += 1
            elif est == "sin_id":
                caja["sin_id"] += 1
            elif est == "partner_desconocido":
                caja["desconocidos"] += 1

    # base del grafico: solo lo que se esperaba resolver por asunto
    for d in list(por_partner.values()) + [total]:
        d["base_asunto"] = d["coincide"] + d["sin_captura"] + d["no_coincide"] + d["capturado_invalido"]
        d["tasa_captura"] = (d["coincide"] / d["base_asunto"] * 100) if d["base_asunto"] else 0.0
    return por_partner, total
