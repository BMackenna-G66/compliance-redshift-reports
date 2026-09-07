"""Paso 5, la parte que decide: de una transacción a un cliente.

La consulta en sí la hace `redshift.py`. Acá vive lo que hay que pensar:

  · **Unicidad.** Toda consulta trae `LIMIT 2`. Dos filas no es «tomo la
    primera»: es `ambiguo`, y un caso ambiguo no dispara ningún correo. Mandarle
    a un cliente el requerimiento de otro es peor que no mandar nada.

  · **Completitud.** Encontrar la fila no alcanza: si no hay correo del cliente
    no se le puede pedir nada. Eso es `incompleto`, un estado distinto de
    `sin_match`, porque se arregla en la base y no en la extracción.

  · **Verificación cruzada.** El correo del partner suele traer beneficiario y
    monto. Si la fila que volvió no coincide, el match es sospechoso aunque el
    identificador calce: puede ser un ID reusado, o un correo que hablaba de
    otra operación. Se marca y se muestra; no se descarta solo.

El caché es en disco y por (llave, valor), no por correo: la misma transacción
aparece en varios correos y la respuesta de la base no cambia entre ellos.
"""
import json
import os

from . import deposito
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .redshift import ErrorRedshift, Redshift

ALIAS_CLIENTE = ("cliente_id", "cliente_nombre", "cliente_correo",
                 "cliente_documento", "cliente_pais")
ALIAS_TX = ("tx_monto", "tx_moneda", "tx_fecha", "tx_estado", "tx_beneficiario",
            "tx_remitente")

ESTADOS = {
    "sin_consulta": "No hay consulta activa para este tipo de llave. Falta configurar consultas.json.",
    "encontrado":   "Una fila, con correo de cliente. Listo para pedirle la documentación.",
    "incompleto":   "Se encontró la transacción pero no tiene correo de cliente. Se arregla en la base.",
    "ambiguo":      "La consulta devolvió más de una fila. No se envía nada: hay que desempatar a mano.",
    "sin_match":    "El identificador no está en la base. O no lo guardamos, o vino corrupto.",
    "error":        "La consulta falló. Ver el detalle; casi siempre es red o permisos.",
}

_CACHE = Path(os.environ.get("RELEVO_DATOS") or
              Path(__file__).resolve().parent.parent / "datos") / "clientes.jsonl"


# --------------------------------------------------------------------------
# comparación laxa, para la verificación cruzada

def _plano(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9 ]", " ", s.upper())


def _parecen(a, b):
    """¿Dos nombres son el mismo? Devuelve True / False / None (no comparable).

    Laxo a propósito: los partners escriben «JUAN PEREZ GOMEZ» donde la base
    dice «Juan Pérez», o al revés. Se pide que la mitad de las palabras del más
    corto estén en el otro.
    """
    ta = {p for p in _plano(a).split() if len(p) > 2}
    tb = {p for p in _plano(b).split() if len(p) > 2}
    if not ta or not tb:
        return None
    comunes = len(ta & tb)
    return comunes >= max(1, min(len(ta), len(tb)) // 2)


def _numero(s):
    """Saca el valor numérico de un monto escrito por cualquiera. None si no hay.

    El problema real: los partners escriben en las dos convenciones. dLocal y OZ
    mandan «1.234,56» y Currencycloud y Nium «1,234.56», así que el punto no
    significa lo mismo según quién escribió. Las reglas, en orden:

      · si están los dos separadores, el de más a la derecha es el decimal;
      · si hay uno solo y aparece varias veces, es de miles («1.234.567»);
      · si hay uno solo y lo siguen exactamente tres dígitos, es de miles
        —«5.000» son cinco mil, no cinco: leerlo mal hacía que la verificación
        gritara «no coincide» contra una base que decía lo mismo;
      · si no, es decimal («12,5», «1.50»).
    """
    t = re.sub(r"[^\d.,]", "", str(s or ""))
    if not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        dec = max(t.rfind(","), t.rfind("."))
        t = re.sub(r"[.,]", "", t[:dec]) + "." + re.sub(r"[^\d]", "", t[dec + 1:])
    elif "," in t or "." in t:
        sep = "," if "," in t else "."
        ent, _, frac = t.rpartition(sep)
        de_miles = t.count(sep) > 1 or len(frac) == 3
        t = re.sub(r"[^\d]", "", t) if de_miles else re.sub(r"[^\d]", "", ent) + "." + frac
    try:
        return float(t)
    except ValueError:
        return None


def _mismo_monto(a, b):
    na, nb = _numero(a), _numero(b)
    if na is None or nb is None:
        return None
    if na == 0 or nb == 0:
        return na == nb
    return abs(na - nb) / max(na, nb) < 0.01      # 1% de tolerancia por comisiones


def _dato(datos, campo):
    """Un campo de `datos`, venga como texto o como {es, valor}.

    La transacción los guarda con etiqueta (`{"es": "Monto", "valor": "usd 200"}`)
    porque el front necesita mostrarlos en español. Acá sólo interesa el valor,
    y conviene aceptar las dos formas: así esta función también sirve suelta.
    """
    v = (datos or {}).get(campo)
    if isinstance(v, dict):
        v = v.get("valor")
    return str(v).strip() if v not in (None, "") else ""


def verificar(fila, datos):
    """Cruza la fila de la base contra lo que decía el correo del partner."""
    fuera = {}
    beneficiario = " ".join(x for x in (_dato(datos, "beneficiario"),
                                        _dato(datos, "beneficiario_apellido")) if x)
    if fila.get("tx_beneficiario") and beneficiario:
        fuera["beneficiario"] = {"base": str(fila["tx_beneficiario"]), "correo": beneficiario,
                                 "coincide": _parecen(fila["tx_beneficiario"], beneficiario)}
    # El remitente vale tanto como el beneficiario, y para un payin de
    # Currencycloud vale más: el correo del partner nombra a quien manda.
    remitente = _dato(datos, "remitente")
    if fila.get("tx_remitente") and remitente:
        fuera["remitente"] = {"base": str(fila["tx_remitente"]), "correo": remitente,
                              "coincide": _parecen(fila["tx_remitente"], remitente)}
    monto = _dato(datos, "monto")
    if fila.get("tx_monto") not in (None, "") and monto:
        fuera["monto"] = {"base": str(fila["tx_monto"]), "correo": monto,
                          "coincide": _mismo_monto(fila["tx_monto"], monto)}
    return fuera


# --------------------------------------------------------------------------
# resolución

def _normalizar_fila(fila):
    """Separa los alias del contrato del resto, que va a `extra`."""
    conocidos = set(ALIAS_CLIENTE) | set(ALIAS_TX)
    limpia = {}
    extra = {}
    for k, v in fila.items():
        if isinstance(v, (datetime,)):
            v = v.isoformat(sep=" ", timespec="seconds")
        elif v is not None and not isinstance(v, (str, int, float, bool)):
            v = str(v)
        (limpia if k in conocidos else extra)[k] = v
    for a in ALIAS_CLIENTE + ALIAS_TX:
        limpia.setdefault(a, None)
    limpia["extra"] = extra
    return limpia


def resolver(tx, rs, consultas, datos=None):
    """Resuelve UNA transacción. Nunca levanta: el error es un estado más."""
    llave, valor = tx.get("llave", ""), tx.get("valor", "")
    base = {"llave": llave, "valor": valor, "estado": "", "motivo": "",
            "cliente": None, "verificacion": {}, "filas": 0, "ms": 0,
            "cuando": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}

    cfg = (consultas.get("consultas") or {}).get(llave)
    if not cfg or not cfg.get("activa"):
        base.update(estado="sin_consulta",
                    motivo=f"no hay consulta activa para `{llave}` en consultas.json")
        return base
    if not valor:
        base.update(estado="sin_match", motivo="la transacción no tiene valor de llave")
        return base

    try:
        filas, ms = rs.dicts(cfg["sql"], {"valor": valor}, timeout=cfg.get("timeout"))
    except ErrorRedshift as e:
        base.update(estado="error", motivo=str(e))
        return base

    base["ms"] = ms
    base["filas"] = len(filas)
    if not filas:
        base.update(estado="sin_match",
                    motivo=f"`{valor}` no aparece en la base con la consulta de `{llave}`")
        return base
    if len(filas) > 1:
        base.update(estado="ambiguo",
                    motivo=f"`{valor}` devolvió {len(filas)} filas: no se puede decidir el cliente")
        base["cliente"] = _normalizar_fila(filas[0])
        return base

    fila = _normalizar_fila(filas[0])
    base["cliente"] = fila
    base["verificacion"] = verificar(fila, datos or tx.get("datos") or {})
    if not fila.get("cliente_correo"):
        base.update(estado="incompleto",
                    motivo="la fila no trae correo de cliente: no se le puede pedir la documentación")
        return base
    base["estado"] = "encontrado"
    discrepa = [k for k, v in base["verificacion"].items() if v.get("coincide") is False]
    base["motivo"] = ("coincide con el correo del partner" if not discrepa
                      else "OJO: no coincide " + " ni ".join(discrepa) + " con lo que dice el correo")
    return base


def resolver_muchas(transacciones, consultas, rs=None, cache=True, limite=0, forzar=False,
                    al_avanzar=None):
    """Resuelve una lista de transacciones reusando una sola conexión.

    Devuelve {"llave|valor": resultado}. Si `cache`, no vuelve a preguntar por
    lo ya resuelto (salvo `forzar`, o si el resultado anterior fue un error —
    un error casi siempre es transitorio y no debe quedar pegado).
    """
    previos = leer_cache() if cache else {}
    fuera = dict(previos) if cache else {}
    propio = rs is None
    rs = rs or Redshift()
    nuevos, hechos = [], 0
    try:
        for tx in transacciones:
            k = f"{tx.get('llave','')}|{tx.get('valor','')}"
            anterior = previos.get(k)
            if (not forzar and anterior
                    and anterior.get("estado") not in ("error", "sin_consulta")):
                continue
            if limite and hechos >= limite:
                break
            r = resolver(tx, rs, consultas)
            fuera[k] = r
            nuevos.append(r)
            hechos += 1
            if al_avanzar:
                al_avanzar(hechos, r)
            # Si la conexión se cayó, no tiene sentido seguir golpeando: se corta
            # y lo que falta queda para la próxima vuelta.
            if r["estado"] == "error" and "no se pudo conectar" in r["motivo"]:
                break
    finally:
        if propio:
            rs.cerrar()
    if cache and nuevos:
        guardar_cache(nuevos)
    return fuera


# --------------------------------------------------------------------------
# caché en disco

def leer_cache(ruta=None):
    """Caché de la resolución en Redshift, indexado por "llave|valor".

    Sin `ruta` y con el depósito activo lee de S3, un objeto por llave — el
    equivalente de la PK `llave_valor` de `relevo_clientes` en §4.
    """
    if ruta is None and deposito.activo():
        return {f"{r.get('llave','')}|{r.get('valor','')}": r
                for r in deposito.todos("clientes")}
    ruta = Path(ruta or _CACHE)
    if not ruta.exists():
        return {}
    fuera = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            r = json.loads(linea)
        except json.JSONDecodeError:
            continue                              # línea a medio escribir: se ignora
        fuera[f"{r.get('llave','')}|{r.get('valor','')}"] = r
    return fuera


def guardar_cache(resultados, ruta=None):
    """Reescribe el archivo deduplicado. Atómico: se escribe al lado y se mueve.

    En S3 no hay reescritura: cada resultado es su propio objeto y se
    sobreescribe al re-resolver, tal como dice §4 para `relevo_clientes`.
    Devuelve cuántos quedaron en total, como la versión en disco.
    """
    if ruta is None and deposito.activo():
        for r in resultados:
            llave = f"{r.get('llave','')}|{r.get('valor','')}"
            deposito.poner("clientes", deposito.clave_segura(llave), r)
        return len(leer_cache())
    ruta = Path(ruta or _CACHE)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    todo = leer_cache(ruta)
    for r in resultados:
        todo[f"{r.get('llave','')}|{r.get('valor','')}"] = r
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in todo.values():
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    os.replace(tmp, ruta)
    return len(todo)


def adjuntar(transacciones, cache=None):
    """Pega el resultado guardado a cada transacción, para que el front lo vea."""
    cache = cache if cache is not None else leer_cache()
    for tx in transacciones:
        tx["cliente"] = cache.get(f"{tx.get('llave','')}|{tx.get('valor','')}")
    return transacciones


def cargar_consultas(ruta=None):
    ruta = Path(ruta or Path(__file__).resolve().parent / "consultas.json")
    if not ruta.exists():
        return {"consultas": {}, "nota": f"no existe {ruta}"}
    return json.loads(ruta.read_text(encoding="utf-8"))
