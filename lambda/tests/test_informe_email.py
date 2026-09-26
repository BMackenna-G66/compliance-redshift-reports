# -*- coding: utf-8 -*-
"""El informe de gestión, dibujado para correo.

QUÉ VIGILA. Tres cosas que se rompen en silencio:

1. **Que sea correo y no página.** Gmail y Outlook tiran `<style>` y las
   clases. Un informe que se ve perfecto en el navegador y llega desarmado a
   la casilla no falla en ningún test que mire el contenido.

2. **Que el tramo de +30 días exista.** El informe del que sale este modelo
   tenía cuatro tramos y los casos de más de 30 días no caían en ninguno: no
   aparecían en la tabla. Son justo los que un informe de gestión tiene que
   mostrar primero.

3. **Que el correo no salga del dominio.** El informe lleva títulos de casos
   con nombre e id de clientes reales. La API todavía no tiene autenticación,
   así que el allowlist de dominio es lo único que impide que alguien se
   mande la cartera de casos a su casilla personal.
"""
import datetime as dt
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k in ("RUNS_TABLE", "CATALOG_TABLE", "REPORT_LAMBDA", "S3_BUCKET"):
    os.environ.setdefault(k, "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import informe_casos  # noqa: E402
import informe_email as E  # noqa: E402

AHORA = dt.datetime(2026, 9, 26, 12, 0, 0)


def caso(**kw):
    base = {
        "case_id": "c1", "title": "Caso de prueba", "status": "open",
        "assigned_to": "ana.perez@global66.com", "note_count": 1,
        "created_at": "2026-09-20 10:00:00", "closed_at": "",
        "sla_estado": "", "sla_aplica": True,
    }
    base.update(kw)
    return base


def armar(casos, equipos=None):
    return informe_casos.armar(casos, equipos=equipos or {}, ahora=AHORA)


def html_de(casos, equipos=None):
    datos = armar(casos, equipos)
    return E.construir(datos, url_casos="https://ejemplo/", ahora=AHORA,
                       equipos=equipos or {})


class EsCorreoYNoPagina(unittest.TestCase):

    def test_no_hay_hoja_de_estilos_ni_clases(self):
        """Gmail las tira. Si aparecen, es que alguien escribió el HTML
        pensando en el navegador y en la casilla va a llegar desarmado."""
        h = html_de([caso()])
        self.assertNotIn("<style", h)
        self.assertNotIn("class=", h)

    def test_no_hay_javascript(self):
        h = html_de([caso()])
        self.assertNotIn("<script", h)

    def test_la_fuente_va_en_cada_celda(self):
        """No alcanza con ponerla en el `<body>`: Outlook no la hereda."""
        h = html_de([caso()])
        self.assertGreater(h.count("font-family:Arial"), 20)

    def test_el_ancho_es_fijo_y_se_achica_en_el_telefono(self):
        h = html_de([caso()])
        self.assertIn('width="860"', h)
        self.assertIn("max-width:100%", h)

    def test_el_texto_plano_no_va_vacio(self):
        """Un cliente que no muestra HTML tiene que poder leer los números,
        no un correo en blanco."""
        t = E.texto_plano(armar([caso(), caso(status="closed")]), "26-09-2026")
        self.assertIn("Casos: 2", t)
        self.assertIn("no desempeño", t)


class NadaSeCuelaSinEscapar(unittest.TestCase):

    def test_un_titulo_con_html_no_rompe_el_correo(self):
        """Los títulos traen nombres de clientes escritos a mano."""
        h = html_de([caso(title="Cliente <script>alerta</script> & Cía",
                          created_at="2026-09-01 10:00:00")])
        self.assertNotIn("<script>alerta", h)
        self.assertIn("&lt;script&gt;alerta", h)
        self.assertIn("&amp; Cía", h)

    def test_un_valor_vacio_se_ve_como_raya_y_no_como_None(self):
        self.assertEqual(E.esc(None), "—")
        self.assertEqual(E.esc(""), "—")


class LosCeros(unittest.TestCase):
    """Una tabla llena de ceros esconde el número que importa."""

    def test_en_las_celdas_de_conteo_el_cero_es_una_raya(self):
        h = html_de([caso(created_at="2026-09-25 10:00:00")])   # 1 día
        # El tramo 30d+ no tiene nada: tiene que decir «—», no «0».
        self.assertIn(">—<", h)

    def test_en_los_totales_el_cero_se_muestra(self):
        self.assertEqual(E._num(0, cero_es_raya=False), 0)
        self.assertEqual(E._num(0), "—")


class ElTramoDeMasDeTreintaDias(unittest.TestCase):
    """El bug heredado que la spec pide arreglar."""

    def test_existe_la_columna(self):
        self.assertIn("30d+", [t[0] for t in E.TRAMOS])

    def test_un_caso_de_cuarenta_dias_aparece_en_la_tabla(self):
        h = html_de([caso(created_at="2026-08-17 10:00:00")])   # 40 días
        self.assertIn("30d+", h)
        # Y el total de la fila lo cuenta: si cayera fuera de todo tramo, la
        # fila sumaría 0 y el caso desaparecería sin avisar.
        datos = armar([caso(created_at="2026-08-17 10:00:00")])
        abiertos = [c for c in datos["casos"] if not informe_casos.esta_cerrado(c)]
        tabla = E.pivot_antiguedad(abiertos, "analista", "Analista", {}, AHORA)
        self.assertIn(">1<", tabla)

    def test_cada_tramo_agarra_su_rango(self):
        self.assertEqual(E._tramo(0), "<3d")
        self.assertEqual(E._tramo(2), "<3d")
        self.assertEqual(E._tramo(3), "3-7d")
        self.assertEqual(E._tramo(6), "3-7d")
        self.assertEqual(E._tramo(7), "7-14d")
        self.assertEqual(E._tramo(13), "7-14d")
        self.assertEqual(E._tramo(14), "14-30d")
        self.assertEqual(E._tramo(29), "14-30d")
        self.assertEqual(E._tramo(30), "30d+")
        self.assertEqual(E._tramo(400), "30d+")

    def test_ningun_caso_abierto_se_queda_sin_tramo(self):
        """La propiedad de fondo: la suma de la fila Total tiene que ser
        igual a la cantidad de abiertos. Así se cazó el bug original."""
        casos = [caso(created_at=f"2026-0{m}-0{d} 10:00:00")
                 for m in (7, 8, 9) for d in (1, 5, 9)]
        datos = armar(casos)
        abiertos = [c for c in datos["casos"] if not informe_casos.esta_cerrado(c)]
        tabla = E.pivot_antiguedad(abiertos, "analista", "Analista", {}, AHORA)
        # La última celda de la fila Total es el gran total.
        import re
        totales = re.findall(r'background:#edf2f7[^>]*>([^<]*)<', tabla)
        self.assertEqual(totales[-1], str(len(abiertos)))


class ElSemaforo(unittest.TestCase):

    def test_los_cortes_son_los_de_la_spec(self):
        self.assertIn("#C3FFEE", E.badge_edad(0))     # OK
        self.assertIn("#C3FFEE", E.badge_edad(6))
        self.assertIn("#FFEED9", E.badge_edad(7))     # warning
        self.assertIn("#FFEED9", E.badge_edad(13))
        self.assertIn("#FFEBEE", E.badge_edad(14))    # crítico
        self.assertIn("#FFEBEE", E.badge_edad(29))
        self.assertIn("#b71c1c", E.badge_edad(30))    # vencido
        self.assertIn("#b71c1c", E.badge_edad(365))

    def test_el_badge_dice_los_dias(self):
        self.assertIn("T-12", E.badge_edad(12))


class LaCartaDeViejos(unittest.TestCase):

    def test_no_entra_un_caso_de_dos_dias(self):
        h = html_de([caso(created_at="2026-09-25 10:00:00")])
        self.assertIn("Ninguno", h)

    def test_se_corta_y_lo_dice(self):
        """Un correo con 300 filas no lo lee nadie y revienta el tope de
        tamaño de Gmail. Se corta, y se dice cuántos quedaron afuera."""
        casos = [caso(case_id=f"c{i}", created_at="2026-09-01 10:00:00")
                 for i in range(40)]
        datos = armar(casos)
        abiertos = datos["casos"]
        carta = E._carta_viejos(abiertos, "https://ejemplo/", AHORA, tope=25)
        self.assertIn("25 más viejos de 40", carta)

    def test_el_mas_viejo_va_primero(self):
        casos = [caso(case_id="nuevo", title="EL NUEVO",
                      created_at="2026-09-20 10:00:00"),
                 caso(case_id="viejo", title="EL VIEJO",
                      created_at="2026-07-01 10:00:00")]
        carta = E._carta_viejos(casos, "https://ejemplo/", AHORA)
        self.assertLess(carta.index("EL VIEJO"), carta.index("EL NUEVO"))


class LaAdvertenciaVaEnElCorreo(unittest.TestCase):
    """El informe mide actividad, no desempeño. Si eso no viaja con los
    números, el que lo recibe va a leer una tabla de rendimiento."""

    def test_el_encabezado_lo_dice(self):
        h = html_de([caso()])
        self.assertIn("no desempeño", h)


# ── El endpoint ──────────────────────────────────────────────────────────

import api_handler as A  # noqa: E402


class _Correo:
    def __init__(self):
        self.enviados = []

    def __call__(self, to, subject, html, from_addr=None, attachments=None):
        self.enviados.append({"to": to, "subject": subject, "html": html})
        return {"sent": True, "error": ""}


def llamar(cuerpo):
    correo = _Correo()
    orig = {"_send_email": A._send_email, "get_cases": A.get_cases,
            "_crm_list": A._crm_list, "_safe_audit": A._safe_audit}
    A._send_email = correo
    A.get_cases = lambda *a, **k: {"statusCode": 200,
                                   "body": json.dumps({"cases": [caso()]})}
    A._crm_list = lambda kind: []
    A._safe_audit = lambda **k: None
    try:
        r = A.enviar_informe_gestion(cuerpo)
    finally:
        for n, f in orig.items():
            setattr(A, n, f)
    return r["statusCode"], json.loads(r["body"]), correo


class ElCorreoNoSaleDelDominio(unittest.TestCase):

    def test_un_destinatario_de_afuera_se_rechaza(self):
        codigo, d, correo = llamar({"para": ["alguien@gmail.com"]})
        self.assertEqual(codigo, 400)
        self.assertEqual(correo.enviados, [], "no tenía que haber salido nada")
        self.assertIn("alguien@gmail.com", d["rechazados"])

    def test_alcanza_con_uno_de_afuera_para_rechazar_todo(self):
        """No se manda a los válidos y se descarta el resto en silencio: eso
        deja a quien lo pidió creyendo que llegó a todos."""
        codigo, _, correo = llamar(
            {"para": ["ana@global66.com", "alguien@gmail.com"]})
        self.assertEqual(codigo, 400)
        self.assertEqual(correo.enviados, [])

    def test_sin_destinatarios_no_hace_nada(self):
        codigo, _, correo = llamar({})
        self.assertEqual(codigo, 400)
        self.assertEqual(correo.enviados, [])

    def test_hay_un_tope_de_destinatarios(self):
        muchos = [f"a{i}@global66.com" for i in range(A.MAX_DESTINATARIOS + 1)]
        codigo, _, correo = llamar({"para": muchos})
        self.assertEqual(codigo, 400)
        self.assertEqual(correo.enviados, [])


class ComoSeManda(unittest.TestCase):

    def test_uno_por_destinatario(self):
        """Si uno de los correos no existe, el resto igual lo recibe. Y nadie
        ve la lista de los demás."""
        _, d, correo = llamar(
            {"para": ["ana@global66.com", "luis@global66.com"]})
        self.assertEqual(len(correo.enviados), 2)
        self.assertEqual({e["to"] for e in correo.enviados},
                         {"ana@global66.com", "luis@global66.com"})
        self.assertEqual(d["enviados"], 2)

    def test_acepta_una_lista_escrita_a_mano(self):
        _, _, correo = llamar({"para": "ana@global66.com, luis@global66.com"})
        self.assertEqual(len(correo.enviados), 2)

    def test_el_asunto_lleva_la_fecha(self):
        _, d, _ = llamar({"para": ["ana@global66.com"]})
        self.assertIn("Reporte de gestión de casos", d["asunto"])
        self.assertIn("Global66", d["asunto"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
