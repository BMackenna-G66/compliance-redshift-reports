"""Qué pide el partner, y el resumen en español.

Esto es lo que el analista necesita leer para saber qué pedirle al cliente, sin
abrir el correo ni traducirlo.

El resumen **se compone de la estructura extraída**, no es texto libre. Se
reconocen sólo ítems de una lista blanca y lo que no matchea se muestra aparte,
textual, en `no_reconocido`. Un resumen no puede inventar un requerimiento que
el partner no pidió — que es la misma regla que gobierna todo el proyecto: donde
no hay certeza, se dice que no la hay, no se adivina.

Los correos vienen en inglés (dLocal, Nium, Currencycloud) y en portugués o
español (OZ Câmbio). La salida es siempre en español.
"""
import re

MESES = {"january": "enero", "february": "febrero", "march": "marzo", "april": "abril",
         "may": "mayo", "june": "junio", "july": "julio", "august": "agosto",
         "september": "septiembre", "october": "octubre", "november": "noviembre",
         "december": "diciembre"}


# --------------------------------------------------------------- qué se pide
def _bloques(cuerpo, req):
    """Los tramos de texto que siguen a una frase que introduce un pedido."""
    fuera = []
    for rx in req["_re_arranques"]:
        for m in rx.finditer(cuerpo or ""):
            fuera.append(cuerpo[m.end():m.end() + req.get("ventana", 700)])
    return fuera


def _lineas(bloque, ruido):
    for l in bloque.split("\n"):
        l = l.strip(" \t\r·*-–—•✔✓>|").strip()
        l = re.sub(r"\*+", "", l).strip()
        if not (3 < len(l) < 120):
            continue
        bajo = l.lower()
        if any(n in bajo for n in ruido):
            continue
        yield l


def extraer(cuerpo, reglas):
    """Devuelve {items, no_reconocido, plazo}."""
    req = reglas.get("requerimiento") or {}
    if not req or not cuerpo:
        return {"items": [], "no_reconocido": [], "plazo": ""}

    ruido = [n.lower() for n in req.get("ruido", [])]
    vistos, no_rec = {}, []
    for bloque in _bloques(cuerpo, req):
        for linea in _lineas(bloque, ruido):
            for c in req["catalogo"]:
                if any(rx.search(linea) for rx in c["_re"]):
                    vistos.setdefault(c["item"], c["es"])
                    break
            else:
                if linea not in no_rec:
                    no_rec.append(linea)

    return {"items": [{"item": k, "es": v} for k, v in vistos.items()],
            "no_reconocido": no_rec[:6],
            "plazo": _plazo(cuerpo, req)}


def _plazo(cuerpo, req):
    for pl in req.get("plazo", []):
        m = pl["_re"].search(cuerpo)
        if not m:
            continue
        v = m.group(1).strip()
        if pl["tipo"] == "dias":
            return f"{v} días hábiles"
        if pl["tipo"] == "dias_corridos":
            return f"{v} días corridos"
        for en, es in MESES.items():           # «4 September 2026» -> «4 de septiembre de 2026»
            v = re.sub(rf"\b{en}\b", f"de {es} de", v, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", v)
    return ""


# ------------------------------------------------- datos de la transacción
def datos(cuerpo, reglas):
    """Beneficiario, remitente, monto, país, fecha.

    Sirven para dos cosas: verificar que la consulta devolvió el cliente
    correcto, y ser el respaldo cuando no hay llave (beneficiario + monto +
    fecha). Se leen de la tabla del correo, que sobrevive a la conversión de
    HTML a texto porque `relevo/html.py` la preserva con tabulaciones.

    Hay dos formatos y el orden entre ellos importa.
    """
    campos = (reglas.get("datos") or {}).get("campos", [])
    fuera = {}

    def es_etiqueta(v):
        return any(re.fullmatch(e, v, re.IGNORECASE)
                   for c in campos for e in c["etiquetas"])

    # (b) PRIMERO: fila de encabezados y debajo la fila de valores, emparejadas
    #     por posición. dLocal usa esto en los «RFI needs attention»:
    #         Country<tab>Document ID<tab>Beneficiary Name
    #         PE<tab>000844236<tab>Robert
    #     Va antes que (a) porque (a), leyendo una fila de encabezados, tomaría
    #     «Country» con valor «Document ID» y dejaría el campo ocupado con basura.
    lineas = (cuerpo or "").split("\n")
    for i in range(len(lineas) - 1):
        enc = lineas[i].split("\t")
        val = lineas[i + 1].split("\t")
        if len(enc) < 2 or len(enc) != len(val):
            continue
        for etiqueta, valor in zip(enc, val):
            etiqueta, valor = etiqueta.strip(), valor.strip()
            # El «valor» no puede ser otra etiqueta. dLocal alterna etiqueta y
            # valor en la MISMA fila —«Beneficiary Last Name\tRuiz\tAmount\tPEN
            # 62100»— y sin esto el emparejado posicional cruza dos filas de
            # etiquetas y deja «Monto = Payout ID».
            if not (etiqueta and valor) or len(valor) > 90 or es_etiqueta(valor):
                continue
            for c in campos:
                if c["campo"] in fuera:
                    continue
                if any(re.fullmatch(e, etiqueta, re.IGNORECASE) for e in c["etiquetas"]):
                    fuera[c["campo"]] = {"es": c["es"], "valor": valor}
                    break

    # (a) DESPUÉS: «Etiqueta<tab>valor» o «Etiqueta: valor» en la misma línea,
    #     sólo para los campos que (b) no llenó.
    for c in campos:
        if c["campo"] in fuera:
            continue
        for m in c["_re"].finditer(cuerpo or ""):
            v = m.group(1).strip()
            if 0 < len(v) < 90 and v not in ("-", "—") and not es_etiqueta(v):
                fuera[c["campo"]] = {"es": c["es"], "valor": v}
                break

    return fuera


# ------------------------------------------------------------------ resumen
def resumir(registro, cuerpo, reglas):
    """Una frase en español con lo que el partner pide y para cuándo.

    Se arma de piezas verificadas. Si no se reconoció nada, lo dice: es más
    útil que una frase inventada que suene bien.
    """
    r = extraer(cuerpo, reglas)
    r["datos"] = datos(cuerpo, reglas)
    partner = registro.get("partner") or "El corresponsal"
    llave = registro.get("valor_consulta") or registro.get("caso_partner") or ""
    ref = f" de {llave}" if llave else ""

    # «needs attention» no trae una lista nueva: dice que lo ya enviado no sirve.
    if registro.get("tipo") == "rfi_recordatorio" and not r["items"]:
        base = (f"{partner} revisó la documentación{ref} y dice que necesita corrección. "
                f"Hay que volver a pedirle al cliente lo que rechazaron — el detalle está "
                f"en el formulario del partner.")
        return {**r, "resumen": base + (f" Plazo: {r['plazo']}." if r["plazo"] else "")}

    if not registro.get("accionable"):
        tipo = {"resuelto": "avisa que cerró el caso",
                "otp": "manda un código de verificación",
                "payout_liberado": "avisa que el pago se liberó",
                "verificacion_aprobada": "avisa que la verificación fue aprobada"}.get(
                    registro.get("tipo"), "manda una notificación")
        return {**r, "resumen": f"{partner} {tipo}{ref}. No requiere acción."}

    # Preguntas a medida: no son catalogables, pero SON el pedido. Van textuales,
    # nunca parafraseadas: parafrasear es donde se cuela lo inventado.
    sueltas = [l for l in r["no_reconocido"]
               if re.search(r"^\d+[.)]|\?$|^(?:pls|please|explain|confirm|provide)", l, re.I)][:2]

    if r["items"]:
        lista = "; ".join(i["es"] for i in r["items"])
        frase = f"{partner} pide {len(r['items'])} dato(s){ref}: {lista}."
        if sueltas:
            frase += " Además, textual: «" + "»; «".join(sueltas) + "»."
    elif sueltas:
        frase = f"{partner} pide{ref}, textual: «" + "»; «".join(sueltas) + "»."
    elif r["no_reconocido"]:
        frase = (f"{partner} pide información{ref}, pero el pedido no coincide con "
                 f"ningún ítem conocido. Hay que leer el correo.")
    else:
        frase = (f"{partner} abrió un requerimiento{ref} y no se pudo extraer qué pide. "
                 f"Hay que leer el correo.")

    if r["plazo"]:
        frase += f" Plazo: {r['plazo']}."
    return {**r, "resumen": frase}
