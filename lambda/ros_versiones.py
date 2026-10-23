# -*- coding: utf-8 -*-
"""Las versiones de un ROS: qué se guardó, con qué hash y dónde.

═══════════════════════════════════════════════════════════════════════════
POR QUÉ UNA VERSIÓN ES INMUTABLE
═══════════════════════════════════════════════════════════════════════════

Lo que se aprueba y se manda al regulador es **una versión específica**, no
«el ROS». Si una edición pisara la versión anterior, la frase «se aprobó esto»
dejaría de poder probarse: el objeto aprobado y el objeto que quedó en disco
serían distintos y nadie podría notar la diferencia.

Por eso una edición **crea** `v{n+1}` y nunca toca `v{n}`, y por eso el hash
se calcula sobre **los mismos bytes que se escriben**. Un hash sobre el dict
en memoria no sirve: se puede volver a serializar distinto y dejar de
coincidir con el archivo, que es justo lo que uno querría verificar.

═══════════════════════════════════════════════════════════════════════════
LA SERIALIZACIÓN ES CANÓNICA, Y NO ES COSMÉTICA
═══════════════════════════════════════════════════════════════════════════

`sort_keys=True`, separadores sin espacios y UTF-8 sin escapar. Dos corridas
sobre el mismo contenido tienen que dar el MISMO hash; con el orden de claves
de Python o con `ensure_ascii` prendido, el mismo ROS da dos hashes distintos
según el día, y el hash deja de significar nada.

`ensure_ascii=False` importa particularmente acá: un ROS chileno viene lleno de
tildes y de «ñ», y escaparlas cambiaría los bytes sin cambiar el contenido.

═══════════════════════════════════════════════════════════════════════════
LO DEVUELTO POR GEREO Y LO EDITADO VIVEN SEPARADOS
═══════════════════════════════════════════════════════════════════════════

`origen` dice de dónde salió cada versión. La v1 de un ROS de GEREO es lo que
devolvió GEREO, intacto; una edición del analista es otra versión, con su
propio hash y su propio autor. Mezclarlos en un solo campo «el JSON» haría
imposible contestar la única pregunta que importa en una auditoría: qué puso
la máquina y qué puso la persona.
"""
from __future__ import annotations

import hashlib
import json
import re

# El ROS se guarda bajo el código de país, que es como lo pide el regulador y
# como lo nombra la especificación. `ros.REGULADORES` habla de nombres largos.
PAIS_POR_REGULADOR = {
    "UIF-AR": "AR",
    "UAF-CL": "CL",
    "UIAF-CO": "CO",
}

ORIGENES = ("gereo", "edicion")

# `ros/` es un prefijo SIN regla de lifecycle, a propósito: el bucket tiene 28
# reglas por carpeta y ninguna lo alcanza, así que nada de acá se borra solo.
# Un ROS es información reservada y el plazo de guarda lo fija la normativa de
# cada país, no una regla de S3 que alguien puso para ahorrar espacio.
RAIZ = "ros"

RE_FOLIO = re.compile(r"^ROS-\d{4}-\d{4}$")


def canonico(obj) -> bytes:
    """Los bytes exactos que se escriben y sobre los que se calcula el hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_de(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def pais_de(reporte: dict) -> str:
    return PAIS_POR_REGULADOR.get(str(reporte.get("regulador") or "").strip(), "")


def prefijo(reporte: dict) -> str:
    """`ros/CL/2026/10/ROS-2026-0001` — todas las versiones del mismo ROS juntas.

    El año y el mes salen de `creado_at` y NO de la fecha de hoy: si salieran
    de hoy, la v2 de un ROS de octubre aterrizaría en la carpeta de noviembre y
    las versiones de un mismo reporte quedarían desparramadas.
    """
    folio = str(reporte.get("folio") or "").strip()
    if not RE_FOLIO.match(folio):
        raise ValueError(f"folio inválido: {folio!r}")
    pais = pais_de(reporte)
    if not pais:
        raise ValueError(f"regulador sin país: {reporte.get('regulador')!r}")
    creado = str(reporte.get("creado_at") or "")
    m = re.match(r"^(\d{4})-(\d{2})", creado)
    if not m:
        raise ValueError(f"creado_at ilegible: {creado!r}")
    return f"{RAIZ}/{pais}/{m.group(1)}/{m.group(2)}/{folio}"


def clave(reporte: dict, numero: int, extension: str) -> str:
    if int(numero) < 1:
        raise ValueError(f"número de versión inválido: {numero!r}")
    if extension not in ("json", "pdf"):
        raise ValueError(f"extensión no permitida: {extension!r}")
    return f"{prefijo(reporte)}/v{int(numero)}.{extension}"


def versiones_de(reporte: dict) -> list:
    """Las versiones ya guardadas. Un ROS viejo no tiene el campo: son cero.

    Importa que esto no explote con un registro anterior a todo esto: el
    modelo tiene que seguir leyéndose sin migrar nada.
    """
    v = reporte.get("versiones")
    return list(v) if isinstance(v, list) else []


def siguiente_numero(reporte: dict) -> int:
    ya = versiones_de(reporte)
    return max((int(x.get("version") or 0) for x in ya), default=0) + 1


def version_de(reporte: dict, numero) -> dict | None:
    try:
        n = int(numero)
    except (TypeError, ValueError):
        return None
    for v in versiones_de(reporte):
        if int(v.get("version") or 0) == n:
            return v
    return None


def descriptor(numero: int, *, json_key: str, json_sha256: str, origen: str,
               quien: str, cuando: str, pdf_key: str = "",
               pdf_sha256: str = "") -> dict:
    """La ficha de una versión. Lo pesado vive en S3; acá van los punteros.

    El PDF es opcional de verdad: GEREO sólo lo manda si se pidió, y un ROS
    sin PDF es un ROS válido. Se guarda `""` y no `None` para que el registro
    tenga siempre la misma forma.
    """
    if origen not in ORIGENES:
        raise ValueError(f"origen desconocido: {origen!r}")
    return {
        "version": int(numero),
        "origen": origen,
        "json_key": json_key,
        "json_sha256": json_sha256,
        "pdf_key": pdf_key or "",
        "pdf_sha256": pdf_sha256 or "",
        "creada_por": str(quien or "").strip(),
        "creada_at": str(cuando or ""),
    }


def agregar(reporte: dict, desc: dict) -> dict:
    """El reporte con la versión nueva. NO muta el que recibe.

    Rechaza repetir un número: el llamador calcula `siguiente_numero()` y
    escribe en S3 con escritura condicional, pero el registro es leer-modificar-
    escribir sin bloqueo y dos ediciones a la vez pueden llegar hasta acá con el
    mismo `n`. Que falle es lo correcto: la alternativa es que una pise a la
    otra en silencio.
    """
    n = int(desc.get("version") or 0)
    if version_de(reporte, n) is not None:
        raise ValueError(f"la versión {n} ya existe en {reporte.get('folio')}")
    salida = dict(reporte)
    salida["versiones"] = versiones_de(reporte) + [desc]
    salida["version_actual"] = n
    return salida


# ═══════════════════════════════════════════════════════════════════════════
# LA EDICIÓN CAMBIA VALORES, NUNCA LA ESTRUCTURA
# ═══════════════════════════════════════════════════════════════════════════
#
# GEREO usa el JSON tal cual para completar el formulario del regulador: un
# campo de más, uno de menos o uno que cambió de tipo y el reporte se cae del
# otro lado —o peor, entra mal— y nos enteramos por el regulador.
#
# Por eso una edición se compara contra la versión anterior y se rechaza
# entera si la forma no coincide. No se recorta ni se completa lo que falta:
# arreglar a medias una estructura que no entendemos es cómo se manda un
# reporte que parece correcto.

def _tipo(v) -> str:
    """El tipo a efectos de forma. `int` y `float` son lo mismo —un monto
    puede venir como 1000 o 1000.0 sin que eso cambie nada— y `None` es
    comodín: un campo que vino vacío puede llenarse, que es el punto de
    editar."""
    if v is None:
        return "nulo"
    if isinstance(v, bool):      # antes que int: en Python bool ES int
        return "bool"
    if isinstance(v, (int, float)):
        return "numero"
    if isinstance(v, str):
        return "texto"
    if isinstance(v, dict):
        return "objeto"
    if isinstance(v, list):
        return "lista"
    return type(v).__name__


def rutas_de(obj, prefijo: str = "") -> dict:
    """Cada hoja del árbol con su tipo. `{"a.b": "texto", "c[0]": "numero"}`."""
    fuera = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            fuera.update(rutas_de(v, f"{prefijo}.{k}" if prefijo else str(k)))
    elif isinstance(obj, list):
        # El largo de una lista ES la estructura: agregar un reportado no es
        # editar un valor, es cambiar lo que el formulario del regulador va a
        # recibir. Para eso se pide otra generación a GEREO.
        for i, v in enumerate(obj):
            fuera.update(rutas_de(v, f"{prefijo}[{i}]"))
        if not obj:
            fuera[prefijo] = "lista"
    else:
        fuera[prefijo] = _tipo(obj)
    return fuera


def _es_hoja(v) -> bool:
    return not isinstance(v, (dict, list))


def diferencias_de_forma(antes, despues) -> list:
    """Qué cambió además de los valores. Lista vacía = la edición es válida.

    SE RECORRE EN PARALELO y no comparando dos mapas planos de rutas, porque
    una lista más larga tiene que poder evaluarse elemento por elemento: con
    rutas planas, un elemento agregado sólo se ve como «sobra x[2]» y no hay
    forma de mirar si respeta la forma de los que ya estaban.
    """
    return _comparar(antes, despues, "")


def _todo_vacio(v) -> bool:
    """Si no queda ningún dato adentro.

    Un elemento AGREGADO con todo en blanco termina como un reportado sin
    nombre ni documento en el reporte que se le manda al regulador. No es una
    edición a medias que alguien complete después: una vez aprobado, sale así.
    """
    if isinstance(v, dict):
        return all(_todo_vacio(x) for x in v.values())
    if isinstance(v, list):
        return all(_todo_vacio(x) for x in v)
    return v is None or (isinstance(v, str) and not v.strip())


def _comparar(a, b, ruta: str, *, agregado: bool = False) -> list:
    """`agregado` marca que `b` es un elemento que sumó una persona y `a` es
    la plantilla. Ver el bloque de listas más abajo."""
    ta, tb = _tipo(a), _tipo(b)

    # `nulo` es comodín ENTRE HOJAS, en los dos sentidos: un campo vacío se
    # puede llenar y uno lleno se puede vaciar. Entre una hoja y un objeto o
    # una lista no: eso cambia la estructura.
    if _es_hoja(a) and _es_hoja(b):
        if ta != tb and "nulo" not in (ta, tb):
            return [f"«{ruta}» era {ta} y llegó como {tb}"]
        return []

    if ta != tb:
        return [f"«{ruta}» era {ta} y llegó como {tb}"]

    if ta == "objeto":
        problemas = []
        for k in sorted(set(a) - set(b)):
            problemas.append(f"falta «{_ruta(ruta, k)}»")
        for k in sorted(set(b) - set(a)):
            problemas.append(f"sobra «{_ruta(ruta, k)}»")
        for k in sorted(set(a) & set(b)):
            problemas += _comparar(a[k], b[k], _ruta(ruta, k),
                                   agregado=agregado)
        return problemas

    # ── Listas ────────────────────────────────────────────────────────────
    #
    # SE PUEDE SUMAR, NO QUITAR. Compliance lo pidió así el 23-10-2026: a un
    # reporte le puede faltar un reportado y el analista lo agrega. Sacar uno
    # que GEREO sí trajo es otra cosa —es borrar algo que el modelo encontró—
    # y no se pidió.
    #
    # EL ELEMENTO NUEVO COPIA LA FORMA DEL PRIMERO de la v1. Si la lista venía
    # vacía no hay plantilla, y adivinar qué campos lleva un reportado es
    # exactamente cómo se manda al regulador un registro al que le falta un
    # dato obligatorio: ahí se pide otra generación a GEREO.
    problemas = []

    # DENTRO DE UN ELEMENTO AGREGADO, EL LARGO ES LIBRE. Lo que hay que
    # preservar es lo que generó GEREO, no lo que sumó una persona: si un
    # reportado trae `telefonos`, el reportado NUEVO puede tener uno, tres o
    # ninguno. Sin esto, agregar una persona fallaba SIEMPRE en cuanto el
    # modelo devolviera cualquier lista adentro —el caso normal—, y fallaba
    # recién al guardar.
    #
    # La forma de cada elemento se sigue verificando contra el [0] de la
    # plantilla; lo único que se suelta es cuántos hay.
    if not agregado and len(b) < len(a):
        for i in range(len(b), len(a)):
            problemas.append(f"falta «{ruta}[{i}]»")
    for i in range(min(len(a), len(b))):
        problemas += _comparar(a[i], b[i], f"{ruta}[{i}]", agregado=agregado)
    if len(b) > len(a):
        if not a:
            problemas.append(
                f"«{ruta}» venía vacía y no hay de dónde copiar la forma de un "
                "elemento nuevo; pedí otra generación a GEREO")
        else:
            for i in range(len(a), len(b)):
                # De acá para abajo, todo es agregado.
                problemas += _comparar(a[0], b[i], f"{ruta}[{i}]",
                                       agregado=True)
                # UN AGREGADO VACÍO NO SE GUARDA. Si no, «Agregar» y guardar
                # sin llenar nada deja en el reporte al regulador un
                # reportado sin nombre ni documento.
                if _todo_vacio(b[i]):
                    problemas.append(
                        f"«{ruta}[{i}]» se agregó y quedó sin ningún dato: "
                        "llenalo o sacalo antes de guardar")
    return problemas


def _ruta(prefijo: str, clave) -> str:
    return f"{prefijo}.{clave}" if prefijo else str(clave)


def fundir(doc_anterior: dict, secciones_editadas: dict,
           claves_editables) -> dict:
    """El documento nuevo: lo editado encima de lo anterior.

    SÓLO SE TOCAN LAS SECCIONES DEL FORMULARIO. `meta` y `reglas` se arrastran
    de la versión anterior y no se exponen a edición: `meta` dice quién y
    cuándo generó el reporte y `reglas` qué se evaluó. Son el registro de lo
    que hizo la máquina, y una persona editándolos borraría justamente la
    parte que permite auditar.
    """
    permitidas = set(claves_editables)
    intrusas = sorted(set(secciones_editadas) - permitidas)
    if intrusas:
        raise ValueError("no se pueden editar estas secciones: "
                         + ", ".join(intrusas))
    salida = dict(doc_anterior)
    for clave, valor in secciones_editadas.items():
        salida[clave] = valor
    return salida


# El nombre largo del país, que es como lo nombra `ros_gereo.SECCIONES`.
# `PAIS_POR_REGULADOR` da el código de dos letras, que es lo que pide la ruta
# en S3; son dos cosas distintas y mezclarlas devuelve secciones vacías sin
# error, que es la peor forma de fallar.
PAIS_LARGO_POR_REGULADOR = {
    "UIF-AR": "Argentina",
    "UAF-CL": "Chile",
    "UIAF-CO": "Colombia",
}


def pais_largo(reporte: dict) -> str:
    return PAIS_LARGO_POR_REGULADOR.get(
        str(reporte.get("regulador") or "").strip(), "")
