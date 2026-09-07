"""Ingesta de correo de corresponsales: una invocación, no un demonio.

Reemplaza el ciclo `gmail.seguir()` que hoy corre en el Mac con `launchd`.
Ahí era un generador con `sleep(45)`; acá es una invocación que EventBridge
dispara cada 5 minutos y que termina siempre. Para el volumen del ciclo RFI
—cientos de correos al mes— sobra.

Las cuatro trampas de Gmail que enumera §13 están cubiertas: tres ya venían
resueltas en `gmail.py` (el filtro `messageAdded`, el 404 del historyId
vencido, y el 403 de cuota tratado como reintentable) y la cuarta se resuelve
acá: **el historyId se persiste DESPUÉS de guardar los mensajes**. Si la
Lambda muere en medio, la próxima corrida repite en vez de perder — y repetir
es gratis porque el almacén deduplica por id.
"""
import json
import os
import time

from . import almacen, estado, gmail as G, reglas as R

CLAVE_HISTORIAL = "gmail_history_id"

SECRETO = os.environ.get("RELEVO_GMAIL_SECRET", "compliance-redshift-reports/relevo-gmail")
USUARIO = os.environ.get("RELEVO_GMAIL_USUARIO", "me")
# Tope por corrida. Recorrer la casilla entera en una invocación la cuelga
# (§9); lo que sobra queda para la corrida siguiente, que llega en 5 minutos.
MAX_POR_CORRIDA = int(os.environ.get("RELEVO_MAX_POR_CORRIDA", "120"))
# Margen antes del timeout de la Lambda, para cerrar ordenado y alcanzar a
# persistir lo que ya se bajó.
SEGUNDOS_LIMITE = int(os.environ.get("RELEVO_SEGUNDOS_LIMITE", "180"))

_credenciales = None


def credenciales():
    """Lee el secreto JSON de Gmail. Se cachea por contenedor.

    Mismo patrón que `_get_imap_password()` de WatchTower: el secreto manda
    sobre las variables de entorno, y si no está se cae a ellas para poder
    correr local.
    """
    global _credenciales
    if _credenciales is not None:
        return _credenciales
    datos = {}
    try:
        import boto3
        raw = boto3.client("secretsmanager").get_secret_value(SecretId=SECRETO)
        datos = json.loads(raw.get("SecretString") or "{}")
    except Exception as e:
        print(f"[relevo] no pude leer el secreto {SECRETO}: {e}")
    _credenciales = {
        "client_id": datos.get("client_id") or os.environ.get("GMAIL_CLIENT_ID", ""),
        "client_secret": datos.get("client_secret") or os.environ.get("GMAIL_CLIENT_SECRET", ""),
        "refresh_token": datos.get("refresh_token") or os.environ.get("GMAIL_REFRESH_TOKEN", ""),
        "usuario": datos.get("usuario") or USUARIO,
    }
    return _credenciales


def cliente():
    c = credenciales()
    if not all((c["client_id"], c["client_secret"], c["refresh_token"])):
        raise G.GmailError(
            f"faltan credenciales de Gmail. Cargá el secreto {SECRETO} con "
            "{client_id, client_secret, refresh_token}.")
    return G.Gmail(c["client_id"], c["client_secret"], c["refresh_token"], c["usuario"])


def correr(maximo=None, forzar_resync=False):
    """Una vuelta de ingesta. Devuelve el resumen, nunca levanta por un correo.

    Camino normal: pedir a Gmail lo nuevo desde el historyId guardado, bajar
    esos mensajes, guardarlos, y sólo entonces mover la marca.

    Primera vez o historyId vencido: Gmail no puede decir "lo nuevo" porque no
    hay punto de partida. Se toma el historyId del perfil y se deja ahí — la
    próxima corrida ya trae lo incremental. No se hace una carga completa de la
    casilla desde acá: eso es un trabajo aparte y no puede colgar la ingesta.
    """
    arranque = time.time()
    tope = maximo or MAX_POR_CORRIDA
    r = {"nuevos": 0, "bajados": 0, "resync": False, "history_id": None, "error": None}

    try:
        g = cliente()
        rg = R.cargar_reglas()
    except Exception as e:
        r["error"] = str(e)[:300]
        return r

    hid = None if forzar_resync else estado.leer(CLAVE_HISTORIAL)

    if not hid:
        # Sin punto de partida: se ancla en el presente y se sale.
        try:
            hid = str(g.perfil()["historyId"])
        except Exception as e:
            r["error"] = f"no pude leer el perfil de Gmail: {str(e)[:200]}"
            return r
        estado.guardar(CLAVE_HISTORIAL, hid)
        r.update(resync=True, history_id=hid,
                 nota="primera corrida: marca anclada, la próxima trae lo incremental")
        return r

    try:
        ids, hid_nuevo = g.historial(hid)
    except Exception as e:
        r["error"] = f"history.list falló: {str(e)[:200]}"
        return r

    if ids is None:
        # 404: el historyId venció (Gmail los retiene ~una semana). Se
        # resincroniza y se sale; no se intenta adivinar lo perdido.
        try:
            hid = str(g.perfil()["historyId"])
        except Exception as e:
            r["error"] = f"resync falló: {str(e)[:200]}"
            return r
        estado.guardar(CLAVE_HISTORIAL, hid)
        r.update(resync=True, history_id=hid,
                 nota="historyId vencido: se resincronizó contra el perfil")
        return r

    pendientes = ids[:tope]
    r["bajados"] = len(pendientes)
    r["quedan"] = max(0, len(ids) - len(pendientes))

    if pendientes:
        try:
            mensajes = G.bajar(g, rg, pendientes)
        except Exception as e:
            # No se mueve la marca: la próxima corrida reintenta estos mismos.
            r["error"] = f"bajando mensajes: {str(e)[:200]}"
            return r
        try:
            r["nuevos"] = almacen.guardar(mensajes)
        except Exception as e:
            r["error"] = f"guardando mensajes: {str(e)[:200]}"
            return r

    # La marca se mueve al final, y sólo si no quedó nada pendiente por tope:
    # si se truncó, avanzar la dejaría un hueco de mensajes nunca vistos.
    if r["quedan"] == 0 and hid_nuevo:
        estado.guardar(CLAVE_HISTORIAL, str(hid_nuevo))
        r["history_id"] = str(hid_nuevo)
    else:
        r["history_id"] = str(hid)
        if r["quedan"]:
            r["nota"] = (f"quedaron {r['quedan']} por el tope de {tope}; la marca no avanza "
                         "para no dejar huecos")

    r["segundos"] = round(time.time() - arranque, 1)
    if r["segundos"] > SEGUNDOS_LIMITE:
        r["nota"] = (r.get("nota", "") + " · la corrida pasó el límite blando: "
                     "bajar RELEVO_MAX_POR_CORRIDA").strip(" ·")
    return r
