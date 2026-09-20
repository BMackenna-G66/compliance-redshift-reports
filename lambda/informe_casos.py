# -*- coding: utf-8 -*-
"""Los números del informe de gestión: por equipo y por analista.

Separado del PDF a propósito. Lo que hay que poder probar con casos inventados
es la cuenta —qué es un caso gestionado, cómo se promedia un cierre, qué pasa
con un analista sin casos cerrados—, y mezclarla con reportlab obligaría a
abrir un PDF para verificar una división.

**Una advertencia sobre para qué sirve esto.** El informe mide *actividad
registrada en la herramienta*, no desempeño. Un caso difícil y uno trivial
cuentan lo mismo, el que toma los casos que nadie quiere sale peor, y lo que se
trabaja por fuera —una llamada, un Slack— no existe acá. Sirve para ver carga,
encontrar casos abandonados y detectar desbalances; para evaluar a una persona
hay que mirar los casos, no el promedio.
"""
from __future__ import annotations

import datetime as dt
import statistics

FORMATO = "%Y-%m-%d %H:%M:%S"

ABIERTOS = ("open", "in_progress", "under_review")
CERRADOS = ("closed", "archived")

SIN_ASIGNAR = "(sin asignar)"
SIN_EQUIPO = "Sin equipo"


def normalizar_analista(valor) -> str:
    """El mismo analista escrito de dos formas es un solo analista.

    En producción Diego aparece como `diego armesto` (10 casos) y como
    `diego.armesto@global66.com` (8): sin esto, un informe que se usa para
    mirar carga de trabajo le parte los números al medio y muestra dos
    personas que no existen.
    """
    a = str(valor or "").strip().lower()
    if not a:
        return SIN_ASIGNAR
    if "@" in a:
        return a
    # "diego armesto" -> "diego.armesto@global66.com"
    return a.replace(" ", ".") + "@global66.com"


def a_fecha(texto):
    if not texto:
        return None
    t = str(texto).strip().replace("T", " ").split(".")[0].split("+")[0]
    if t.endswith("Z"):
        t = t[:-1]
    for f in (FORMATO, "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(t, f)
        except ValueError:
            continue
    return None


def esta_cerrado(c) -> bool:
    return (c.get("status") or "").strip().lower() in CERRADOS


def fue_gestionado(c) -> bool:
    """Si el caso muestra trabajo real, no sólo existir.

    Cuenta como gestionado si salió de `open` —alguien lo movió— o si tiene
    notas. Un caso `open` sin una sola nota es, hasta donde la herramienta
    sabe, un caso que nadie tocó.

    NO alcanza con estar asignado: asignar es repartir, no gestionar. Esa
    distinción es justamente lo que el informe tiene que poder mostrar.
    """
    if (c.get("status") or "").strip().lower() != "open":
        return True
    return int(c.get("note_count") or 0) > 0


def dias_de_cierre(c):
    """Días entre que se creó y se cerró, o None si no aplica."""
    if not esta_cerrado(c):
        return None
    ini, fin = a_fecha(c.get("created_at")), a_fecha(c.get("closed_at"))
    if not ini or not fin or fin < ini:
        return None
    return (fin - ini).total_seconds() / 86400


def dias_abierto(c, ahora=None):
    ini = a_fecha(c.get("created_at"))
    if not ini:
        return None
    return ((ahora or dt.datetime.utcnow()) - ini).total_seconds() / 86400


def _pct(parte, total):
    return round(100.0 * parte / total, 1) if total else 0.0


def indicadores(casos, ahora=None) -> dict:
    """Los números de un grupo de casos: un equipo, un analista o el total."""
    total = len(casos)
    cerrados = [c for c in casos if esta_cerrado(c)]
    abiertos = [c for c in casos if not esta_cerrado(c)]
    gestionados = [c for c in casos if fue_gestionado(c)]
    sin_tocar = [c for c in abiertos if not fue_gestionado(c)]

    tiempos = [d for d in (dias_de_cierre(c) for c in cerrados) if d is not None]
    edades = [d for d in (dias_abierto(c, ahora) for c in abiertos) if d is not None]
    vencidos = [c for c in abiertos if c.get("sla_estado") == "vencido"]
    con_plazo = [c for c in abiertos if c.get("sla_aplica")]

    return {
        "total": total,
        "abiertos": len(abiertos),
        "cerrados": len(cerrados),
        "gestionados": len(gestionados),
        "sin_tocar": len(sin_tocar),
        "pct_gestionados": _pct(len(gestionados), total),
        "pct_cerrados": _pct(len(cerrados), total),
        # La mediana va al lado del promedio y no en su lugar: con un caso de
        # 61 días entre 16, el promedio dice 16 y la mediana dice otra cosa.
        # Mostrar sólo uno de los dos deja pensar que todos tardan lo mismo.
        "cierre_promedio": round(statistics.fmean(tiempos), 1) if tiempos else None,
        "cierre_mediana": round(statistics.median(tiempos), 1) if tiempos else None,
        "cierre_max": round(max(tiempos), 1) if tiempos else None,
        "edad_promedio_abiertos": round(statistics.fmean(edades), 1) if edades else None,
        "mas_viejo_abierto": round(max(edades), 1) if edades else None,
        "vencidos": len(vencidos),
        "pct_vencidos": _pct(len(vencidos), len(con_plazo)),
    }


def por_analista(casos, equipos=None, ahora=None) -> list:
    """Un bloque por analista, del que más casos tiene al que menos."""
    equipos = equipos or {}
    grupos = {}
    for c in casos:
        grupos.setdefault(normalizar_analista(c.get("assigned_to")), []).append(c)
    salida = []
    for analista, suyos in grupos.items():
        salida.append({
            "analista": analista,
            "equipo": equipos.get(analista, SIN_EQUIPO),
            **indicadores(suyos, ahora),
        })
    salida.sort(key=lambda x: (-x["total"], x["analista"]))
    return salida


def por_equipo(casos, equipos=None, ahora=None) -> list:
    """Un bloque por equipo, con sus analistas adentro.

    Los casos sin asignar quedan en su propio grupo y no se reparten: no son de
    nadie, y esconderlos dentro de un equipo haría desaparecer justo lo que hay
    que ver.
    """
    equipos = equipos or {}
    grupos = {}
    for c in casos:
        a = normalizar_analista(c.get("assigned_to"))
        equipo = SIN_ASIGNAR if a == SIN_ASIGNAR else equipos.get(a, SIN_EQUIPO)
        grupos.setdefault(equipo, []).append(c)

    salida = []
    for equipo, suyos in grupos.items():
        salida.append({
            "equipo": equipo,
            **indicadores(suyos, ahora),
            "analistas": por_analista(suyos, equipos, ahora),
        })
    # Los sin asignar van último: es una alerta, no un equipo.
    salida.sort(key=lambda x: (x["equipo"] == SIN_ASIGNAR, -x["total"], x["equipo"]))
    return salida


def filtrar(casos, desde="", hasta="", analista="", equipo="", equipos=None) -> list:
    """El recorte que pidió quien genera el informe.

    `desde`/`hasta` miran la fecha de CREACIÓN del caso. Es la que corresponde
    para "cuántos casos entraron en septiembre"; para medir cierres del mes hay
    que mirar otra cosa, y eso se dice en el PDF para que nadie lo confunda.
    """
    equipos = equipos or {}
    fuera = []
    for c in casos:
        creado = str(c.get("created_at") or "")
        if desde and creado[:10] < desde[:10]:
            continue
        if hasta and creado[:10] > hasta[:10]:
            continue
        a = normalizar_analista(c.get("assigned_to"))
        if analista and a != normalizar_analista(analista):
            continue
        if equipo:
            suyo = SIN_ASIGNAR if a == SIN_ASIGNAR else equipos.get(a, SIN_EQUIPO)
            if suyo != equipo:
                continue
        fuera.append(c)
    return fuera


def armar(casos, equipos=None, desde="", hasta="", analista="", equipo="",
          ahora=None) -> dict:
    """Todo lo que el PDF necesita, ya calculado."""
    sel = filtrar(casos, desde, hasta, analista, equipo, equipos)
    return {
        "filtro": {"desde": desde, "hasta": hasta, "analista": analista,
                   "equipo": equipo},
        "total_general": indicadores(sel, ahora),
        "equipos": por_equipo(sel, equipos, ahora),
        "analistas": por_analista(sel, equipos, ahora),
        "casos": sel,
    }
