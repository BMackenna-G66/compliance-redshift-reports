# -*- coding: utf-8 -*-
"""Los números del informe de alertas: por persona y por regla.

Hermano de `informe_casos`. Misma separación y por el mismo motivo: lo que
hay que poder probar con datos inventados es la cuenta, no el dibujo.

═══════════════════════════════════════════════════════════════════════════
LO QUE ESTE INFORME NO PUEDE MEDIR, Y POR QUÉ
═══════════════════════════════════════════════════════════════════════════

La spec propone columnas de «gestionadas hoy», «cerradas», «resultado de la
gestión» y «cumplimiento de SLA». Ninguna se puede calcular hoy:

· `reviewed_at` y `reviewed_by` existen en el modelo y están VACÍOS en las
  122 alertas. Nadie marca una alerta como revisada.
· `status` es `active` en las 122. Una alerta no cambia de estado: lo que
  cambia es que se le cuelga un caso.

Poner esas columnas igual mostraría ceros con cara de dato, y un cero que en
realidad significa «no lo medimos» es peor que no mostrar la columna: se lee
como «nadie gestionó nada». Así que lo que se mide es lo que la herramienta
registra de verdad — quién la tiene, hace cuánto entró, y si terminó en un
caso — y el correo dice explícitamente qué quedó afuera.

LO ACCIONABLE de este informe es la columna «sin caso»: una alerta que nadie
convirtió en caso y lleva semanas abierta es trabajo que no empezó.
"""
from __future__ import annotations

import datetime as dt

from informe_casos import SIN_ASIGNAR, a_fecha, normalizar_analista  # noqa: F401

PRIORIDADES = ("high", "medium", "low")


def tiene_caso(a) -> bool:
    """Si la alerta terminó en un caso.

    Se miran las dos: `case_id` es el vínculo real y `tiene_caso` la bandera
    que arma la API. Con una sola, 7 de 67 quedaban afuera."""
    return bool(a.get("case_id")) or bool(a.get("tiene_caso"))


def dias_abierta(a, ahora=None):
    ini = a_fecha(a.get("created_at"))
    if not ini:
        return None
    return ((ahora or dt.datetime.utcnow()) - ini).total_seconds() / 86400


def _pct(parte, total):
    return round(100.0 * parte / total, 1) if total else 0.0


def indicadores(alertas, ahora=None, viejas_dias: int = 30) -> dict:
    """Los números de un grupo de alertas: una persona, una regla o el total."""
    total = len(alertas)
    con_caso = [a for a in alertas if tiene_caso(a)]
    sin_caso = [a for a in alertas if not tiene_caso(a)]
    edades = [d for d in (dias_abierta(a, ahora) for a in alertas) if d is not None]
    viejas = [a for a in sin_caso
              if (dias_abierta(a, ahora) or 0) > viejas_dias]

    return {
        "total": total,
        "con_caso": len(con_caso),
        "sin_caso": len(sin_caso),
        "pct_con_caso": _pct(len(con_caso), total),
        "alta": sum(1 for a in alertas if (a.get("priority") or "") == "high"),
        "media": sum(1 for a in alertas if (a.get("priority") or "") == "medium"),
        "baja": sum(1 for a in alertas if (a.get("priority") or "") == "low"),
        # Sin caso y pasadas de tiempo: lo accionable.
        "sin_caso_viejas": len(viejas),
        "edad_promedio": round(sum(edades) / len(edades), 1) if edades else None,
        "mas_vieja": round(max(edades), 1) if edades else None,
    }


def por_persona(alertas, ahora=None) -> list:
    grupos: dict = {}
    for a in alertas:
        grupos.setdefault(normalizar_analista(a.get("assigned_to")), []).append(a)
    salida = [{"persona": p, **indicadores(suyas, ahora)}
              for p, suyas in grupos.items()]
    # Los sin asignar van último: es una alerta, no una persona.
    salida.sort(key=lambda x: (x["persona"] == SIN_ASIGNAR, -x["total"], x["persona"]))
    return salida


def por_regla(alertas, ahora=None) -> list:
    grupos: dict = {}
    for a in alertas:
        grupos.setdefault(a.get("report_name") or "(sin regla)", []).append(a)
    salida = [{"regla": r, **indicadores(suyas, ahora)}
              for r, suyas in grupos.items()]
    salida.sort(key=lambda x: (-x["total"], x["regla"]))
    return salida


def filtrar(alertas, desde="", hasta="", persona="", regla="") -> list:
    fuera = []
    for a in alertas:
        creada = str(a.get("created_at") or "")
        if desde and creada[:10] < desde[:10]:
            continue
        if hasta and creada[:10] > hasta[:10]:
            continue
        if persona and normalizar_analista(a.get("assigned_to")) != \
                normalizar_analista(persona):
            continue
        if regla and (a.get("report_name") or "") != regla:
            continue
        fuera.append(a)
    return fuera


def armar(alertas, desde="", hasta="", persona="", regla="", ahora=None) -> dict:
    sel = filtrar(alertas, desde, hasta, persona, regla)
    return {
        "filtro": {"desde": desde, "hasta": hasta, "persona": persona,
                   "regla": regla},
        "total_general": indicadores(sel, ahora),
        "personas": por_persona(sel, ahora),
        "reglas": por_regla(sel, ahora),
        "alertas": sel,
    }
