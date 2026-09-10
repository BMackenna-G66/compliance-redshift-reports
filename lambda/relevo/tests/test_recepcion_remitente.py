"""Quién mandó la respuesta: el `From` miente cuando hay un grupo de Google.

`compliance@global66.com` es una lista y **reescribe el `From` de todo lo que
distribuye**. Mirando el `From`, la respuesta de un cliente que entra por el
grupo se clasificaba como correo nuestro, se marcaba procesada y no se volvía
a mirar nunca — el caso quedaba esperando para siempre algo que ya había
llegado, sin ningún error a la vista.

Los headers de acá están copiados de correos reales ya ingeridos.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from relevo import recepcion  # noqa: E402


def m(headers):
    return {"id": "x", "thread_id": "t", "asunto": "s", "headers": headers}


class ElFromMienteCuandoHayGrupo(unittest.TestCase):
    def test_un_partner_que_entra_por_el_grupo_NO_es_nuestro(self):
        """El caso que rompía: From reescrito por Google Groups."""
        self.assertTrue(recepcion._es_del_cliente(m({
            "From": "\"'d·Local' via Compliance\" <compliance@global66.com>",
            "X-Original-Sender": "no_reply@dlocal.com",
            "Reply-To": "\"d·Local\" <no_reply@dlocal.com>",
        })))

    def test_un_cliente_que_responde_al_grupo_NO_es_nuestro(self):
        """Exactamente el camino del envío a mano: el cliente contesta al
        grupo, Google reescribe el From, y esto tiene que seguir siendo suyo."""
        self.assertTrue(recepcion._es_del_cliente(m({
            "From": "\"Benjamin Mackenna via Compliance\" <compliance@global66.com>",
            "X-Original-Sender": "benjaminmackenna99@gmail.com",
        })))

    def test_un_cliente_que_responde_derecho_a_la_casilla_NO_es_nuestro(self):
        self.assertTrue(recepcion._es_del_cliente(m({
            "From": "Benjamin Mackenna <benjaminmackenna99@gmail.com>",
            "To": "compliance.masivo@global66.com",
        })))


class LoNuestroSigueSiendoNuestro(unittest.TestCase):
    def test_lo_que_mandamos_por_la_api_SI_es_nuestro(self):
        """Sin grupo de por medio no hay X-Original-Sender: manda el From."""
        self.assertFalse(recepcion._es_del_cliente(m({
            "From": "Compliance Global66 <compliance@global66.com>",
            "To": "cliente@example.com",
        })))

    def test_lo_que_sale_de_la_casilla_SI_es_nuestro(self):
        self.assertFalse(recepcion._es_del_cliente(m({
            "From": "<compliance.masivo@global66.com>",
            "To": "cliente@example.com",
        })))

    def test_un_reenvio_nuestro_por_el_grupo_SI_es_nuestro(self):
        """Si alguien nuestro escribe al grupo, X-Original-Sender lo delata."""
        self.assertFalse(recepcion._es_del_cliente(m({
            "From": "\"Ana via Compliance\" <compliance@global66.com>",
            "X-Original-Sender": "compliance.masivo@global66.com",
        })))

    def test_no_distingue_mayusculas(self):
        self.assertFalse(recepcion._es_del_cliente(m({
            "FROM": "Compliance <Compliance@Global66.com>",
        })))


class SinHeaders(unittest.TestCase):
    def test_sin_headers_se_asume_del_cliente(self):
        """Preferir procesar de más: un mensaje sin headers correlacionado por
        token ya pasó un filtro fuerte, y descartarlo pierde la respuesta."""
        self.assertTrue(recepcion._es_del_cliente({"id": "x"}))


if __name__ == "__main__":
    unittest.main()
