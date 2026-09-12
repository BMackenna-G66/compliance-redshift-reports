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



class ElTextoDelCliente(unittest.TestCase):
    """Lo que escribió el cliente, sin nuestro propio correo devuelto.

    Medido sobre una respuesta real: 2.212 caracteres, de los cuales el
    cliente escribió 21. Mostrar la cita entera convierte el panel del caso
    en una pared de texto propio.
    """

    def test_recorta_la_cita_de_gmail_en_espanol(self):
        t = ("De que se trata esto?\n\nEl vie, 11 sept 2026 a las 22:23, "
             "<compliance@global66.com> escribió:\n> hola")
        self.assertEqual(recepcion.solo_lo_nuevo(t), "De que se trata esto?")

    def test_recorta_la_cita_de_gmail_en_ingles(self):
        t = ("Here are the docs.\n\nOn Fri, 11 Sep 2026 at 22:23, "
             "compliance@global66.com wrote:\n> hi")
        self.assertEqual(recepcion.solo_lo_nuevo(t), "Here are the docs.")

    def test_recorta_la_cita_de_outlook(self):
        t = "Adjunto lo pedido.\n\n________________________________\nDe: compliance@global66.com"
        self.assertEqual(recepcion.solo_lo_nuevo(t), "Adjunto lo pedido.")

    def test_un_texto_sin_cita_queda_igual(self):
        self.assertEqual(recepcion.solo_lo_nuevo("Adjunto todo, saludos."),
                         "Adjunto todo, saludos.")

    def test_si_el_recorte_deja_vacio_se_devuelve_el_original(self):
        """Alguien que responde sólo arriba de la cita sin escribir nada, o un
        formato que no reconocemos: perder la respuesta entera por un
        separador raro es peor que mostrar de más."""
        t = "> hola\n> mundo"
        self.assertEqual(recepcion.solo_lo_nuevo(t), t)

    def test_vacio_no_rompe(self):
        self.assertEqual(recepcion.solo_lo_nuevo(""), "")
        self.assertEqual(recepcion.solo_lo_nuevo(None), "")

    def test_respeta_el_tope(self):
        self.assertEqual(len(recepcion.solo_lo_nuevo("x" * 9000, maximo=4000)), 4000)

if __name__ == "__main__":
    unittest.main()
