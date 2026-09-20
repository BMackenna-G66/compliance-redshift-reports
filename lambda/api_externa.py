# -*- coding: utf-8 -*-
"""API externa de gestión de casos: `/v1/casos/*`.

Para que un sistema de terceros —hoy el de casos del equipo— pueda hacer toda
la gestión desde afuera: filtrar, crear, mover el estado, dejar notas y
comunicarse con el cliente.

**Qué resuelve y qué NO.**

Resuelve tres cosas: autenticación por clave, un contrato estable y versionado,
y atribución real de quién hizo cada cosa. En el API interno el autor de una
acción llega en el cuerpo (`actor_email`) y es declarativo: cualquiera puede
escribir el mail de otro. Acá el autor sale de la clave presentada y el cuerpo
no puede cambiarlo, así que el registro dice la verdad.

**NO es todavía una frontera de seguridad.** La ruta `$default` del API Gateway
está en `Auth: NONE` y el authorizer de Cognito existe pero no está conectado a
ninguna ruta: hoy cualquiera con la URL puede llamar los endpoints internos sin
clave. Mientras eso siga así, esta clave sirve para identificar, auditar y
versionar el contrato — no para impedir el acceso. Cerrar el resto del API es
un trabajo aparte y rompe al frontend, que omite el header `Authorization` a
propósito por la configuración de CORS.

**El contrato es la proyección, no el objeto interno.** `caso_publico()` arma
explícitamente lo que sale. Si mañana alguien agrega o renombra un campo del
caso, el consumidor externo no se entera: hay que tocar esa función a mano, que
es justo lo que se quiere de un contrato versionado.
"""
from __future__ import annotations

import hmac
import json
import os
import re

import boto3

# Los permisos que puede tener una clave. Se piden de a uno por endpoint.
LEER = "casos:leer"
ESCRIBIR = "casos:escribir"
COMUNICAR = "casos:comunicar"
PERMISOS_VALIDOS = {LEER, ESCRIBIR, COMUNICAR}

CLAVES_SECRET = os.environ.get(
    "API_EXTERNA_KEYS_SECRET", "compliance-redshift-reports/api-externa-keys")

# Topes. No son una cuota distribuida —para eso haría falta un contador
# compartido— sino un freno a un loop desbocado del otro lado.
MAX_POR_PAGINA = 200
MAX_LOTE = 50

_cache: dict | None = None


def _consumidores() -> dict:
    """{'nombre': {'clave', 'permisos', 'activo'}} desde Secrets Manager.

    Una clave por consumidor, como en el endpoint de delitos: así la auditoría
    sabe quién hizo qué y se revoca a uno sin romperle el acceso al resto.

    Falla CERRADA: si el secreto no se puede leer, no se autoriza a nadie. Es
    preferible que la integración se caiga a que quede abierta por un error de
    permisos que nadie mira.
    """
    global _cache
    if _cache is not None:
        return _cache
    try:
        sm = boto3.client("secretsmanager")
        raw = sm.get_secret_value(SecretId=CLAVES_SECRET).get("SecretString", "") or "{}"
        crudo = json.loads(raw)
    except Exception as e:
        print(f"[api-externa] no pude leer las claves ({CLAVES_SECRET}): {e}")
        _cache = {}
        return _cache

    limpio = {}
    for nombre, cfg in (crudo or {}).items():
        # Se acepta la forma corta {"nombre": "clave"} para no obligar a
        # escribir el JSON largo cuando la clave es de sólo lectura.
        if isinstance(cfg, str):
            cfg = {"clave": cfg, "permisos": [LEER]}
        clave = str((cfg or {}).get("clave") or "").strip()
        if not nombre or not clave:
            continue
        permisos = {p for p in (cfg.get("permisos") or []) if p in PERMISOS_VALIDOS}
        limpio[str(nombre)] = {
            "clave": clave,
            "permisos": permisos,
            "activo": cfg.get("activo", True) is not False,
        }
    _cache = limpio
    return _cache


def identificar(event: dict) -> dict | None:
    """El consumidor detrás del header `x-api-key`, o None.

    Compara en tiempo constante y recorre TODAS las claves sin cortar en el
    primer acierto: cortar antes filtra información por el tiempo de respuesta.
    """
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    presentada = str(headers.get("x-api-key") or "").strip()
    if not presentada:
        return None
    hallado = None
    for nombre, cfg in _consumidores().items():
        if hmac.compare_digest(presentada, cfg["clave"]) and cfg["activo"]:
            hallado = {"nombre": nombre, "permisos": cfg["permisos"]}
    return hallado


def autorizar(event: dict, permiso: str):
    """(consumidor, None) si puede; (None, motivo) si no.

    El motivo distingue 401 de 403 a propósito: "no sé quién sos" y "sé quién
    sos pero no podés" son problemas distintos para quien integra, y mezclarlos
    manda a revisar la clave cuando lo que falta es un permiso.
    """
    c = identificar(event)
    if not c:
        return None, (401, {"error": "no_autorizado",
                            "message": "Header x-api-key ausente, inválido o revocado."})
    if permiso not in c["permisos"]:
        return None, (403, {"error": "sin_permiso",
                            "message": f"La clave no tiene el permiso '{permiso}'.",
                            "permisos": sorted(c["permisos"])})
    return c, None


def actor(consumidor: dict) -> str:
    """Cómo queda firmado en el histórico. El prefijo `api:` es deliberado:
    en una auditoría hay que poder separar lo que hizo una persona en la
    pantalla de lo que hizo un sistema por la API."""
    return f"api:{consumidor['nombre']}"


# ── el contrato ──────────────────────────────────────────────────────────
def caso_publico(c: dict) -> dict:
    """Lo que ve el consumidor externo. Explícito a propósito: ver el módulo."""
    return {
        "id": c.get("case_id", ""),
        "titulo": c.get("title", ""),
        "descripcion": c.get("description", ""),
        "estado": c.get("status", ""),
        "prioridad": c.get("priority", ""),
        "cliente": {
            "tipo": c.get("entity_type", ""),
            "id": c.get("entity_id", ""),
            "nombre": c.get("entity_name", ""),
        },
        "origen": {
            "reporte": c.get("report_name", ""),
            "prioridad_alerta": c.get("alert_priority", ""),
        },
        "asignado_a": c.get("assigned_to", ""),
        "creado_por": c.get("created_by", ""),
        "creado_at": c.get("created_at", ""),
        "actualizado_at": c.get("updated_at", ""),
        "cerrado_at": c.get("closed_at", ""),
        "notas": c.get("note_count", 0),
        # El plazo de los casos de alerta transaccional (ver sla_casos.py).
        "plazo": {
            "aplica": c.get("sla_aplica", False),
            "estado": c.get("sla_estado", ""),
            "dias_abierto": c.get("sla_dias"),
            "horas_restantes": c.get("sla_horas_restantes"),
            "cierre_at": c.get("sla_cierre_at", ""),
            "accion": c.get("sla_accion", ""),
        } if c.get("sla_aplica") else {"aplica": False},
    }


def nota_publica(n: dict) -> dict:
    """Una nota, como la ve el consumidor.

    El autor sale de `author_email`, que es el nombre que usa el caso guardado.
    No es un detalle: al escribirlo como `actor_email` —que es el nombre que
    usan OTROS endpoints— la nota se guardaba sin autor y nadie se enteraba,
    porque el endpoint devolvía 201 igual. Ver `cuerpo_nota`.
    """
    return {"texto": n.get("content", ""),
            "autor": n.get("author_email", ""),
            "cuando": n.get("created_at", "")}


def cuerpo_nota(texto: str, actor: str) -> dict:
    """El cuerpo que espera `add_case_note`.

    Vive acá, al lado de `nota_publica`, justamente para que el nombre del
    campo del autor se lea escrito dos veces en el mismo archivo: es la única
    defensa barata contra volver a equivocarlo.
    """
    return {"content": texto, "author_email": actor}


ESTADOS = ("open", "in_progress", "under_review", "closed", "archived")
PRIORIDADES = ("high", "medium", "low")


def valida_estado(v):
    return str(v or "").strip().lower() in ESTADOS


def valida_prioridad(v):
    return str(v or "").strip().lower() in PRIORIDADES


# ── la regla de Argentina ────────────────────────────────────────────────
# Los casos que interesan son clientes bloqueados por una regla del motor de
# fraude; el código de la regla viaja dentro de `agent_comment`, con la forma
# "operation-alert - FRAUD - PSP-C-AMT-J9H7". No hay una columna con el código
# suelto, así que se filtra por texto.
#
# El código se valida contra este patrón antes de entrar al SQL. No es cosmético:
# `_rs_exec` interpola el WHERE como texto, así que sin esto el parámetro sería
# una inyección directa contra Redshift.
RE_REGLA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")


def regla_valida(codigo) -> bool:
    return bool(RE_REGLA.match(str(codigo or "").strip()))


def sql_alertas_por_regla(codigo: str, pais: str = "", limite: int = 200) -> str:
    """Los clientes que la regla dejó bloqueados, listos para volverse caso.

    Sale de la misma vista que ya usa la creación de casos desde alertas
    (`compliance.priority_queue_b2c`), así que el país, el correo y el score
    son los mismos que vería el analista en la pantalla.
    """
    if not regla_valida(codigo):
        raise ValueError(f"código de regla inválido: {codigo!r}")
    filtro_pais = ""
    if pais:
        if not re.match(r"^[A-Za-z]{2}$", str(pais).strip()):
            raise ValueError(f"país inválido: {pais!r}")
        filtro_pais = f" AND UPPER(pais_cliente) = '{str(pais).strip().upper()}'"
    limite = max(1, min(int(limite or 200), MAX_POR_PAGINA))
    return (
        "SELECT customer_id, nombre, apellido, email, pais_cliente, dni, tipo_dni, "
        "       compliance_status, agent_comment, compliance_agent, risk_score, "
        "       status_created_at "
        "FROM compliance.priority_queue_b2c "
        f"WHERE agent_comment LIKE '%{codigo}%'{filtro_pais} "
        "ORDER BY status_created_at DESC "
        f"LIMIT {limite}"
    )


def alerta_publica(row: dict) -> dict:
    return {
        "cliente_id": row.get("customer_id"),
        "nombre": " ".join(x for x in (row.get("nombre"), row.get("apellido")) if x).strip(),
        "email": row.get("email", ""),
        "pais": row.get("pais_cliente", ""),
        "documento": {"tipo": row.get("tipo_dni", ""), "numero": row.get("dni", "")},
        "estado_compliance": row.get("compliance_status", ""),
        "regla": row.get("agent_comment", ""),
        "motor": row.get("compliance_agent", ""),
        "score": row.get("risk_score"),
        "bloqueado_at": row.get("status_created_at", ""),
    }
