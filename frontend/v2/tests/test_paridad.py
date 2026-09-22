"""El guardián de la paridad con v1.

EL PROBLEMA QUE RESUELVE. v2 se escribió pantalla por pantalla mirando v1, y
así es como se pierden cosas: nadie nota que el botón «extraer la ficha KYC»
no se portó hasta que alguien lo busca en producción y no está. Pasó de
verdad: el detalle del caso quedó con 5 de las 17 acciones que tiene v1, y la
ficha del cliente perdió cuatro secciones enteras.

CÓMO LO RESUELVE. Lee las rutas de la API que v1 usa —de su HTML, no de una
lista escrita a mano que se desactualiza al primer commit— y las que usa v2, y
compara. Lo que v1 hace y v2 todavía no tiene que estar en PENDIENTES con su
motivo. Ni uno más, ni uno menos:

  · aparece algo sin declarar   → falla: se está perdiendo una función
  · se declara algo ya portado  → falla: la lista miente, hay que borrar esa
                                  línea

La segunda mitad es la que hace que la lista se vacíe en vez de pudrirse.

POR QUÉ COMPARA RUTAS Y NO MÉTODOS. v1 arma varias rutas en variables
(`const path = '/cases' + qs`), así que leer el método de cada llamada no es
confiable. La ruta sí: es un literal en los dos lados. Y el modo en que esto
se rompe —«la pantalla perdió el botón»— se ve igual de bien a nivel ruta.

QUÉ NO MIDE. Que v2 nombre `/cases/{id}/export` no prueba que la exportación
ande. Mide que la función EXISTE, que es justo lo que se estaba perdiendo en
silencio. La calidad la miden los tests de cada pantalla.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
V1 = RAIZ / "frontend" / "index.html"
V2 = RAIZ / "frontend" / "v2" / "src"
BACKEND = RAIZ / "lambda" / "api_handler.py"


# ── Lo que todavía no está portado ────────────────────────────────────────
#
# Cada línea es una capacidad de v1 que v2 no tiene. Se borran a medida que se
# portan; el objetivo es que esto quede vacío. Las que NO van a portarse
# llevan escrito el motivo: son decisiones, no olvidos.

PENDIENTES = {
    # ── El detalle del caso ───────────────────────────────────────────────
    "/cases/bulk-assign": "asignación masiva de casos",

    # ── La ficha del cliente ──────────────────────────────────────────────
    "/clientes/:x/solicitudes-recientes": "documentación pedida y recibida",
    "/customer/context": "el contexto del cliente (perfil KYC de la ficha)",

    # ── Alertas ───────────────────────────────────────────────────────────
    "/alerts/:x": "borrar una alerta",
    "/alerts/:x/link-case": "atar una alerta a un caso",
    "/alerts/bulk-distribute": "repartir alertas entre analistas",
    "/alerts/notify": "notificar por correo/Slack",
    "/alerts/export.xlsx": "exportar alertas a Excel",
    "/alert-prioritization/send-manual": "envío manual de la cola priorizada",
    "/alert-document-config": "configuración de documentos por reporte",
    "/alert-document-config/:x": "editar y borrar esa configuración",

    # ── Reportes y corridas ───────────────────────────────────────────────
    "/schedules": "la programación de reportes",

    # ── Análisis ──────────────────────────────────────────────────────────
    "/analyze/entity-name": "resolver el nombre de una entidad",

    # ── El tablero ────────────────────────────────────────────────────────
    "/dashboard/stats": "las tarjetas del tablero de v1",
    "/dashboard/stats/result": "su resultado asincrónico",
    "/analytics/summary": "el resumen analítico",
    "/analytics/result": "su resultado asincrónico",
    "/analytics/sla": "el analítico de plazos",
    "/analytics/sla/result": "su resultado asincrónico",

    # ── Institucional ─────────────────────────────────────────────────────
    "/institutional/clients/refresh": "refrescar las empresas",
    "/institutional/rules/:x": "editar y borrar una regla institucional",
    "/institutional/alerts/check": "correr el chequeo institucional",
    "/institutional/alerts/:x": "revisar una alerta institucional",

    # ── Relevo ────────────────────────────────────────────────────────────
    "/relevo/casos/:x": "el detalle de un caso de relevo",
    "/relevo/casos/:x/pedido": "mandarle el pedido de documentos",
    "/relevo/casos/:x/mensaje": "mandarle un mensaje",
    "/relevo/casos/:x/recontactar": "recontactar",
    "/relevo/casos/:x/devolucion": "la devolución de fondos",
    "/relevo/casos/:x/checklist": "su checklist de documentos",
    "/relevo/casos/:x/descarga": "bajar lo que mandó el cliente",
    "/relevo/clientes": "el padrón de clientes del relevo",
    "/relevo/config": "la configuración del relevo",
    "/relevo/espejo": "el espejo de Redshift",
    "/relevo/mensajes": "las plantillas de mensaje",
    "/relevo/vencidos": "los vencidos del relevo",
    "/relevo/pedidos/lote": "pedidos en lote",
    "/relevo/probar": "probar el envío sin mandar nada al cliente",
    "/relevo/resolver": "resolver un pendiente del relevo",

    # ── Administración ────────────────────────────────────────────────────
    "/rules": "las reglas de alertamiento",
    "/rules/:x": "editar y borrar una regla",
    "/slack-users": "los destinatarios de Slack",
    "/slack-users/:x": "quitar un destinatario",
    "/users/:x": "editar y dar de baja un usuario del CRM",
    "/email-templates": "las plantillas de correo",
    "/email-templates/preview": "previsualizar una plantilla",
    "/whitelist/bulk": "alta masiva de whitelist",

    # ── Embargos ──────────────────────────────────────────────────────────
    "/embargos/:x/resultados": "los resultados de una corrida de embargos",

    # ── Decisiones, no olvidos ────────────────────────────────────────────
    "/roles": "v2 lee los roles de Firestore (wt_roles), no de la API",
    "/cluster/wake": "v2 lo llama como /cluster/{accion}, cubre wake y pause",
}


# ── La lectura ────────────────────────────────────────────────────────────

def _segmentos_del_backend():
    """Los primeros segmentos que la API sirve de verdad.

    Sirve de vocabulario para reconocer qué literal `/loquesea` es una ruta de
    la API y cuál es una clase de CSS o una ruta de archivo."""
    texto = BACKEND.read_text(encoding="utf-8")
    return {m.group(1) for m in
            re.finditer(r'parts(?:\[0\])?\s*==\s*\[?\s*"([a-zA-Z0-9_.-]+)"', texto)}


def _argumento(texto, i):
    """La expresión que va desde `i` hasta la coma o el `)` que la cierra."""
    prof, j, comilla = 0, i, ""
    while j < len(texto):
        c = texto[j]
        if comilla:
            if c == "\\":
                j += 2
                continue
            if c == comilla:
                comilla = ""
        elif c in "'\"`":
            comilla = c
        elif c in "([{":
            prof += 1
        elif c in ")]}":
            if prof == 0:
                return texto[i:j]
            prof -= 1
        elif c == "," and prof == 0:
            return texto[i:j]
        j += 1
    return texto[i:j]


def _sumandos(expr):
    """Parte una concatenación por los `+` de afuera de todo paréntesis."""
    partes, prof, ini, comilla = [], 0, 0, ""
    for j, c in enumerate(expr):
        if comilla:
            if c == "\\":
                continue
            if c == comilla:
                comilla = ""
        elif c in "'\"`":
            comilla = c
        elif c in "([{":
            prof += 1
        elif c in ")]}":
            prof -= 1
        elif c == "+" and prof == 0:
            partes.append(expr[ini:j])
            ini = j + 1
    partes.append(expr[ini:])
    return partes


def _ruta(expr):
    """Reconstruye `'/cases/' + id + '/export'` como `/cases/:x/export`."""
    trozos = []
    for parte in _sumandos(expr):
        t = parte.strip()
        m = re.fullmatch(r"""['"`](.*)['"`]""", t, re.S)
        if m:
            literal = re.sub(r"\$\{[^}]*\}", ":x", m.group(1))
            if "?" in literal:                 # empezó el query: la ruta terminó
                trozos.append(literal.split("?")[0])
                break
            trozos.append(literal)
        else:
            if "?" in t:                       # una ternaria que arma el query
                break
            trozos.append(":x")
    ruta = "".join(trozos).split("?")[0].rstrip("/")
    ruta = re.sub(r":x(?=:x)", "", ruta)       # dos identificadores pegados
    return ruta


def _literales(texto, vocabulario):
    """Toda cadena `/loquesea` cuyo primer segmento la API sirve.

    Hace falta además de las llamadas porque v1 arma varias rutas en una
    variable antes de pasarlas, y ahí el literal es lo único visible."""
    hallados = set()
    for m in re.finditer(r"""['"](/[a-zA-Z0-9_./${}-]*)['"]""", texto):
        ruta = re.sub(r"\$\{[^}]*\}", ":x", m.group(1)).rstrip("/")
        if ruta.lstrip("/").split("/")[0] in vocabulario:
            hallados.add(ruta)
    return hallados


def rutas_de_v1(vocabulario):
    texto = V1.read_text(encoding="utf-8")
    hallados = set()
    for m in re.finditer(r"\bapi(?:Raw)?\(\s*'(\w+)'\s*,\s*", texto):
        ruta = _ruta(_argumento(texto, m.end()))
        if ruta.startswith("/") and ruta != "/:x":
            hallados.add(ruta)
    # Los fetch sueltos contra la API. Son pocos —la previsualización de
    # plantillas— pero se pierden si sólo se miran las llamadas a api().
    for m in re.finditer(r"fetch\(\s*this\.apiBase\s*\+\s*", texto):
        ruta = _ruta(_argumento(texto, m.end()))
        if ruta.startswith("/"):
            hallados.add(ruta)
    return hallados | _literales(texto, vocabulario)


def rutas_de_v2(vocabulario):
    hallados = set()
    for archivo in list(V2.rglob("*.js")) + list(V2.rglob("*.jsx")):
        texto = archivo.read_text(encoding="utf-8")
        for m in re.finditer(r"\.(?:get|post|del)\(\s*(?=['\"`])", texto):
            ruta = _ruta(_argumento(texto, m.end()))
            if ruta.startswith("/"):
                hallados.add(ruta)
        for m in re.finditer(r"crudo\(\s*'\w+'\s*,\s*", texto):
            ruta = _ruta(_argumento(texto, m.end()))
            if ruta.startswith("/"):
                hallados.add(ruta)
        hallados |= _literales(texto, vocabulario)
    return hallados


class LaParidadConV1(unittest.TestCase):
    """v2 puede reemplazar a v1 el día que este test no tenga nada que decir."""

    @classmethod
    def setUpClass(cls):
        vocabulario = _segmentos_del_backend()
        cls.vocabulario = vocabulario
        cls.v1 = rutas_de_v1(vocabulario)
        cls.v2 = rutas_de_v2(vocabulario)
        cls.falta = cls.v1 - cls.v2

    def test_la_lectura_encuentra_algo(self):
        """Sin esto, un regex que deja de matchear haría que «no falta nada»
        sea cierto por accidente y el guardián se volvería decorativo."""
        self.assertGreater(len(self.vocabulario), 30, "no se leyó el backend")
        self.assertGreater(len(self.v1), 80, "no se leyeron las rutas de v1")
        self.assertGreater(len(self.v2), 40, "no se leyeron las rutas de v2")

    def test_nada_se_pierde_sin_declararlo(self):
        sin_declarar = sorted(self.falta - set(PENDIENTES))
        self.assertEqual(sin_declarar, [], (
            "v2 no cubre esto y no está declarado. O se porta, o se agrega a "
            "PENDIENTES con el motivo por el que no va:\n  " +
            "\n  ".join(sin_declarar)))

    def test_la_lista_de_pendientes_no_miente(self):
        ya_estan = sorted(set(PENDIENTES) - self.falta)
        self.assertEqual(ya_estan, [], (
            "esto ya está portado: sacalo de PENDIENTES para que la lista siga "
            "sirviendo de medida:\n  " + "\n  ".join(ya_estan)))

    def test_cada_pendiente_dice_de_que_se_trata(self):
        for ruta, motivo in PENDIENTES.items():
            self.assertTrue(str(motivo).strip(),
                            f"{ruta} figura pendiente sin decir qué es")


if __name__ == "__main__":
    unittest.main(verbosity=2)
