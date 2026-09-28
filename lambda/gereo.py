# -*- coding: utf-8 -*-
"""Cliente de la API de GEREO, que genera el borrador del ROS.

QUÉ HACE GEREO Y QUÉ NO. Le pasás un cliente y un período y devuelve el
reporte armado: datos, señales de alerta y una narrativa. **Es un borrador.**
No se presenta a ningún regulador, y varios campos vienen vacíos a propósito
porque dependen del criterio de un analista. Que la respuesta diga `OK`
significa que el análisis corrió, no que el reporte esté listo.

Por eso este módulo no decide nada: trae el borrador y lo deja en manos de
quien firma. `ros.py` dice, sobre la narrativa, que «un texto generado que
alguien firma sin leer es exactamente el accidente que hay que evitar»; eso
sigue valiendo, y por eso el texto de GEREO nunca se escribe solo en el
campo que firma el oficial.

═══════════════════════════════════════════════════════════════════════════
LAS TRES COSAS QUE SE HACEN DISTINTO Y NO SON CAPRICHO
═══════════════════════════════════════════════════════════════════════════

1. **La matriz por país se valida ACÁ, antes de salir a la red.** Argentina
   no admite B2B ni clientes asociados; Colombia no admite asociados; Chile
   sí, hasta 15. GEREO lo rechaza con 422 igual, pero pegarle a la base de
   datos de producción para que nos diga algo que ya sabíamos es gastar el
   backend que atiende a sus analistas.

2. **`es_detencion` NO es un error.** Si el cliente existe pero su país de
   origen no es el del reporte, GEREO responde 200 con `es_detencion: true`.
   Es la regla de negocio funcionando —un cliente peruano no se reporta a la
   UAF de Chile—, así que se devuelve como resultado propio y no se
   reintenta: reintentar da exactamente lo mismo.

3. **Sólo el 503 se reintenta.** Un 404 (el cliente no existe) y un 422 (el
   cuerpo está mal) no mejoran insistiendo; tratarlos igual que un problema
   pasajero esconde el error real detrás de tres reintentos.

LO QUE NO SE LOGUEA. La respuesta trae nombre, documento, dirección, correo y
teléfono de personas reales más el detalle de sus operaciones. Un `print` del
response completo termina en un log de CloudWatch que vive años. Acá se
loguea el CÓDIGO y el ESTADO, nunca el cuerpo.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("GEREO_URL", "https://gereo.global66.com").rstrip("/")
SECRETO = os.environ.get("GEREO_SECRET_NAME",
                         "compliance-redshift-reports/gereo-api-key")

# El doc pide 60 s o más: un ROS consulta la base, evalúa reglas y redacta.
TIMEOUT_ROS = 90
TIMEOUT_SALUD = 15

# Qué admite cada país. Sale de la tabla del documento de integración.
PAISES = {
    "Argentina": {"tipos": ("B2C",), "asociados": 0,
                  "regulador": "UIF-AR"},
    "Chile":     {"tipos": ("B2C", "B2B"), "asociados": 15,
                  "regulador": "UAF-CL"},
    "Colombia":  {"tipos": ("B2C", "B2B"), "asociados": 0,
                  "regulador": "UIAF-CO"},
}

# El mismo mapa al revés, para partir del regulador que ya usa `ros.py`.
PAIS_POR_REGULADOR = {v["regulador"]: k for k, v in PAISES.items()}

# `natural`/`juridica` también se aceptan del lado de GEREO; se normaliza acá
# para que la pantalla no tenga que saberlo.
TIPOS = {"b2c": "B2C", "natural": "B2C", "b2b": "B2B", "juridica": "B2B"}

_clave_cache: str | None = None


class ErrorGereo(Exception):
    """Algo salió mal del lado de GEREO o del pedido.

    `reintentable` es lo único que quien llama necesita para decidir: el
    documento es explícito en que sólo el 503 mejora insistiendo.
    """

    def __init__(self, mensaje, codigo=0, campo="", reintentable=False):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.campo = campo
        self.reintentable = reintentable

    def como_dict(self):
        return {"error": self.mensaje, "codigo": self.codigo,
                "campo": self.campo, "reintentable": self.reintentable}


def clave(cliente_secrets=None) -> str:
    """La clave, de Secrets Manager. Nunca del código.

    El repo es público: una clave escrita acá habría que rotarla el mismo día
    y la integración se corta. Se cachea por contenedor, igual que la de
    Gmail; si se rota, entra cuando Lambda recicle.
    """
    global _clave_cache
    if _clave_cache:
        return _clave_cache
    valor = ""
    try:
        import boto3
        sm = cliente_secrets or boto3.client("secretsmanager")
        valor = (sm.get_secret_value(SecretId=SECRETO)["SecretString"] or "").strip()
    except Exception as e:                                       # noqa: BLE001
        print(f"[gereo] no pude leer el secreto {SECRETO}: {type(e).__name__}")
    if not valor:
        valor = (os.environ.get("GEREO_API_KEY") or "").strip()
    _clave_cache = valor
    return valor


# ── Validación previa ────────────────────────────────────────────────────

def normalizar_tipo(v) -> str:
    return TIPOS.get(str(v or "").strip().lower(), "")


def validar(pedido: dict) -> list:
    """Qué está mal en el pedido. Lista vacía = se puede mandar.

    Se valida contra la matriz del país ANTES de la llamada: GEREO lo
    rechazaría igual, pero con un viaje a su base de datos de por medio.
    """
    faltan = []
    pais = str(pedido.get("pais") or "").strip()
    if pais not in PAISES:
        return [f"país inválido: {pais!r}. Los que hay son "
                + ", ".join(PAISES)]
    reglas = PAISES[pais]

    if not str(pedido.get("customer_id") or "").strip():
        faltan.append("falta el customer_id del cliente reportado")

    tipo = normalizar_tipo(pedido.get("tipo_cliente"))
    if not tipo:
        faltan.append("tipo_cliente tiene que ser B2C o B2B")
    elif tipo not in reglas["tipos"]:
        faltan.append(
            f"el ROS de {pais} sólo cubre {' y '.join(reglas['tipos'])}: "
            f"no admite {tipo}")

    asociados = pedido.get("clientes_asociados") or []
    if isinstance(asociados, str):
        asociados = [x.strip() for x in asociados.split(",") if x.strip()]
    if asociados and reglas["asociados"] == 0:
        faltan.append(f"el ROS de {pais} se emite por un único cliente: "
                      "no admite clientes asociados")
    elif len(asociados) > reglas["asociados"]:
        faltan.append(f"{pais} admite hasta {reglas['asociados']} clientes "
                      f"asociados y mandaste {len(asociados)}")

    for campo in ("fecha_inicio", "fecha_fin"):
        v = str(pedido.get(campo) or "").strip()
        if campo == "fecha_inicio" and not v:
            faltan.append("falta fecha_inicio (mm/aaaa)")
        elif v and not _mes_valido(v):
            faltan.append(f"{campo} tiene que ser mm/aaaa, llegó {v!r}")

    return faltan


def _mes_valido(v: str) -> bool:
    partes = str(v).split("/")
    if len(partes) != 2:
        return False
    mes, anio = partes
    return (mes.isdigit() and anio.isdigit()
            and 1 <= int(mes) <= 12 and len(anio) == 4)


def cuerpo_para(pedido: dict) -> dict:
    """El JSON que espera GEREO, con lo nuestro normalizado."""
    asociados = pedido.get("clientes_asociados") or []
    if isinstance(asociados, str):
        asociados = [x.strip() for x in asociados.split(",") if x.strip()]
    cuerpo = {
        "pais": str(pedido.get("pais") or "").strip(),
        "customer_id": str(pedido.get("customer_id") or "").strip(),
        "tipo_cliente": normalizar_tipo(pedido.get("tipo_cliente")),
        "fecha_inicio": str(pedido.get("fecha_inicio") or "").strip(),
    }
    if asociados:
        cuerpo["clientes_asociados"] = [str(x).strip() for x in asociados]
    fin = str(pedido.get("fecha_fin") or "").strip()
    if fin:
        cuerpo["fecha_fin"] = fin
    # Sólo si se va a usar: armar el PDF le suma segundos a cada llamada.
    if pedido.get("incluir_pdf"):
        cuerpo["incluir_pdf"] = True
    return cuerpo


# ── Las llamadas ─────────────────────────────────────────────────────────

def _pedir(ruta: str, cuerpo=None, timeout=TIMEOUT_SALUD, abrir=None):
    k = clave()
    if not k:
        raise ErrorGereo("No hay clave de GEREO configurada "
                         f"(secreto {SECRETO}).", codigo=0)
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(
        BASE + ruta, data=datos,
        headers={"X-API-Key": k, "Content-Type": "application/json"},
        method="POST" if datos else "GET")
    abrir = abrir or urllib.request.urlopen
    try:
        with abrir(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        crudo = e.read().decode("utf-8", "replace")
        try:
            d = json.loads(crudo)
        except Exception:                                        # noqa: BLE001
            d = {}
        # Se loguea el código, nunca el cuerpo: trae datos de personas.
        print(f"[gereo] {ruta} respondió {e.code}")
        raise _traducir(e.code, d) from e
    except Exception as e:                                       # noqa: BLE001
        print(f"[gereo] {ruta} falló: {type(e).__name__}")
        raise ErrorGereo(f"No se pudo hablar con GEREO: {type(e).__name__}",
                         codigo=0, reintentable=True) from e


def _traducir(codigo: int, d: dict) -> ErrorGereo:
    """El código HTTP, en algo que se pueda mostrar y sobre lo que decidir.

    Los mensajes distinguen a propósito «corregí el pedido» de «revisá el
    dato»: el documento insiste en que 422 y 404 no se traten igual.
    """
    mensaje = str(d.get("mensaje") or d.get("error") or "").strip()
    campo = str(d.get("campo") or "")
    if codigo == 401:
        return ErrorGereo(
            "GEREO no aceptó la clave. Puede estar revocada o rotada: "
            "avisale a Compliance.", 401)
    if codigo == 404:
        return ErrorGereo(
            mensaje or "Ese cliente no existe en la base de GEREO. "
                       "Revisá el identificador; reintentar no cambia nada.",
            404)
    if codigo == 422:
        return ErrorGereo(
            mensaje or "GEREO rechazó una opción que ese país no admite.",
            422, campo=campo)
    if codigo == 400:
        return ErrorGereo(mensaje or "El rango de fechas no es válido.", 400)
    if codigo == 503:
        return ErrorGereo(
            mensaje or "La fuente de datos de GEREO no está respondiendo. "
                       "Se puede reintentar más tarde.",
            503, reintentable=True)
    return ErrorGereo(mensaje or f"GEREO respondió {codigo}.", codigo)


def salud(abrir=None) -> dict:
    """¿La clave sirve y para qué países hay ROS hoy?

    Sirve de healthcheck de la integración: si empieza a dar 401, nos
    revocaron o rotaron la clave.
    """
    return _pedir("/api/v1/salud", timeout=TIMEOUT_SALUD, abrir=abrir)


def generar_ros(pedido: dict, abrir=None) -> dict:
    """El borrador del ROS. Tarda decenas de segundos.

    Devuelve siempre un dict con `detenido` explícito, para que quien llame
    no tenga que acordarse de mirar `es_detencion`.
    """
    faltan = validar(pedido)
    if faltan:
        raise ErrorGereo("; ".join(faltan), 422)

    d = _pedir("/api/v1/ros", cuerpo_para(pedido), timeout=TIMEOUT_ROS,
               abrir=abrir)

    if d.get("es_detencion"):
        # 200, pero no hay reporte. No es una falla y no se reintenta.
        print(f"[gereo] detenido: {d.get('estado')}")
        return {"detenido": True, "estado": d.get("estado", ""),
                "mensaje": d.get("mensaje", ""), "opciones": d.get("opciones", {})}

    doc = d.get("ros_doc") or {}
    return {
        "detenido": False,
        "estado": d.get("estado", ""),
        # El eco de lo que GEREO realmente usó, incluido el mes de término que
        # resuelve solo. Es el registro de con qué parámetros se emitió.
        "opciones": d.get("opciones", {}),
        "ros_doc": doc,
        # Sólo las gatilladas. Las evaluadas están en `ros_doc.reglas`.
        "senales": d.get("senales") or [],
        # Lo que quedó pendiente de criterio humano. Es lo primero que tiene
        # que ver el analista, no una nota al pie.
        "advertencias": (doc.get("meta") or {}).get("advertencias") or [],
        "pdf_base64": d.get("pdf_base64"),
    }
