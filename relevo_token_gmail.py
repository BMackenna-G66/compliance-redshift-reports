#!/usr/bin/env python3
"""Re-consiente el acceso a Gmail de Relevo y actualiza el secreto de AWS.

    python3 relevo_token_gmail.py                  # pide gmail.modify (lo normal)
    python3 relevo_token_gmail.py --scope readonly # vuelve a sólo lectura
    python3 relevo_token_gmail.py --solo-mostrar   # no escribe el secreto

**Por qué está en este repo y no en el Mac.** El original vive en `~/relevo`,
escribe a un `.env` y pide que uno copie el refresh token a mano. Desde que el
módulo corre en Lambda, el token que importa es el del secreto de AWS, y el Mac
ya no es parte del sistema. Dejar la única herramienta de re-consentimiento
allá contradecía eso.

**Qué scope pedir.** Hoy el token está en `gmail.readonly` y por eso el módulo
puede leer la casilla pero no escribirle a un cliente. Lo que destraba el ciclo
es **`gmail.modify`**, no `gmail.send`:

    gmail.send    → mandar el pedido al cliente (paso 6)
    gmail.modify  → eso MÁS dejar la devolución al partner como borrador (paso 9)

Los dos son *restricted scopes* de Google, así que cuestan lo mismo en trámite.
Pedir `send` obliga a re-consentir otra vez cuando se quiera el borrador.

**La salvaguarda que justifica este archivo:** el token nuevo se **prueba antes
de escribir el secreto**. Pisar un refresh token que funciona con uno que no
deja la ingesta muerta hasta que alguien se dé cuenta, y la ingesta es lo único
que hoy corre solo. Si la prueba falla, no se escribe nada.

Además guarda la versión anterior del secreto en `AWSPREVIOUS`, que es el
comportamiento por defecto de Secrets Manager: para volver atrás alcanza con
mover la etiqueta (el script lo dice al final).
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1"
SECRETO = os.environ.get("RELEVO_GMAIL_SECRET", "compliance-redshift-reports/relevo-gmail")

SCOPES = {
    "readonly": "https://www.googleapis.com/auth/gmail.readonly",
    "send":     "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/gmail.send",
    "modify":   "https://www.googleapis.com/auth/gmail.modify",
}

_recibido = {}


class Manejador(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _recibido.update({k: v[0] for k, v in q.items()})
        ok = "code" in _recibido
        cuerpo = f"""<!doctype html><meta charset="utf-8"><title>Relevo</title>
<body style="font:16px/1.6 -apple-system,system-ui,sans-serif;max-width:34em;margin:16vh auto;padding:0 6vw">
<h2 style="font-weight:600">{'Autorizado' if ok else 'No se pudo autorizar'}</h2>
<p style="color:#555">{'Cerrá esta pestaña y volvé a la terminal.' if ok else
   'Volvé a la terminal: ahí está el detalle.'}</p></body>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(cuerpo.encode())

    def log_message(self, *_):
        pass


def _secretos():
    import boto3
    return boto3.client("secretsmanager",
                        region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _leer_secreto():
    v = _secretos().get_secret_value(SecretId=SECRETO)["SecretString"]
    return json.loads(v)


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _access_token(cid, csec, refresh):
    datos = urllib.parse.urlencode({
        "client_id": cid, "client_secret": csec,
        "refresh_token": refresh, "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN, data=datos), timeout=30) as r:
        return json.load(r)["access_token"]


def _probar(cid, csec, refresh, usuario, quiere_escritura):
    """Prueba el token nuevo ANTES de escribir el secreto. (ok, detalle).

    Lectura: `profile`, que es lo que usa la ingesta.
    Escritura: se pide un borrador vacío y se borra. Es la única forma de saber
    de verdad si el scope alcanza — el token dice qué scopes tiene, pero eso no
    prueba que Google los vaya a honrar para esta casilla.
    """
    try:
        tok = _access_token(cid, csec, refresh)
    except urllib.error.HTTPError as e:
        return False, f"no se pudo canjear el refresh token: {e.code} {e.read()[:200]!r}"

    cab = {"Authorization": f"Bearer {tok}"}
    try:
        p = urllib.request.Request(f"{API}/users/{usuario}/profile", headers=cab)
        with urllib.request.urlopen(p, timeout=30) as r:
            perfil = json.load(r)
    except urllib.error.HTTPError as e:
        return False, f"lectura FALLÓ ({e.code}): {e.read()[:200]!r}"

    detalle = (f"lectura ✓  {perfil.get('emailAddress')} "
               f"({perfil.get('messagesTotal')} mensajes, historyId {perfil.get('historyId')})")
    if not quiere_escritura:
        return True, detalle

    # multipart/alternative mínimo: no se manda a nadie, se crea y se borra.
    crudo = base64.urlsafe_b64encode(
        b"To: nobody@example.invalid\r\nSubject: prueba de scope\r\n\r\nx").decode()
    cuerpo = json.dumps({"message": {"raw": crudo}}).encode()
    try:
        p = urllib.request.Request(f"{API}/users/{usuario}/drafts", data=cuerpo,
                                   headers={**cab, "Content-Type": "application/json"})
        with urllib.request.urlopen(p, timeout=30) as r:
            borrador = json.load(r)
    except urllib.error.HTTPError as e:
        return False, (f"{detalle}\n  escritura FALLÓ ({e.code}): "
                       f"{e.read()[:250].decode('utf-8', 'replace')}")

    bid = borrador.get("id")
    try:
        p = urllib.request.Request(f"{API}/users/{usuario}/drafts/{bid}",
                                   headers=cab, method="DELETE")
        urllib.request.urlopen(p, timeout=30)
        limpio = "y se borró"
    except urllib.error.HTTPError:
        limpio = f"OJO: quedó el borrador {bid}, borralo a mano"
    return True, f"{detalle}\n  escritura ✓  se creó un borrador de prueba {limpio}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=sorted(SCOPES), default="modify",
                    help="qué pedir. Por defecto modify: leer + enviar + borradores")
    ap.add_argument("--usuario", default="me")
    ap.add_argument("--solo-mostrar", action="store_true",
                    help="prueba el token nuevo pero NO escribe el secreto")
    a = ap.parse_args()

    print(f"\n  Secreto      : {SECRETO}")
    actual = _leer_secreto()
    cid, csec = actual["client_id"], actual["client_secret"]
    usuario = a.usuario or actual.get("usuario") or "me"
    print(f"  client_id    : {cid[:24]}…")
    print(f"  scope pedido : {SCOPES[a.scope]}")

    puerto = _puerto_libre()
    redirect = f"http://localhost:{puerto}"
    verificador = base64.urlsafe_b64encode(os.urandom(40)).decode().rstrip("=")
    desafio = base64.urlsafe_b64encode(
        hashlib.sha256(verificador.encode()).digest()).decode().rstrip("=")
    estado = secrets.token_urlsafe(16)

    url = AUTORIZAR + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPES[a.scope], "access_type": "offline", "prompt": "consent",
        "code_challenge": desafio, "code_challenge_method": "S256", "state": estado})

    servidor = http.server.HTTPServer(("127.0.0.1", puerto), Manejador)
    threading.Thread(target=servidor.handle_request, daemon=True).start()

    print("\n  Autorizá con compliance.masivo@global66.com — la cuenta DUEÑA de la casilla.")
    print("  Con otra cuenta el token sale válido y no lee nada: la API de Gmail no")
    print("  lee buzones ajenos aunque te hayan dado acceso en la web.")
    print(f"\n  Si el navegador no abre solo:\n\n{url}\n")
    webbrowser.open(url)

    print("  esperando la autorización…")
    for _ in range(600):
        if _recibido:
            break
        time.sleep(0.5)
    servidor.server_close()

    if "error" in _recibido:
        raise SystemExit(f"\n  Google devolvió: {_recibido['error']} "
                         f"{_recibido.get('error_description', '')}")
    if "code" not in _recibido:
        raise SystemExit("\n  No llegó el código. Probá de nuevo.")
    if _recibido.get("state") != estado:
        raise SystemExit("\n  El state no coincide. Abortando por seguridad.")

    datos = urllib.parse.urlencode({
        "code": _recibido["code"], "client_id": cid, "client_secret": csec,
        "redirect_uri": redirect, "grant_type": "authorization_code",
        "code_verifier": verificador}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN, data=datos), timeout=30) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"\n  Falló el canje: {e.code}\n  "
                         f"{e.read()[:400].decode('utf-8', 'replace')}")

    if "refresh_token" not in tok:
        raise SystemExit(
            "\n  Google no devolvió refresh_token. Pasa cuando la cuenta ya autorizó\n"
            "  antes esta app: revocá el acceso en https://myaccount.google.com/permissions\n"
            "  y volvé a correr esto.")

    nuevo = tok["refresh_token"]
    print(f"\n  Token nuevo  : {nuevo[:8]}…{nuevo[-4:]} ({len(nuevo)} caracteres)")
    print(f"  Scopes que concedió Google: {tok.get('scope', '(no informado)')}")

    print("\n  Probando el token ANTES de tocar el secreto…")
    ok, detalle = _probar(cid, csec, nuevo, usuario, a.scope in ("send", "modify"))
    print("  " + detalle.replace("\n", "\n  "))
    if not ok:
        raise SystemExit("\n  NO se escribió el secreto: el token nuevo no pasó la prueba.\n"
                         "  El que está en producción sigue intacto.")

    if a.solo_mostrar:
        print("\n  --solo-mostrar: no se escribió nada. El secreto sigue con el token viejo.")
        return

    _secretos().put_secret_value(
        SecretId=SECRETO,
        SecretString=json.dumps({**actual, "refresh_token": nuevo, "usuario": usuario}))
    print(f"\n  ✓ Secreto actualizado: {SECRETO}")
    print("    La versión anterior quedó etiquetada AWSPREVIOUS. Para volver atrás:")
    print(f"      aws secretsmanager get-secret-value --secret-id {SECRETO} \\")
    print("        --version-stage AWSPREVIOUS --query SecretString --output text")
    print("\n  Las Lambdas leen el secreto en cada invocación fría; para forzarlo ya:")
    print("      curl -s $API/relevo/salud")
    print("\n  Después, para habilitar el envío (sigue apagado por defecto):")
    print("      Admin → Relevo → Configuración → Activar el envío\n")


if __name__ == "__main__":
    main()
