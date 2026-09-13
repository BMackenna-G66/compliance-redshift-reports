"""Validacion de clientes. Interfaz unica; Redshift es una implementacion mas."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Protocol, Set

LOTE_DEFECTO = 1000


class ValidadorClientes(Protocol):
    def validar(self, documentos: List[str]) -> Dict[str, dict]:
        """documento normalizado -> datos del cliente ({} si no es cliente)."""


class ValidadorCSV:
    """Implementacion offline para pruebas: lee una lista de documentos cliente."""

    def __init__(self, documentos_cliente: Iterable[str]):
        self._docs: Set[str] = {str(d).strip().lstrip("0") for d in documentos_cliente}

    def validar(self, documentos: List[str]) -> Dict[str, dict]:
        return {d: ({"user_id": None, "match": "csv"} if d.lstrip("0") in self._docs else {})
                for d in documentos}


SQL_VALIDACION = """
-- Busca por documento normalizado y tolera ceros a la izquierda en ambos lados.
SELECT
    u.document_number                          AS documento_origen,
    LTRIM(REGEXP_REPLACE(u.document_number, '[^0-9]', ''), '0') AS documento_normalizado,
    u.id                                       AS user_id,
    u.document_type,
    u.first_name,
    u.last_name,
    u.status,
    u.country,
    u.created_at
FROM {tabla} u
WHERE LTRIM(REGEXP_REPLACE(u.document_number, '[^0-9]', ''), '0') IN ({placeholders})
"""


class ValidadorRedshift:
    """Valida contra Redshift por lotes. La conexion se inyecta (psycopg2/redshift_connector)."""

    def __init__(self, conexion, tabla: str = "core.users",
                 lote: int = LOTE_DEFECTO, sql: Optional[str] = None):
        self.conexion = conexion
        self.tabla = tabla
        self.lote = lote
        self.sql = sql or SQL_VALIDACION

    def validar(self, documentos: List[str]) -> Dict[str, dict]:
        resultado: Dict[str, dict] = {d: {} for d in documentos}
        unicos = sorted({d for d in documentos if d})
        with self.conexion.cursor() as cur:
            for i in range(0, len(unicos), self.lote):
                bloque = unicos[i:i + self.lote]
                placeholders = ", ".join(["%s"] * len(bloque))
                cur.execute(self.sql.format(tabla=self.tabla, placeholders=placeholders), bloque)
                columnas = [c[0] for c in cur.description]
                for fila in cur.fetchall():
                    registro = dict(zip(columnas, fila))
                    clave = str(registro.get("documento_normalizado", "")).strip()
                    if clave in resultado:
                        resultado[clave] = registro
        return resultado


def marcar_clientes(personas: List[Dict], validador: ValidadorClientes) -> List[Dict]:
    """Agrega es_cliente y los datos del cliente a cada persona consolidada."""
    documentos = [p["numero_documento"] for p in personas]
    hallazgos = validador.validar(documentos)
    for p in personas:
        datos = hallazgos.get(p["numero_documento"]) or {}
        p["es_cliente"] = bool(datos)
        p["user_id"] = datos.get("user_id", "")
        p["estado_cliente"] = datos.get("status", "")
        p["pais_cliente"] = datos.get("country", "")
        p["nombre_en_sistema"] = " ".join(
            str(datos.get(k, "") or "") for k in ("first_name", "last_name")).strip()
    return personas


class ValidadorSimulado:
    """SOLO PARA DEMO. Marca como cliente una fraccion determinista del lote.

    Existe para poder probar el pipeline completo sin credenciales de Redshift.
    En produccion se reemplaza por ValidadorRedshift sin tocar el resto del codigo.
    """

    def __init__(self, tasa: float = 0.12, semilla: int = 66):
        self.tasa = tasa
        self.semilla = semilla

    def validar(self, documentos: List[str]) -> Dict[str, dict]:
        import hashlib
        salida = {}
        for d in documentos:
            h = int(hashlib.md5(f"{self.semilla}:{d}".encode()).hexdigest()[:8], 16)
            es_cliente = (h % 1000) < int(self.tasa * 1000)
            salida[d] = ({"user_id": f"SIM-{h % 999999:06d}", "status": "active",
                          "country": "CO", "first_name": "", "last_name": "",
                          "match": "SIMULADO"} if es_cliente else {})
        return salida
