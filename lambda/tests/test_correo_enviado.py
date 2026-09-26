# -*- coding: utf-8 -*-
"""El correo que sale queda registrado con lo que decía y con quién lo mandó.

LO QUE PASABA. El historial del caso existía y los dos frentes lo mostraban,
pero el camino por el que salen casi todos los correos —el botón manual, que
se usa desde la alerta y desde el caso— guardaba el asunto y los documentos
pedidos, y nada más. Medido en producción el 26-09-2026: de 107 envíos
registrados, **107 sin el cuerpo**, 101 de ellos por este camino.

El efecto no era una pantalla rota sino una pantalla que mentía por omisión:
el caso mostraba que se había escrito, sin poder decir qué se dijo. Del lado
del analista eso se lee como «acá sólo está la respuesta del cliente».

POR QUÉ ESTOS TESTS MIRAN EL REGISTRO Y NO LA RESPUESTA HTTP. El endpoint
devolvía 200 antes y devuelve 200 ahora; lo que cambió es lo que queda
escrito. Un test sobre la respuesta habría pasado los dos días.
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


class _Banco:
    """Reemplaza las piezas que salen de la máquina: S3, el correo y el caso."""

    def __init__(self, envio=None):
        self.guardado = {}
        self.envio = envio or {"sent": True, "error": ""}

    def instalar(self):
        self.orig = {
            "_crm_put": A._crm_put, "_crm_update": A._crm_update,
            "_crm_get": A._crm_get, "_crm_list": A._crm_list,
            "_send_email": A._send_email, "create_case": A.create_case,
            "_register_email_ref": A._register_email_ref,
            "_email_template_attachment": A._email_template_attachment,
        }
        A._crm_put = lambda kind, i, d: self.guardado.__setitem__((kind, i), d)
        A._crm_update = lambda kind, i, d: {"case_id": i, "email_ref": "AB12"}
        A._crm_get = lambda kind, i: {"case_id": i}
        A._crm_list = lambda kind: list(
            v for (k, _), v in self.guardado.items() if k == kind)
        A._send_email = lambda *a, **k: self.envio
        A.create_case = lambda b: {"statusCode": 200,
                                   "body": json.dumps({"case_id": "CASO-1"})}
        A._register_email_ref = lambda c: "AB12"
        A._email_template_attachment = lambda t: None
        return self

    def desinstalar(self):
        for nombre, fn in self.orig.items():
            setattr(A, nombre, fn)

    @property
    def pedido(self):
        for (kind, _), d in self.guardado.items():
            if kind == "document_requests":
                return d
        raise AssertionError("no se guardó ningún document_request")


def enviar(**extra):
    cuerpo = {
        "entity_type": "customer", "entity_id": "1234567",
        "nombre": "Nombre Apellido", "correo": "cliente@ejemplo.cl",
        "documentos": ["cedula"], "case_id": "CASO-1",
        "template_key": "general_b2c",
    }
    cuerpo.update(extra)
    banco = _Banco().instalar()
    try:
        r = A.send_manual_document_request(cuerpo)
    finally:
        banco.desinstalar()
    return r["statusCode"], json.loads(r["body"]), banco


class QuedaEscritoQueDecia(unittest.TestCase):

    def test_se_guarda_el_cuerpo_del_correo(self):
        codigo, _, b = enviar()
        self.assertEqual(codigo, 200)
        self.assertTrue(b.pedido.get("cuerpo_texto"),
                        "el correo salió y no quedó registro de qué decía")

    def test_el_cuerpo_es_texto_y_no_html(self):
        """Lo que se audita es el contenido, no el diseño; y un HTML crudo en
        la pantalla del caso no lo lee nadie."""
        _, _, b = enviar()
        cuerpo = b.pedido["cuerpo_texto"]
        self.assertNotIn("<", cuerpo)
        self.assertNotIn("</", cuerpo)

    def test_lo_que_escribio_la_persona_queda_aparte(self):
        """El cuerpo renderizado mezcla plantilla y texto del analista.
        Guardarlo suelto es lo que permite decir después qué puso una persona
        y qué puso el sistema."""
        _, _, b = enviar(template_key="texto_libre",
                         texto_libre="Necesitamos el contrato de arriendo.")
        self.assertEqual(b.pedido["texto_libre"],
                         "Necesitamos el contrato de arriendo.")
        self.assertIn("contrato de arriendo", b.pedido["cuerpo_texto"])

    def test_un_envio_fallido_igual_deja_registro_de_que_decia(self):
        """Que no saliera no significa que no pasó: en una auditoría, un
        intento fallido es lo que explica un silencio del cliente."""
        banco = _Banco(envio={"sent": False, "error": "buzón lleno"}).instalar()
        try:
            A.send_manual_document_request({
                "entity_type": "customer", "entity_id": "1", "nombre": "X",
                "correo": "cliente@ejemplo.cl", "documentos": ["cedula"],
                "case_id": "CASO-1", "template_key": "general_b2c",
            })
        finally:
            banco.desinstalar()
        self.assertFalse(banco.pedido["sent"])
        self.assertTrue(banco.pedido["cuerpo_texto"])


class QuedaEscritoQuienLoMando(unittest.TestCase):

    def test_se_guarda_quien_apreto_enviar(self):
        _, _, b = enviar(user_email="analista@global66.com")
        self.assertEqual(b.pedido["enviado_por"], "analista@global66.com")

    def test_la_api_externa_manda_el_suyo_con_otro_nombre(self):
        """`v1_comunicar` ya traía el actor como `actor_email`. Si sólo se
        mirara `user_email`, los envíos de terceros quedarían sin autor
        teniéndolo."""
        _, _, b = enviar(actor_email="sistema-externo")
        self.assertEqual(b.pedido["enviado_por"], "sistema-externo")

    def test_sin_autor_se_dice_que_no_se_sabe(self):
        """Nunca en blanco y nunca atribuido de más: un correo al cliente
        firmado por quien no fue es peor que uno sin firmar."""
        _, _, b = enviar()
        self.assertEqual(b.pedido["enviado_por"], "(sin identificar)")


class ElHistorialLoDevuelve(unittest.TestCase):
    """De nada sirve guardarlo si `GET /cases/{id}/correos` no lo muestra."""

    def test_el_historial_trae_cuerpo_y_autor(self):
        pedidos = [{
            "case_id": "CASO-1", "correo": "cliente@ejemplo.cl",
            "subject": "Solicitud", "sent": True, "created_at": "2026-09-26T10:00:00",
            "cuerpo_texto": "Hola, necesitamos tu cédula.",
            "enviado_por": "analista@global66.com",
        }]
        correos = A._correos_del_caso({"case_id": "CASO-1"}, pedidos)
        self.assertEqual(len(correos), 1)
        self.assertEqual(correos[0]["cuerpo"], "Hola, necesitamos tu cédula.")
        self.assertEqual(correos[0]["enviado_por"], "analista@global66.com")

    def test_un_envio_viejo_no_inventa_autor(self):
        """Los 107 que ya existen no tienen ninguno de los dos campos. La
        pantalla dice que falta; acá se vigila que no se rellene solo."""
        pedidos = [{"case_id": "CASO-1", "sent": True, "created_at": "2026-01-01"}]
        c = A._correos_del_caso({"case_id": "CASO-1"}, pedidos)[0]
        self.assertEqual(c["enviado_por"], "")
        self.assertEqual(c["cuerpo"], "")

    def test_la_api_externa_no_expone_ni_el_cuerpo_ni_el_autor(self):
        """`/v1/casos/{id}/comunicaciones` la consume un tercero: el cuerpo
        del correo y el correo interno de un analista no son suyos."""
        import ast
        texto = Path(A.__file__).read_text(encoding="utf-8")
        for nodo in ast.parse(texto).body:
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "v1_comunicaciones":
                fuente = ast.get_source_segment(texto, nodo)
                break
        else:
            raise AssertionError("no encontré v1_comunicaciones")
        self.assertNotIn('"cuerpo"', fuente)
        self.assertNotIn('"enviado_por"', fuente)


class LosTresCaminosEscribenIgual(unittest.TestCase):
    """Los dos automáticos y el manual guardan en la misma colección y se
    leen con el mismo código. Si uno deja de escribir un campo, el historial
    queda disparejo sin que falle nada — que es exactamente lo que pasó."""

    def _campos_por_camino(self):
        """Las claves que escribe cada `_crm_put("document_requests", ...)`.

        Se leen del árbol y no con una expresión regular: los tres bloques
        tienen indentaciones distintas —dos están dentro de un `for`— y una
        regex atada a los espacios encontraba uno solo y daba por buenos los
        otros dos sin mirarlos.
        """
        import ast
        arbol = ast.parse(Path(A.__file__).read_text(encoding="utf-8"))
        caminos = []
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            f = nodo.func
            if not (isinstance(f, ast.Name) and f.id == "_crm_put"):
                continue
            if not (nodo.args and isinstance(nodo.args[0], ast.Constant)
                    and nodo.args[0].value == "document_requests"):
                continue
            registro = nodo.args[-1]
            self.assertIsInstance(registro, ast.Dict,
                                  "el registro dejó de escribirse literal")
            caminos.append({k.value for k in registro.keys
                            if isinstance(k, ast.Constant)})
        return caminos

    def test_los_tres_guardan_el_cuerpo(self):
        caminos = self._campos_por_camino()
        self.assertEqual(len(caminos), 3, "cambió la cantidad de caminos de envío")
        for i, campos in enumerate(caminos, 1):
            self.assertIn("cuerpo_texto", campos, f"el camino {i} no guarda el cuerpo")

    def test_los_tres_guardan_quien_mando(self):
        for i, campos in enumerate(self._campos_por_camino(), 1):
            self.assertIn("enviado_por", campos, f"el camino {i} no guarda el autor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
