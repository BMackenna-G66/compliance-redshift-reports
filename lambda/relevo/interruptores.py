"""El tablero: todos los interruptores del módulo, en un solo lugar.

Antes había uno solo —`envio_general`— y los cinco procesos programados no se
podían apagar desde ningún lado que no fuera la consola de EventBridge. Este
archivo los junta y les pone las mismas reglas: cada uno tiene autor, fecha y
un motivo declarado de existir.

**Dos clases de interruptor, con semántica OPUESTA a propósito.**

    PROCESO  → lee. Ingesta, snapshot, resolución, recepción, espejo.
               Si la configuración no se puede leer, **corre igual**
               (fail-open): que S3 tosa no puede dejar la casilla sin leer
               durante horas. Lo peor que pasa al correr de más es gastar
               una invocación.

    SALIDA   → toca el mundo. Envío al cliente, general y por partner.
               Si la configuración no se puede leer, **NO sale** (fail-closed):
               ante la duda no se le escribe a un cliente real. Lo peor que
               pasa al no salir es que alguien reintente.

Confundir las dos es el error caro: un `envio_general` que falla abierto manda
correos que nadie autorizó, y una `ingesta` que falla cerrada deja el módulo
ciego sin que nadie se entere.

**El maestro.** `modulo` apaga todo de una. Existe para el caso feo —algo está
mal y no sabemos qué— donde uno quiere parar y pensar sin ir apagando cinco
cosas a mano.

**Cómo se guardan.** Una clave de configuración por interruptor, no un
diccionario con todos adentro. Así cada uno lleva su propio `quien` y `cuando`:
con el diccionario, cambiar uno pisaba la autoría de los otros seis, y en un
tablero de control "quién apagó esto" es media respuesta. Se sigue leyendo el
diccionario viejo (`interruptores`) para no romper lo que ya estaba guardado;
la clave individual manda sobre él.
"""
import json
import os
import time

PREFIJO = "sw"          # las claves quedan como "sw_envio_general"
CLAVE_LEGADO = "interruptores"

PROCESO, SALIDA, MAESTRO = "proceso", "salida", "maestro"

# El catálogo es la fuente de verdad: de acá salen los valores por defecto, la
# validación y lo que dibuja la pantalla. Agregar un interruptor es agregar una
# fila, no tocar cinco archivos.
CATALOGO = [
    {
        "clave": "modulo", "tipo": MAESTRO, "defecto": True,
        "etiqueta": "Módulo Relevo",
        "descripcion": "Apaga todo de una: los cinco procesos programados y "
                       "cualquier envío. Es el freno de mano.",
        "al_apagar": "El módulo deja de leer la casilla y de resolver clientes. "
                     "Los datos que ya están no se pierden.",
    },
    {
        "clave": "ingesta", "tipo": PROCESO, "defecto": True,
        "etiqueta": "Ingesta de correo", "cada": "5 min",
        "descripcion": "Lee la casilla de corresponsales y guarda los correos nuevos.",
        "al_apagar": "Dejan de entrar casos nuevos. El historyId de Gmail caduca "
                     "en ~1 semana: si se apaga más que eso hay que resincronizar.",
    },
    {
        "clave": "vista", "tipo": PROCESO, "defecto": True,
        "etiqueta": "Extracción y snapshot", "cada": "5 min",
        "descripcion": "Pasa los correos por el motor —partner, transacción, qué "
                       "pide— y precalcula la pantalla.",
        "al_apagar": "La pantalla se congela en el último snapshot. Los correos "
                     "siguen entrando si la ingesta está prendida.",
    },
    {
        "clave": "resolucion", "tipo": PROCESO, "defecto": True,
        "etiqueta": "Resolución del cliente", "cada": "15 min",
        "descripcion": "Busca en Redshift quién es el cliente de cada transacción. "
                       "Sólo lee; no enciende el clúster.",
        "al_apagar": "Los casos nuevos quedan en «sin cliente» y no se les puede "
                     "pedir nada.",
    },
    {
        "clave": "recepcion", "tipo": PROCESO, "defecto": True,
        "etiqueta": "Recepción de respuestas", "cada": "10 min",
        "descripcion": "Detecta las respuestas de los clientes, baja los adjuntos "
                       "y mueve el checklist a «recibido».",
        "al_apagar": "Las respuestas siguen llegando a la casilla pero no se "
                     "asocian al caso. Al prenderlo se procesan las atrasadas.",
    },
    {
        "clave": "espejo", "tipo": PROCESO, "defecto": True,
        "etiqueta": "Espejo analítico", "cada": "diario 12:45 UTC",
        "descripcion": "Copia el estado del módulo al esquema `relevo` de Redshift "
                       "para poder consultarlo con SQL.",
        "al_apagar": "Las tablas de Redshift quedan con los datos del último día "
                     "que corrió. No afecta la operación.",
    },
    {
        "clave": "envio_general", "tipo": SALIDA, "defecto": False,
        "etiqueta": "Envío de correos al cliente", "peligro": True,
        "descripcion": "Habilita escribirle a clientes reales. Ningún proceso "
                       "programado envía: esto sólo abre los botones que aprieta "
                       "una persona.",
        "al_apagar": "No sale ningún correo, ni a mano ni por lote.",
    },
]

_POR_CLAVE = {i["clave"]: i for i in CATALOGO}


# ── partners: se descubren de las reglas, no se escriben a mano ──────────
def _partners():
    try:
        from . import reglas as R
        return sorted({p["nombre"] for p in (R.cargar_reglas().get("partners") or [])
                       if p.get("nombre")})
    except Exception:
        return []


def clave_partner(partner):
    return "envio_" + str(partner or "").lower().replace(" ", "_")


def catalogo_completo():
    """El catálogo más un interruptor de envío por cada partner conocido."""
    fuera = list(CATALOGO)
    for p in _partners():
        fuera.append({
            "clave": clave_partner(p), "tipo": SALIDA, "defecto": None,
            "etiqueta": p, "partner": p, "peligro": True,
            "descripcion": f"Envío a clientes de casos de {p}.",
            "al_apagar": f"Los casos de {p} no se pueden pedir, aunque el "
                         f"interruptor general esté prendido.",
        })
    return fuera


# ── lectura ──────────────────────────────────────────────────────────────
def _config():
    from . import api as rapi
    return rapi.leer_config()


def _valor(cfg, clave):
    """El valor efectivo, o None si nadie lo tocó nunca.

    Precedencia: la clave individual (`sw_<clave>`) manda sobre el diccionario
    legado (`interruptores`), que se sigue leyendo para no romper lo guardado
    antes de que existiera este archivo.
    """
    v = cfg.get(f"{PREFIJO}_{clave}")
    if isinstance(v, dict) and "valor" in v:
        v = v["valor"]
    if v is not None:
        return bool(v)
    legado = cfg.get(CLAVE_LEGADO)
    if isinstance(legado, dict) and clave in legado:
        return bool(legado[clave])
    return None


def _defecto(clave):
    d = _POR_CLAVE.get(clave)
    if d is not None:
        return d.get("defecto")
    # Un partner sin interruptor propio sigue al general. Devolver None dice
    # exactamente eso: "no declarado", que no es lo mismo que "apagado".
    return None


def valor(clave, cfg=None):
    """El estado efectivo del interruptor. None = no declarado."""
    cfg = cfg if cfg is not None else _config()
    v = _valor(cfg, clave)
    return _defecto(clave) if v is None else v


# ── las dos preguntas, con semántica opuesta ─────────────────────────────
def puede_correr(proceso):
    """(sí, motivo) para un proceso programado. **Falla ABIERTO.**

    Que la configuración no se pueda leer no puede dejar la casilla sin leer:
    el costo de correr de más es una invocación, el de no correr es quedarse
    ciego sin avisar.
    """
    try:
        cfg = _config()
    except Exception as e:
        print(f"[relevo/sw] no pude leer la config, {proceso} corre igual: {e}")
        return True, ""
    if valor("modulo", cfg) is False:
        return False, "el módulo Relevo está apagado (interruptor maestro)"
    if valor(proceso, cfg) is False:
        etq = (_POR_CLAVE.get(proceso) or {}).get("etiqueta", proceso)
        return False, f"«{etq}» está apagado en Admin → Relevo → Interruptores"
    return True, ""


def puede_salir(partner=""):
    """(sí, motivo) para escribirle a un cliente. **Falla CERRADO.**

    Ante la duda no se le escribe a nadie. Una excepción leyendo la
    configuración propaga y el envío no ocurre, que es lo correcto.
    """
    cfg = _config()
    if valor("modulo", cfg) is False:
        return False, "el módulo Relevo está apagado (interruptor maestro)"
    if not valor("envio_general", cfg):
        return False, ("el interruptor general de envío está apagado "
                       "(Admin → Relevo → Interruptores)")
    if partner:
        v = _valor(cfg, clave_partner(partner))
        if v is False:
            return False, f"el envío a casos de {partner} está apagado"
    return True, ""


# ── escritura ────────────────────────────────────────────────────────────
def declarados():
    """Las claves que este módulo acepta. Rechazar lo demás evita que un typo
    en el front cree un interruptor fantasma que nadie mira."""
    return {i["clave"] for i in catalogo_completo()}


def cambiar(clave, valor_nuevo, quien=""):
    """Prende o apaga uno. Exige autor: apagar un proceso es una decisión."""
    quien = str(quien or "").strip()
    if not quien:
        return {"error": "quien es requerido: un interruptor lo mueve una persona"}
    if clave not in declarados():
        return {"error": f"interruptor desconocido: {clave!r}"}
    from . import api as rapi
    rapi.guardar_config(f"{PREFIJO}_{clave}", bool(valor_nuevo), quien)
    return {"cambiado": clave, "valor": bool(valor_nuevo), "por": quien,
            "estado": estado()}


def estado():
    """Todo el tablero, listo para dibujar: valor, autor, fecha y qué implica."""
    cfg = _config()
    # La autoría vive en el objeto de configuración, no en el valor.
    autores = {}
    try:
        from . import deposito
        if deposito.activo():
            for d in deposito.todos("config"):
                c = str(d.get("clave") or "")
                if c.startswith(f"{PREFIJO}_"):
                    autores[c[len(PREFIJO) + 1:]] = {"quien": d.get("quien"),
                                                     "cuando": d.get("cuando")}
    except Exception as e:
        print(f"[relevo/sw] no pude leer la autoría: {e}")

    filas = []
    for i in catalogo_completo():
        v = valor(i["clave"], cfg)
        filas.append({
            **i,
            "valor": v,
            "declarado": _valor(cfg, i["clave"]) is not None,
            "quien": (autores.get(i["clave"]) or {}).get("quien"),
            "cuando": (autores.get(i["clave"]) or {}).get("cuando"),
        })
    apagados = [f for f in filas if f["valor"] is False]
    return {
        "interruptores": filas,
        "apagados": [f["clave"] for f in apagados],
        "n_apagados": len(apagados),
        # Lo que hay que gritar: un proceso apagado se ve igual que una semana
        # tranquila, así que el resumen lo dice aparte.
        "procesos_apagados": [f["clave"] for f in apagados if f["tipo"] == PROCESO],
        "envio_activo": bool(valor("envio_general", cfg)) and valor("modulo", cfg) is not False,
        "generado_en": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    }
