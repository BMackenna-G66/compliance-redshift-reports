# -*- coding: utf-8 -*-
"""Lo que el front repite del backend, y tiene que seguir coincidiendo.

LA REGLA DE v2 es no duplicar decisiones de negocio: se le piden al backend.
Pero hay tres casos donde el front NO puede pedirlas —no hay endpoint— y las
repite para armar un desplegable o una etiqueta. Esas son las que este
archivo vigila.

No es un test de estilo: si el backend agrega un estado manual y el front no
lo tiene, la opción simplemente no aparece en la pantalla y nadie se entera.
Si el front tiene uno que el backend no acepta, el usuario lo elige y recibe
un error que no entiende. Las dos fallas son silenciosas para quien las
sufre, y las dos se ven acá en un segundo.

CUANDO ESTE TEST FALLE: no lo ajustes para que pase. Mirá cuál de los dos
lados cambió y por qué — puede ser que haya que actualizar el front, o que el
cambio del backend no debiera haber ocurrido.
"""
import ast
import json
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
LAMBDA = RAIZ / "lambda"
SRC = Path(__file__).resolve().parents[1] / "src"


def _lista_python(archivo: Path, nombre: str):
    """Una constante de lista de Python, sin importar el módulo.

    Se lee con `ast` en vez de importar: `relevo/casos.py` arrastra
    dependencias de AWS y este test tiene que correr sin credenciales.
    """
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name) and destino.id == nombre:
                    return ast.literal_eval(nodo.value)
    raise AssertionError(f"no encontré {nombre} en {archivo.name}")


def _dict_python(archivo: Path, nombre: str):
    return _lista_python(archivo, nombre)


def _lista_js(archivo: Path, nombre: str):
    """Una constante `export const NOMBRE = [...]` de un módulo JS."""
    texto = archivo.read_text(encoding="utf-8")
    m = re.search(r"export const " + re.escape(nombre) + r"\s*=\s*\[(.*?)\];", texto, re.S)
    if not m:
        raise AssertionError(f"no encontré {nombre} en {archivo.name}")
    return re.findall(r"'([^']+)'", m.group(1))


def _claves_js(archivo: Path, nombre: str):
    """Las claves de un `export const NOMBRE = { ... }` de un módulo JS."""
    texto = archivo.read_text(encoding="utf-8")
    i = texto.index(f"export const {nombre} = {{")
    # Se corta en la línea que cierra el objeto al margen izquierdo.
    fin = texto.index("\n};", i)
    cuerpo = texto[i:fin]
    return re.findall(r"^\s{2}([A-Za-z_][\w]*)\s*:", cuerpo, re.M)


class EstadosManualesDeRelevo(unittest.TestCase):
    """Los estados que un analista puede fijar a mano en un caso de relevo.

    El backend los valida contra `ESTADOS_MANUALES` y rechaza cualquier otro
    con un 400. El front los usa para armar el desplegable.
    """

    def setUp(self):
        self.backend = _lista_python(LAMBDA / "relevo" / "casos.py", "ESTADOS_MANUALES")
        self.front = _lista_js(SRC / "comun" / "relevo.js", "ESTADOS_MANUALES")

    def test_son_exactamente_los_mismos(self):
        self.assertEqual(sorted(self.front), sorted(self.backend))

    def test_el_front_no_ofrece_ninguno_que_el_backend_rechace(self):
        de_mas = set(self.front) - set(self.backend)
        self.assertEqual(de_mas, set(),
                         f"el front ofrece estados que el backend rechaza: {de_mas}")

    def test_el_front_no_esconde_ninguno_que_el_backend_acepte(self):
        faltan = set(self.backend) - set(self.front)
        self.assertEqual(faltan, set(),
                         f"el backend acepta estados que el front no ofrece: {faltan}")

    def test_los_diagnosticos_siguen_afuera(self):
        """`casos.py` los deja afuera a propósito: no son etapas del trabajo
        sino datos que faltan, y fijarlos a mano tapa el diagnóstico."""
        for d in ("sin_cliente", "sin_correo", "sin_requerimiento", "informativo"):
            with self.subTest(d):
                self.assertNotIn(d, self.front)


class ModulosDeV1(unittest.TestCase):
    """v2 tiene que cubrir todos los módulos de permisos que v1 conoce.

    Los dos fronts leen la misma colección `wt_roles`. Si v1 puede otorgar un
    módulo que v2 no tiene como pantalla, ese acceso existe pero no lleva a
    ningún lado — y al revés, si v2 muestra una pantalla cuyo módulo v1 no
    puede otorgar, nadie puede darle ese acceso a un perfil de sólo lectura.

    Este test es el que dice si v2 está listo para reemplazar a v1.
    """

    def _modulos_v1(self):
        html = (RAIZ / "frontend" / "index.html").read_text(encoding="utf-8")
        i = html.index("ALL_MODULES: [")
        cuerpo = html[i:html.index("],", i)]
        return set(re.findall(r"key:\s*'([a-z_]+)'", cuerpo))

    def _modulos_v2(self):
        texto = (SRC / "dominio.js").read_text(encoding="utf-8")
        return set(re.findall(r"modulo:\s*'([a-z_]+)'", texto))

    def test_v2_cubre_todos_los_modulos_de_v1(self):
        faltan = self._modulos_v1() - self._modulos_v2()
        self.assertEqual(faltan, set(),
                         f"v1 puede otorgar módulos que v2 no tiene como pantalla: {faltan}")

    def test_lo_que_v2_agrega_es_solo_admin(self):
        """v2 tiene `admin`, que v1 no lista porque su panel de permisos no lo
        ofrece —y está bien: nadie debería poder darle administración a un
        perfil de sólo lectura desde esa pantalla."""
        de_mas = self._modulos_v2() - self._modulos_v1()
        self.assertEqual(de_mas, {"admin"},
                         f"v2 usa módulos que v1 no conoce: {de_mas - {'admin'}}")


class NombresDeEstado(unittest.TestCase):
    """Cada estado del backend tiene que tener nombre legible en el front."""

    def test_no_falta_ninguno(self):
        backend = set(_dict_python(LAMBDA / "relevo" / "casos.py", "ESTADOS"))
        front = set(_claves_js(SRC / "comun" / "relevo.js", "NOMBRE_ESTADO"))
        faltan = backend - front
        self.assertEqual(faltan, set(),
                         f"estados sin nombre legible: {faltan}")


class EtapasDeRelevo(unittest.TestCase):
    """Los números de etapa que el front dibuja tienen que existir atrás."""

    def test_el_front_conoce_todas_las_etapas_del_backend(self):
        backend = set(_dict_python(LAMBDA / "relevo" / "casos.py", "ETAPA").values())
        texto = (SRC / "comun" / "relevo.js").read_text(encoding="utf-8")
        front = {int(n) for n in re.findall(r"\{ n: (-?\d+),", texto)}
        faltan = backend - front
        self.assertEqual(faltan, set(),
                         f"el backend usa etapas que el front no dibuja: {faltan}")


class CortesDelAnalisisIndividual(unittest.TestCase):
    """Los cortes de nivel: el front los muestra como referencia.

    El endpoint `GET /flags` los devuelve, así que la pantalla de banderas los
    lee. Pero `dominio.js` también los tiene en `NIVELES` para pintar los
    badges sin esperar una llamada, y ahí sí pueden desincronizarse.
    """

    def test_coinciden_con_aml_individual(self):
        backend = _dict_python(LAMBDA / "aml_individual.py", "CORTES_NIVEL")
        texto = (SRC / "dominio.js").read_text(encoding="utf-8")
        front = {}
        for nivel, clave in (("CRITICO", "critico"), ("ALTO", "alto"), ("MEDIO", "medio")):
            m = re.search(nivel + r":\s*\{[^}]*desde:\s*(\d+)", texto)
            self.assertIsNotNone(m, f"no encontré el corte de {nivel} en dominio.js")
            front[clave] = int(m.group(1))
        self.assertEqual(front, backend)

    def test_el_maximo_del_front_es_la_suma_de_los_pesos(self):
        pesos = _dict_python(LAMBDA / "aml_individual.py", "FLAG_WEIGHTS")
        texto = (SRC / "dominio.js").read_text(encoding="utf-8")
        m = re.search(r"NIVELES_MAXIMO = (\d+)", texto)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), sum(pesos.values()))


class CortesDeLasAlertas(unittest.TestCase):
    """La otra escala: P1/P2/P3 sobre 100, de `handler.py`."""

    def test_coinciden_con_handler(self):
        texto_py = (LAMBDA / "handler.py").read_text(encoding="utf-8")
        m = re.search(r'"P1" if score >= (\d+) else "P2" if score >= (\d+)', texto_py)
        self.assertIsNotNone(m, "no encontré los cortes de prioridad en handler.py")
        p1, p2 = int(m.group(1)), int(m.group(2))

        texto_js = (SRC / "dominio.js").read_text(encoding="utf-8")
        front = {}
        for nivel in ("P1", "P2"):
            mm = re.search(nivel + r":\s*\{[^}]*desde:\s*(\d+)", texto_js)
            self.assertIsNotNone(mm, f"no encontré el corte de {nivel}")
            front[nivel] = int(mm.group(1))
        self.assertEqual(front, {"P1": p1, "P2": p2})


class ElPlazoDeLosCasos(unittest.TestCase):
    """El respaldo del plazo en `dominio.js` es sólo para el primer render:
    el valor de verdad viaja en `sla_config`. Aun así, si se separan, la
    pantalla parpadea con un plazo equivocado antes de corregirse."""

    def test_el_respaldo_coincide_con_sla_casos(self):
        texto_py = (LAMBDA / "sla_casos.py").read_text(encoding="utf-8")
        recontacto = float(re.search(r"HORAS_RECONTACTO = ([\d.]+)", texto_py).group(1))
        cierre = float(re.search(r"HORAS_CIERRE = ([\d.]+)", texto_py).group(1))

        texto_js = (SRC / "dominio.js").read_text(encoding="utf-8")
        m = re.search(r"PLAZO_RESPALDO = \{ horas_recontacto: (\d+), horas_cierre: (\d+) \}",
                      texto_js)
        self.assertIsNotNone(m, "no encontré PLAZO_RESPALDO en dominio.js")
        self.assertEqual((float(m.group(1)), float(m.group(2))), (recontacto, cierre))


class ElMapaDeMontos(unittest.TestCase):
    """Los reportes del mapa de montos tienen que existir en el catálogo."""

    def test_los_reportes_existen_en_el_backend(self):
        texto_py = (LAMBDA / "api_handler.py").read_text(encoding="utf-8")
        catalogo = set(re.findall(r'"report_name":\s*"([^"]+)"', texto_py))
        texto_js = (SRC / "dominio.js").read_text(encoding="utf-8")
        i = texto_js.index("export const MONTO_POR_REPORTE = {")
        cuerpo = texto_js[i:texto_js.index("\n};", i)]
        front = set(re.findall(r"^\s{2}([a-z_]+):", cuerpo, re.M))
        # `operation-alert_-_psp_sum_30` es una consulta a medida y no está en
        # el catálogo de reportes del código; por eso tampoco está en el mapa.
        faltan = front - catalogo
        self.assertEqual(faltan, set(),
                         f"el mapa nombra reportes que no están en el catálogo: {faltan}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
