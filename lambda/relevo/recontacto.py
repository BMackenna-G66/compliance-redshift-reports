"""Recontacto: la precedencia de mantenedores y la cola de vencidos (§7).

El motor ya calcula `intentos`, `ultimo_contacto`, `proximo_contacto`,
`vencido`, `agotado` y `faltantes` — pero con una `POLITICA` fija en el módulo.
Lo que falta, y va acá, es la **precedencia de §7**:

    plazo escrito en el correo del partner    ← lo más específico
            ↓  si no hay
    mantenedor del partner   (relevo_config: politica_<partner>)
            ↓  si no hay
    mantenedor general       (relevo_config: politica_general)
                              por defecto: 3 días hábiles, 3 intentos

Va en una capa encima y no dentro de `casos.py` a propósito: ese módulo está
cubierto por los 104 tests y su cálculo es correcto — lo que cambia es de
dónde salen los parámetros, que es una decisión de configuración, no del motor.

**Nada de acá contacta a nadie.** Calcula la cola y compone el recontacto; el
envío sigue pasando por `envio.enviar()`, con su interruptor y sus
salvaguardas. Ningún proceso programado importa este módulo.
"""
import re
import time
from datetime import datetime, timedelta, timezone

from . import casos, checklist, correo

POR_DEFECTO = {"dias_habiles": 3, "intentos": 3}

# "8 de septiembre de 2026", "08-09-2026", "2026-09-08", "en 5 días hábiles"
_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
          "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
          "noviembre": 11, "diciembre": 12}


def _fecha_del_plazo(texto, tz):
    """Intenta leer una fecha concreta del plazo que escribió el partner.

    Devuelve datetime con zona, o None. Es deliberadamente conservador: si no
    reconoce el formato devuelve None y se cae al mantenedor, que es un
    comportamiento definido. Adivinar una fecha de un texto ambiguo sería
    peor que no usarla.
    """
    s = str(texto or "").strip().lower()
    if not s:
        return None
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+de\s+(\d{4}))?", s)
    if m and m.group(2) in _MESES:
        dia, mes = int(m.group(1)), _MESES[m.group(2)]
        anio = int(m.group(3)) if m.group(3) else datetime.now(tz).year
        try:
            return datetime(anio, mes, dia, 23, 59, 59, tzinfo=tz)
        except ValueError:
            return None
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            23, 59, 59, tzinfo=tz)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)),
                            23, 59, 59, tzinfo=tz)
        except ValueError:
            return None
    return None


def politica_de(caso, config=None):
    """Resuelve la precedencia de §7. Devuelve la política y de dónde salió."""
    config = config if config is not None else _config()
    partner = str(caso.get("partner") or "").lower().replace(" ", "_")
    clave = f"politica_{partner}"
    if isinstance(config.get(clave), dict):
        p = dict(POR_DEFECTO); p.update(config[clave])
        return {**p, "fuente": clave}
    if isinstance(config.get("politica_general"), dict):
        p = dict(POR_DEFECTO); p.update(config["politica_general"])
        return {**p, "fuente": "politica_general"}
    return {**POR_DEFECTO, "fuente": "por_defecto"}


def _config():
    from . import api as rapi
    return rapi.leer_config()


def _habiles(desde, dias):
    """Igual que el motor: sin calendario de feriados. Errar por un día no
    rompe nada y un calendario chileno no vale la pena acá."""
    d, sumados = desde, 0
    while sumados < dias:
        d += timedelta(days=1)
        if d.weekday() < 5:
            sumados += 1
    return d


def seguimiento(caso, config=None, hoy=None):
    """Seguimiento con la política resuelta y los faltantes del checklist.

    Dos diferencias con lo que calcula el motor:

    1. Los parámetros salen de la precedencia de §7, no de la constante.
    2. `faltantes` sale del **checklist**, que es la fuente de verdad desde el
       paso 7: el motor los deducía del `detalle.recibidos` de las acciones, y
       eso no sabe nada de lo que una persona marcó `entregado`.
    """
    hoy = hoy or datetime.now(timezone.utc).astimezone()
    pol = politica_de(caso, config)
    base = dict(caso.get("seguimiento") or {})

    contactos = [a for a in (caso.get("acciones") or [])
                 if a.get("accion") in casos.CONTACTOS]
    intentos = len(contactos)

    # Faltantes desde el checklist. Si el caso no tiene checklist —porque el
    # pedido se marcó a mano y no salió de acá— se conserva lo que dedujo el
    # motor, que es mejor que nada.
    res = checklist.resumen(caso.get("id") or "")
    if res.get("total"):
        faltantes = res.get("faltantes") or []
        fuente_faltantes = "checklist"
    else:
        faltantes = [i.get("es") or i.get("item") if isinstance(i, dict) else i
                     for i in (base.get("faltantes") or [])]
        fuente_faltantes = "acciones"

    fuera = {
        "intentos": intentos,
        "ultimo_contacto": contactos[-1].get("cuando") if contactos else "",
        "proximo_contacto": "",
        "vencido": False,
        "agotado": intentos >= int(pol["intentos"]),
        "faltantes": faltantes,
        "fuente_faltantes": fuente_faltantes,
        "politica": pol,
        "plazo_partner": "",
        "checklist": {k: v for k, v in res.items() if k != "faltantes"},
    }

    if not contactos:
        return fuera
    if caso.get("estado") not in ("pedido_enviado", "recontactado", "respuesta_parcial"):
        return fuera

    ult = casos._fecha(fuera["ultimo_contacto"], hoy.tzinfo)
    if ult is None:
        return fuera

    # Precedencia: el plazo del correo del partner manda sobre el mantenedor,
    # pero sólo si es POSTERIOR al último contacto. Un plazo que ya venció
    # cuando se envió el pedido no sirve para calcular el próximo contacto.
    texto_plazo = caso.get("plazo")
    if isinstance(texto_plazo, dict):
        texto_plazo = texto_plazo.get("texto") or texto_plazo.get("fecha") or ""
    del_partner = _fecha_del_plazo(texto_plazo, hoy.tzinfo)
    if del_partner and del_partner > ult:
        prox = del_partner
        fuera["plazo_partner"] = str(texto_plazo)
        fuera["politica"] = {**pol, "fuente": "plazo_del_partner"}
    else:
        prox = _habiles(ult, int(pol["dias_habiles"]))

    fuera["proximo_contacto"] = prox.isoformat(timespec="seconds")
    fuera["vencido"] = hoy >= prox
    return fuera


def cola(casos_lista, config=None, hoy=None, solo_vencidos=True):
    """La cola de recontacto, ordenada por lo más atrasado primero.

    Excluye lo `agotado`: si ya se hicieron los intentos que la política
    permite, el caso no vuelve a la cola — lo que corresponde ahí es darlo por
    sin respuesta, y eso lo decide una persona.
    """
    config = config if config is not None else _config()
    hoy = hoy or datetime.now(timezone.utc).astimezone()
    fuera = []
    for c in casos_lista:
        if c.get("estado") not in ("pedido_enviado", "recontactado", "respuesta_parcial"):
            continue
        s = seguimiento(c, config, hoy)
        if s["agotado"]:
            continue
        if solo_vencidos and not s["vencido"]:
            continue
        cl = c.get("cliente") or {}
        d = cl.get("cliente") if isinstance(cl.get("cliente"), dict) else cl
        fuera.append({
            "caso_id": c.get("id"),
            "partner": c.get("partner"),
            "estado": c.get("estado"),
            "cliente_nombre": (d or {}).get("cliente_nombre"),
            "cliente_correo": (d or {}).get("cliente_correo"),
            "intentos": s["intentos"],
            "ultimo_contacto": s["ultimo_contacto"],
            "proximo_contacto": s["proximo_contacto"],
            "vencido": s["vencido"],
            "faltantes": s["faltantes"],
            "fuente_faltantes": s["fuente_faltantes"],
            "politica": s["politica"],
            "plazo_partner": s["plazo_partner"],
        })
    fuera.sort(key=lambda x: x.get("proximo_contacto") or "")
    return fuera


def previsualizar_recontacto(caso_id):
    """El correo de recontacto: sólo lo que falta. No toca la red."""
    from . import envio, vista
    d, meta = vista.completa()
    if d is None:
        return {"error": "sin snapshot", "meta": meta}
    caso = next((c for c in d["casos"] if c.get("id") == caso_id), None)
    if caso is None:
        return {"error": f"caso '{caso_id}' no encontrado"}

    s = seguimiento(caso)
    if not s["faltantes"]:
        return {"error": "no queda nada por pedir: el checklist no tiene pendientes",
                "checklist": s["checklist"]}

    # Se recompone con SÓLO los faltantes: recontactar pidiendo todo de nuevo
    # es lo que hace que un cliente deje de responder.
    caso_recorte = dict(caso)
    caso_recorte["items"] = [{"item": f, "es": f} for f in s["faltantes"]]
    c = correo.componer(
        caso_recorte,
        nota=("Te escribimos de nuevo porque todavía nos falta parte de la "
              "información. Si ya la enviaste, avísanos respondiendo este correo."))
    permitido, motivo = envio.puede_enviar(caso.get("partner"))
    return {
        "caso_id": caso_id,
        "es_recontacto": True,
        "intento_numero": s["intentos"] + 1,
        "de_maximo": s["politica"]["intentos"],
        "politica": s["politica"],
        "asunto": c["asunto"],
        "para": c["para"],
        "html": c["html"],
        "texto": c["texto"],
        "faltantes": s["faltantes"],
        "fuente_faltantes": s["fuente_faltantes"],
        "avisos": c["avisos"],
        "puede_enviar": bool(permitido and c["para"]),
        "bloqueos": [x for x in (motivo, "" if c["para"] else
                                 "el caso no tiene correo de cliente") if x],
    }


def recontactar(caso_id, quien="", nota=""):
    """Manda el recontacto. Respeta el interruptor y sólo pide lo que falta."""
    from . import envio
    if not str(quien or "").strip():
        return {"enviado": False, "error": "quien es requerido"}

    pv = previsualizar_recontacto(caso_id)
    if pv.get("error"):
        return {"enviado": False, "error": pv["error"]}
    if not pv["puede_enviar"]:
        return {"enviado": False, "bloqueado": True,
                "error": "; ".join(pv["bloqueos"]) or "bloqueado"}
    if pv["intento_numero"] > int(pv["politica"]["intentos"]):
        return {"enviado": False, "error":
                f"se agotaron los {pv['politica']['intentos']} intentos que permite "
                f"la política ({pv['politica']['fuente']})"}

    # Se reusa envio.enviar con el bloqueo de doble envío saltado a propósito:
    # un recontacto ES un segundo contacto. El tope de intentos es lo que lo
    # limita, no el bloqueo de duplicados.
    r = envio.enviar(caso_id, quien=quien, saltar_bloqueo_doble=True,
                     nota=nota or ("Te escribimos de nuevo porque todavía nos falta "
                                   "parte de la información."))
    if r.get("enviado"):
        try:
            casos.registrar(caso_id, "recontactado", quien=quien,
                            detalle={"ref": r.get("ref"), "intento": pv["intento_numero"],
                                     "faltantes": pv["faltantes"]})
        except Exception as e:
            print(f"[relevo] recontacto enviado pero no pude anotar la acción: {e}")
    return {**r, "intento_numero": pv["intento_numero"], "faltantes": pv["faltantes"]}
