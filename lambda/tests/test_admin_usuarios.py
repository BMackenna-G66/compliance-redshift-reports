# -*- coding: utf-8 -*-
"""Administrar usuarios es administrar permisos.

LO QUE PASABA. `delete_case` y otras cinco acciones pedían ser admin, pero
`POST/PUT/DELETE /users` no pedía nada. O sea que cualquiera que conociera la
URL podía darse el rol de administrador con un pedido y después hacer todo lo
demás: el guard existía, y al lado estaba abierta la puerta para saltárselo.

Comprobado el 27-09-2026 contra producción: cambié un rol con un `curl` sin
ser nadie.

LO QUE HAY QUE SOSTENER, y es lo que miran estos tests:

1. Escribir en el padrón pide ser admin. Leerlo no: la propia pantalla lo
   necesita para dibujarse.
2. El sistema NO se puede quedar sin administradores. Desde que hace falta
   ser admin para repartir permisos, un rol mal cargado dejaría a todos
   afuera y la única salida sería editar S3 a mano. De ahí el admin de
   arranque, que vale aunque el store diga otra cosa o no se pueda leer.
3. Queda escrito QUIÉN cambió un permiso. Antes el registro decía `"admin"` a
   secas, que es justo el dato que no sirve.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_handler as A  # noqa: E402

FIJO = sorted(A._ADMINS_FIJOS)[0]
PADRON = [
    {"email": "jefa@global66.com", "role_name": "admin", "is_active": True},
    {"email": "ana@global66.com", "role_name": "analyst", "is_active": True},
    {"email": "exjefe@global66.com", "role_name": "admin", "is_active": False},
]


class _Banco:
    def __init__(self, padron=None, store_roto=False):
        self.padron = PADRON if padron is None else padron
        self.store_roto = store_roto
        self.escrito = {}
        self.auditado = []

    def __enter__(self):
        self.orig = {n: getattr(A, n) for n in
                     ("_crm_list", "_crm_put", "_crm_update", "_safe_audit")}

        def listar(kind):
            if self.store_roto:
                raise RuntimeError("S3 caído")
            return self.padron if kind == "users" else []

        A._crm_list = listar
        A._crm_put = lambda k, i, d: self.escrito.__setitem__((k, i), d)
        A._crm_update = lambda k, i, d: (self.escrito.__setitem__((k, i), d) or
                                         {"email": i, **d})
        A._safe_audit = lambda **kw: self.auditado.append(kw)
        return self

    def __exit__(self, *a):
        for n, f in self.orig.items():
            setattr(A, n, f)


def llamar(fn, *args, **kw):
    banco = kw.pop("banco", None) or _Banco()
    with banco:
        r = fn(*args)
    return r["statusCode"], json.loads(r["body"]), banco


class EscribirEnElPadronPideSerAdmin(unittest.TestCase):

    def test_un_analista_no_puede_cambiar_roles(self):
        """El agujero que se cierra: con esto abierto, cualquiera se daba el
        rol de admin y el resto de los guards no servía de nada."""
        codigo, d, b = llamar(A.update_user, "ana@global66.com",
                              {"role_id": 3, "actor_email": "ana@global66.com"})
        self.assertEqual(codigo, 403)
        self.assertEqual(b.escrito, {}, "no tenía que haber escrito nada")

    def test_sin_decir_quien_es_tampoco(self):
        codigo, _, b = llamar(A.update_user, "ana@global66.com", {"role_id": 3})
        self.assertEqual(codigo, 403)
        self.assertEqual(b.escrito, {})

    def test_un_admin_desactivado_ya_no_es_admin(self):
        codigo, _, _ = llamar(A.update_user, "ana@global66.com",
                              {"role_id": 3, "actor_email": "exjefe@global66.com"})
        self.assertEqual(codigo, 403)

    def test_un_admin_activo_si_puede(self):
        codigo, _, b = llamar(A.update_user, "ana@global66.com",
                              {"role_id": 3, "actor_email": "jefa@global66.com"})
        self.assertEqual(codigo, 200)
        self.assertEqual(b.escrito[("users", "ana@global66.com")]["role_name"],
                         "admin")

    def test_crear_usuarios_tambien_pide_admin(self):
        codigo, _, b = llamar(A.create_user,
                              {"email": "nuevo@global66.com", "role_id": 3,
                               "actor_email": "ana@global66.com"})
        self.assertEqual(codigo, 403)
        self.assertEqual(b.escrito, {},
                         "si no, se crea un admin nuevo y da lo mismo el guard")

    def test_desactivar_usuarios_tambien(self):
        """Desactivar a todos los admins es otra forma de tomar el control."""
        codigo, _, b = llamar(A.deactivate_user, "jefa@global66.com",
                              {"actor_email": "ana@global66.com"})
        self.assertEqual(codigo, 403)
        self.assertEqual(b.escrito, {})

    def test_leer_el_padron_no_pide_nada(self):
        """La pantalla lo necesita para dibujarse; cerrarlo rompería la app
        sin cerrar ningún agujero: los correos ya se ven en cada caso."""
        import inspect
        self.assertNotIn("_require_admin", inspect.getsource(A.get_users))


class NoSePuedeQuedarSinAdministradores(unittest.TestCase):
    """Desde que repartir permisos pide ser admin, el sistema puede trabarse
    solo. Medido antes de este cambio: de 12 usuarios, CERO eran admin."""

    def test_el_admin_de_arranque_manda_aunque_el_padron_diga_otra_cosa(self):
        padron = [{"email": FIJO, "role_name": "analyst", "is_active": True}]
        codigo, _, _ = llamar(A.update_user, "ana@global66.com",
                              {"role_id": 3, "actor_email": FIJO},
                              banco=_Banco(padron=padron))
        self.assertEqual(codigo, 200)

    def test_vale_aunque_ni_siquiera_este_en_el_padron(self):
        codigo, _, _ = llamar(A.update_user, "ana@global66.com",
                              {"role_id": 3, "actor_email": FIJO},
                              banco=_Banco(padron=[]))
        self.assertEqual(codigo, 200)

    def test_vale_aunque_no_se_pueda_leer_el_padron(self):
        """Su razón de ser es que el store puede estar roto: si dependiera de
        leerlo, no serviría para nada."""
        codigo, _, _ = llamar(A.update_user, "ana@global66.com",
                              {"role_id": 3, "actor_email": FIJO},
                              banco=_Banco(store_roto=True))
        self.assertEqual(codigo, 200)

    def test_con_el_padron_roto_nadie_mas_entra(self):
        """Falla cerrado para todos los demás: el arranque es una excepción
        nombrada, no un agujero para cuando algo anda mal."""
        codigo, _, _ = llamar(A.update_user, "ana@global66.com",
                              {"role_id": 3, "actor_email": "jefa@global66.com"},
                              banco=_Banco(store_roto=True))
        self.assertEqual(codigo, 403)

    def test_no_distingue_mayusculas_ni_espacios(self):
        codigo, _, _ = llamar(A.update_user, "ana@global66.com",
                              {"role_id": 3, "actor_email": f"  {FIJO.upper()} "},
                              banco=_Banco(padron=[]))
        self.assertEqual(codigo, 200)

    def test_la_lista_sale_de_una_variable_de_entorno(self):
        """Para poder cambiarla sin tocar el código."""
        import inspect
        fuente = inspect.getsource(A)
        i = fuente.index("_ADMINS_FIJOS = {")
        self.assertIn("ADMINS_FIJOS", fuente[i:i + 400])
        self.assertIn("os.environ.get", fuente[i:i + 400])


class QuedaEscritoQuienCambioUnPermiso(unittest.TestCase):

    def test_el_registro_dice_quien_fue_y_no_admin_a_secas(self):
        _, _, b = llamar(A.update_user, "ana@global66.com",
                         {"role_id": 3, "actor_email": "jefa@global66.com"})
        self.assertEqual(b.auditado[0]["user_email"], "jefa@global66.com")

    def test_tambien_al_crear_y_al_desactivar(self):
        _, _, b = llamar(A.create_user,
                         {"email": "nuevo@global66.com",
                          "actor_email": "jefa@global66.com"})
        self.assertEqual(b.auditado[0]["user_email"], "jefa@global66.com")

        _, _, b2 = llamar(A.deactivate_user, "ana@global66.com",
                          {"actor_email": "jefa@global66.com"})
        self.assertEqual(b2.auditado[0]["user_email"], "jefa@global66.com")


class LosFrentesMandanElActor(unittest.TestCase):
    """Si el front no lo manda, el panel de usuarios responde 403 a todos —y
    el mensaje habla del rol, que es donde NO está el problema."""

    RAIZ = Path(__file__).resolve().parents[2]

    def test_v1_lo_manda_en_las_tres_llamadas(self):
        html = (self.RAIZ / "frontend" / "index.html").read_text(encoding="utf-8")
        for fragmento in ("'POST', '/users'", "`/users/${this.crmUserModal.userId}`",
                          "'DELETE', `/users/${userId}`"):
            i = html.index(fragmento)
            self.assertIn("actor_email", html[i:i + 400],
                          f"{fragmento} sale sin actor: el panel va a dar 403")

    def test_v2_lo_pone_en_todo_lo_que_escribe(self):
        api = (self.RAIZ / "frontend" / "v2" / "src" / "api.js").read_text(encoding="utf-8")
        self.assertIn("metodo !== 'GET'", api,
                      "v2 volvió a mandar cuerpo sólo cuando hay algo que mandar, "
                      "y los DELETE quedan sin actor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
