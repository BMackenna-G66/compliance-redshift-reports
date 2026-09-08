"""Resolución del cliente en Redshift: de identificador del partner a persona.

Paso 4 de la migración. El motor ya sabe resolver (`cliente.resolver_muchas`
con las cuatro consultas de §6); acá va lo que hace falta para que eso corra
como invocación de Lambda en vez de dentro del demonio del Mac.

Las tres reglas de §6 que no se pueden romper, y dónde viven:

1. **`LIMIT 2` en toda consulta.** Está en `consultas.json`, y `resolver()`
   marca `ambiguo` cuando vuelven dos filas. Un caso ambiguo no dispara
   ningún correo: mandarle a un cliente el requerimiento de otro es peor que
   no mandar nada.
2. **Sólo lectura, verificado en código.** La guarda de `redshift.py` rechaza
   toda sentencia que no empiece en SELECT o WITH y rechaza el `;` que
   permitiría encadenar una segunda. Con `awsuser` —superusuario del
   cluster— es lo único que separa un typo en `consultas.json` de un DROP en
   producción.
3. **Nunca despertar el cluster desde acá.** Un correo no lo justifica. Este
   módulo sólo usa la Data API; no llama a ResumeCluster ni a nada que
   encienda nada. Si el cluster está dormido la resolución se encola sola:
   `resolver_muchas` corta al primer error de conexión y no cachea los
   errores, así que la próxima vuelta reintenta desde donde quedó. Los casos
   se quedan en `sin_cliente` hasta que haya disponibilidad, y **la lectura
   de correo no se ve afectada** — son procesos separados y eso es lo que no
   se puede perder.
"""
import os
import time

from . import almacen, cliente, deposito, pipeline, reglas as R, transacciones as TX

# Tope por corrida. La consulta de Currencycloud escanea 1,8 M de filas con
# función JSON y tarda 13-18 s (§6), así que unas pocas por vuelta llenan el
# tiempo de una invocación. Lo que falta queda para la siguiente.
# 12 y no 25: medido, cada resolución cuesta ~22 s (la de Currencycloud
# declara 180 s de timeout), y la Lambda corta a los 900 s. Con la
# persistencia incremental de abajo un corte ya no pierde trabajo, pero
# igual conviene que la vuelta termine.
MAX_POR_CORRIDA = int(os.environ.get("RELEVO_RESOLVER_MAX", "12"))
SEGUNDOS_LIMITE = int(os.environ.get("RELEVO_RESOLVER_SEGUNDOS", "540"))


def llaves_inactivas():
    """Llaves cuya consulta está declarada `activa: False` en consultas.json.

    Hoy es `cc_external_id`: §6 dice que no se sabe cómo se compone ese
    identificador y la deja inactiva a propósito, con sus casos a revisión
    manual. Son 14 transacciones.
    """
    try:
        c = cliente.cargar_consultas()
    except Exception:
        return set()
    items = c.get("consultas", c) if isinstance(c, dict) else {}
    if not isinstance(items, dict):
        return set()
    return {k for k, v in items.items()
            if isinstance(v, dict) and v.get("activa") is False}


def pendientes(txs=None, cache=None):
    """Transacciones que todavía no tienen una resolución utilizable.

    Se reintenta lo que quedó en `error`: es casi siempre transitorio —el
    cluster dormido, un timeout— y no debe quedar pegado. Un `sin_match` o un
    `ambiguo` son respuestas: no se vuelven a preguntar salvo que alguien
    fuerce.

    `sin_consulta` es el caso interesante y hay que partirlo en dos. El motor
    lo devuelve tanto cuando falta configurar una consulta —transitorio, se
    reintenta— como cuando la consulta está declarada inactiva a propósito,
    que no es transitorio en absoluto: es una decisión. Sin esta distinción,
    las 14 transacciones de `cc_external_id` se reintentarían en cada corrida
    para siempre, consumiendo 14 de los 25 cupos por vuelta para nada.
    """
    if txs is None:
        txs = construir_transacciones()
    if cache is None:
        cache = cliente.leer_cache()
    inactivas = llaves_inactivas()
    fuera = []
    for tx in txs:
        if tx.get("llave") in inactivas:
            continue
        k = f"{tx.get('llave','')}|{tx.get('valor','')}"
        previo = cache.get(k)
        if not previo or previo.get("estado") in ("error", "sin_consulta"):
            fuera.append(tx)
    return fuera


def construir_transacciones():
    """Reconstruye las transacciones desde el depósito. Es el paso previo a
    resolver: el almacén guarda correos, no transacciones."""
    rg = R.cargar_reglas()
    mensajes = almacen.leer()
    registros = [pipeline.procesar(m, rg) for m in mensajes]
    return TX.construir(registros, {m["id"]: m for m in mensajes}, rg)


def correr(maximo=None, forzar=False):
    """Una vuelta de resolución. Devuelve el resumen, nunca levanta.

    No recibe transacciones: las reconstruye del depósito, porque la ingesta
    guarda correos y esto tiene que trabajar sobre lo que haya en ese momento.
    """
    arranque = time.time()
    tope = maximo or MAX_POR_CORRIDA
    r = {"pendientes": 0, "resueltos": 0, "por_estado": {}, "error": None}

    try:
        txs = construir_transacciones()
        cache = cliente.leer_cache()
    except Exception as e:
        r["error"] = f"reconstruyendo transacciones: {str(e)[:200]}"
        return r

    cola = txs if forzar else pendientes(txs, cache)
    r["pendientes"] = len(cola)
    r["transacciones"] = len(txs)
    if not cola:
        r["segundos"] = round(time.time() - arranque, 1)
        return r

    try:
        consultas = cliente.cargar_consultas()
    except Exception as e:
        r["error"] = f"cargando consultas.json: {str(e)[:200]}"
        return r

    # resolver_muchas guarda el caché UNA sola vez, al terminar. Con la
    # consulta de Currencycloud declarando 180 s de timeout, una vuelta
    # desafortunada puede acercarse al límite de la Lambda (900 s) y morir sin
    # guardar nada: se perdería todo el trabajo del lote, que son minutos de
    # cluster ya pagados. Se aprovecha el callback al_avanzar, que el motor ya
    # expone, para persistir cada resultado en el momento. Se escribe directo
    # al depósito en vez de llamar a guardar_cache() porque ésa relee el caché
    # completo para contar, y hacerlo en cada iteración sería caro.
    guardados = [0]

    def _persistir(hechos, res):
        # `res`, no `r`: `r` es el resumen de la corrida en el ámbito de arriba
        # y taparlo acá se lee mal.
        guardados[0] = hechos
        # NO se persisten los errores. Un error es transitorio —cluster
        # dormido, timeout— y escribirlo pisaría una resolución buena anterior
        # con basura: el cliente perdería su correo hasta el próximo reintento.
        # Sin entrada en el caché, `pendientes()` lo toma igual para reintentar,
        # así que no se pierde nada por omitirlo. Comprobado: forzar una vuelta
        # contra un cluster inalcanzable degradaba 3 `encontrado` a `error`.
        if res.get("estado") == "error":
            return
        try:
            if deposito.activo():
                llave = f"{res.get('llave','')}|{res.get('valor','')}"
                deposito.poner("clientes", deposito.clave_segura(llave), res)
        except Exception as e:
            print(f"[relevo] no pude persistir la resolución {res.get('valor')}: {e}")

    try:
        # cache=True hace que no vuelva a preguntar por lo ya resuelto. El
        # corte por error de conexión ya está dentro de resolver_muchas: si el
        # cluster está dormido, para.
        antes = len(cache)
        resultado = cliente.resolver_muchas(cola, consultas, cache=True,
                                            limite=tope, forzar=forzar,
                                            al_avanzar=_persistir)
    except Exception as e:
        # Ni siquiera acá se despierta el cluster: se reporta y se reintenta
        # en la próxima vuelta.
        r["error"] = f"resolviendo: {str(e)[:250]}"
        return r

    nuevo_cache = cliente.leer_cache()
    # `guardados[0]` y no el delta de tamaño del caché: recuperar una entrada
    # que estaba en error la sobreescribe sin cambiar el total, así que el
    # delta reportaba 1 cuando en realidad se habían resuelto 4. El contador
    # del callback cuenta lo que de verdad pasó por Redshift.
    r["resueltos"] = guardados[0]
    r["nuevos_en_cache"] = max(0, len(nuevo_cache) - antes)
    r["en_cache"] = len(nuevo_cache)
    r["quedan"] = max(0, len(cola) - r["resueltos"])

    conteo = {}
    for v in nuevo_cache.values():
        e = str(v.get("estado") or "?")
        conteo[e] = conteo.get(e, 0) + 1
    r["por_estado"] = conteo

    # Si quedaron errores de conexión, se dice explícito para que se lea en el
    # log como "el cluster no estaba", no como "la resolución falló".
    errores = [v for v in nuevo_cache.values() if v.get("estado") == "error"]
    if errores:
        r["nota"] = (f"{len(errores)} con error (probable cluster dormido): "
                     "se reintentan en la próxima vuelta, no se despierta el cluster")

    r["segundos"] = round(time.time() - arranque, 1)
    if r["segundos"] > SEGUNDOS_LIMITE:
        r["nota"] = ((r.get("nota", "") + " · la corrida pasó el límite blando: "
                      "bajar RELEVO_RESOLVER_MAX").strip(" ·"))
    return r
