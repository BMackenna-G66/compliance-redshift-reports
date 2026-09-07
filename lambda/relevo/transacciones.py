"""La tabla de transacciones: una fila por identificador, no por correo.

Por qué no alcanza la lista de mensajes:

  · un correo puede traer VARIAS transacciones — Nium encadena PY separados por
    barra, OZ manda «IDs A / B» en el asunto;
  · varias correos pueden hablar de LA MISMA transacción — Currencycloud
    promedia 2,6 mensajes por caso.

Así que la unidad de seguimiento es el identificador, y cada fila arrastra los
correos donde apareció para poder volver al original.
"""
from .requerimiento import resumir


def _fecha(m):
    f = m.get("fecha") or ""
    if isinstance(f, str) and f.isdigit():        # internalDate de Gmail, en ms
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(f) / 1000, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    return str(f)[:16]


def construir(registros, mensajes, reglas):
    """`mensajes` es {id: mensaje}. Devuelve la lista de transacciones."""
    filas = {}
    for reg in registros:
        if not reg.get("partner"):
            continue
        for h in reg.get("ids", []):
            if h["rol"] != "llave_consulta" or not h["valido"]:
                continue
            clave = (h["llave"], h["valor_consulta"])
            f = filas.setdefault(clave, {
                "llave": h["llave"], "valor": h["valor_consulta"],
                "crudo": h["valor_crudo"], "de_quien": h["de_quien"],
                "partner": reg["partner"], "caso_partner": reg.get("caso_partner", ""),
                "correos": [], "resumen": "", "items": [], "plazo": "", "datos": {},
                "accionable": False, "estado": reg.get("estado", ""),
            })
            m = mensajes.get(reg.get("id")) or {}
            f["correos"].append({
                "id": reg.get("id"),
                "thread_id": m.get("thread_id") or "",
                "asunto": reg.get("asunto", ""),
                "tipo": reg.get("tipo", ""),
                "accionable": reg.get("accionable"),
                "fecha": _fecha(m),
                "ambito": h["ambito"],
                "url_gmail": (f"https://mail.google.com/mail/u/0/#all/{m['thread_id']}"
                              if m.get("thread_id") else ""),
            })
            if not f["caso_partner"] and reg.get("caso_partner"):
                f["caso_partner"] = reg["caso_partner"]
            # Se guardan TODAS las lecturas y se resuelven al final. Los datos de
            # la transacción no cambian entre correos: si el último es un aviso
            # corto sin tabla, los datos siguen estando en uno anterior. Tomar
            # sólo el más reciente los perdía.
            if reg.get("accionable"):
                f["accionable"] = True
                if m.get("cuerpo"):
                    f.setdefault("_lecturas", []).append((_fecha(m), resumir(reg, m["cuerpo"], reglas)))

    for f in filas.values():
        # de la más reciente a la más vieja
        lecturas = sorted(f.pop("_lecturas", []), key=lambda x: x[0], reverse=True)
        for _, s in lecturas:
            # el resumen y el pedido, del correo más reciente que los tenga
            if not f["resumen"] and (s["items"] or s["resumen"]):
                f.update(resumen=s["resumen"], items=s["items"], plazo=s["plazo"],
                         no_reconocido=s["no_reconocido"])
            if not f["items"] and s["items"]:
                f.update(items=s["items"], no_reconocido=s["no_reconocido"])
            if not f["plazo"] and s["plazo"]:
                f["plazo"] = s["plazo"]
            # los datos se acumulan campo por campo; gana el correo más reciente
            for k, v in (s.get("datos") or {}).items():
                f["datos"].setdefault(k, v)

        f["correos"].sort(key=lambda c: c["fecha"], reverse=True)
        f["n_correos"] = len(f["correos"])
        f["ultima"] = f["correos"][0]["fecha"] if f["correos"] else ""
        f.pop("_ref", None)
        if not f["resumen"]:
            f["resumen"] = ("Sin cuerpo descargado para esta transacción: no se puede decir "
                            "qué pide el partner." if f["accionable"]
                            else "Sólo notificaciones informativas. No requiere acción.")
    return sorted(filas.values(), key=lambda f: f["ultima"], reverse=True)
