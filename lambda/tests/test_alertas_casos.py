# -*- coding: utf-8 -*-
"""Las columnas de caso en la tabla de Alertados.

La sutileza que esto cubre: hay DOS formas de que una alerta tenga caso, y
significan cosas distintas.

  · **Vinculado** — alguien ató esta alerta a ese caso. Es el dato preciso.
  · **Del cliente** — el cliente alertado tiene un caso, pero nadie ató esta
    alerta a él.

Medido sobre producción: 66 alertas vinculadas contra 72 cuyo cliente tiene
caso. Mostrar sólo el vínculo escondería 6; mostrarlas iguales haría que una
alerta sin atender parezca atendida. Por eso se informan distinto.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import api_handler as A  # noqa: E402


def caso(cid, cliente, estado="open", creado="2026-09-10 10:00:00", asignado=""):
    return {"case_id": cid, "entity_id": cliente, "status": estado,
            "created_at": creado, "assigned_to": asignado}


def indice(casos):
    por_id = {c["case_id"]: c for c in casos}
    por_cliente = {}
    for c in casos:
        por_cliente.setdefault(str(c["entity_id"]), []).append(c)
    for v in por_cliente.values():
        v.sort(key=lambda c: c["created_at"], reverse=True)
    return por_id, por_cliente


def alerta(cliente="123", case_id=""):
    return {"entity_value": cliente, "case_id": case_id}


class SinCaso(unittest.TestCase):

    def test_un_cliente_sin_casos(self):
        r = A._caso_de_la_alerta(alerta("999"), *indice([caso("c1", "123")]))
        self.assertFalse(r["tiene_caso"])
        self.assertEqual(r["caso_estado_es"], "Sin caso")
        self.assertEqual(r["casos_del_cliente"], 0)
        self.assertEqual(r["caso_id"], "")

    def test_sin_casos_en_todo_el_sistema(self):
        r = A._caso_de_la_alerta(alerta("123"), {}, {})
        self.assertFalse(r["tiene_caso"])


class VinculoExplicito(unittest.TestCase):

    def test_manda_el_caso_vinculado(self):
        casos = [caso("c1", "123", "closed"), caso("c2", "123", "open")]
        r = A._caso_de_la_alerta(alerta("123", "c1"), *indice(casos))
        self.assertEqual(r["caso_id"], "c1")
        self.assertEqual(r["caso_vinculo"], "vinculado")
        self.assertEqual(r["caso_estado_es"], "Cerrado")

    def test_el_vinculo_le_gana_al_caso_abierto_del_cliente(self):
        """Si alguien ató esta alerta a un caso cerrado, eso es lo que pasó con
        esta alerta — aunque el cliente tenga otro abierto."""
        casos = [caso("c1", "123", "closed"), caso("c2", "123", "open")]
        r = A._caso_de_la_alerta(alerta("123", "c1"), *indice(casos))
        self.assertEqual(r["caso_estado"], "closed")

    def test_un_vinculo_a_un_caso_borrado_cae_al_del_cliente(self):
        """Los casos se pueden borrar; el vínculo queda apuntando a la nada. En
        vez de decir 'sin caso', se informa el del cliente, que sí existe."""
        casos = [caso("c2", "123", "open")]
        r = A._caso_de_la_alerta(alerta("123", "borrado"), *indice(casos))
        self.assertTrue(r["tiene_caso"])
        self.assertEqual(r["caso_id"], "c2")
        self.assertEqual(r["caso_vinculo"], "del_cliente")


class CasoDelCliente(unittest.TestCase):

    def test_sin_vinculo_usa_el_del_cliente(self):
        r = A._caso_de_la_alerta(alerta("123"), *indice([caso("c1", "123")]))
        self.assertTrue(r["tiene_caso"])
        self.assertEqual(r["caso_vinculo"], "del_cliente")

    def test_con_varios_manda_el_abierto_mas_reciente(self):
        """9 clientes de producción tienen más de un caso."""
        casos = [caso("viejo", "123", "open", "2026-09-01 10:00:00"),
                 caso("nuevo", "123", "open", "2026-09-15 10:00:00")]
        r = A._caso_de_la_alerta(alerta("123"), *indice(casos))
        self.assertEqual(r["caso_id"], "nuevo")
        self.assertEqual(r["casos_del_cliente"], 2)

    def test_un_abierto_viejo_le_gana_a_un_cerrado_nuevo(self):
        """Lo que el analista necesita ver es lo que sigue pendiente."""
        casos = [caso("abierto", "123", "open", "2026-09-01 10:00:00"),
                 caso("cerrado", "123", "closed", "2026-09-15 10:00:00")]
        r = A._caso_de_la_alerta(alerta("123"), *indice(casos))
        self.assertEqual(r["caso_id"], "abierto")

    def test_si_estan_todos_cerrados_muestra_el_mas_reciente(self):
        casos = [caso("v", "123", "closed", "2026-09-01 10:00:00"),
                 caso("n", "123", "closed", "2026-09-15 10:00:00")]
        r = A._caso_de_la_alerta(alerta("123"), *indice(casos))
        self.assertEqual(r["caso_id"], "n")
        self.assertEqual(r["caso_estado_es"], "Cerrado")

    def test_archivado_cuenta_como_cerrado_para_elegir(self):
        casos = [caso("arch", "123", "archived", "2026-09-15 10:00:00"),
                 caso("abierto", "123", "under_review", "2026-09-01 10:00:00")]
        r = A._caso_de_la_alerta(alerta("123"), *indice(casos))
        self.assertEqual(r["caso_id"], "abierto")


class ElClienteSeComparaComoTexto(unittest.TestCase):
    """El id del cliente llega como número en el caso y como texto en la
    alerta; compararlos sin normalizar da 'sin caso' para todos."""

    def test_numero_contra_texto(self):
        por_id, por_cliente = indice([caso("c1", 4171334)])
        r = A._caso_de_la_alerta({"entity_value": "4171334", "case_id": ""},
                                 por_id, por_cliente)
        self.assertTrue(r["tiene_caso"])

    def test_con_espacios_alrededor(self):
        por_id, por_cliente = indice([caso("c1", "4171334")])
        r = A._caso_de_la_alerta({"entity_value": "  4171334  ", "case_id": ""},
                                 por_id, por_cliente)
        self.assertTrue(r["tiene_caso"])


class Etiquetas(unittest.TestCase):

    def test_los_estados_se_muestran_en_español(self):
        for interno, es in (("open", "Abierto"), ("in_progress", "En investigación"),
                            ("under_review", "Bajo revisión"), ("closed", "Cerrado")):
            r = A._caso_de_la_alerta(alerta("123"), *indice([caso("c1", "123", interno)]))
            with self.subTest(interno):
                self.assertEqual(r["caso_estado_es"], es)

    def test_un_estado_desconocido_no_se_traga(self):
        """Mejor mostrar el valor crudo que una celda vacía que parece un bug."""
        r = A._caso_de_la_alerta(alerta("123"), *indice([caso("c1", "123", "inventado")]))
        self.assertEqual(r["caso_estado_es"], "inventado")


if __name__ == "__main__":
    unittest.main(verbosity=1)
