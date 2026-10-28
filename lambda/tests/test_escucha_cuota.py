# -*- coding: utf-8 -*-
"""La escucha de respuestas, segunda vuelta: la cuota de IMAP.

POR QUÉ EXISTE ESTE ARCHIVO. El 28-10-2026 llegó un aviso que decía «Proceso
caído: Escucha de respuestas de clientes». Era cierto a medias y mentía en lo
importante.

El aviso venía de un timeout suelto al conectar: pasó dos veces en catorce
días y las dos se curó solo en la corrida siguiente. Eso NO era la falla.

La falla de verdad no estaba avisando nada:

1. **El cuerpo se bajaba antes de saber si hacía falta.** `_process_reply_
   message` arrancaba con `fetch(BODY.PEEK[])` —el mensaje entero, adjuntos
   incluidos— y recién después consultaba el ledger de Message-ID. Con 40
   mensajes en la ventana y una corrida cada 10 minutos, eran 40 descargas
   completas 144 veces por día para terminar descartándolas por duplicadas.
   Así se revienta la cuota de IMAP de Gmail, que contesta `[OVERQUOTA]` y
   después corta la conexión.

2. **Los duplicados gastaban el cupo de la corrida.** El tope de 40 se
   aplicaba con `nums[:40]`, y como la búsqueda devuelve los más viejos
   primero, los 40 duplicados de siempre se comían la corrida entera. La
   respuesta recién llegada —la última de la lista— no se miraba NUNCA. El
   log lo venía diciendo en la cara, corrida tras corrida: todo duplicados,
   un resto en `pendientes` que no bajaba, y `processed: 0`.

3. **Y cuando Gmail cortaba, la Lambda moría muda.** `imap.select()` y
   `imap.search()` caen fuera del try de cada mensaje, y el try de afuera
   tenía `finally` pero no `except`: el `abort` subía sin que nadie lo
   atrapara y la invocación moría con una excepción sin manejar. Eso no
   devuelve `{"status": "error"}`, así que `_avisar_falla` no se llamaba.
   Caídas y caídas sin un solo aviso: el mismo silencio de los ocho días,
   otra vez y por otra puerta.

Es el mismo modo de falla que este módulo existe para vigilar: lo que se cae
y no grita.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for k, v in (("RUNS_TABLE", "test"), ("CATALOG_TABLE", "test"),
             ("REPORT_LAMBDA", "test"), ("S3_BUCKET", "test"),
             ("CLUSTER_IDENTIFIER", "test"), ("DATABASE_NAME", "test"),
             ("DB_USER", "test"), ("SES_FROM_ADDRESS", "nadie@ejemplo.test"),
             ("SES_TO_ADDRESSES", "nadie@ejemplo.test"),
             ("AWS_DEFAULT_REGION", "us-east-1")):
    os.environ.setdefault(k, v)

import imaplib  # noqa: E402

import api_handler as A  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def _cuerpo(mid, asunto):
    return (f"Message-ID: {mid}\r\nSubject: {asunto}\r\n"
            f"From: cliente@ejemplo.test\r\n\r\ntexto del cliente\r\n"
            f"{'x' * 5000}\r\n").encode()


class ImapFalso:
    """Lo mínimo de IMAP para ejercitar el poller, contando qué se baja."""

    def __init__(self, mensajes, abortar_en=()):
        self.mensajes = mensajes            # [(num, message_id, asunto)]
        self.abortar_en = set(abortar_en)
        self.fetches = []                   # [(num, spec)]
        self.carpeta = None

    def login(self, usuario, clave):
        return ("OK", [b"logueado"])

    def select(self, carpeta):
        if "select" in self.abortar_en:
            raise imaplib.IMAP4.abort("command: SELECT => socket error: EOF")
        self.carpeta = carpeta
        return ("OK", [b"1"])

    def search(self, charset, criterio):
        if self.carpeta != "INBOX":
            return ("OK", [b""])
        return ("OK", [b" ".join(n for n, _, _ in self.mensajes)])

    def fetch(self, num, spec):
        self.fetches.append((num, spec))
        mid, asunto = next((m, a) for n, m, a in self.mensajes if n == num)
        if "HEADER.FIELDS" in spec:
            datos = (f"Message-ID: {mid}\r\nSubject: {asunto}\r\n"
                     f"From: cliente@ejemplo.test\r\n\r\n").encode()
        else:
            datos = _cuerpo(mid, asunto)
        return ("OK", [(b"1 (BODY[] {n}", datos), b")"])

    def store(self, *a):
        return ("OK", [b""])

    def close(self):
        pass

    def logout(self):
        pass

    # ── lo que el test quiere saber ──
    def cuerpos_bajados(self):
        return [n for n, spec in self.fetches if "HEADER.FIELDS" not in spec]


def _correr(imap_falso, ya_procesados=()):
    """Corre el poller contra un IMAP falso, sin red y sin S3."""
    with mock.patch.object(A, "_get_imap_password", return_value="clave"), \
         mock.patch.object(imaplib, "IMAP4_SSL", return_value=imap_falso), \
         mock.patch.object(A, "_email_ya_procesado",
                           side_effect=lambda mid: mid in ya_procesados), \
         mock.patch.object(A, "_crm_get", return_value=None):
        return A.poll_document_replies()


class UnDuplicadoNoSeBajaEntero(unittest.TestCase):
    """Bajar el cuerpo para después descartarlo es lo que revienta la cuota."""

    def test_del_duplicado_solo_se_leen_los_encabezados(self):
        imap = ImapFalso([(b"1", "<viejo@x>", "Re: docs [ref: aaaaaaaa]")])
        r = _correr(imap, ya_procesados={"<viejo@x>"})
        self.assertEqual(r["duplicados"], 1)
        self.assertEqual(
            imap.cuerpos_bajados(), [],
            "bajó el mensaje entero para terminar descartándolo por duplicado")

    def test_de_lo_que_no_matchea_tampoco(self):
        """Sin caso al que pegarlo, el cuerpo no se usa para nada."""
        imap = ImapFalso([(b"1", "<nuevo@x>", "Re: docs [ref: aaaaaaaa]")])
        r = _correr(imap)
        self.assertEqual(r["unmatched"], 1)
        self.assertEqual(imap.cuerpos_bajados(), [])


class LosDuplicadosNoSeComenLaCorrida(unittest.TestCase):
    """LA REGRESIÓN QUE IMPORTA: la respuesta nueva está DETRÁS de los viejos.

    La búsqueda devuelve los más viejos primero. Con `nums[:40]`, 40
    duplicados de siempre ocupaban la corrida entera y lo recién llegado
    quedaba como `pendientes` para siempre: el cliente mandaba el documento
    y en el caso no aparecía nada.
    """

    def _casilla(self, viejos, nuevos):
        msgs = [(str(i).encode(), f"<viejo{i}@x>", f"Re: docs [ref: {i:08d}]")
                for i in range(1, viejos + 1)]
        msgs += [(str(viejos + i).encode(), f"<nuevo{i}@x>",
                  f"Re: docs [ref: n{i:07d}]") for i in range(1, nuevos + 1)]
        return msgs, {f"<viejo{i}@x>" for i in range(1, viejos + 1)}

    def test_lo_nuevo_se_mira_aunque_haya_mas_duplicados_que_el_tope(self):
        msgs, ledger = self._casilla(viejos=40, nuevos=20)
        imap = ImapFalso(msgs)
        r = _correr(imap, ya_procesados=ledger)
        self.assertEqual(r["duplicados"], 40)
        self.assertEqual(r["unmatched"], 20,
                         "las respuestas nuevas quedaron detrás de los "
                         "duplicados y no se miraron")
        self.assertEqual(r["pendientes"], 0)

    def test_el_tope_sigue_acotando_el_trabajo_de_verdad(self):
        """El cupo no se eliminó: sigue valiendo para lo que hay que procesar."""
        msgs, _ = self._casilla(viejos=0, nuevos=45)
        r = _correr(ImapFalso(msgs))
        self.assertEqual(r["unmatched"], 40)
        self.assertEqual(r["pendientes"], 5)


class UnCorteDeGmailNoMataLaLambdaEnSilencio(unittest.TestCase):
    """El `abort` de select/search subía sin except y la invocación moría.

    Una Lambda que muere con una excepción sin manejar no devuelve
    `{"status": "error"}`, así que `_avisar_falla` no llegaba a llamarse.
    """

    def test_el_abort_vuelve_como_status_error(self):
        imap = ImapFalso([(b"1", "<a@x>", "Re: docs [ref: aaaaaaaa]")],
                         abortar_en={"select"})
        r = _correr(imap)
        self.assertEqual(r["status"], "error")
        self.assertIn("EOF", r["error"])

    def test_y_el_resultado_conserva_los_contadores(self):
        """Para que el log diga cuánto alcanzó a hacer antes de cortarse."""
        imap = ImapFalso([(b"1", "<a@x>", "Re: docs [ref: aaaaaaaa]")],
                         abortar_en={"select"})
        r = _correr(imap)
        for k in ("processed", "matched", "duplicados", "pendientes"):
            self.assertIn(k, r)

    def test_el_try_de_afuera_tiene_except_y_no_solo_finally(self):
        fuente = (RAIZ / "api_handler.py").read_text(encoding="utf-8")
        i = fuente.index("def poll_document_replies(")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        self.assertIn("IMAP corto la lectura", cuerpo,
                      "volvió a quedar un try/finally sin except: un corte de "
                      "Gmail mata la invocación sin avisar")


class LaConexionSeReintentaPeroLaClaveNo(unittest.TestCase):
    """Un timeout de red se cura solo; una credencial rechazada no."""

    def _conectar(self, efectos):
        intentos = {"n": 0}

        def fabrica(*a, **k):
            intentos["n"] += 1
            e = efectos[min(intentos["n"], len(efectos)) - 1]
            if e is not None:
                raise e
            return ImapFalso([])

        with mock.patch.object(A, "_get_imap_password", return_value="clave"), \
             mock.patch.object(imaplib, "IMAP4_SSL", side_effect=fabrica), \
             mock.patch.object(A, "time") as t:
            t.time.return_value = 0
            r = A.poll_document_replies()
        return r, intentos["n"]

    def test_un_timeout_suelto_se_reintenta_y_la_corrida_sale_bien(self):
        r, n = self._conectar([TimeoutError("The read operation timed out"), None])
        self.assertEqual(r["status"], "ok")
        self.assertEqual(n, 2)

    def test_si_el_timeout_no_cede_recien_ahi_es_error(self):
        r, n = self._conectar([TimeoutError("The read operation timed out")] * 5)
        self.assertEqual(r["status"], "error")
        self.assertEqual(n, A.INTENTOS_CONEXION_IMAP)

    def test_una_clave_rechazada_no_se_reintenta(self):
        """Tres logins fallidos seguidos es lo que hace que Gmail trabe la
        cuenta. Reintentar no la va a arreglar: hay que avisar."""
        r, n = self._conectar([imaplib.IMAP4.error("AUTHENTICATIONFAILED")] * 5)
        self.assertEqual(r["status"], "error")
        self.assertEqual(n, 1)


class ElAvisoNoGritaPorUnaSolaFalla(unittest.TestCase):
    """Un «Proceso caído» por algo que ya se curó enseña a ignorar el aviso."""

    def _handler(self):
        import handler as H
        return H

    def test_la_primera_falla_no_avisa_y_la_segunda_si(self):
        H = self._handler()
        guardado = {}

        class S3Falso:
            def get_object(self, Bucket, Key):                  # noqa: N803
                if Key not in guardado:
                    raise KeyError(Key)
                return {"Body": type("B", (), {"read": lambda s: guardado[Key]})()}

            def put_object(self, Bucket, Key, Body):            # noqa: N803
                guardado[Key] = Body

            def delete_object(self, Bucket, Key):               # noqa: N803
                guardado.pop(Key, None)

        with mock.patch.object(H, "s3", S3Falso()):
            self.assertEqual(H._racha_fallas(True), 1)
            self.assertEqual(H._racha_fallas(True), 2)
            self.assertEqual(H._racha_fallas(False), 0)
            self.assertEqual(H._racha_fallas(True), 1)

    def test_si_s3_falla_avisa_igual(self):
        """Un control que se queda mudo cuando su almacén falla no es un
        control. Ante la duda, gritar."""
        H = self._handler()

        class S3Roto:
            def get_object(self, **k):
                raise RuntimeError("sin S3")

            def put_object(self, **k):
                raise RuntimeError("sin S3")

            def delete_object(self, **k):
                raise RuntimeError("sin S3")

        with mock.patch.object(H, "s3", S3Roto()):
            self.assertGreaterEqual(H._racha_fallas(True), 2)

    def test_el_despacho_usa_la_racha(self):
        fuente = (RAIZ / "handler.py").read_text(encoding="utf-8")
        i = fuente.index('if report_name == "poll_document_replies":')
        cuerpo = fuente[i:fuente.index("return r", i) + len("return r")]
        self.assertIn("_racha_fallas", cuerpo)
        self.assertIn("_avisar_falla", cuerpo)


if __name__ == "__main__":
    unittest.main()
