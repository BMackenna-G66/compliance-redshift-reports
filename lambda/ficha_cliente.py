"""La ficha del cliente: todo lo que una auditoría pregunta, en un lugar.

Sale del punto 6 de las observaciones funcionales. Lo que hoy hay que tener a
la vista, y dónde vivía cada cosa antes de esto:

    historial de correos          → dentro de cada caso, uno por uno
    documentación pedida/recibida → dentro de cada caso, uno por uno
    resumen transaccional         → otra pestaña (Análisis Individual)
    tipo de productos             → no existía

**Por cliente, no por caso.** Es la diferencia que importa: un cliente puede
tener varios casos a lo largo del tiempo, y una auditoría pide *todo lo del
cliente*, no lo de un expediente. Entrar por el caso y ver sólo ese caso es
justamente lo que obligaba a abrir cinco pestañas y reconstruir a mano.

**Los productos se derivan del uso, no de una declaración.** No hay una tabla
que diga qué productos tiene contratados un cliente, así que se infieren de lo
que efectivamente movió:

    cuenta virtual  → el perfil KYC ya trae si está activa y de qué tipo
    remesas         → transacciones que no pasan por bridge
    cripto          → transacciones que sí

Derivar del uso no puede quedar desactualizado, que es la ventaja. La
limitación, que conviene decir en voz alta: un producto contratado y nunca
usado no aparece.

**No todas las filas de la tabla de transacciones son plata que se movió.**
Esto es lo que más cambia los números y por eso está acá arriba. La tabla
`transaction` guarda también cotizaciones, errores y devoluciones: en el
histórico completo de un cliente de prueba, 64 filas eran en realidad 63
transferencias exitosas (USD 26.513,78) y una devuelta (USD 382,04). Contar
todo junto infla el total y mezcla plata movida con plata que volvió. Así que
los totales se calculan sobre las **efectivas** y el resto se informa aparte
—las devoluciones y las retenidas por compliance no son ruido: son señal.

**`payment_method` no sirve para separar productos.** Medido sobre los últimos
3 meses: 2.068.423 de 2.069.828 filas dicen `WALLET`. Un `COUNT(DISTINCT
payment_method)` iba a devolver 1 siempre, y buscar `bridge` ahí no encuentra
nada nunca. Lo que sí delata cripto son los nombres de banco: en 6 meses,
`outbound_bank_name = 'BRIDGE'` → 36.195 operaciones de 6.421 clientes.
"""

# Estados en los que la plata efectivamente se movió. Los totales de la ficha
# se calculan sólo sobre éstos.
EFECTIVAS = ("TRANSFERENCIA_EXITOSA", "TRANSFERENCIA_ENVIADA")
# Volvió al cliente. Para AML una devolución es una señal, no un descarte.
DEVUELTAS = ("DEVUELTO",)
# Frenadas por nosotros. Que el propio historial las muestre evita tener que
# ir a preguntar a otro lado por qué un envío no salió.
RETENIDAS = ("UNDER_COMPLIANCE_REVIEW", "INFO_REQUESTED", "ENVIO_RECHAZADO")

TABLA = '"db_prod"."transaction"."transaction"'

# Lo que delata una operación cripto. Mismo criterio que
# `queries/crypto_bridge_transactions.sql`, para que la ficha y el reporte de
# detección no puedan discrepar sobre si un cliente opera en cripto.
CRIPTO = ("LOWER(COALESCE(t.outbound_bank_name,'') || COALESCE(t.inbound_bank_name,'')) "
          "LIKE '%bridge%'")


def _lista(valores):
    return ", ".join(f"'{v}'" for v in valores)


_EFECTIVA = f"t.tx_status IN ({_lista(EFECTIVAS)})"


def entero(valor):
    """El id validado como entero, o None.

    Va interpolado en el SQL —la Data API no admite parámetros en todas las
    posiciones— así que ésta es la barrera contra inyección, y por eso devuelve
    None en vez de arriesgar un passthrough: quien llama no debe poder armar
    una consulta con algo que no sea un número.
    """
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= 2147483647 else None


def sql_resumen(customer_id: int) -> str:
    """Una fila con todo: volumen, período, productos y los estados aparte.

    Siempre devuelve exactamente una fila, incluso para un cliente sin
    transacciones (los COUNT dan 0). Eso es deliberado: `_rs_exec_multi`
    devuelve `[]` tanto cuando la consulta falla como cuando no hay datos, y
    sin esta garantía no habría forma de distinguir "este cliente no operó" de
    "Redshift no contestó". Con ella, una lista vacía significa falla y se
    puede decir así en pantalla en vez de mostrar un cero que miente.
    """
    return f"""
        SELECT
            COUNT(*)                                                  AS n_filas,
            SUM(CASE WHEN {_EFECTIVA} THEN 1 ELSE 0 END)              AS n_efectivas,
            SUM(CASE WHEN t.tx_status IN ({_lista(DEVUELTAS)})
                     THEN 1 ELSE 0 END)                               AS n_devueltas,
            SUM(CASE WHEN t.tx_status IN ({_lista(RETENIDAS)})
                     THEN 1 ELSE 0 END)                               AS n_retenidas,
            ROUND(SUM(CASE WHEN {_EFECTIVA}
                     THEN t.destiny_amount_usd ELSE 0 END), 2)        AS total_usd,
            ROUND(SUM(CASE WHEN t.tx_status IN ({_lista(DEVUELTAS)})
                     THEN t.destiny_amount_usd ELSE 0 END), 2)        AS devuelto_usd,
            ROUND(AVG(CASE WHEN {_EFECTIVA}
                     THEN t.destiny_amount_usd END), 2)               AS ticket_promedio_usd,
            ROUND(MAX(CASE WHEN {_EFECTIVA}
                     THEN t.destiny_amount_usd END), 2)               AS ticket_mayor_usd,
            MIN(CASE WHEN {_EFECTIVA} THEN t.start_date END)          AS primera,
            MAX(CASE WHEN {_EFECTIVA} THEN t.start_date END)          AS ultima,
            COUNT(DISTINCT CASE WHEN {_EFECTIVA}
                     THEN t.destiny_country END)                      AS paises_destino,
            COUNT(DISTINCT CASE WHEN {_EFECTIVA}
                     THEN t.beneficiary_generated_id END)             AS beneficiarios,
            SUM(CASE WHEN {_EFECTIVA} AND {CRIPTO} THEN 1 ELSE 0 END) AS n_cripto,
            ROUND(SUM(CASE WHEN {_EFECTIVA} AND {CRIPTO}
                     THEN t.destiny_amount_usd ELSE 0 END), 2)        AS usd_cripto,
            SUM(CASE WHEN {_EFECTIVA} AND NOT {CRIPTO}
                     THEN 1 ELSE 0 END)                               AS n_remesas,
            ROUND(SUM(CASE WHEN {_EFECTIVA} AND NOT {CRIPTO}
                     THEN t.destiny_amount_usd ELSE 0 END), 2)        AS usd_remesas
        FROM {TABLA} AS t
        WHERE t.customer_id = {customer_id}
    """


def sql_por_pais(customer_id: int) -> str:
    """Adónde manda. Primera pregunta de cualquier revisión de riesgo."""
    return f"""
        SELECT t.destiny_country                    AS pais,
               COUNT(*)                             AS n,
               ROUND(SUM(t.destiny_amount_usd), 2)  AS usd
        FROM {TABLA} AS t
        WHERE t.customer_id = {customer_id}
          AND {_EFECTIVA}
          AND t.destiny_country IS NOT NULL
        GROUP BY 1 ORDER BY 3 DESC LIMIT 10
    """


def sql_por_mes(customer_id: int) -> str:
    """El período mes a mes. Un total sin curva esconde justo lo que se busca,
    que es el mes en que el comportamiento cambió."""
    return f"""
        SELECT TO_CHAR(DATE_TRUNC('month', t.start_date), 'YYYY-MM') AS mes,
               COUNT(*)                                              AS n,
               ROUND(SUM(t.destiny_amount_usd), 2)                   AS usd,
               SUM(CASE WHEN {CRIPTO} THEN 1 ELSE 0 END)             AS n_cripto
        FROM {TABLA} AS t
        WHERE t.customer_id = {customer_id}
          AND {_EFECTIVA}
          AND t.start_date IS NOT NULL
        GROUP BY 1 ORDER BY 1 DESC LIMIT 24
    """


def _num(v, defecto=0):
    if v in (None, ""):
        return defecto
    try:
        return float(v)
    except (TypeError, ValueError):
        return defecto


def _usd(v):
    return f"USD {_num(v):,.2f}"


def _si(valor):
    return str(valor or "").strip().lower() in ("true", "t", "1", "si", "sí", "yes", "y")


def productos(perfil: dict, resumen: dict) -> list:
    """Los tres productos, cada uno con el dato que sostiene la afirmación.

    Cada entrada lleva `evidencia`. En una ficha que se usa para auditar,
    decir "opera cripto" sin decir de dónde sale es una afirmación que nadie
    puede verificar ni discutir — y la que más caro sale si está mal.
    """
    perfil = perfil or {}
    resumen = resumen or {}
    n_remesas = int(_num(resumen.get("n_remesas")))
    n_cripto = int(_num(resumen.get("n_cripto")))
    tiene_va = _si(perfil.get("virtual_account_active")) or bool(
        perfil.get("virtual_account_number"))

    return [
        {
            "producto": "Cuenta virtual",
            "tiene": tiene_va,
            "detalle": " · ".join(str(x) for x in (
                perfil.get("virtual_account_type"),
                perfil.get("virtual_account_country_code"),
                perfil.get("virtual_account_number")) if x) or "—",
            "desde": str(perfil.get("virtual_account_created_at") or "")[:10],
            "evidencia": "campos virtual_account del perfil KYC",
        },
        {
            "producto": "Remesas",
            "tiene": n_remesas > 0,
            "detalle": (f"{n_remesas:,} envío(s) · {_usd(resumen.get('usd_remesas'))}"
                        if n_remesas else "sin envíos efectivos"),
            "desde": str(resumen.get("primera") or "")[:10],
            "evidencia": "transferencias exitosas o enviadas que no pasan por bridge",
        },
        {
            "producto": "Cripto",
            "tiene": n_cripto > 0,
            "detalle": (f"{n_cripto:,} operación(es) · {_usd(resumen.get('usd_cripto'))}"
                        if n_cripto else "sin operaciones vía bridge"),
            "desde": "",
            "evidencia": "banco de origen o destino con 'bridge' en el nombre",
        },
    ]


def periodo(resumen: dict) -> str:
    """'2026-06-11 a 2026-09-11 (3 meses)'. El período es parte de lo pedido:
    un resumen que no dice de cuándo a cuándo no se puede auditar."""
    a, b = resumen.get("primera"), resumen.get("ultima")
    if not a or not b:
        return "sin transacciones efectivas"
    a, b = str(a)[:10], str(b)[:10]
    try:
        import datetime as dt
        dias = (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
    except ValueError:
        return f"{a} a {b}"
    if dias < 45:
        cuanto = f"{dias} día{'s' if dias != 1 else ''}"
    elif dias < 365:
        m = max(1, round(dias / 30))
        cuanto = f"{m} mes{'es' if m != 1 else ''}"
    else:
        anios = dias / 365
        cuanto = f"{anios:.1f} años".replace(".0 ", " ")
    return f"{a} a {b} ({cuanto})"


def alertas_del_resumen(resumen: dict) -> list:
    """Lo que merece un cartel en la ficha sin tener que leer los números.

    No es scoring de riesgo —eso ya lo hacen las alertas— sino hacer visible
    lo que se pierde en una tabla: que la mitad de los envíos volvieron, o que
    hay operaciones frenadas por compliance que nadie miró.
    """
    r = resumen or {}
    avisos = []
    n_ef = int(_num(r.get("n_efectivas")))
    n_dev = int(_num(r.get("n_devueltas")))
    n_ret = int(_num(r.get("n_retenidas")))

    if n_dev and n_ef and (n_dev / (n_dev + n_ef)) >= 0.20:
        avisos.append({
            "tono": "alto",
            "texto": (f"{n_dev} de {n_dev + n_ef} operaciones fueron devueltas "
                      f"({n_dev / (n_dev + n_ef):.0%}) · {_usd(r.get('devuelto_usd'))}"),
        })
    elif n_dev:
        avisos.append({"tono": "medio",
                       "texto": f"{n_dev} operación(es) devuelta(s) · "
                                f"{_usd(r.get('devuelto_usd'))}"})
    if n_ret:
        avisos.append({"tono": "alto",
                       "texto": f"{n_ret} operación(es) retenida(s) por compliance "
                                f"(revisión, info solicitada o envío rechazado)"})
    if int(_num(r.get("n_cripto"))) and int(_num(r.get("n_remesas"))):
        avisos.append({"tono": "medio",
                       "texto": "Opera remesas y cripto en la misma cuenta"})
    return avisos
