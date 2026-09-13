"""El cruce contra Redshift: quién de la lista del juzgado es cliente de Global66.

**La definición de "cliente" no vive acá, vive en la consulta.** Benjamín la dio
tal cual: si el documento aparece en el cruce de `kyc_document` con
`customer_v2`, es cliente; si no aparece, no lo es. Sin filtro de estado, sin
filtro de país, sin distinguir activo de inactivo. Este módulo no agrega
criterios propios — lo único que hace es correr esa consulta por lotes en vez
de una persona a la vez, porque un oficio trae hasta 15.000 personas.

**Qué se cambió de la consulta original y qué no.** El `=` pasó a `IN (...)`.
Nada más: la misma normalización, las mismas tablas, el mismo INNER JOIN. Si
la definición de cliente cambia, se cambia el SQL de acá y no hay que tocar
nada más del pipeline.

**Por qué los documentos van interpolados y no como parámetros.** La Data API
de Redshift no admite una cantidad variable de parámetros en un `IN`, así que
el lote se interpola. La barrera es `_clave_sql`, que deja pasar sólo `[A-Z0-9]`
— y lo que entra ya viene de `normalize_doc_id`, que reduce a dígitos. Aun así
se valida acá, porque el día que alguien llame a este módulo desde otro lado,
esa suposición deja de ser cierta.

**El cluster está pausado casi siempre.** `db_redshift.ensure_available()` lo
despierta y espera. Un oficio judicial tiene plazo de respuesta: es preferible
esperar el arranque a devolver "no es cliente" porque la base no contestó — de
hecho, ante cualquier falla este módulo levanta excepción en vez de devolver
un resultado vacío, porque un vacío silencioso acá se traduce en decirle a un
juzgado que no tenemos a alguien que sí es cliente.
"""
from __future__ import annotations

import re
from typing import Dict, List

# Tamaño de lote. 15.000 personas son 30 consultas; cada sentencia queda en
# ~7 KB, muy por debajo del límite de la Data API.
LOTE = 500

_SOLO_ALFANUM = re.compile(r"[^A-Z0-9]")

# La consulta de Benjamín, con `=` cambiado por `IN`. **El WHERE no se toca**:
# aparecer acá ES la definición de cliente.
#
# Al SELECT sí se le sumaron `document_type` y `country_code`. No cambian a
# quién se considera cliente —eso lo decide el WHERE— pero son lo único que
# permite ver un cruce sospechoso. Medido sobre un oficio real: de 7 personas
# marcadas como clientes, 2 lo eran por número de documento repetido entre
# países (una CC colombiana que en la base es un DNI argentino, y otra que es
# un RUT chileno), o sea personas distintas. Sin estas dos columnas ese 29%
# de falsos positivos es invisible.
SQL = """
SELECT DISTINCT
    kd.document_number AS dni,
    TRIM(
        COALESCE(c.name, '') || ' ' ||
        COALESCE(c.last_name, '')
    ) AS nombre_completo,
    kd.document_type AS tipo_dni,
    c.customer_id,
    c.country_code AS pais_cliente,
    REGEXP_REPLACE(UPPER(TRIM(kd.document_number)), '[^A-Z0-9]', '') AS dni_normalizado
FROM "db_prod"."customer"."kyc_document" kd
INNER JOIN "db_prod"."customer"."customer_v2" c
    ON kd.customer_id = c.customer_id
WHERE REGEXP_REPLACE(UPPER(TRIM(kd.document_number)), '[^A-Z0-9]', '') IN ({docs})
ORDER BY c.customer_id
"""


def clave_sql(documento) -> str:
    """Normaliza un documento igual que lo hace la consulta.

    Tiene que ser idéntico a `REGEXP_REPLACE(UPPER(TRIM(x)), '[^A-Z0-9]', '')`:
    si los dos lados no normalizan igual, el cruce falla en silencio y todos
    salen "no cliente".

    Ojo con una diferencia conocida río arriba: `normalize_doc_id` del pipeline
    reduce a dígitos y quita ceros a la izquierda, mientras que esta expresión
    conserva letras y ceros. Hoy no cambia nada —medido sobre los 42.477
    documentos de los cuatro archivos reales: cero con ceros a la izquierda, y
    los que traen letras los descarta `validate_doc_id` antes de llegar acá,
    con motivo `documento_no_numerico`, para revisión manual—. Queda anotado
    porque el día que se acepten pasaportes hay que resolverlo a propósito.
    """
    return _SOLO_ALFANUM.sub("", str(documento or "").strip().upper())


class ValidadorRedshift:
    """Implementa el Protocol `ValidadorClientes` sobre la Data API.

    El paquete original traía un `ValidadorRedshift` que asume una conexión
    DB-API (`cursor()`, marcadores `%s`). Acá no hay una: el repo habla con
    Redshift por la Data API a través de `db_redshift`. Esto es esa misma
    interfaz, implementada sobre lo que el proyecto ya usa — que es
    exactamente para lo que el pipeline la definió como Protocol.
    """

    def __init__(self, ejecutor=None, lote: int = LOTE):
        # `ejecutor(sql) -> list[dict]`. Inyectable para poder probar sin
        # cluster; por defecto usa el `db_redshift` del propio repo.
        self._ejecutor = ejecutor
        self.lote = max(1, int(lote))
        self.consultas = 0

    def _correr(self, sql: str) -> List[dict]:
        if self._ejecutor is not None:
            return self._ejecutor(sql)
        import db_redshift
        db_redshift.ensure_available()
        return db_redshift.fetchall(sql)

    def validar(self, documentos: List[str]) -> Dict[str, dict]:
        """{documento -> datos del cliente}. Diccionario vacío = no es cliente."""
        salida: Dict[str, dict] = {d: {} for d in documentos}

        # Se consulta por clave normalizada, pero se responde con la clave que
        # pidió quien llama: el pipeline indexa por `numero_documento`.
        por_clave: Dict[str, List[str]] = {}
        for d in documentos:
            k = clave_sql(d)
            if k:
                por_clave.setdefault(k, []).append(d)

        claves = sorted(por_clave)
        for i in range(0, len(claves), self.lote):
            bloque = claves[i:i + self.lote]
            lista = ", ".join(f"'{k}'" for k in bloque)
            filas = self._correr(SQL.format(docs=lista))
            self.consultas += 1
            for fila in filas:
                k = str(fila.get("dni_normalizado") or "").strip()
                for original in por_clave.get(k, []):
                    # DISTINCT puede devolver más de una fila por persona (dos
                    # documentos cargados, por ejemplo). Se queda la primera:
                    # para responderle al juzgado alcanza con que sea cliente.
                    if not salida[original]:
                        salida[original] = {
                            "customer_id": fila.get("customer_id"),
                            "user_id": fila.get("customer_id"),
                            "nombre_en_sistema": (fila.get("nombre_completo") or "").strip(),
                            "tipo_documento_sistema": fila.get("tipo_dni") or "",
                            "pais_cliente": fila.get("pais_cliente") or "",
                            "documento_sistema": fila.get("dni") or "",
                            "match": "redshift",
                        }
        return salida


def marcar_clientes(personas: List[Dict], validador) -> List[Dict]:
    """Marca `es_cliente` sobre las personas consolidadas.

    **Ser cliente son dos condiciones, no una: el número Y el tipo.** El cruce
    contra Redshift es sólo por número, y eso produce falsos positivos entre
    países: medido sobre un oficio real, de 7 personas marcadas como clientes
    2 lo eran porque una cédula colombiana coincide con un DNI argentino y con
    un RUT chileno, de gente distinta. Responderle a un juzgado que embargue a
    la persona equivocada es el error más caro de este módulo, así que el tipo
    de documento también tiene que coincidir.

    **La regla se aplica acá y no en el WHERE a propósito.** Filtrándola en el
    SQL, la coincidencia por número desaparecería sin dejar rastro. Acá se ve:
    la persona queda como NO cliente —que es la respuesta al juzgado— pero con
    `REVISAR:coincide_numero_pero_no_tipo` y los dos tipos, para que un
    analista pueda mirarlo si hace falta. En un expediente judicial, "hubo una
    coincidencia y se descartó por esto" es información, no ruido.

    **Un tipo que falta no es una discrepancia.** Si el oficio no dice el tipo,
    no hay nada que comparar: la persona sigue siendo cliente por número y se
    marca para revisión. Rechazarla sería perder un cliente real por un dato
    que el juzgado no mandó, y ése es el error en la dirección contraria.

    El nombre del sistema se guarda aparte y NO pisa el del oficio: cuál va en
    el Word es una decisión del área. Lo que hace falta es tenerlos juntos para
    poder contrastarlos, sobre todo donde el nombre del oficio viene corrupto
    de origen.
    """
    hallazgos = validador.validar([p["numero_documento"] for p in personas])
    for p in personas:
        datos = hallazgos.get(p["numero_documento"]) or {}
        coincide_numero = bool(datos)

        tipo_oficio = str(p.get("tipo_documento") or "").strip().upper()
        tipo_base = str(datos.get("tipo_documento_sistema") or "").strip().upper()
        sin_tipo = not tipo_oficio or not tipo_base
        coincide_tipo = sin_tipo or tipo_oficio == tipo_base

        p["es_cliente"] = coincide_numero and coincide_tipo
        p["coincide_numero"] = coincide_numero
        p["tipo_documento_coincide"] = coincide_tipo
        p["customer_id"] = datos.get("customer_id", "") if p["es_cliente"] else ""
        p["nombre_en_sistema"] = datos.get("nombre_en_sistema", "")
        p["tipo_documento_sistema"] = tipo_base
        p["pais_cliente"] = datos.get("pais_cliente", "")

        marca = ""
        if coincide_numero and not coincide_tipo:
            marca = (f"REVISAR:coincide_numero_pero_no_tipo "
                     f"(oficio {tipo_oficio} / base {tipo_base}"
                     + (f", {p['pais_cliente']}" if p.get("pais_cliente") else "") + ")")
        elif coincide_numero and sin_tipo:
            marca = ("REVISAR:no_se_pudo_comparar_el_tipo "
                     f"(oficio {tipo_oficio or 'sin dato'} / base {tipo_base or 'sin dato'})")
        if marca:
            p["flags"] = "; ".join(x for x in (p.get("flags"), marca) if x)
    return personas
