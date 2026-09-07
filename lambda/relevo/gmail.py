"""Ingesta desde Gmail. Sin dependencias: urllib y json.

Por que no alcanza un conector generico
---------------------------------------
Verificado el 2026-09-02 contra la casilla real: el conector MCP devuelve
`sender = compliance@global66.com` en el 100% de los correos de partner, porque
ese es el `From` que reescribe Google Groups. El remitente real vive en
`X-Original-Sender`, y solo aparece si uno lo pide explicitamente. Con
`format=metadata&metadataHeaders=X-Original-Sender` (o `format=raw`) el header
llega intacto:

    X-Original-Sender: no_reply@dlocal.com
    From:              'd·Local' via Compliance <compliance@global66.com>
    Delivered-To:      compliance.masivo@global66.com

Credenciales
------------
Nunca en el codigo. Se leen del entorno:

    GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
    GMAIL_USUARIO   (por defecto "me")

Para una casilla compartida como compliance.masivo@global66.com hay dos caminos:
  1. Refresh token obtenido una vez por alguien con acceso delegado a la casilla.
     Es lo que implementa este modulo y no necesita librerias.
  2. Service account con delegacion a nivel dominio, impersonando la casilla.
     Es lo correcto para produccion y lo tiene que habilitar Workspace; requiere
     firmar un JWT RS256, asi que ahi si hace falta `google-auth`.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://gmail.googleapis.com/gmail/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Los headers que hay que pedir por nombre. Sin esto el remitente real se pierde.
HEADERS = ["From", "Reply-To", "X-Original-Sender", "X-Original-From", "List-ID",
           "Message-ID", "In-Reply-To", "References", "Subject", "Date", "Delivered-To"]

# Las busquedas que funcionaron (Metodo de extraccion §2). Buscar solo por patron
# de asunto pierde correos: en Nium el texto completo encontro 105 hilos contra 74.
CONSULTAS = [
    '"New RFI is requested" OR "RFI needs attention" OR "OTP code requested" OR "has been released" OR "verification has been approved"',
    '"Compliance Operations, NIUM" OR "service from Nium" OR "support.nium.com" OR "Additional Information Request" OR "Prohibited/Restricted Business"',
    '"Currencycloud" OR "Compliance Query" OR "Bank RFI" OR "Retrospective Compliance" OR "Fraud Notification"',
    'ozcambio OR "OZ NOTIFICATION" OR "OZ NOTIFICACION" OR "OZ NOTIFICACIÓN"',
]


class GmailError(RuntimeError):
    pass


class Gmail:
    def __init__(self, client_id=None, client_secret=None, refresh_token=None, usuario=None):
        self.cid = client_id or os.environ.get("GMAIL_CLIENT_ID")
        self.sec = client_secret or os.environ.get("GMAIL_CLIENT_SECRET")
        self.ref = refresh_token or os.environ.get("GMAIL_REFRESH_TOKEN")
        self.usuario = usuario or os.environ.get("GMAIL_USUARIO", "me")
        if not all((self.cid, self.sec, self.ref)):
            raise GmailError(
                "faltan credenciales: exportá GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET y "
                "GMAIL_REFRESH_TOKEN (o pasalas al constructor). Nunca las pongas en el código.")
        self._tok, self._vence = None, 0

    # ------------------------------------------------------------------ auth
    def _token(self):
        if self._tok and time.time() < self._vence - 60:
            return self._tok
        datos = urllib.parse.urlencode({
            "client_id": self.cid, "client_secret": self.sec,
            "refresh_token": self.ref, "grant_type": "refresh_token"}).encode()
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=datos), timeout=30) as r:
            j = json.load(r)
        self._tok = j["access_token"]
        self._vence = time.time() + int(j.get("expires_in", 3600))
        return self._tok

    def _get(self, ruta, **params):
        url = f"{API}/users/{self.usuario}/{ruta}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        pedido = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._token()}"})
        for intento in range(5):
            try:
                with urllib.request.urlopen(pedido, timeout=60) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                cuerpo = e.read()
                # Gmail devuelve 403 —no 429— cuando se pasa la cuota por minuto.
                # Sin esto, el servicio 24/7 se cae con un error duro en el
                # momento en que baja muchos cuerpos seguidos.
                cuota = e.code == 403 and b"Quota exceeded" in cuerpo
                if (e.code in (429, 500, 502, 503) or cuota) and intento < 5:
                    espera = 2 ** intento * (15 if cuota else 1)   # la cuota es por minuto
                    time.sleep(espera)
                    continue
                raise GmailError(
                    f"{e.code} en {ruta}: {cuerpo[:300].decode('utf-8', 'replace')}") from e

    # --------------------------------------------------------------- lectura
    def perfil(self):
        return self._get("profile")

    def listar_ids(self, query, maximo=0):
        """IDs de mensajes que matchean la query. Deduplicados: un mismo mensaje
        aparece en varias consultas."""
        ids, token = [], None
        while True:
            p = {"q": query, "maxResults": 500}
            if token:
                p["pageToken"] = token
            r = self._get("messages", **p)
            ids += [m["id"] for m in r.get("messages", [])]
            token = r.get("nextPageToken")
            if not token or (maximo and len(ids) >= maximo):
                break
        return ids[:maximo] if maximo else ids

    def historial(self, desde_history_id):
        """Ids nuevos desde un historyId. Es el mecanismo de tiempo real barato:
        una llamada devuelve solo lo que cambio."""
        ids, token = [], None
        ultimo = desde_history_id
        while True:
            p = {"startHistoryId": desde_history_id, "historyTypes": "messageAdded", "maxResults": 500}
            if token:
                p["pageToken"] = token
            try:
                r = self._get("history", **p)
            except GmailError as e:
                if "404" in str(e):      # historyId demasiado viejo: hay que resincronizar
                    return None, None
                raise
            for h in r.get("history", []):
                ultimo = h.get("id", ultimo)
                for m in h.get("messagesAdded", []):
                    ids.append(m["message"]["id"])
            token = r.get("nextPageToken")
            if not token:
                ultimo = r.get("historyId", ultimo)
                break
        return list(dict.fromkeys(ids)), ultimo

    def mensaje(self, mid, con_cuerpo=False):
        if con_cuerpo:
            return self._get(f"messages/{mid}", format="full")
        return self._get(f"messages/{mid}", format="metadata", metadataHeaders=HEADERS)

    def observar(self, topic):
        """Suscripcion push via Pub/Sub. Caduca a los 7 dias: hay que renovarla."""
        url = f"{API}/users/{self.usuario}/watch"
        cuerpo = json.dumps({"topicName": topic, "labelIds": ["INBOX"]}).encode()
        pedido = urllib.request.Request(url, data=cuerpo, headers={
            "Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return json.load(r)


# ------------------------------------------------------------------ conversion
def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8", "replace")


def _cuerpo(payload):
    """Junta text/plain y text/html de todas las partes. El texto citado se
    conserva a proposito: 25 de los 71 PY de Nium viven ahi."""
    trozos = []

    def caminar(p):
        mime = p.get("mimeType", "")
        datos = (p.get("body") or {}).get("data")
        if datos and mime in ("text/plain", "text/html"):
            t = _b64(datos)
            if mime == "text/html":
                from .html import a_texto
                t = a_texto(t)
            trozos.append(t)
        for hijo in p.get("parts", []) or []:
            caminar(hijo)

    caminar(payload or {})
    return "\n".join(trozos)


def a_mensaje(j):
    """Convierte la respuesta de la API a la forma que consume el pipeline."""
    headers = {h["name"]: h["value"] for h in (j.get("payload", {}).get("headers") or [])}
    asunto = next((v for k, v in headers.items() if k.lower() == "subject"), "")
    return {
        "id": j["id"],
        "thread_id": j.get("threadId"),
        "asunto": asunto,
        "cuerpo": _cuerpo(j.get("payload")),
        "headers": headers,
        "texto_adjuntos": [],
        "fecha": j.get("internalDate"),
        "esperado": None,
    }


def _necesita_cuerpo(reglas):
    """Que partners declaran reglas con ambito 'cuerpo'. Sale de reglas.json, no
    de una lista a mano: si manana Currencycloud deja de necesitarlo, es config."""
    return {p["id"] for p in reglas["partners"]
            if any("cuerpo" in e.get("ambito", []) for e in p["extraccion"])}


def bajar(gmail, reglas, ids, siempre_cuerpo=False, avisar=None):
    """Baja mensajes en dos pasadas: metadata para todos (barato), y el cuerpo
    solo para los partners cuyas reglas lo necesitan."""
    from .partner import identificar
    con_cuerpo = _necesita_cuerpo(reglas)
    fuera = []
    for i, mid in enumerate(ids, 1):
        m = a_mensaje(gmail.mensaje(mid, con_cuerpo=siempre_cuerpo))
        if not siempre_cuerpo:
            p, _, _ = identificar(m, reglas)
            if p and p["id"] in con_cuerpo:
                m = a_mensaje(gmail.mensaje(mid, con_cuerpo=True))
        fuera.append(m)
        if avisar and i % 25 == 0:
            avisar(i, len(ids))
    return fuera


def recolectar(gmail, reglas, consultas=None, maximo=0, siempre_cuerpo=False, avisar=None):
    """Backfill: corre las cuatro busquedas, deduplica y baja.

    `maximo` es POR CONSULTA, no global. Truncar el total dejaba la muestra
    entera en manos del primer corresponsal de la lista: con maximo=20 bajaban
    20 correos de dLocal y cero de los otros tres.
    """
    ids = []
    for q in (consultas or CONSULTAS):
        ids += gmail.listar_ids(q, maximo=maximo)
    ids = list(dict.fromkeys(ids))          # dedup por id de mensaje
    return bajar(gmail, reglas, ids, siempre_cuerpo=siempre_cuerpo, avisar=avisar)


def seguir(gmail, reglas, history_id=None, cada=45, siempre_cuerpo=False):
    """Tiempo real. Cede listas de mensajes nuevos a medida que llegan.

    Usa history.list, que devuelve solo lo que cambio desde el ultimo historyId.
    Si el historyId caduca (Gmail los retiene ~una semana) resincroniza solo.
    Para produccion 24/7 conviene ademas users.watch con Pub/Sub y dejar esto
    como respaldo; ver §7 del documento de estructura.
    """
    hid = history_id or gmail.perfil()["historyId"]
    while True:
        nuevos, hid_nuevo = gmail.historial(hid)
        if nuevos is None:                   # historyId vencido
            hid = gmail.perfil()["historyId"]
            yield []
        else:
            hid = hid_nuevo or hid
            yield bajar(gmail, reglas, nuevos, siempre_cuerpo=siempre_cuerpo) if nuevos else []
        time.sleep(cada)
