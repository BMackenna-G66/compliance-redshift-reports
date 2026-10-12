# -*- coding: utf-8 -*-
"""Quién es el que llama, verificado contra Firebase.

═══════════════════════════════════════════════════════════════════════════
EL PROBLEMA QUE RESUELVE
═══════════════════════════════════════════════════════════════════════════

Hasta ahora la API no autentica: `_actor()` lee `actor_email` del cuerpo y le
cree. Para un registro de auditoría es incómodo; para un botón que manda un
reporte al regulador es inaceptable — «sólo el Oficial de Cumplimiento» y el
cuatro ojos no se pueden sostener sobre un campo que cualquiera escribe.

Acá el correo sale del ID token de Firebase, que es la misma sesión con la que
la persona entró a la pantalla.

═══════════════════════════════════════════════════════════════════════════
POR QUÉ `accounts:lookup` Y NO VERIFICAR LA FIRMA ACÁ
═══════════════════════════════════════════════════════════════════════════

`tokeninfo` de Google NO sirve: es para tokens de Google Sign-In
(`iss = accounts.google.com`). Un ID token de Firebase trae
`iss = securetoken.google.com/<proyecto>` y lo firma otra clave.

Verificar la firma localmente es posible —`PyJWT[crypto]` son 16 MB medidos y
entran de sobra en el paquete— pero `accounts:lookup` es el verificador que
Firebase publica para esto: valida firma, vencimiento y proyecto, y además
dice si la cuenta fue deshabilitada, que una verificación local de la firma
NO puede saber. Alguien dado de baja esta mañana seguiría teniendo un token
válido por una hora.

Esa última razón es la que decide. El costo es una llamada de red por request,
y una aprobación de ROS son unidades por semana.

═══════════════════════════════════════════════════════════════════════════
EL TOKEN NO SE GUARDA, NO SE LOGUEA Y NO VIAJA
═══════════════════════════════════════════════════════════════════════════

Ni a otra Lambda, ni al historial, ni a un `print`, ni para depurar. El Report
Runner hace `logger.info("Event: %s", json.dumps(event))`: cualquier cosa que
entre en un payload de `invoke` queda en CloudWatch para siempre. Lo único que
sale de este módulo es el correo ya verificado.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# La `apiKey` de un proyecto web de Firebase es un identificador público, no
# un secreto: viaja en cada request desde el navegador y ya está en claro en
# `frontend/v2/src/sesion.js` y en v1. Lo que protege los datos son las reglas
# de Firestore y esta verificación, no esconderla. Se deja configurable por
# entorno igual, para que un ambiente de prueba no tenga que tocar el código.
API_KEY = os.environ.get("FIREBASE_WEB_API_KEY",
                         "AIzaSyCKduUg-DLxeOEx7ZDTbS8TpxRdTVyFMjI")
PROYECTO = os.environ.get("FIREBASE_PROJECT_ID", "global66-compliance")

URL = "https://identitytoolkit.googleapis.com/v1/accounts:lookup"

# Sólo gente de la casa. El proyecto de Firebase ya restringe quién puede
# entrar, pero esto es el cinturón: un proyecto mal configurado no alcanza
# para aprobar un ROS.
DOMINIO = "@global66.com"

TIMEOUT = 8


class TokenInvalido(Exception):
    """No se pudo establecer quién llama. Siempre termina en 401.

    El mensaje va al cliente, así que NUNCA lleva el token ni nada que
    permita reconstruirlo.
    """


def token_del_evento(event: dict) -> str:
    """El Bearer del header `Authorization`, o cadena vacía.

    Va por header y no por el cuerpo porque un GET no manda cuerpo, y la
    alternativa —el query string— deja la credencial en los access logs, en
    CloudWatch y en el historial del navegador.
    """
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    crudo = str(headers.get("authorization") or "").strip()
    if not crudo:
        return ""
    partes = crudo.split(None, 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        # Un header presente pero mal formado NO es «anónimo»: es un intento
        # fallido, y se trata como tal más arriba.
        raise TokenInvalido("El header Authorization tiene que ser "
                            "'Bearer <token>'.")
    return partes[1].strip()


def _consultar(id_token: str) -> dict:
    cuerpo = json.dumps({"idToken": id_token}).encode("utf-8")
    pedido = urllib.request.Request(
        f"{URL}?key={API_KEY}", data=cuerpo,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        # Firebase contesta 400 con INVALID_ID_TOKEN / TOKEN_EXPIRED / etc.
        # No se reenvía su texto al cliente: puede cambiar y no le dice nada
        # a quien lo lee.
        if 400 <= e.code < 500:
            raise TokenInvalido("La sesión no es válida o venció. "
                                "Volvé a entrar.") from e
        raise
    except urllib.error.URLError as e:
        # Google no contestó. NO es un token inválido y no se puede dejar
        # pasar como anónimo: se corta con un error distinto, para que un
        # problema de red no se lea como un problema de credenciales.
        raise RuntimeError(f"no pude verificar la sesión: {type(e).__name__}") from e


def verificar(id_token: str) -> dict:
    """El correo de quien llama, o `TokenInvalido`.

    Devuelve sólo lo que hace falta aguas arriba: correo y uid. El token no
    sale de acá.
    """
    if not str(id_token or "").strip():
        raise TokenInvalido("Falta el token de sesión.")

    datos = _consultar(id_token)
    usuarios = datos.get("users") or []
    if not usuarios:
        raise TokenInvalido("La sesión no corresponde a ningún usuario.")
    u = usuarios[0]

    correo = str(u.get("email") or "").strip().lower()
    if not correo:
        raise TokenInvalido("La sesión no trae correo.")
    # `disabled` es la razón por la que esto va contra Firebase y no contra
    # una verificación local de la firma: alguien dado de baja esta mañana
    # sigue teniendo un token firmado y válido por una hora.
    if u.get("disabled"):
        raise TokenInvalido("La cuenta está deshabilitada.")
    if not u.get("emailVerified"):
        raise TokenInvalido("El correo de la cuenta no está verificado.")
    if not correo.endswith(DOMINIO):
        raise TokenInvalido(f"Sólo cuentas {DOMINIO}.")

    return {"email": correo, "uid": str(u.get("localId") or "")}
