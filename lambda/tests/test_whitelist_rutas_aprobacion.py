# -*- coding: utf-8 -*-
"""Las rutas de aprobación de whitelist, con la API de verdad.

El módulo puro ya prueba las reglas. Acá se prueba lo que sólo se rompe en el
cableado: que la identidad salga del token y no del cuerpo, que la entrada se
guarde, que la auditoría no lleve el valor del cliente, y que una pendiente no
entre en el SQL de los reportes.
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
import whitelist_aprobacion as W  # noqa: E402

OFICIAL = "oficial@global66.com"
ANALISTA = "analista@global66.com"


def pendiente(**extra):
    e = {"whitelist_id": "w1", "entity_field": "customer_id",
         "entity_value": "9000001", "duration_days": 90, "scope": "global",
         "estado": "pendiente", "solicitado_por": ANALISTA,
         "created_by": ANALISTA}
    e.update(extra)
    return e


class _Base(unittest.TestCase):
    """Reemplaza S3, la auditoría, el padrón y el token."""

    def correr(self, fn, entrada, quien=OFICIAL, cuerpo=None, oficiales=None):
        guardado, auditado = {}, []
        orig = {n: getattr(A, n) for n in
                ("_crm_get", "_crm_put", "_safe_audit", "_identidad",
                 "_oficiales_cumplimiento")}
        A._crm_get = lambda t, k: (dict(entrada) if entrada else None)
        A._crm_put = lambda t, k, v: guardado.update(entrada=v)
        A._safe_audit = lambda **k: auditado.append(k)
        A._identidad = lambda ev: (({"email": quien, "uid": "u"}, None)
                                   if quien else (None, A.resp(401, {"error": "sin token"})))
        A._oficiales_cumplimiento = lambda: (
            [OFICIAL] if oficiales is None else oficiales)
        try:
            r = fn("w1", cuerpo or {}, {"headers": {}})
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return r, json.loads(r["body"]), guardado.get("entrada", {}), auditado


class Aprobar(_Base):

    def test_un_oficial_distinto_del_que_pidio_aprueba(self):
        r, d, guardado, _ = self.correr(A.aprobar_whitelist, pendiente())
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(guardado["estado"], "aprobada")
        self.assertEqual(guardado["aprobacion"]["por"], OFICIAL)

    def test_LA_IDENTIDAD_SALE_DEL_TOKEN_NO_DEL_CUERPO(self):
        """Aprobar con el `actor_email` de otro sería firmar por otro."""
        r, d, guardado, _ = self.correr(
            A.aprobar_whitelist, pendiente(),
            cuerpo={"actor_email": "otro@global66.com"})
        self.assertEqual(guardado["aprobacion"]["por"], OFICIAL)

    def test_SIN_TOKEN_NO_SE_APRUEBA(self):
        r, d, guardado, _ = self.correr(A.aprobar_whitelist, pendiente(),
                                        quien="")
        self.assertEqual(r["statusCode"], 401)
        self.assertEqual(guardado, {})

    def test_el_que_la_pidio_no_la_aprueba(self):
        r, d, guardado, _ = self.correr(
            A.aprobar_whitelist, pendiente(solicitado_por=OFICIAL))
        self.assertEqual(r["statusCode"], 409)
        self.assertTrue(any("pediste vos" in m for m in d["motivos"]))
        self.assertEqual(guardado, {})

    def test_quien_no_esta_en_el_padron_no_aprueba(self):
        r, d, _, _ = self.correr(A.aprobar_whitelist, pendiente(),
                                 quien="cualquiera@global66.com")
        self.assertEqual(r["statusCode"], 409)

    def test_el_padron_vacio_no_deja_aprobar_a_nadie(self):
        r, d, _, _ = self.correr(A.aprobar_whitelist, pendiente(), oficiales=[])
        self.assertEqual(r["statusCode"], 409)

    def test_una_entrada_que_no_existe_es_404(self):
        r, d, _, _ = self.correr(A.aprobar_whitelist, None)
        self.assertEqual(r["statusCode"], 404)

    def test_LA_AUDITORIA_NO_LLEVA_EL_VALOR_DEL_CLIENTE(self):
        """El log vive años y el valor identifica a una persona o empresa."""
        _, _, _, auditado = self.correr(A.aprobar_whitelist, pendiente())
        self.assertNotIn("9000001", json.dumps(auditado))

    def test_la_auditoria_dice_quien_pidio_y_quien_firmo(self):
        _, _, _, auditado = self.correr(A.aprobar_whitelist, pendiente())
        self.assertEqual(auditado[0]["action"], "whitelist.aprobar")
        self.assertEqual(auditado[0]["user_email"], OFICIAL)
        self.assertEqual(auditado[0]["new_value"]["solicitado_por"], ANALISTA)

    def test_al_aprobar_queda_la_fecha_de_vencimiento(self):
        r, d, guardado, _ = self.correr(A.aprobar_whitelist, pendiente())
        self.assertTrue(guardado["expires_at"])
        self.assertTrue(d["expires_at"])


class Rechazar(_Base):

    def test_rechazar_exige_motivo(self):
        """El que la pidió tiene que poder leer por qué no se aprobó."""
        r, d, guardado, _ = self.correr(A.rechazar_whitelist, pendiente())
        self.assertEqual(r["statusCode"], 400)
        self.assertEqual(guardado, {})

    def test_rechazar_guarda_el_motivo(self):
        r, d, guardado, _ = self.correr(
            A.rechazar_whitelist, pendiente(),
            cuerpo={"motivo": "el cliente sigue operando"})
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(guardado["estado"], "rechazada")
        self.assertEqual(guardado["rechazo"]["motivo"], "el cliente sigue operando")

    def test_EL_CUATRO_OJOS_VALE_TAMBIEN_PARA_RECHAZAR(self):
        """Rechazar lo propio es tan poco un control como aprobarlo."""
        r, d, _, _ = self.correr(A.rechazar_whitelist,
                                 pendiente(solicitado_por=OFICIAL),
                                 cuerpo={"motivo": "no"})
        self.assertEqual(r["statusCode"], 409)


class ElRuteo(unittest.TestCase):

    def _ruta(self, metodo, camino, **mocks):
        llamadas = []
        orig = {n: getattr(A, n) for n in ("aprobar_whitelist",
                                           "rechazar_whitelist",
                                           "remove_from_whitelist")}
        for n in orig:
            setattr(A, n, (lambda nombre: lambda *a, **k: (
                llamadas.append(nombre), A.resp(200, {}))[1])(n))
        try:
            A.handler({"rawPath": camino,
                       "requestContext": {"http": {"method": metodo}},
                       "headers": {}}, None)
        finally:
            for n, f in orig.items():
                setattr(A, n, f)
        return llamadas

    def test_aprobar_tiene_ruta(self):
        self.assertEqual(self._ruta("POST", "/whitelist/w1/aprobar"),
                         ["aprobar_whitelist"])

    def test_rechazar_tiene_ruta(self):
        self.assertEqual(self._ruta("POST", "/whitelist/w1/rechazar"),
                         ["rechazar_whitelist"])

    def test_LA_BAJA_SIGUE_FUNCIONANDO(self):
        """Las rutas nuevas van antes del DELETE genérico: que no lo tapen."""
        self.assertEqual(self._ruta("DELETE", "/whitelist/w1"),
                         ["remove_from_whitelist"])


class LoQueLlegaAlSQLDeLosReportes(unittest.TestCase):
    """La línea que hace que la aprobación signifique algo."""

    def test_UNA_PENDIENTE_NO_ENTRA_AL_SQL(self):
        self.assertFalse(W.aplica(pendiente()))

    def test_el_filtro_del_runner_usa_aplica(self):
        # Inspección de fuente: `handler.py` necesita env de AWS para
        # importarse, y lo que importa es que no exista una segunda condición
        # de vigencia que se olvide del estado.
        raiz = Path(__file__).resolve().parents[2]
        fuente = (raiz / "lambda" / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def fetch_active_whitelist(")
        cuerpo = fuente[i:i + 2500]
        self.assertIn("whitelist_aprobacion.aplica(i, now)", cuerpo)
        # Y que no quede la condición vieja al lado.
        self.assertNotIn("if exp and exp <= now:", cuerpo)

    def test_SIN_EL_MODULO_NO_APLICA_NINGUNA(self):
        """Fallar hacia 'no silenciar a nadie' es el lado seguro."""
        raiz = Path(__file__).resolve().parents[2]
        fuente = (raiz / "lambda" / "handler.py").read_text(encoding="utf-8")
        i = fuente.index("def fetch_active_whitelist(")
        cuerpo = fuente[i:i + 2500]
        self.assertIn("if not whitelist_aprobacion:", cuerpo)
        self.assertIn("return []", cuerpo)


if __name__ == "__main__":
    unittest.main()
