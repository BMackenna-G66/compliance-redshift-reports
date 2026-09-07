"""El caso: la unidad de seguimiento y de trabajo.

Hasta acá la unidad era la transacción, y eso alcanzaba para medir la
extracción. Para operar no alcanza, y los datos lo dicen: el cliente 3950037
tiene seis transacciones abiertas, pero Nium las agrupó todas en **un** caso
(el 1088170). Mandarle seis correos pidiéndole documentos sería seis veces el
mismo pedido.

Así que el grano del caso es el que el partner ya usa:

  · si el correo trae número de caso del partner  -> (partner, caso_partner)
    Currencycloud lo trae en el 100% de los casos y Nium en la mitad.
  · si no                                          -> (partner, llave, valor)
    dLocal y OZ no mandan número de caso: ahí el caso ES la transacción.

El id del caso tiene que ser **estable**: es la clave del registro de acciones
y la que va a espejarse al CRM. Por eso se deriva de esos campos y nunca de
algo que cambie al llegar un correo nuevo, como una fecha o un contador.

El estado NO se guarda: se deriva. Lo que se guarda es el registro de acciones
—qué se hizo, cuándo y quién— y el estado sale de la última acción más lo que
ya se sabe del caso. Un estado mutable se desincroniza en silencio; un registro
de acciones se puede auditar, y es exactamente lo que el CRM quiere recibir.
"""
import json
import os

from . import deposito
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Las acciones que alguien puede ejecutar sobre un caso.
#
# El ciclo NO es lineal, y ese es el punto: se pide, el cliente no contesta, se
# recontacta, contesta a medias, se vuelve a pedir lo que falta. Por eso
# `recontactado` es repetible y por eso el estado es la última acción en el
# tiempo y no «la más avanzada»: después de una respuesta parcial y un
# recontacto, la verdad es que estamos esperando de nuevo.
ACCIONES = ["pedido_enviado", "recontactado", "respuesta_parcial", "respuesta_recibida",
            "devuelto", "cerrado", "sin_respuesta", "descartado"]

# Terminales: una vez registradas mandan, sin importar qué venga después.
TERMINALES = ["devuelto", "cerrado", "sin_respuesta", "descartado"]

# Las que cuentan como «le escribimos al cliente». Son las que suman intento.
CONTACTOS = ["pedido_enviado", "recontactado"]

# Política de recontacto. Vive acá y no repartida en el código: cambiarla es
# cambiar estas dos líneas.
POLITICA = {
    "dias_para_recontactar": 3,      # días hábiles desde el último contacto
    "max_intentos": 3,               # después de esto el caso queda `agotado`
}

ESTADOS = {
    "informativo":      "Sólo notificaciones. No requiere acción.",
    "sin_cliente":      "No se pudo ubicar al cliente. No se le puede pedir nada todavía.",
    "sin_correo":       "Se ubicó al cliente pero no tiene correo. Se arregla en la base.",
    "listo_para_pedir": "Cliente ubicado con correo. Falta pedirle la documentación.",
    "pedido_enviado":   "Se le pidió la documentación al cliente. Esperando respuesta.",
    "recontactado":     "Se le volvió a pedir. Esperando respuesta.",
    "respuesta_parcial": "El cliente respondió pero falta parte de lo pedido.",
    "respuesta_recibida": "El cliente respondió. Falta armar la devolución al partner.",
    "sin_respuesta":    "Se agotaron los intentos y el cliente no respondió.",
    "devuelto":         "Se le devolvió al partner. Esperando cierre.",
    "cerrado":          "Caso cerrado.",
    "descartado":       "Se decidió no accionar este caso.",
}

# Etapa numérica, para ordenar y para pintar el flujograma. Los negativos son
# los estados que no están sobre el carril feliz.
ETAPA = {"informativo": -2, "descartado": -2, "sin_respuesta": -2,
         "sin_cliente": -1, "sin_correo": -1,
         "listo_para_pedir": 0, "pedido_enviado": 1, "recontactado": 1,
         "respuesta_parcial": 2, "respuesta_recibida": 2, "devuelto": 3, "cerrado": 4}

_REGISTRO = Path(os.environ.get("RELEVO_DATOS") or
                 Path(__file__).resolve().parent.parent / "datos") / "acciones.jsonl"


def _slug(s):
    """Un trozo de id: sin acentos, sin espacios, estable."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def id_de(transaccion):
    """El id estable del caso al que pertenece una transacción."""
    p = _slug(transaccion.get("partner"))
    if transaccion.get("caso_partner"):
        return f"{p}:caso:{_slug(transaccion['caso_partner'])}"
    return f"{p}:{_slug(transaccion.get('llave'))}:{_slug(transaccion.get('valor'))}"


def construir(transacciones, acciones=None):
    """Agrupa transacciones en casos. `transacciones` ya trae el cliente pegado."""
    acciones = acciones if acciones is not None else leer_acciones()
    casos = {}
    for t in transacciones:
        cid = id_de(t)
        c = casos.setdefault(cid, {
            "id": cid, "partner": t["partner"], "caso_partner": t.get("caso_partner", ""),
            "transacciones": [], "items": [], "no_reconocido": [], "plazo": "",
            "resumen": "", "accionable": False, "cliente": None, "correos": [],
        })
        c["transacciones"].append({
            "llave": t["llave"], "valor": t["valor"], "crudo": t.get("crudo", ""),
            "resumen": t.get("resumen", ""), "datos": t.get("datos", {}),
            "ultima": t.get("ultima", ""), "n_correos": t.get("n_correos", 0),
        })
        c["correos"].extend(t.get("correos") or [])
        if t.get("accionable"):
            c["accionable"] = True
        # El pedido se une entre las transacciones del caso: el partner puede
        # detallar los documentos en un correo y agregar uno en el siguiente.
        for it in t.get("items") or []:
            if it["item"] not in {x["item"] for x in c["items"]}:
                c["items"].append(it)
        for l in t.get("no_reconocido") or []:
            if l not in c["no_reconocido"]:
                c["no_reconocido"].append(l)
        # Del plazo gana el más corto: si dos correos del mismo caso dan plazos
        # distintos, el que manda es el que vence primero.
        if t.get("plazo") and (not c["plazo"] or t["plazo"] < c["plazo"]):
            c["plazo"] = t["plazo"]
        if not c["resumen"] and t.get("resumen"):
            c["resumen"] = t["resumen"]
        # El cliente es del caso, no de la transacción: se toma el primero que
        # resuelva y se avisa si dos transacciones del caso apuntan a clientes
        # distintos, que sería una señal de que el agrupado está mal.
        res = t.get("cliente") or {}
        cli = res.get("cliente") or {}
        if cli.get("cliente_id"):
            if c["cliente"] is None:
                c["cliente"] = {**cli, "verificacion": res.get("verificacion") or {},
                                "estado_consulta": res.get("estado")}
                if not c["cliente"].get("cliente_nombre") and cli.get("tx_remitente"):
                    c["cliente"]["cliente_nombre"] = cli["tx_remitente"]
            elif str(c["cliente"].get("cliente_id")) != str(cli["cliente_id"]):
                c.setdefault("alertas", []).append(
                    f"dos clientes distintos en el mismo caso: "
                    f"{c['cliente']['cliente_id']} y {cli['cliente_id']}")

    for c in casos.values():
        c["correos"].sort(key=lambda x: x.get("fecha", ""), reverse=True)
        c["n_transacciones"] = len(c["transacciones"])
        c["n_correos"] = len(c["correos"])
        c["ultima"] = c["correos"][0]["fecha"] if c["correos"] else ""
        c["primera"] = c["correos"][-1]["fecha"] if c["correos"] else ""
        c["acciones"] = sorted(acciones.get(c["id"], []), key=lambda a: a["cuando"])
        c["estado"] = _estado(c)
        c["etapa"] = ETAPA.get(c["estado"], 0)
        c["motivo_estado"] = ESTADOS.get(c["estado"], "")
        c["seguimiento"] = _seguimiento(c)
    return sorted(casos.values(), key=lambda c: c["ultima"], reverse=True)


def _estado(caso):
    """El estado sale de las acciones registradas; si no hay, de lo que se sabe.

    Las acciones ganan porque son hechos: si alguien mandó el correo, el caso
    está pedido aunque después la consulta a la base falle.

    Dos reglas, y en este orden:

      · **Las terminales son pegajosas.** Un caso cerrado, devuelto, descartado
        o sin respuesta no vuelve al ruedo porque alguien registre otra cosa.
      · **Entre las no terminales manda la última en el tiempo**, no «la más
        avanzada». Después de una respuesta parcial y un recontacto, la verdad
        es que estamos esperando de nuevo, y un `max()` por posición diría que
        el cliente ya respondió.
    """
    hechas = [a for a in caso["acciones"] if a["accion"] in ACCIONES]
    if hechas:
        terminales = [a for a in hechas if a["accion"] in TERMINALES]
        return (terminales[-1] if terminales else hechas[-1])["accion"]
    if not caso["accionable"]:
        return "informativo"
    cli = caso.get("cliente")
    if not cli:
        return "sin_cliente"
    if not cli.get("cliente_correo"):
        return "sin_correo"
    return "listo_para_pedir"


def _habiles(desde, dias):
    """Suma días hábiles. Sin feriados: no vale la pena un calendario chileno
    para decidir cuándo recontactar, y errar por un día no rompe nada."""
    d, sumados = desde, 0
    while sumados < dias:
        d += timedelta(days=1)
        if d.weekday() < 5:
            sumados += 1
    return d


def _fecha(texto, tz):
    """Una marca de tiempo del registro, siempre con zona.

    `registrar()` escribe con offset, pero el archivo se puede haber editado a
    mano o venir de una versión anterior. Comparar una fecha sin zona contra una
    con zona levanta TypeError, y eso se llevaba puesta la lista de casos
    completa por una sola línea mala. Se normaliza y, si no se puede leer, se
    devuelve None en vez de reventar.
    """
    try:
        d = datetime.fromisoformat(str(texto))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=tz)


def _seguimiento(caso, hoy=None):
    """Los campos derivados del recontacto: intentos, cuándo toca, qué falta.

    Nada de esto se guarda. Sale de contar las acciones, así que no puede
    quedar desincronizado con el histórico.
    """
    hoy = hoy or datetime.now(timezone.utc).astimezone()
    contactos = [a for a in caso["acciones"] if a["accion"] in CONTACTOS]
    fuera = {"intentos": len(contactos), "ultimo_contacto": "", "proximo_contacto": "",
             "vencido": False, "agotado": False, "faltantes": [], "recibidos": []}

    # Lo que el cliente ya mandó se acumula del detalle de sus respuestas, y lo
    # que falta es el pedido menos eso. Así el recontacto pide sólo el resto.
    for a in caso["acciones"]:
        if a["accion"] in ("respuesta_parcial", "respuesta_recibida"):
            for it in (a.get("detalle") or {}).get("recibidos") or []:
                if it not in fuera["recibidos"]:
                    fuera["recibidos"].append(it)
    pedidos = [i["item"] for i in caso["items"]]
    if a_recibir := [i for i in pedidos if i not in fuera["recibidos"]]:
        fuera["faltantes"] = [i for i in caso["items"] if i["item"] in a_recibir]

    if not contactos:
        return fuera
    fuera["ultimo_contacto"] = contactos[-1]["cuando"]
    fuera["agotado"] = len(contactos) >= POLITICA["max_intentos"]

    # El próximo contacto sólo tiene sentido si seguimos esperando al cliente.
    if caso["estado"] not in ("pedido_enviado", "recontactado", "respuesta_parcial"):
        return fuera
    ult = _fecha(fuera["ultimo_contacto"], hoy.tzinfo)
    if ult is None:
        return fuera
    prox = _habiles(ult, POLITICA["dias_para_recontactar"])
    fuera["proximo_contacto"] = prox.isoformat(timespec="seconds")
    fuera["vencido"] = hoy >= prox
    return fuera


# --------------------------------------------------------------------------
# el eje cliente: el 360

def por_cliente(casos):
    """Un cliente, todos sus casos. Es la vista que el CRM va a querer.

    Y es lo que evita el pedido repetido: si un cliente tiene tres casos
    abiertos, se le escribe UNA vez con los tres, no tres veces.
    """
    grupos = {}
    for c in casos:
        cli = c.get("cliente") or {}
        cid = cli.get("cliente_id")
        if not cid:
            continue
        g = grupos.setdefault(str(cid), {
            "cliente_id": cid, "cliente_nombre": cli.get("cliente_nombre") or "",
            "cliente_correo": cli.get("cliente_correo") or "",
            "cliente_pais": cli.get("cliente_pais") or "",
            "casos": [], "partners": [], "items": [], "plazo": "",
        })
        g["casos"].append(c)
        if c["partner"] not in g["partners"]:
            g["partners"].append(c["partner"])
        for it in c["items"]:
            if it["item"] not in {x["item"] for x in g["items"]}:
                g["items"].append(it)
        if c["plazo"] and (not g["plazo"] or c["plazo"] < g["plazo"]):
            g["plazo"] = c["plazo"]
        if not g["cliente_correo"] and cli.get("cliente_correo"):
            g["cliente_correo"] = cli["cliente_correo"]

    for g in grupos.values():
        g["n_casos"] = len(g["casos"])
        seg = [c.get("seguimiento") or {} for c in g["casos"]]
        # Lo que un operador necesita saber de un vistazo: a quién le toca
        # recontacto hoy y con quién ya se agotaron los intentos.
        g["vencidos"] = sum(1 for x in seg if x.get("vencido"))
        g["agotados"] = sum(1 for x in seg if x.get("agotado"))
        g["intentos"] = max((x.get("intentos", 0) for x in seg), default=0)
        g["proximo_contacto"] = min((x["proximo_contacto"] for x in seg
                                     if x.get("proximo_contacto")), default="")
        g["n_transacciones"] = sum(c["n_transacciones"] for c in g["casos"])
        g["por_pedir"] = [c for c in g["casos"] if c["estado"] == "listo_para_pedir"]
        g["n_por_pedir"] = len(g["por_pedir"])
        g["ultima"] = max((c["ultima"] for c in g["casos"]), default="")
        # La etapa del cliente es la del caso MENOS avanzado que siga vivo: es
        # lo que hay que mirar para saber si al cliente le falta algo.
        vivos = [c for c in g["casos"] if c["etapa"] >= 0 and c["estado"] != "cerrado"]
        g["etapa"] = min((c["etapa"] for c in vivos), default=4)
    return sorted(grupos.values(), key=lambda g: (-g["n_por_pedir"], g["ultima"]), reverse=False)


# --------------------------------------------------------------------------
# registro de acciones

def registrar(caso_id, accion, quien="", detalle=None, ruta=None):
    """Anota una acción. Sólo agrega: el histórico no se reescribe nunca."""
    if accion not in ACCIONES:
        raise ValueError(f"acción desconocida: {accion!r}. Válidas: {', '.join(ACCIONES)}")
    ev = {"caso": caso_id, "accion": accion, "quien": quien,
          "cuando": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
          "detalle": detalle or {}}
    if ruta is None and deposito.activo():
        # Un objeto por acción, bajo el prefijo del caso. Es append-only de
        # verdad: sin lectura-modificación-escritura, dos invocaciones
        # concurrentes no se pisan. Equivale a la clave compuesta
        # (caso_id, cuando) de `relevo_acciones` en §4.
        deposito.poner(
            f"acciones/{deposito.clave_segura(caso_id)}",
            deposito.clave_segura(f"{ev['cuando']}|{accion}|{quien}"),
            ev,
        )
        return ev

    ruta = Path(ruta or _REGISTRO)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    return ev


def leer_acciones(ruta=None):
    """Devuelve {caso_id: [acciones]}."""
    if ruta is None and deposito.activo():
        fuera = {}
        for ev in deposito.todos("acciones"):
            fuera.setdefault(ev.get("caso", ""), []).append(ev)
        for lista in fuera.values():
            lista.sort(key=lambda e: e.get("cuando", ""))
        return fuera
    ruta = Path(ruta or _REGISTRO)
    if not ruta.exists():
        return {}
    fuera = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            ev = json.loads(linea)
        except json.JSONDecodeError:
            continue                        # línea a medio escribir: se ignora
        fuera.setdefault(ev.get("caso", ""), []).append(ev)
    return fuera
