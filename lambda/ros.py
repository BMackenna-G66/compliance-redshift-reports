# -*- coding: utf-8 -*-
"""El registro de Reportes de Operación Sospechosa.

QUÉ ES UN ROS ACÁ. Cuando una investigación concluye que hay sospecha de
lavado, se reporta a la unidad de inteligencia financiera del país. Este
módulo NO reporta: lleva el registro de qué se decidió reportar, sobre quién,
con qué evidencia y en qué estado está. El envío al regulador es manual, por
sus canales, fuera del sistema.

LO QUE EL SISTEMA ARMA Y LO QUE ESCRIBE UNA PERSONA — la distinción que
ordena todo este archivo:

  · El sistema arma los HECHOS: quién es el sujeto, qué alertas lo marcaron,
    qué banderas se activaron, en qué período, por cuánto. Eso ya está en el
    caso y en sus alertas, y copiarlo a mano es cómo se cometen errores.

  · Una persona escribe la NARRATIVA: por qué esto es sospechoso. Un ROS es
    una afirmación legal firmada por el oficial de cumplimiento. El sistema
    no la redacta ni la sugiere, porque un texto generado que alguien firma
    sin leer es exactamente el accidente que hay que evitar.

SIN PLAZOS, POR AHORA. Se decidió no llevar cuenta regresiva: los plazos
legales difieren por país y no estaban definidos al construir esto. El
modelo deja el lugar —`vence_at` viaja vacío— para que agregarlos después no
obligue a rehacer nada.

EL SERVICIO EXTERNO. Va a haber uno que reciba el envío. Hasta que exista,
`origen` dice de dónde salió cada ROS y `externo_id` queda vacío: cuando se
conecte, los que vengan de allá se distinguen de los de acá sin migrar nada.
"""
import datetime as dt
import re

# ── Los reguladores ────────────────────────────────────────────────────────
# Sólo los tres donde se reporta de verdad. El prototipo dibujaba cinco
# —sumaba México y Brasil— pero eso era relleno del diseño.
REGULADORES = {
    "UIF-AR":  {"nombre": "UIF", "pais": "Argentina",
                "completo": "Unidad de Información Financiera"},
    "UAF-CL":  {"nombre": "UAF", "pais": "Chile",
                "completo": "Unidad de Análisis Financiero"},
    "UIAF-CO": {"nombre": "UIAF", "pais": "Colombia",
                "completo": "Unidad de Información y Análisis Financiero"},
}

# ── Los estados ────────────────────────────────────────────────────────────
# Un ROS no se "edita y listo": pasa por revisión antes de salir, porque lo
# firma el oficial de cumplimiento y compromete a la empresa.
#
# `descartado` está a propósito: decidir que algo NO se reporta es una
# decisión de compliance tan registrable como decidir que sí, y si no tuviera
# dónde anotarse, el caso simplemente desaparecería del registro sin rastro.
ESTADOS = {
    "borrador":       "Se está armando. Todavía no salió de quien lo escribe.",
    "revision_legal": "En revisión antes de enviarlo.",
    "enviado":        "Reportado al regulador.",
    "descartado":     "Se evaluó y se decidió no reportar.",
}

# De dónde se puede pasar a dónde. Un ROS enviado no vuelve a borrador: ya
# salió, y fingir que no sería falsear el registro. Para corregir uno enviado
# se emite otro; así funciona con los reguladores.
TRANSICIONES = {
    "borrador":       ["revision_legal", "descartado"],
    "revision_legal": ["borrador", "enviado", "descartado"],
    "enviado":        [],
    "descartado":     ["borrador"],
}

TERMINALES = ("enviado",)

FORMATO = "%Y-%m-%d %H:%M:%S"
RE_FOLIO = re.compile(r"^ROS-(\d{4})-(\d{4})$")


def ahora():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _texto(v):
    return str(v or "").strip()


# ── El folio ───────────────────────────────────────────────────────────────

def siguiente_folio(folios_existentes, momento=None):
    """El folio correlativo del año: `ROS-2026-0001`.

    Correlativo y no un identificador aleatorio porque un registro
    regulatorio se cita por número, y «ROS-2026-0007» se dicta por teléfono;
    un uuid, no.

    OJO CON LA CARRERA: dos ROS creados en el mismo instante podrían pedir el
    mismo número. El volumen real es de unos pocos por mes, así que la
    ventana es despreciable, pero quien llame a esto debe verificar que el
    folio no exista antes de guardar —`crear()` lo hace— en vez de confiar.
    """
    anio = (momento or ahora()).year
    usados = set()
    for f in folios_existentes or []:
        m = RE_FOLIO.match(_texto(f))
        if m and int(m.group(1)) == anio:
            usados.add(int(m.group(2)))
    n = 1
    while n in usados:
        n += 1
    return f"ROS-{anio}-{n:04d}"


# ── La evidencia ───────────────────────────────────────────────────────────

# Los campos que NO son un monto movido aunque digan «usd»: promedios,
# máximos y ratios. Un ROS lista lo que el cliente movió; poner «USD 9,15» de
# ticket promedio al lado de «USD 704» de total, en una lista titulada
# «montos», invita a leerlos como cosas del mismo orden — y esto va en un
# documento que lee un regulador. El promedio sigue estando en la alerta,
# que es donde tiene sentido.
_NO_SON_MONTO = ("avg", "promedio", "max_", "min_", "ratio", "_vs_")


def _es_monto(clave: str) -> bool:
    c = str(clave or "").lower()
    if "usd" not in c:
        return False
    return not any(p in c for p in _NO_SON_MONTO)


def evidencia_de(caso, alertas, filas_de_alerta=None):
    """Los hechos del caso, listos para el reporte.

    `filas_de_alerta` es una función que devuelve el `row_data` ya parseado de
    una alerta; se inyecta para que este módulo no sepa de S3 ni de JSON y se
    pueda probar con diccionarios.

    LOS MONTOS NO SE SUMAN ENTRE REPORTES DISTINTOS. Cada reporte mide una
    cosa —lo girado en 7 días, el acumulado de depósitos chicos— y sumarlos
    daría un total que no significa nada y que terminaría escrito en un
    documento legal. Se listan por separado, con el nombre del campo.
    """
    leer = filas_de_alerta or (lambda a: a.get("row_data") if isinstance(a.get("row_data"), dict) else {})
    als = list(alertas or [])

    fechas = sorted(_texto(a.get("created_at")) for a in als if _texto(a.get("created_at")))
    montos = []
    for a in als:
        fila = leer(a) or {}
        for clave, valor in fila.items():
            if _es_monto(clave) and valor not in (None, "", 0, "0"):
                montos.append({"alerta": a.get("alert_id", ""), "campo": clave,
                               "valor": str(valor)})

    return {
        "sujeto": {
            "entity_id": _texto(caso.get("entity_id")),
            "entity_name": _texto(caso.get("entity_name")),
            "entity_type": _texto(caso.get("entity_type")),
        },
        "caso": {
            "case_id": _texto(caso.get("case_id")),
            "titulo": _texto(caso.get("title")),
            "creado_at": _texto(caso.get("created_at")),
            "report_name": _texto(caso.get("report_name")),
        },
        "alertas": [
            {"alert_id": a.get("alert_id", ""),
             "motivo": _texto(a.get("reason")),
             "report_name": _texto(a.get("report_name")),
             "created_at": _texto(a.get("created_at"))}
            for a in als
        ],
        "periodo": {"desde": fechas[0] if fechas else "", "hasta": fechas[-1] if fechas else ""},
        "n_alertas": len(als),
        "montos": montos,
    }


# ── Crear y mover ──────────────────────────────────────────────────────────

def validar_creacion(datos, folios_existentes=None):
    """Qué falta para poder crear el ROS. Lista vacía = está bien.

    Se valida acá y no en la pantalla porque el mismo control tiene que valer
    cuando el ROS entre por la API externa.
    """
    faltan = []
    if not _texto(datos.get("case_id")):
        faltan.append("el caso del que sale el reporte")
    if _texto(datos.get("regulador")) not in REGULADORES:
        faltan.append("a qué regulador se reporta (%s)" % ", ".join(REGULADORES))
    if not _texto(datos.get("creado_por")):
        faltan.append("quién lo crea: un registro regulatorio sin autor no sirve")
    folio = _texto(datos.get("folio"))
    if folio and folio in set(folios_existentes or []):
        faltan.append(f"el folio {folio} ya existe")
    return faltan


def crear(datos, caso, alertas, folios_existentes=None, momento=None, leer_fila=None):
    """Arma un ROS en borrador con la evidencia del caso."""
    falta = validar_creacion(datos, folios_existentes)
    if falta:
        raise ValueError("; ".join(falta))

    t = (momento or ahora()).strftime(FORMATO)
    return {
        "folio": _texto(datos.get("folio")) or siguiente_folio(folios_existentes, momento),
        "case_id": _texto(datos.get("case_id")),
        "regulador": _texto(datos.get("regulador")),
        "estado": "borrador",
        # La narrativa la escribe una persona. El sistema no la redacta: un
        # ROS es una afirmación legal firmada, y un texto generado que alguien
        # firma sin leer es el accidente que hay que evitar.
        "narrativa": _texto(datos.get("narrativa")),
        "tipologia": _texto(datos.get("tipologia")),
        "evidencia": evidencia_de(caso, alertas, leer_fila),
        # El lugar del plazo, vacío a propósito: se decidió no llevar cuenta
        # regresiva por ahora, y dejarlo acá evita rehacer el modelo después.
        "vence_at": "",
        # Para cuando exista el servicio externo: los que vengan de allá se
        # van a distinguir de los de acá sin migrar nada.
        "origen": _texto(datos.get("origen")) or "watchtower",
        "externo_id": "",
        "creado_por": _texto(datos.get("creado_por")),
        "creado_at": t,
        "actualizado_at": t,
        "enviado_at": "",
        "historial": [{"estado": "borrador", "quien": _texto(datos.get("creado_por")),
                       "cuando": t, "nota": ""}],
    }


def puede_pasar(desde, hasta):
    return hasta in TRANSICIONES.get(_texto(desde), [])


def cambiar_estado(reporte, nuevo, quien, nota="", momento=None):
    """Mueve el ROS de estado, dejando rastro.

    El historial no se puede desactivar: es un registro regulatorio y quién
    lo movió, cuándo y por qué es justamente lo que se audita.
    """
    actual = _texto(reporte.get("estado"))
    nuevo = _texto(nuevo)
    if nuevo not in ESTADOS:
        raise ValueError(f"estado desconocido: {nuevo!r}")
    if not _texto(quien):
        raise ValueError("falta quién hace el cambio")
    if not puede_pasar(actual, nuevo):
        posibles = TRANSICIONES.get(actual, [])
        raise ValueError(
            f"no se puede pasar de {actual!r} a {nuevo!r}"
            + (f"; desde {actual!r} sólo se puede ir a {posibles}" if posibles
               else f"; {actual!r} es un estado final"))

    # Un ROS enviado necesita su narrativa: es lo que se reporta. Dejar salir
    # uno vacío sería registrar como reportado algo que no dice nada.
    if nuevo == "enviado" and not _texto(reporte.get("narrativa")):
        raise ValueError("no se puede marcar como enviado un reporte sin narrativa")

    t = (momento or ahora()).strftime(FORMATO)
    salida = dict(reporte)
    salida["estado"] = nuevo
    salida["actualizado_at"] = t
    if nuevo == "enviado":
        salida["enviado_at"] = t
    salida["historial"] = list(reporte.get("historial") or []) + [
        {"estado": nuevo, "quien": _texto(quien), "cuando": t, "nota": _texto(nota)}
    ]
    return salida


def editable(reporte):
    """Un ROS enviado no se edita. Ya salió."""
    return _texto(reporte.get("estado")) not in TERMINALES


# ── Resumen ────────────────────────────────────────────────────────────────

def indicadores(reportes):
    r = list(reportes or [])
    por_estado = {e: 0 for e in ESTADOS}
    for x in r:
        e = _texto(x.get("estado"))
        if e in por_estado:
            por_estado[e] += 1
    return {
        "total": len(r),
        "por_estado": por_estado,
        # «En curso» es lo que todavía requiere trabajo: ni enviado ni
        # descartado. Es el número que dice cuánto queda por hacer.
        "en_curso": por_estado["borrador"] + por_estado["revision_legal"],
        "por_regulador": {
            k: sum(1 for x in r if _texto(x.get("regulador")) == k) for k in REGULADORES
        },
    }
