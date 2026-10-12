# -*- coding: utf-8 -*-
"""Quién llama, verificado contra Firebase.

LO QUE VIGILA ESTE ARCHIVO:

1. **Un token inválido NUNCA se degrada a anónimo.** Si se degradara, un bug
   del front que mandara tokens vencidos pasaría invisible —todo seguiría
   andando— hasta el día del corte, que es cuando se rompería todo junto y
   sin pista de por qué.

2. **El token no sale del módulo.** Ni al cliente, ni a un log, ni a otra
   Lambda. El Report Runner loguea el evento entero: lo que entre en un
   payload queda en CloudWatch para siempre.

3. **Con token, el actor sale del token.** El `actor_email` del cuerpo deja
   de tener efecto. Es todo el punto del cambio.

Los datos de las respuestas son inventados: el repo es público.
"""
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import auth_firebase as F  # noqa: E402

TOKEN = "eyJ-un-token-de-mentira.para-los-tests.no-sirve-para-nada"

BIEN = {"users": [{"localId": "uid-1", "email": "analista@global66.com",
                   "emailVerified": True, "disabled": False}]}


def _respuesta(payload):
    """Doble de `urlopen` que devuelve lo que se le pase."""
    def _abrir(pedido, timeout=None):
        class _R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _R(json.dumps(payload).encode())
    return _abrir


def _error_http(codigo):
    def _abrir(pedido, timeout=None):
        raise urllib.error.HTTPError("u", codigo, "no", {}, None)
    return _abrir


class ElTokenSaleDelHeaderYNoDeLaURL(unittest.TestCase):
    """Un GET no manda cuerpo, y el query string deja la credencial en los
    access logs, en CloudWatch y en el historial del navegador."""

    def test_lee_el_bearer(self):
        self.assertEqual(
            F.token_del_evento({"headers": {"Authorization": f"Bearer {TOKEN}"}}),
            TOKEN)

    def test_el_header_no_distingue_mayusculas(self):
        for clave in ("authorization", "AUTHORIZATION", "Authorization"):
            with self.subTest(clave):
                self.assertEqual(
                    F.token_del_evento({"headers": {clave: f"bearer {TOKEN}"}}),
                    TOKEN)

    def test_sin_header_devuelve_vacio_y_no_explota(self):
        for evento in ({}, {"headers": {}}, {"headers": None},
                       {"headers": {"Authorization": "   "}}):
            with self.subTest(evento=evento):
                self.assertEqual(F.token_del_evento(evento), "")

    def test_UN_HEADER_MAL_FORMADO_NO_ES_ANONIMO(self):
        """Es un intento fallido, no una visita sin credencial."""
        for malo in (TOKEN, f"Basic {TOKEN}", "Bearer", "Bearer  "):
            with self.subTest(malo=malo[:20]):
                with self.assertRaises(F.TokenInvalido):
                    F.token_del_evento({"headers": {"Authorization": malo}})


class LoQueSeRechaza(unittest.TestCase):

    def _con(self, abrir):
        orig = F.urllib.request.urlopen
        F.urllib.request.urlopen = abrir
        self.addCleanup(lambda: setattr(F.urllib.request, "urlopen", orig))

    def test_un_token_vacio(self):
        for vacio in ("", "   ", None):
            with self.subTest(vacio=vacio), self.assertRaises(F.TokenInvalido):
                F.verificar(vacio)

    def test_un_token_que_firebase_rechaza(self):
        """400 de Firebase: inválido, vencido o de otro proyecto."""
        self._con(_error_http(400))
        with self.assertRaises(F.TokenInvalido):
            F.verificar(TOKEN)

    def test_una_cuenta_deshabilitada(self):
        """LA RAZÓN por la que esto va contra Firebase y no contra una
        verificación local de la firma: alguien dado de baja esta mañana
        sigue teniendo un token firmado y válido por una hora."""
        self._con(_respuesta({"users": [dict(BIEN["users"][0], disabled=True)]}))
        with self.assertRaises(F.TokenInvalido) as c:
            F.verificar(TOKEN)
        self.assertIn("deshabilitada", str(c.exception))

    def test_un_correo_sin_verificar(self):
        self._con(_respuesta({"users": [dict(BIEN["users"][0],
                                             emailVerified=False)]}))
        with self.assertRaises(F.TokenInvalido):
            F.verificar(TOKEN)

    def test_un_correo_de_afuera(self):
        """El proyecto de Firebase ya restringe quién entra, pero esto es el
        cinturón: un proyecto mal configurado no alcanza para aprobar un ROS."""
        self._con(_respuesta({"users": [dict(BIEN["users"][0],
                                             email="alguien@gmail.com")]}))
        with self.assertRaises(F.TokenInvalido) as c:
            F.verificar(TOKEN)
        self.assertIn("global66.com", str(c.exception))

    def test_un_dominio_que_solo_TERMINA_pareciendose(self):
        self._con(_respuesta({"users": [dict(BIEN["users"][0],
                                             email="x@noglobal66.com.ar")]}))
        with self.assertRaises(F.TokenInvalido):
            F.verificar(TOKEN)

    def test_una_respuesta_sin_usuarios(self):
        self._con(_respuesta({"users": []}))
        with self.assertRaises(F.TokenInvalido):
            F.verificar(TOKEN)

    def test_GOOGLE_CAIDO_NO_ES_UN_TOKEN_INVALIDO(self):
        """Un problema de red no puede leerse como un problema de
        credenciales. Son dos errores distintos y se tratan distinto."""
        def _cae(pedido, timeout=None):
            raise urllib.error.URLError("sin red")
        self._con(_cae)
        with self.assertRaises(RuntimeError):
            F.verificar(TOKEN)
        # Y no es TokenInvalido, que terminaría en un 401 engañoso.
        self._con(_cae)
        try:
            F.verificar(TOKEN)
        except Exception as e:
            self.assertNotIsInstance(e, F.TokenInvalido)


class ELTOKENNOSALEDELMODULO(unittest.TestCase):

    def test_lo_que_devuelve_es_solo_el_correo_y_el_uid(self):
        orig = F.urllib.request.urlopen
        F.urllib.request.urlopen = _respuesta(BIEN)
        self.addCleanup(lambda: setattr(F.urllib.request, "urlopen", orig))
        quien = F.verificar(TOKEN)
        self.assertEqual(sorted(quien), ["email", "uid"])
        self.assertNotIn(TOKEN, json.dumps(quien))

    def test_los_mensajes_de_error_no_lo_llevan(self):
        """El mensaje va al cliente: no puede traer la credencial ni nada que
        permita reconstruirla."""
        orig = F.urllib.request.urlopen
        F.urllib.request.urlopen = _error_http(400)
        self.addCleanup(lambda: setattr(F.urllib.request, "urlopen", orig))
        try:
            F.verificar(TOKEN)
        except F.TokenInvalido as e:
            self.assertNotIn(TOKEN, str(e))
            self.assertNotIn(TOKEN[:20], str(e))

    def test_el_correo_se_normaliza(self):
        orig = F.urllib.request.urlopen
        F.urllib.request.urlopen = _respuesta(
            {"users": [dict(BIEN["users"][0], email="  Analista@Global66.com  ")]})
        self.addCleanup(lambda: setattr(F.urllib.request, "urlopen", orig))
        self.assertEqual(F.verificar(TOKEN)["email"], "analista@global66.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── El tramo transitorio, en el ruteo ──────────────────────────────────────

import api_handler as A  # noqa: E402


class ElTramoTransitorio(unittest.TestCase):
    """Las rutas que YA EXISTEN aceptan token y también siguen sin él,
    porque el caché de la SPA tarda hasta un día en renovarse y romperlas de
    golpe dejaría sin pantalla de ROS a medio equipo. Cada llamada sin token
    queda contada; cuando no quede ninguna, un PR borra este camino."""

    def _llamar(self, headers=None, metodo="GET", ruta="/ros", cuerpo=None,
                verifica=None):
        vistos = {"auditoria": [], "listar": 0, "crear": []}
        orig = {n: getattr(A, n) for n in
                ("_safe_audit", "listar_ros", "crear_ros", "auth_firebase")}

        class _Auth:
            TokenInvalido = F.TokenInvalido
            token_del_evento = staticmethod(F.token_del_evento)
            verificar = staticmethod(verifica or (lambda t: {
                "email": "analista@global66.com", "uid": "uid-1"}))

        A._safe_audit = lambda **k: vistos["auditoria"].append(k)
        A.listar_ros = lambda: (vistos.update(listar=vistos["listar"] + 1)
                                or A.resp(200, {"ros": []}))
        A.crear_ros = lambda b: (vistos["crear"].append(b)
                                 or A.resp(201, {"ros": {}}))
        A.auth_firebase = _Auth()
        try:
            r = A.handler({
                "requestContext": {"http": {"method": metodo, "path": ruta}},
                "rawPath": ruta, "headers": headers or {},
                "body": json.dumps(cuerpo) if cuerpo else None}, None)
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return r, vistos

    def test_sin_token_la_pantalla_sigue_andando(self):
        r, vistos = self._llamar()
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(vistos["listar"], 1)

    def test_y_queda_contada_con_la_ruta(self):
        _, vistos = self._llamar()
        sin = [a for a in vistos["auditoria"] if a.get("action") == "api.sin_token"]
        self.assertEqual(len(sin), 1)
        self.assertEqual(sin[0]["user_email"], "sin_token")
        self.assertIn("/ros", sin[0]["entity_id"])

    def test_NO_SE_INVENTA_UN_ACTOR(self):
        """Poner `unknown` donde no se sabe quién fue es exactamente lo que
        hace que un registro de auditoría deje de servir."""
        _, vistos = self._llamar()
        sin = [a for a in vistos["auditoria"] if a.get("action") == "api.sin_token"]
        self.assertNotEqual(sin[0]["user_email"], "unknown")

    def test_UN_TOKEN_INVALIDO_ES_401_AUNQUE_LA_RUTA_NO_LO_EXIJA(self):
        """Si se degradara a anónimo, un bug del front que mandara tokens
        vencidos pasaría invisible hasta el día del corte."""
        def _rechaza(t):
            raise F.TokenInvalido("La sesión no es válida o venció.")
        r, vistos = self._llamar(headers={"Authorization": f"Bearer {TOKEN}"},
                                 verifica=_rechaza)
        self.assertEqual(r["statusCode"], 401)
        self.assertEqual(vistos["listar"], 0, "atendió igual")

    def test_un_header_mal_formado_tambien_es_401(self):
        r, _ = self._llamar(headers={"Authorization": TOKEN})
        self.assertEqual(r["statusCode"], 401)

    def test_google_caido_es_503_y_no_401(self):
        """Un problema de red no se le muestra al analista como «tu sesión no
        vale»: lo mandaría a cerrar sesión y volver a entrar para nada."""
        def _cae(t):
            raise RuntimeError("sin red")
        r, _ = self._llamar(headers={"Authorization": f"Bearer {TOKEN}"},
                            verifica=_cae)
        self.assertEqual(r["statusCode"], 503)

    def test_CON_TOKEN_EL_ACTOR_SALE_DEL_TOKEN(self):
        """El `actor_email` del cuerpo deja de tener efecto. Es el punto."""
        _, vistos = self._llamar(
            headers={"Authorization": f"Bearer {TOKEN}"}, metodo="POST",
            cuerpo={"case_id": "c-1", "actor_email": "otro@global66.com"})
        self.assertEqual(vistos["crear"][0]["actor_email"],
                         "analista@global66.com")
        self.assertEqual(vistos["crear"][0]["quien"], "analista@global66.com")

    def test_con_token_no_se_cuenta_como_sin_token(self):
        _, vistos = self._llamar(headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(
            [a for a in vistos["auditoria"] if a.get("action") == "api.sin_token"],
            [])
