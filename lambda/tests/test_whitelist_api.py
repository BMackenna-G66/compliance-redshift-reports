# -*- coding: utf-8 -*-
"""El alta de whitelist por API externa: qué deja pasar y qué no.

Una entrada de whitelist deja de alertar sobre un cliente. El sistema que la
pide ya hizo sus controles, pero sobre SU modelo; los de acá —el caso existe,
el cliente es el del caso, quien lo pide trabaja acá— sólo los puede afirmar
WatchTower. Cada uno tiene su test, y cada uno fue una forma concreta de
silenciar a alguien que nadie revisó.

Los dos que no son obvios:

  * **El alcance `report` sin reporte no excluye nada.** El Report Runner
    aplica la entrada si el alcance es global o si el nombre del reporte
    coincide; con el nombre vacío no coincide con ninguno. La entrada se ve
    en la pantalla, vence a los 30 días y no silencia nada. 10 de los 328
    casos no tienen reporte de origen, así que no es hipotético.

  * **La idempotencia no corre el vencimiento.** Un reintento tiene que
    devolver la entrada que ya está, no crear otra ni estirarle el plazo: si
    lo estirara, un sistema que reintenta solo mantendría a un cliente
    silenciado para siempre sin que nadie lo decida.

Los ids y correos son ficticios: el repo es público.
"""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_externa as X  # noqa: E402
import whitelist_api as W  # noqa: E402

AHORA = 1_800_000_000
UN_DIA = 86_400

USUARIOS = [
    {"email": "ana.perez@ejemplo.test", "is_active": True},
    {"email": "Luis.Soto@Ejemplo.test", "is_active": True},
    {"email": "ex.analista@ejemplo.test", "is_active": False},
    # Un registro viejo sin el campo: no autoriza.
    {"email": "sin.flag@ejemplo.test"},
]

CASO = {
    "case_id": "caso-0001",
    "entity_type": "customer",
    "entity_id": "90000001",
    "report_name": "psp_alerts_cl",
}


def cuerpo(**cambios):
    base = {
        "cliente": {"tipo": "customer", "id": "90000001"},
        "caso_id": "caso-0001",
        "motivo": "Operación verificada con el cliente, es su nómina mensual.",
        "solicitado_por": "ana.perez@ejemplo.test",
    }
    base.update(cambios)
    return base


class ElPermisoEsPropio(unittest.TestCase):
    """Gestionar casos no da derecho a silenciar alertas."""

    def test_los_dos_permisos_son_validos(self):
        self.assertIn(X.WHITELIST_LEER, X.PERMISOS_VALIDOS)
        self.assertIn(X.WHITELIST_ESCRIBIR, X.PERMISOS_VALIDOS)

    def test_no_se_heredan_de_los_de_casos(self):
        for p in (X.LEER, X.ESCRIBIR, X.COMUNICAR):
            self.assertNotIn(p, (X.WHITELIST_LEER, X.WHITELIST_ESCRIBIR))

    def test_una_clave_que_gestiona_casos_no_escribe_whitelist(self):
        X._cache = {"octopus": {"clave": "k-casos-000000000000",
                                "permisos": {X.LEER, X.ESCRIBIR, X.COMUNICAR},
                                "activo": True}}
        try:
            c, motivo = X.autorizar({"headers": {"x-api-key": "k-casos-000000000000"}},
                                    X.WHITELIST_ESCRIBIR)
            self.assertIsNone(c)
            self.assertEqual(motivo[0], 403)
        finally:
            X._cache = None

    def test_el_permiso_de_lectura_no_alcanza_para_escribir(self):
        X._cache = {"octopus": {"clave": "k-wl-lee-0000000000",
                                "permisos": {X.WHITELIST_LEER},
                                "activo": True}}
        try:
            ev = {"headers": {"x-api-key": "k-wl-lee-0000000000"}}
            self.assertIsNone(X.autorizar(ev, X.WHITELIST_ESCRIBIR)[0])
            self.assertIsNotNone(X.autorizar(ev, X.WHITELIST_LEER)[0])
        finally:
            X._cache = None


class QuienLoPide(unittest.TestCase):
    """`solicitado_por` tiene que ser un usuario registrado y activo."""

    def test_un_usuario_registrado_y_activo_puede(self):
        self.assertTrue(W.usuario_habilitado(USUARIOS, "ana.perez@ejemplo.test"))

    def test_cualquier_usuario_no_solo_la_analista_del_caso(self):
        # Definición de Benjamín (23-10-2026): el control es "es de este
        # equipo", no "es la asignada". Luis no está asignado a ningún caso.
        self.assertTrue(W.usuario_habilitado(USUARIOS, "luis.soto@ejemplo.test"))

    def test_el_correo_se_compara_normalizado(self):
        self.assertTrue(W.usuario_habilitado(USUARIOS, "  LUIS.SOTO@EJEMPLO.TEST  "))

    def test_un_usuario_dado_de_baja_no_puede(self):
        self.assertFalse(W.usuario_habilitado(USUARIOS, "ex.analista@ejemplo.test"))

    def test_un_desconocido_no_puede(self):
        self.assertFalse(W.usuario_habilitado(USUARIOS, "cualquiera@otraempresa.test"))

    def test_un_registro_sin_el_flag_no_autoriza(self):
        # `is_active` se lee con default False. La proyección de la pantalla
        # usa default True, que es permisivo: en un control de acceso el
        # default tiene que ser el que no deja pasar.
        self.assertFalse(W.usuario_habilitado(USUARIOS, "sin.flag@ejemplo.test"))

    def test_sin_padron_no_pasa_nadie(self):
        self.assertFalse(W.usuario_habilitado([], "ana.perez@ejemplo.test"))

    def test_el_correo_vacio_no_pasa(self):
        self.assertFalse(W.usuario_habilitado(USUARIOS, ""))


class LaFormaDelCuerpo(unittest.TestCase):

    def test_un_cuerpo_completo_pasa(self):
        self.assertEqual(W.motivo_de_rechazo_alta(cuerpo()), "")

    def test_el_caso_es_obligatorio(self):
        self.assertIn("caso_id", W.motivo_de_rechazo_alta(cuerpo(caso_id="")))

    def test_el_motivo_es_obligatorio(self):
        self.assertIn("motivo", W.motivo_de_rechazo_alta(cuerpo(motivo="   ")))

    def test_el_solicitante_es_obligatorio(self):
        self.assertIn("solicitado_por",
                      W.motivo_de_rechazo_alta(cuerpo(solicitado_por="")))

    def test_el_id_del_cliente_es_solo_digitos(self):
        malo = cuerpo(cliente={"tipo": "customer", "id": "90000001'); DROP"})
        self.assertIn("dígitos", W.motivo_de_rechazo_alta(malo))

    def test_el_motivo_del_rechazo_no_repite_el_valor(self):
        # El texto va al cliente y al log. Si el valor es un intento de
        # inyección, no tiene por qué viajar a ninguno de los dos.
        payload = "\\') AND (1=0) --"
        texto = W.motivo_de_rechazo_alta(cuerpo(cliente={"tipo": "customer",
                                                         "id": payload}))
        self.assertNotIn(payload, texto)
        self.assertNotIn("1=0", texto)

    def test_un_tipo_de_cliente_desconocido_se_rechaza(self):
        malo = cuerpo(cliente={"tipo": "beneficiary", "id": "90000001"})
        self.assertIn("cliente.tipo", W.motivo_de_rechazo_alta(malo))

    def test_company_es_un_tipo_valido(self):
        self.assertEqual(
            W.motivo_de_rechazo_alta(cuerpo(cliente={"tipo": "company",
                                                     "id": "77000001"})), "")

    def test_el_motivo_largo_se_rechaza(self):
        self.assertIn("500", W.motivo_de_rechazo_alta(cuerpo(motivo="x" * 501)))


class ElAlcanceNoSePideGlobal(unittest.TestCase):
    """`global` saca al cliente de TODOS los reportes, `high_risk_countries`
    incluido. Esa decisión se toma en la pantalla, no por una integración."""

    def test_el_alcance_por_defecto_es_el_reporte(self):
        self.assertEqual(W.ALCANCE, "report")

    def test_pedir_global_se_rechaza(self):
        texto = W.motivo_de_rechazo_alta(cuerpo(alcance="global"))
        self.assertIn("pantalla", texto)

    def test_pedir_el_reporte_explicitamente_pasa(self):
        self.assertEqual(W.motivo_de_rechazo_alta(cuerpo(alcance="report")), "")


class LaDuracion(unittest.TestCase):

    def test_por_defecto_son_30_dias(self):
        self.assertEqual(W.dias_de(cuerpo()), 30)
        self.assertEqual(W.DIAS_POR_DEFECTO, 30)

    def test_se_pueden_pedir_60_o_90(self):
        self.assertEqual(W.dias_de(cuerpo(dias=60)), 60)
        self.assertEqual(W.dias_de(cuerpo(dias="90")), 90)

    def test_cualquier_otro_numero_se_rechaza(self):
        self.assertIsNone(W.dias_de(cuerpo(dias=365)))
        self.assertIn("30, 60 o 90", W.motivo_de_rechazo_alta(cuerpo(dias=365)))

    def test_un_valor_que_no_es_numero_se_rechaza(self):
        self.assertIsNone(W.dias_de(cuerpo(dias="para siempre")))


class ElClienteEsElDelCaso(unittest.TestCase):
    """El control que no se le puede delegar a quien llama: si se equivoca de
    caso, se silencia a alguien que nadie revisó."""

    def test_el_cliente_del_caso_coincide(self):
        self.assertEqual(
            W.desajuste_con_el_caso(CASO, {"tipo": "customer", "id": "90000001"}), "")

    def test_otro_id_no_coincide(self):
        self.assertIn("no es el del caso",
                      W.desajuste_con_el_caso(CASO, {"tipo": "customer",
                                                      "id": "90000002"}))

    def test_el_mismo_numero_con_otro_tipo_no_coincide(self):
        # 90000001 como empresa es otro cliente distinto del customer 90000001.
        self.assertIn("tipo",
                      W.desajuste_con_el_caso(CASO, {"tipo": "company",
                                                      "id": "90000001"}))

    def test_el_tipo_viejo_customer_id_se_acepta(self):
        # Un caso real guardado dice `customer_id` en vez de `customer`. Es un
        # tipeo del dato, no otro cliente: rechazarlo sería un 409 que nadie
        # puede explicar.
        viejo = {**CASO, "entity_type": "customer_id"}
        self.assertEqual(
            W.desajuste_con_el_caso(viejo, {"tipo": "customer", "id": "90000001"}), "")

    def test_un_caso_sin_tipo_de_cliente_no_pasa(self):
        self.assertIn("tipo",
                      W.desajuste_con_el_caso({**CASO, "entity_type": ""},
                                              {"tipo": "customer", "id": "90000001"}))


class ElReporteDelCaso(unittest.TestCase):

    def test_sale_del_caso(self):
        self.assertEqual(W.reporte_del_caso(CASO), "psp_alerts_cl")

    def test_un_caso_sin_reporte_no_tiene_alcance(self):
        # El handler responde 409 con esto: una entrada `report` sin nombre de
        # reporte queda guardada y no excluye nada.
        self.assertEqual(W.reporte_del_caso({**CASO, "report_name": ""}), "")


class LaIdempotencia(unittest.TestCase):

    def entrada(self, **cambios):
        base = {
            "whitelist_id": "wl-0001",
            "entity_field": "customer_id",
            "entity_value": "90000001",
            "scope": "report",
            "report_name": "psp_alerts_cl",
            "expires_at": AHORA + 10 * UN_DIA,
            "created_at": "2026-10-20 10:00:00",
        }
        base.update(cambios)
        return base

    def test_una_vigente_del_mismo_alcance_ya_cubre(self):
        ya = W.entrada_que_ya_cubre([self.entrada()], "customer_id", "90000001",
                                    "psp_alerts_cl", ahora=AHORA)
        self.assertEqual(ya["whitelist_id"], "wl-0001")

    def test_una_global_vigente_tambien_cubre(self):
        # Así la aplica el Report Runner: `scope == "global"` entra en todos
        # los reportes. Crear una segunda más angosta no cambiaría nada.
        ya = W.entrada_que_ya_cubre([self.entrada(scope="global", report_name="")],
                                    "customer_id", "90000001", "psp_alerts_cl",
                                    ahora=AHORA)
        self.assertIsNotNone(ya)

    def test_una_de_otro_reporte_no_cubre(self):
        self.assertIsNone(
            W.entrada_que_ya_cubre([self.entrada(report_name="otro_reporte")],
                                   "customer_id", "90000001", "psp_alerts_cl",
                                   ahora=AHORA))

    def test_una_vencida_no_cubre(self):
        self.assertIsNone(
            W.entrada_que_ya_cubre([self.entrada(expires_at=AHORA - UN_DIA)],
                                   "customer_id", "90000001", "psp_alerts_cl",
                                   ahora=AHORA))

    def test_la_de_otro_cliente_no_cubre(self):
        self.assertIsNone(
            W.entrada_que_ya_cubre([self.entrada(entity_value="90000002")],
                                   "customer_id", "90000001", "psp_alerts_cl",
                                   ahora=AHORA))

    def test_el_mismo_numero_de_otro_campo_no_cubre(self):
        self.assertIsNone(
            W.entrada_que_ya_cubre([self.entrada(entity_field="company_id")],
                                   "customer_id", "90000001", "psp_alerts_cl",
                                   ahora=AHORA))

    def test_devuelve_la_entrada_tal_cual_sin_tocar_el_vencimiento(self):
        original = self.entrada()
        vence = original["expires_at"]
        ya = W.entrada_que_ya_cubre([original], "customer_id", "90000001",
                                    "psp_alerts_cl", ahora=AHORA)
        self.assertEqual(ya["expires_at"], vence)
        self.assertEqual(original["expires_at"], vence)


class LaConsulta(unittest.TestCase):

    def entradas(self):
        return [
            {"whitelist_id": "wl-a", "entity_field": "customer_id",
             "entity_value": "90000001", "scope": "report",
             "report_name": "psp_alerts_cl", "expires_at": AHORA + UN_DIA,
             "created_at": "2026-10-21 09:00:00"},
            {"whitelist_id": "wl-b", "entity_field": "customer_id",
             "entity_value": "90000001", "scope": "global",
             "expires_at": AHORA + 5 * UN_DIA,
             "created_at": "2026-10-22 09:00:00"},
            {"whitelist_id": "wl-vieja", "entity_field": "customer_id",
             "entity_value": "90000001", "scope": "global",
             "expires_at": AHORA - UN_DIA, "created_at": "2026-09-01 09:00:00"},
            {"whitelist_id": "wl-otro", "entity_field": "customer_id",
             "entity_value": "90000002", "scope": "global",
             "expires_at": AHORA + UN_DIA, "created_at": "2026-10-22 09:00:00"},
        ]

    def test_devuelve_solo_las_vigentes_de_ese_cliente(self):
        v = W.vigentes_de(self.entradas(), "customer_id", "90000001", ahora=AHORA)
        self.assertEqual([e["whitelist_id"] for e in v], ["wl-b", "wl-a"])

    def test_sin_entradas_no_esta_vigente(self):
        self.assertEqual(
            W.vigentes_de(self.entradas(), "company_id", "90000001", ahora=AHORA), [])

    def test_la_proyeccion_dice_quien_y_desde_donde(self):
        p = W.entrada_publica({
            "whitelist_id": "wl-a", "entity_field": "customer_id",
            "entity_value": "90000001", "scope": "report",
            "report_name": "psp_alerts_cl", "case_id": "caso-0001",
            "reason": "revisado con el cliente",
            "solicitado_por": "ana.perez@ejemplo.test", "origen": "api:octopus",
            "created_at": "2026-10-21 09:00:00",
            "expires_at_str": "2026-11-20 09:00:00", "duration_days": 30})
        self.assertEqual(p["solicitado_por"], "ana.perez@ejemplo.test")
        self.assertEqual(p["origen"], "api:octopus")
        self.assertEqual(p["cliente"], {"tipo": "customer", "id": "90000001"})
        self.assertEqual(p["hasta"], "2026-11-20 09:00:00")

    def test_una_entrada_de_pantalla_cae_a_created_by(self):
        # Las altas viejas y las de pantalla no tienen `solicitado_por`.
        p = W.entrada_publica({"entity_field": "company_id",
                               "entity_value": "77000001",
                               "created_by": "rocio.ejemplo@ejemplo.test"})
        self.assertEqual(p["solicitado_por"], "rocio.ejemplo@ejemplo.test")
        self.assertEqual(p["origen"], "")
        self.assertEqual(p["cliente"]["tipo"], "company")


class LaNotaDelCaso(unittest.TestCase):

    def test_dice_quien_lo_pidio_desde_donde_y_por_que(self):
        n = W.nota_de_alta("ana.perez@ejemplo.test", "api:octopus",
                           "psp_alerts_cl", 30, "nómina mensual verificada")
        self.assertIn("ana.perez@ejemplo.test", n)
        self.assertIn("api:octopus", n)
        self.assertIn("psp_alerts_cl", n)
        self.assertIn("30 días", n)
        self.assertIn("nómina mensual verificada", n)


class ElTiempoPorDefecto(unittest.TestCase):
    """Las funciones aceptan `ahora` para los tests, pero sin él usan el reloj
    real: un default congelado haría que en producción nada venza."""

    def test_sin_ahora_usa_el_reloj(self):
        vencida = {"entity_field": "customer_id", "entity_value": "90000001",
                   "scope": "global", "expires_at": int(time.time()) - 10}
        self.assertIsNone(W.entrada_que_ya_cubre([vencida], "customer_id",
                                                 "90000001", "psp_alerts_cl"))
        self.assertEqual(W.vigentes_de([vencida], "customer_id", "90000001"), [])


class ElEndpoint(unittest.TestCase):
    """El camino completo de `POST /v1/whitelist`, con S3 simulado.

    Lo que prueba que no prueban las funciones puras: que cada control esté
    efectivamente CABLEADO en el handler, en el orden correcto, y que cuando
    uno rechaza NO se escriba nada. Un control que existe y no se llama es
    peor que no tenerlo: da la tranquilidad sin el efecto.
    """

    CLAVE = "k-octopus-00000000000"

    def setUp(self):
        import api_handler as A
        self.A = A
        X._cache = {"octopus": {"clave": self.CLAVE,
                                "permisos": {X.WHITELIST_LEER, X.WHITELIST_ESCRIBIR},
                                "activo": True},
                    "solo-casos": {"clave": "k-casos-0000000000000",
                                   "permisos": {X.LEER, X.ESCRIBIR},
                                   "activo": True}}
        self.casos = {"caso-0001": dict(CASO)}
        self.whitelist = []
        self.puesto = []
        self.notas = []
        self.auditado = []
        self._orig = {n: getattr(A, n) for n in
                      ("_crm_get", "_crm_list", "_crm_put", "_safe_audit",
                       "get_users", "add_case_note")}
        A._crm_get = lambda tipo, k: (self.casos.get(k) if tipo == "cases" else None)
        A._crm_list = lambda tipo: (list(self.whitelist) if tipo == "whitelist" else [])
        A._crm_put = lambda tipo, k, v: self.puesto.append(v)
        A._safe_audit = lambda **k: self.auditado.append(k)
        A.get_users = lambda: A.resp(200, {"users": USUARIOS})
        A.add_case_note = lambda cid, b: (self.notas.append((cid, b))
                                          or A.resp(201, {"message": "ok"}))

    def tearDown(self):
        for n, f in self._orig.items():
            setattr(self.A, n, f)
        X._cache = None

    def alta(self, cuerpo_=None, clave=None):
        import json as _json
        ev = {"headers": {"x-api-key": clave or self.CLAVE}}
        r = self.A.v1_whitelist_alta(ev, cuerpo() if cuerpo_ is None else cuerpo_)
        return r["statusCode"], _json.loads(r["body"])

    def consulta(self, cid="90000001", q=None, clave=None):
        import json as _json
        ev = {"headers": {"x-api-key": clave or self.CLAVE}}
        r = self.A.v1_whitelist_consulta(ev, cid, q or {})
        return r["statusCode"], _json.loads(r["body"])

    # ── lo que tiene que funcionar ──────────────────────────────────────
    def test_el_alta_valida_crea_la_entrada(self):
        codigo, d = self.alta()
        self.assertEqual(codigo, 201)
        self.assertFalse(d["ya_existia"])
        self.assertEqual(len(self.puesto), 1)
        guardado = self.puesto[0]
        self.assertEqual(guardado["entity_field"], "customer_id")
        self.assertEqual(guardado["entity_value"], "90000001")
        self.assertEqual(guardado["scope"], "report")
        self.assertEqual(guardado["report_name"], "psp_alerts_cl")
        self.assertEqual(guardado["duration_days"], 30)

    def test_guarda_quien_lo_pidio_desde_donde_y_el_caso(self):
        self.alta()
        g = self.puesto[0]
        self.assertEqual(g["solicitado_por"], "ana.perez@ejemplo.test")
        self.assertEqual(g["origen"], "api:octopus")
        self.assertEqual(g["case_id"], "caso-0001")
        # `created_by` se llena igual para que la columna que ya existe en las
        # dos pantallas no quede vacía con un bundle viejo.
        self.assertEqual(g["created_by"], "ana.perez@ejemplo.test")

    def test_deja_la_nota_en_el_caso(self):
        self.alta()
        self.assertEqual(len(self.notas), 1)
        caso_id, nota = self.notas[0]
        self.assertEqual(caso_id, "caso-0001")
        self.assertIn("ana.perez@ejemplo.test", nota["content"])
        # El autor de la nota es el sistema: acá el autor no es declarativo.
        self.assertEqual(nota["author_email"], "api:octopus")

    def test_se_audita_COMO_PEDIDO(self):
        """`whitelist.solicitar`, no `whitelist.add`.

        El alta dejó de ser el final del trámite: Octopus PIDE y un Oficial
        firma. Si las dos acciones se llamaran igual, la auditoría no
        distinguiría al que pidió del que decidió.
        """
        self.alta()
        self.assertEqual(len(self.auditado), 1)
        a = self.auditado[0]
        self.assertEqual(a["action"], "whitelist.solicitar")
        self.assertEqual(a["user_email"], "ana.perez@ejemplo.test")
        # La auditoría no lleva el id del cliente.
        self.assertNotIn("90000001", str(a))

    def test_LO_QUE_PIDE_OCTOPUS_NACE_PENDIENTE(self):
        """Que el pedido venga de un sistema no lo hace más firmado.

        Un sistema externo que silenciara clientes sin pasar por un Oficial
        sería la misma puerta que el control vino a cerrar, con un candado
        más caro.
        """
        import whitelist_aprobacion
        self.alta()
        entrada = self.puesto[0][1] if isinstance(self.puesto[0], tuple) else self.puesto[0]
        self.assertEqual(entrada["estado"], "pendiente")
        self.assertFalse(whitelist_aprobacion.aplica(entrada))
        # Y el cuatro ojos mide contra quien lo pidió de verdad, no contra
        # el sistema que lo mandó.
        self.assertEqual(entrada["solicitado_por"], "ana.perez@ejemplo.test")

    def test_si_la_nota_falla_el_alta_igual_queda(self):
        self.A.add_case_note = lambda cid, b: (_ for _ in ()).throw(RuntimeError("s3"))
        codigo, _ = self.alta()
        self.assertEqual(codigo, 201)
        self.assertEqual(len(self.puesto), 1)

    # ── lo que tiene que rechazar ───────────────────────────────────────
    def test_sin_clave_es_401_y_no_escribe(self):
        import json as _json
        r = self.A.v1_whitelist_alta({"headers": {}}, cuerpo())
        self.assertEqual(r["statusCode"], 401)
        self.assertEqual(self.puesto, [])
        self.assertEqual(_json.loads(r["body"])["error"], "no_autorizado")

    def test_una_clave_de_casos_es_403_y_no_escribe(self):
        codigo, d = self.alta(clave="k-casos-0000000000000")
        self.assertEqual(codigo, 403)
        self.assertEqual(d["error"], "sin_permiso")
        self.assertEqual(self.puesto, [])

    def test_un_caso_que_no_existe_es_404(self):
        codigo, _ = self.alta(cuerpo(caso_id="caso-9999"))
        self.assertEqual(codigo, 404)
        self.assertEqual(self.puesto, [])

    def test_otro_cliente_que_el_del_caso_es_409(self):
        codigo, d = self.alta(cuerpo(cliente={"tipo": "customer", "id": "90000002"}))
        self.assertEqual(codigo, 409)
        self.assertEqual(d["error"], "cliente_no_es_del_caso")
        self.assertEqual(self.puesto, [])

    def test_un_caso_sin_reporte_es_409_y_NO_cae_a_global(self):
        """Lo que pasaría sin este control: la entrada se guarda con alcance
        `report` y nombre vacío, no coincide con ningún reporte y no silencia
        nada. Caer a `global` sería lo contrario: excluir de todos."""
        self.casos["caso-0001"]["report_name"] = ""
        codigo, d = self.alta()
        self.assertEqual(codigo, 409)
        self.assertEqual(d["error"], "caso_sin_reporte")
        self.assertEqual(self.puesto, [])

    def test_un_solicitante_no_registrado_es_403(self):
        codigo, d = self.alta(cuerpo(solicitado_por="alguien@otraempresa.test"))
        self.assertEqual(codigo, 403)
        self.assertEqual(d["error"], "solicitante_no_habilitado")
        self.assertEqual(self.puesto, [])

    def test_un_solicitante_dado_de_baja_es_403_con_el_MISMO_mensaje(self):
        # Distinguir "no existe" de "está de baja" filtra quién trabaja acá.
        _, ajeno = self.alta(cuerpo(solicitado_por="alguien@otraempresa.test"))
        codigo, baja = self.alta(cuerpo(solicitado_por="ex.analista@ejemplo.test"))
        self.assertEqual(codigo, 403)
        self.assertEqual(baja, ajeno)
        self.assertEqual(self.puesto, [])

    def test_el_payload_de_inyeccion_es_400_y_no_escribe(self):
        codigo, d = self.alta(cuerpo(cliente={"tipo": "customer",
                                              "id": "\\') AND (1=0) --"}))
        self.assertEqual(codigo, 400)
        self.assertEqual(self.puesto, [])
        self.assertNotIn("1=0", d["error"])

    def test_sin_motivo_es_400(self):
        codigo, _ = self.alta(cuerpo(motivo=""))
        self.assertEqual(codigo, 400)
        self.assertEqual(self.puesto, [])

    def test_el_cuerpo_no_puede_declarar_el_origen(self):
        # `origen` sale de la clave presentada, no del cuerpo: si lo pudiera
        # declarar quien llama, la auditoría diría lo que él quiera.
        self.alta(cuerpo(origen="api:otro-sistema"))
        self.assertEqual(self.puesto[0]["origen"], "api:octopus")

    # ── idempotencia ────────────────────────────────────────────────────
    def test_el_reintento_devuelve_la_que_ya_esta_sin_crear_otra(self):
        self.alta()
        self.whitelist = list(self.puesto)
        vence = self.whitelist[0]["expires_at"]

        codigo, d = self.alta()
        self.assertEqual(codigo, 200)
        self.assertTrue(d["ya_existia"])
        self.assertEqual(d["whitelist_id"], self.whitelist[0]["whitelist_id"])
        self.assertEqual(len(self.puesto), 1, "creó una segunda entrada")
        self.assertEqual(self.whitelist[0]["expires_at"], vence,
                         "le corrió el vencimiento a la entrada que ya estaba")

    def test_el_reintento_no_deja_una_segunda_nota(self):
        self.alta()
        self.whitelist = list(self.puesto)
        self.alta()
        self.assertEqual(len(self.notas), 1)

    # ── la consulta ─────────────────────────────────────────────────────
    def test_la_consulta_dice_si_esta_vigente(self):
        self.alta()
        self.whitelist = list(self.puesto)
        codigo, d = self.consulta()
        self.assertEqual(codigo, 200)
        self.assertTrue(d["vigente"])
        self.assertEqual(d["entradas"][0]["caso_id"], "caso-0001")
        self.assertEqual(d["entradas"][0]["origen"], "api:octopus")

    def test_un_cliente_sin_entradas_no_esta_vigente(self):
        codigo, d = self.consulta()
        self.assertEqual(codigo, 200)
        self.assertFalse(d["vigente"])
        self.assertEqual(d["entradas"], [])

    def test_la_consulta_exige_el_permiso_de_lectura(self):
        codigo, _ = self.consulta(clave="k-casos-0000000000000")
        self.assertEqual(codigo, 403)

    def test_la_consulta_distingue_customer_de_company(self):
        self.alta()
        self.whitelist = list(self.puesto)
        self.assertFalse(self.consulta(q={"tipo": "company"})[1]["vigente"])
        self.assertTrue(self.consulta(q={"tipo": "customer"})[1]["vigente"])

    def test_la_consulta_rechaza_un_id_que_no_es_numero(self):
        codigo, _ = self.consulta(cid="\\') AND (1=0) --")
        self.assertEqual(codigo, 400)


class ElRuteo(unittest.TestCase):
    """Que las rutas estén colgadas del árbol `/v1` y no en otro lado."""

    def test_las_rutas_figuran_en_el_404_de_la_api_externa(self):
        import json as _json
        import api_handler as A
        r = A.handler({"rawPath": "/v1/nada",
                       "requestContext": {"http": {"method": "GET"}},
                       "headers": {}}, None)
        rutas = " ".join(_json.loads(r["body"]).get("rutas", []))
        self.assertIn("POST   /v1/whitelist", rutas)
        self.assertIn("GET    /v1/whitelist/{cliente_id}", rutas)

    def _por_la_ruta(self, metodo, ruta, cuerpo_=""):
        import json as _json
        import api_handler as A
        r = A.handler({"rawPath": ruta,
                       "requestContext": {"http": {"method": metodo}},
                       "headers": {}, "body": cuerpo_}, None)
        return r["statusCode"], _json.loads(r["body"])

    def test_el_POST_llega_al_handler_y_pide_la_clave(self):
        # 401 y no 404: prueba que la ruta está CABLEADA. Llamar a
        # `v1_whitelist_alta` directo no lo prueba — la función podía existir
        # y no estar colgada de ningún lado.
        codigo, d = self._por_la_ruta("POST", "/v1/whitelist", "{}")
        self.assertEqual(codigo, 401)
        self.assertEqual(d["error"], "no_autorizado")

    def test_el_GET_de_consulta_llega_al_handler_y_pide_la_clave(self):
        codigo, d = self._por_la_ruta("GET", "/v1/whitelist/90000001")
        self.assertEqual(codigo, 401)
        self.assertEqual(d["error"], "no_autorizado")

    def test_un_metodo_que_no_existe_es_404_y_no_200(self):
        # No hay DELETE por API: la baja sigue siendo de la pantalla.
        codigo, _ = self._por_la_ruta("DELETE", "/v1/whitelist/90000001")
        self.assertEqual(codigo, 404)

    def test_la_whitelist_interna_sigue_en_su_ruta(self):
        # `/whitelist` (pantallas) y `/v1/whitelist` (API) son dos rutas
        # distintas: el prefijo `/v1` no puede tragarse la interna.
        import api_handler as A
        self.assertIsNotNone(getattr(A, "add_to_whitelist", None))
        self.assertIsNotNone(getattr(A, "v1_whitelist_alta", None))


if __name__ == "__main__":
    unittest.main()


class ElContratoDiceSiSILENCIA(unittest.TestCase):
    """Que `estado` y `silencia` no se desincronicen del módulo de aprobación.

    `whitelist_api` es puro y no importa `whitelist_aprobacion`: duplica la
    lectura del campo para no arrastrar la dependencia. Esto es lo que
    sostiene esa duplicación.
    """

    def test_los_estados_son_los_mismos_de_los_dos_lados(self):
        import whitelist_aprobacion as W
        import whitelist_api as A
        for estado in W.ESTADOS:
            with self.subTest(estado=estado):
                self.assertEqual(A._estado({"estado": estado}), estado)

    def test_sin_estado_las_dos_dicen_heredada(self):
        import whitelist_aprobacion as W
        import whitelist_api as A
        vieja = {"whitelist_id": "x", "created_at": "2026-08-01 00:00:00"}
        self.assertEqual(A._estado(vieja), W.HEREDADA)

    def test_UNA_PENDIENTE_NO_SILENCIA_EN_EL_CONTRATO(self):
        import whitelist_api as A
        pub = A.entrada_publica({"whitelist_id": "x", "estado": "pendiente"})
        self.assertEqual(pub["estado"], "pendiente")
        self.assertFalse(pub["silencia"])
        # Y no promete un «hasta» que todavía no existe.
        self.assertEqual(pub["hasta"], "")

    def test_una_aprobada_si_silencia_en_el_contrato(self):
        import whitelist_api as A
        pub = A.entrada_publica({"whitelist_id": "x", "estado": "aprobada",
                                 "expires_at_str": "2027-01-01 00:00:00"})
        self.assertTrue(pub["silencia"])

    def test_un_estado_inventado_no_se_toma_por_bueno(self):
        import whitelist_api as A
        self.assertEqual(A._estado({"estado": "aprobadisima"}), "heredada")
