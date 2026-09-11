"""El correo al cliente: §8 de docs/MIGRACION_A_WATCHTOWER.md.

**No hay plantilla fija de RFI.** El contenido se adapta a lo que pide cada
partner, que es justamente lo que el motor extrae y traduce. Lo que se replica
de WatchTower es el formato/layout; lo que lo llena es la estructura extraída.

**La lista blanca no se negocia.** El resumen se compone de ítems del catálogo
—texto en español ya escrito, no generado— y de datos de la operación. Nunca de
texto libre. Un requerimiento inventado que el partner no pidió es un incidente
de compliance, no un typo. Lo que el motor no pudo mapear al catálogo se marca
aparte, en crudo, para que alguien lo redacte a mano: hoy 60 de 89 casos
accionables tienen lista concreta y los otros 27 son el bucle de mejora.

**Sin formulario PDF adjunto**: esto no es una solicitud KYC.

El token del asunto es `rfi:` y NO `ref:` (§13.19). El poller AML de WatchTower
busca `SUBJECT "ref:"`; si acá se usara el mismo prefijo, ese poller encontraría
respuestas de RFI, no las matchearía con ningún caso AML, y las marcaría leídas.
"""
import html as _html
import re
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

PREFIJO_TOKEN = "rfi"
REMITENTE_POR_DEFECTO = "compliance@global66.com"

# Campos de la operación que se le muestran al cliente, para que sepa de qué
# se le habla. Se eligen a dedo: nada de volcar la fila completa.
_CAMPOS_OPERACION = [
    ("tx_monto", "Monto"),
    ("tx_moneda", "Moneda"),
    ("tx_fecha", "Fecha"),
    ("tx_beneficiario", "Beneficiario"),
    ("tx_remitente", "Remitente"),
    ("tx_id", "N° de operación"),
]


def token_nuevo():
    return uuid.uuid4().hex[:8]


def asunto_de(token):
    return f"Solicitud de información — Global66 [{PREFIJO_TOKEN}: {token}]"


def _plano(v):
    """Desenvuelve los valores que el motor entrega como {es, valor}.

    Sin esto un diccionario se imprime tal cual en el cuerpo del correo —
    verificado: el beneficiario salía como
    {'es': 'Beneficiario', 'valor': 'AGUSTIN...'} en un correo real.
    """
    if isinstance(v, dict):
        for k in ("valor", "value", "texto", "es"):
            if v.get(k) not in (None, ""):
                return v[k]
        return ""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(_plano(x)) for x in v if _plano(x) != "")
    return v


def _fecha_corta(v):
    """'2026-06-05 20:54:47' → '2026-06-05'. Al cliente no le sirve la hora."""
    s = str(_plano(v) or "").strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T]", s)
    return m.group(1) if m else s


def _e(v):
    return _html.escape(str(_plano(v) or "").strip())


def _items_del_caso(caso):
    """(del_catalogo, en_crudo). Sólo el primero va como lista numerada.

    **`resumen` NO entra acá, y ese era un defecto grave.** Antes, cuando no
    se mapeaba ningún ítem, se promovía `caso["resumen"]` al cuerpo del
    correo. Pero `resumen` no es una cita del partner: es una frase de
    diagnóstico que `requerimiento.py` escribe **para el analista**. Medido
    sobre casos reales que estaban a un clic de salir:

        «OZ Câmbio abrió un requerimiento de 14844610 y no se pudo extraer
         qué pide. Hay que leer el correo.»
        «dLocal revisó la documentación y dice que necesita corrección. Hay
         que volver a pedirle al cliente lo que rechazaron…»

    Eso le habría llegado a un cliente, bajo el título "Necesitamos la
    siguiente información". Es estado interno filtrado hacia afuera y un
    incidente de compliance, no un typo.

    **`no_reconocido` tampoco va al correo, y eso corrige un arreglo mío
    anterior.** Al sacar `resumen` lo reemplacé por `no_reconocido` —las
    líneas del pedido del partner que no matchearon el catálogo— razonando
    que al menos eran texto suyo. Medido sobre los cuatro casos reales que
    quedaban así, es basura:

        «Ma. Carla D. Alarde»                     ← firma de una analista de Currencycloud
        «Zendesk App Integration, 6 Sept 2026»    ← metadata del cliente de correo
        «[KKJL2N-9ZN3M]»                          ← código de ticket
        «body[dir=rt»                             ← CSS suelto
        «If you require more time, please…»       ← boilerplate

    Mandarle eso a un cliente bajo el título "Necesitamos la siguiente
    información" es peor que no mandarle nada. Y el módulo ya tenía la regla
    escrita en §8: el pedido se compone de ítems del catálogo, **nunca de
    texto libre**. `no_reconocido` es texto libre.

    Así que se devuelve —la pantalla lo muestra para que el analista vea qué
    escribió el partner y redacte el pedido a mano— pero **el cuerpo del
    correo sólo usa el catálogo**. Un caso sin ítems del catálogo no se envía:
    lo redacta una persona y lo manda con `revisado=true`.
    """
    catalogo, crudo = [], []
    for it in (caso.get("items") or []):
        if isinstance(it, dict):
            texto = (it.get("es") or "").strip()
            if texto:
                catalogo.append(texto)
            elif it.get("crudo") or it.get("texto"):
                crudo.append(str(it.get("crudo") or it.get("texto")).strip())
        elif isinstance(it, str) and it.strip():
            catalogo.append(it.strip())
    if not catalogo:
        for linea in (caso.get("no_reconocido") or []):
            t = str(linea).strip()
            if t and t not in crudo:
                crudo.append(t)
    return catalogo, crudo


def _datos_operacion(caso):
    """Datos de la operación, para que el cliente sepa de qué se le habla.

    Dos fuentes, en orden. Primero lo que resolvió Redshift, que vive plano en
    `caso["cliente"]` y es autoritativo: son nuestros propios registros.
    Después lo que el motor extrajo del correo del partner, que está en
    `transaccion["datos"]` con otros nombres y sirve cuando la resolución no
    llegó a traer la transacción.
    """
    fuente = {}
    cl = caso.get("cliente") or {}
    if isinstance(cl, dict):
        fuente.update({k: v for k, v in cl.items() if v not in (None, "", [])})
        interno = cl.get("cliente")
        if isinstance(interno, dict):
            fuente.update({k: v for k, v in interno.items() if v not in (None, "", [])})

    # Lo extraído del correo del partner, con los nombres que usa el motor.
    for t in (caso.get("transacciones") or []):
        d = t.get("datos")
        if not isinstance(d, dict):
            continue
        for origen, destino in (("monto", "tx_monto"), ("moneda", "tx_moneda"),
                                ("fecha_tx", "tx_fecha"), ("beneficiario", "tx_beneficiario"),
                                ("remitente", "tx_remitente")):
            if d.get(origen) and not fuente.get(destino):
                fuente[destino] = d[origen]
        if t.get("valor") and not fuente.get("tx_id"):
            fuente["tx_id"] = t["valor"]

    salida = []
    for campo, etq in _CAMPOS_OPERACION:
        v = _plano(fuente.get(campo))
        if v in (None, "", []):
            continue
        salida.append((etq, _fecha_corta(v) if campo == "tx_fecha" else v))
    return salida


def destinatario(caso):
    """Correo del cliente, o "" si el caso no llegó a resolverlo."""
    cl = caso.get("cliente") or {}
    d = cl.get("cliente") if isinstance(cl.get("cliente"), dict) else cl
    return str((d or {}).get("cliente_correo") or "").strip()


def nombre_cliente(caso):
    cl = caso.get("cliente") or {}
    d = cl.get("cliente") if isinstance(cl.get("cliente"), dict) else cl
    return str((d or {}).get("cliente_nombre") or "").strip()


# Sufijos y palabras que delatan una razón social. Medido sobre los casos
# resueltos: 15 de 159 (9%) son empresas — POWERLAND LLC, BLESS CORP SPA,
# Nataly Yepes Pinilla SAS. A todos ellos el correo les decía "Hola Fulano,
# una de TUS operaciones", que a una LLC se lee mal.
#
# **Por qué por el nombre y no por `is_company`.** El campo existe en
# `customer.customer` pero hoy no lo traemos: agregarlo obliga a tocar
# consultas.json y re-resolver los 170 casos. Esto es una heurística y se dice
# que lo es — va con un aviso en la previsualización para que quien manda lo
# vea y pueda desmentirlo. Errar hacia el trato formal es barato; errar hacia
# el tuteo con una sociedad no.
_EMPRESA = re.compile(
    r"(?i)(?:^|[\s,.])(?:s\.?p\.?a|s\.?a\.?s?|s\.?a\.?c|ltda?|limitada|e\.?i\.?r\.?l|"
    r"inc|llc|corp|corporation|company|cia|compa[ñn][ií]a|holding|group|trading|"
    r"import(?:adora|aciones)?|export(?:adora|aciones)?|comercial(?:izadora)?|"
    r"servicios|soluciones|tecnolog[ií]a)s?(?:[\s,.]|$)")


def es_empresa(nombre):
    """True si el nombre parece una razón social. Heurística, no verdad."""
    return bool(_EMPRESA.search(str(nombre or "")))


def _plazo(caso):
    """El plazo del correo del partner, si lo trajo. Es lo más específico (§7)."""
    p = caso.get("plazo")
    if isinstance(p, dict):
        return str(p.get("texto") or p.get("fecha") or "").strip()
    return str(p or "").strip()


def componer(caso, token=None, nota=""):
    """Devuelve {asunto, html, texto, token, para, avisos}.

    `avisos` lista lo que hay que mirar antes de mandar: sin correo, sin ítems
    mapeados, o pedido en crudo. La pantalla los muestra; no se bloquea acá el
    envío por un aviso, eso lo decide quien manda.
    """
    token = token or token_nuevo()
    catalogo, crudo = _items_del_caso(caso)
    datos = _datos_operacion(caso)
    para = destinatario(caso)
    nombre = nombre_cliente(caso)
    plazo = _plazo(caso)

    empresa = es_empresa(nombre)

    avisos = []
    if not para:
        avisos.append("El caso no tiene correo de cliente resuelto: no se puede enviar.")
    if not catalogo and not crudo:
        avisos.append("El partner no dejó un requerimiento identificable; hay que redactarlo a mano.")
    elif not catalogo:
        avisos.append("Ningún ítem se mapeó al catálogo. El correo NO se manda así: "
                      "hay que leer lo que escribió el partner y redactar el pedido "
                      "a mano.")
    if empresa:
        avisos.append(f"«{nombre}» parece una empresa, así que el correo trata de usted. "
                      "Es una deducción por el nombre: si es una persona, corregí el texto.")

    # Persona: la voz de siempre, sin tocar. Empresa: usted y plural.
    T = {
        "saludo": ("Estimados," if not nombre else f"Estimados de {nombre}:") if empresa
                  else ("Hola" + (" " + nombre if nombre else "") + ","),
        "intro": ("Estamos realizando una revisión de rutina sobre una de sus operaciones y "
                  "necesitamos algunos antecedentes para poder completarla.") if empresa else
                 ("Estamos realizando una revisión de rutina sobre una de tus operaciones y "
                  "necesitamos algunos antecedentes para poder completarla."),
        "pedimos": ("Para poder continuar necesitamos que nos envíen:" if empresa
                    else "Para poder continuar necesitamos que nos envíes:"),
        "responder": ("Les pedimos responder" if empresa else "Te pedimos responder"),
        "puede_responder": ("Pueden responder directamente a este correo adjuntando los "
                            "documentos.") if empresa else
                           ("Puedes responder directamente a este correo adjuntando los "
                            "documentos."),
        "mantener": ("<strong>Mantengan el asunto tal como está</strong>" if empresa
                     else "<strong>Mantén el asunto tal como está</strong>"),
        "pie": ("Este correo se envió porque tienen una operación en revisión. Si creen que "
                "es un error, respondan este mismo mensaje.") if empresa else
               ("Este correo se envió porque tenés una operación en revisión. Si creés que "
                "es un error, respondé este mismo mensaje."),
    }
    saludo = T["saludo"]

    filas_datos = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#666;font-size:14px">{_e(etq)}</td>'
        f'<td style="padding:6px 0;color:#111;font-size:14px"><strong>{_e(v)}</strong></td></tr>'
        for etq, v in datos)
    bloque_datos = (
        f'<p style="margin:0 0 8px;font-size:16px;color:#111">Se trata de esta operación:</p>'
        f'<table style="border-collapse:collapse;margin:0 0 20px">{filas_datos}</table>'
    ) if filas_datos else ""

    items_html = "".join(
        f'<li style="margin:0 0 8px;font-size:16px;color:#111">{_e(x)}</li>' for x in catalogo)
    bloque_items = (
        f'<p style="margin:0 0 8px;font-size:16px;color:#111">'
        f'{T["pedimos"]}</p>'
        f'<ol style="margin:0 0 20px;padding-left:22px">{items_html}</ol>'
    ) if items_html else ""

    # El crudo NO se compone en el cuerpo: ver _items_del_caso. Sin ítems del
    # catálogo no hay correo que mandar, y el envío está bloqueado aparte.
    bloque_crudo = ""

    bloque_plazo = (
        f'<p style="margin:0 0 20px;font-size:16px;color:#111">'
        f'{T["responder"]} <strong>{_e(plazo)}</strong>.</p>') if plazo else (
        f'<p style="margin:0 0 20px;font-size:16px;color:#111">'
        f'{T["responder"]} a la brevedad.</p>')

    bloque_nota = (f'<p style="margin:0 0 20px;font-size:16px;color:#111">{_e(nota)}</p>'
                   if nota else "")

    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:24px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
       style="background:#ffffff;border-radius:8px;overflow:hidden;font-family:Arial,Helvetica,sans-serif">
  <tr><td style="background:#f97316;padding:20px 32px">
    <span style="color:#ffffff;font-size:20px;font-weight:bold">Global66</span>
    <span style="color:#ffe8d5;font-size:14px;margin-left:8px">Compliance</span>
  </td></tr>
  <tr><td style="padding:32px">
    <p style="margin:0 0 16px;font-size:16px;color:#111">{_e(saludo)}</p>
    <p style="margin:0 0 20px;font-size:16px;color:#111">
      {_e(T["intro"])}
    </p>
    {bloque_datos}
    {bloque_items}
    {bloque_crudo}
    {bloque_plazo}
    {bloque_nota}
    <p style="margin:0 0 20px;font-size:14px;color:#666">
      {T["puede_responder"]}
      {T["mantener"]}: nos permite asociar la
      respuesta a la solicitud.
    </p>
    <p style="margin:0;font-size:14px;color:#666">Equipo de Compliance · Global66</p>
  </td></tr>
  <tr><td style="background:#fafafa;padding:16px 32px;border-top:1px solid #eee">
    <p style="margin:0;font-size:12px;color:#999">
      {T["pie"]}
    </p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

    lineas = [saludo, "", T["intro"], ""]
    if datos:
        lineas.append("Operación:")
        lineas += [f"  {etq}: {_plano(v)}" for etq, v in datos]
        lineas.append("")
    if catalogo:
        lineas.append(T["pedimos"].replace("Para poder continuar necesitamos", "Necesitamos"))
        lineas += [f"  {i}. {x}" for i, x in enumerate(catalogo, 1)]
        lineas.append("")

    lineas.append(f'{T["responder"]} {plazo}.' if plazo else f'{T["responder"]} a la brevedad.')
    if nota:
        lineas += ["", nota]
    lineas += ["", T["puede_responder"] + " " +
               re.sub(r"</?strong>", "", T["mantener"]) + ".",
               "", "Equipo de Compliance · Global66"]

    # El formato corporativo manda: la plantilla oficial aporta cabecera,
    # tipografía, saludo, cierre, firma y pie; acá sólo se compone el medio.
    # Si por lo que sea no está disponible —no viajó en el paquete, cambió el
    # marcador— se cae al HTML propio en vez de no mandar nada. El correo feo
    # es un problema menor; el correo que no sale frena un caso.
    try:
        from . import plantilla
        oficial = plantilla.componer(
            nombre,
            plantilla.bloque(datos=datos, catalogo=catalogo, plazo=plazo,
                             nota=nota, empresa=empresa),
            empresa=empresa)
        if oficial and not plantilla.quedan_marcadores(oficial):
            html = oficial
        elif oficial:
            avisos.append("La plantilla oficial dejó marcadores sin reemplazar; "
                          "se usó el formato propio.")
    except Exception as e:
        print(f"[relevo/correo] no pude usar la plantilla oficial: {e}")

    return {
        "asunto": asunto_de(token),
        "html": html,
        "texto": "\n".join(lineas),
        "token": token,
        "para": para,
        "nombre": nombre,
        "items_catalogo": catalogo,
        "items_crudo": crudo,
        "datos": datos,
        "plazo": plazo,
        "avisos": avisos,
    }


def a_mime(compuesto, remitente=None):
    """MIME multipart/alternative listo para gmail.enviar(). Sin adjuntos (§8)."""
    m = MIMEMultipart("alternative")
    m["Subject"] = compuesto["asunto"]
    m["From"] = remitente or REMITENTE_POR_DEFECTO
    m["To"] = compuesto["para"]
    m.attach(MIMEText(compuesto["texto"], "plain", "utf-8"))
    m.attach(MIMEText(compuesto["html"], "html", "utf-8"))
    return m.as_bytes()


_RE_TOKEN = re.compile(rf"\[{PREFIJO_TOKEN}:\s*([0-9a-f]{{6,16}})\]", re.I)


def token_de_asunto(asunto):
    m = _RE_TOKEN.search(str(asunto or ""))
    return m.group(1).lower() if m else ""
