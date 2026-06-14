"""
Compliance Reports API — HTTP handler for the frontend.

All routes require Cognito JWT in Authorization header (validated by API Gateway).

Routes:
  GET  /reports             → list built-in + custom reports
  POST /execute             → execute a report async, returns run_id
  GET  /runs                → list recent runs (last 50)
  GET  /runs/{run_id}       → get run status + presigned download URL + result preview
  POST /queries             → save a custom SQL query to catalog
  DELETE /queries/{name}    → delete a custom query
  GET  /cluster/status      → get Redshift cluster status
  POST /cluster/wake        → resume a paused cluster
  POST /cluster/pause       → pause the cluster
  GET  /whitelist           → list active whitelist entries
  POST /whitelist           → add an entry to the whitelist
  DELETE /whitelist/{id}    → remove a whitelist entry
  GET  /alerts              → list active alert entries
  GET  /alerts/reviewed     → list reviewed (ya revisados) entries
  POST /alerts              → add an alert entry
  PUT  /alerts/{id}/review  → mark alert as reviewed (move to ya revisados)
  DELETE /alerts/{id}       → permanently remove an alert
  GET  /dashboard/stats        → submit 3 queries to Redshift; returns stmt_ids immediately
  GET  /dashboard/stats/result → poll results for stmt_ids (q0=, q1=, q2=); returns per-query
                                 rows when done, null when still running, all_done flag
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import time
import uuid

import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
s3 = boto3.client("s3")
redshift = boto3.client("redshift")
redshift_data = boto3.client("redshift-data")

CLUSTER_ID = os.environ.get("CLUSTER_IDENTIFIER", "compliance-redshift-cluster")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "dev")
DB_USER = os.environ.get("DB_USER", "awsuser")

RUNS_TABLE_NAME = os.environ["RUNS_TABLE"]
CATALOG_TABLE_NAME = os.environ["CATALOG_TABLE"]
REPORT_LAMBDA_NAME = os.environ["REPORT_LAMBDA"]
S3_BUCKET = os.environ["S3_BUCKET"]

runs_table = dynamodb.Table(RUNS_TABLE_NAME)
catalog_table = dynamodb.Table(CATALOG_TABLE_NAME)

# ---------------------------------------------------------------------------
# Built-in report definitions (mirrors REPORT_CONFIGS in handler.py)
# ---------------------------------------------------------------------------
BUILTIN_REPORTS = [
    # ─── AML Transaccional ───────────────────────────────────────────────────
    {
        "report_name": "high_risk_countries",
        "display_name": "Transacciones a Países Alto Riesgo",
        "description": "Transacciones outbound a jurisdicciones FATF/OFAC de alto riesgo. Incluye flag de mismatch SWIFT.",
        "category": "aml_transaccional",
        "category_label": "AML Transaccional",
        "is_custom": False,
        "params": [
            {"name": "since_date", "type": "date", "label": "Desde fecha", "default": "first_day_of_month"},
            {"name": "only_successful", "type": "bool", "label": "Solo transferencias exitosas", "default": False},
        ],
    },
    {
        "report_name": "amount_ranges_by_country",
        "display_name": "Rangos de Monto por País (7d)",
        "description": "Volumen y cantidad de transacciones agrupadas por rango USD × país destino, últimos 7 días.",
        "category": "aml_transaccional",
        "category_label": "AML Transaccional",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "top_customers_by_range_country",
        "display_name": "Top Clientes por Rango y País (7d)",
        "description": "Top 15 clientes por cantidad de transacciones para cada combinación país × rango USD, últimos 7 días.",
        "category": "aml_transaccional",
        "category_label": "AML Transaccional",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "tax_haven_transactions",
        "display_name": "Transacciones a Régimen Fiscal Preferencial (90d)",
        "description": "Transacciones exitosas hacia países con régimen fiscal preferencial o zonas francas en últimos 90 días.",
        "category": "aml_transaccional",
        "category_label": "AML Transaccional",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "tax_haven_funding",
        "display_name": "Fondeos desde Régimen Fiscal Preferencial (7d)",
        "description": "Cash calls entrantes (CR pagados) cuyo remitente proviene de países con régimen fiscal preferencial.",
        "category": "aml_transaccional",
        "category_label": "AML Transaccional",
        "is_custom": False,
        "params": [],
    },
    # ─── Patrones AML ────────────────────────────────────────────────────────
    {
        "report_name": "payin_payout_accumulation",
        "display_name": "Acumulación Pay In → Pay Out (7d)",
        "description": "Clientes con múltiples pay-ins seguidos de pay-outs en 7 días. Indica posible layering.",
        "category": "patrones_aml",
        "category_label": "Patrones AML",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "small_payin_structuring",
        "display_name": "Pay In Pequeños → Pay Out (Smurfing, 7d)",
        "description": "Clientes con 5+ pay-ins < USD 1.000 seguidos de pay-outs. Patrón de estructuración/smurfing.",
        "category": "patrones_aml",
        "category_label": "Patrones AML",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "velocity_payin_payout",
        "display_name": "Velocity Pay In ↔ Pay Out < 24h (7d)",
        "description": "Pares de pay-in y pay-out del mismo cliente separados por menos de 24 horas.",
        "category": "patrones_aml",
        "category_label": "Patrones AML",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "external_funder_single",
        "display_name": "Tercero que Fondea Una Sola Cuenta (7d)",
        "description": "Personas externas que fondean repetidamente (3+) una única cuenta de cliente.",
        "category": "patrones_aml",
        "category_label": "Patrones AML",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "external_funder_multiple",
        "display_name": "Tercero que Fondea Múltiples Cuentas (7d)",
        "description": "Personas externas que fondean 2+ cuentas distintas de clientes en los últimos 7 días.",
        "category": "patrones_aml",
        "category_label": "Patrones AML",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "circular_transactions",
        "display_name": "Circularidad DNI Cliente ↔ Beneficiario (90d)",
        "description": "Clientes que envían fondos a personas que también les envían fondos — posible circularidad.",
        "category": "patrones_aml",
        "category_label": "Patrones AML",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "structuring_detection",
        "display_name": "Estructuración / Fraccionamiento (7d)",
        "description": "Clientes con 5+ transacciones todas < USD 1.000 y volumen total > USD 3.000.",
        "category": "patrones_aml",
        "category_label": "Patrones AML",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "shared_beneficiary",
        "display_name": "Beneficiario Compartido por Múltiples Remitentes (7d)",
        "description": "Beneficiarios que reciben fondos de 3+ clientes distintos en los últimos 7 días.",
        "category": "patrones_aml",
        "category_label": "Patrones AML",
        "is_custom": False,
        "params": [],
    },
    # ─── Comportamiento Clientes ──────────────────────────────────────────────
    {
        "report_name": "customer_metrics_7d",
        "display_name": "Métricas por Cliente B2C (7d)",
        "description": "Resumen de transacciones, beneficiarios únicos, montos y canales por cliente individual.",
        "category": "comportamiento_clientes",
        "category_label": "Comportamiento Clientes",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "beneficiary_concentration",
        "display_name": "Concentración de Beneficiarios (7d)",
        "description": "Clientes con 5+ transacciones pero solo 1-2 beneficiarios distintos — posible concentración sospechosa.",
        "category": "comportamiento_clientes",
        "category_label": "Comportamiento Clientes",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "beneficiary_dispersion",
        "display_name": "Dispersión de Beneficiarios (7d)",
        "description": "Clientes individuales que envían a 5+ beneficiarios distintos — posible dispersión de fondos.",
        "category": "comportamiento_clientes",
        "category_label": "Comportamiento Clientes",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "outbound_bank_change",
        "display_name": "Cambio de Banco Outbound (30d vs 7d)",
        "description": "Clientes que usaron un banco outbound nuevo en los últimos 7 días que no habían usado antes.",
        "category": "comportamiento_clientes",
        "category_label": "Comportamiento Clientes",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "new_corridor_detection",
        "display_name": "Corredor Nuevo para el Cliente (7d vs 90d)",
        "description": "Clientes que usaron una ruta origen/destino nueva en los últimos 7d que no habían usado en 90d.",
        "category": "comportamiento_clientes",
        "category_label": "Comportamiento Clientes",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "high_volume_vs_historical",
        "display_name": "Alto Volumen vs Histórico (7d vs 90d)",
        "description": "Clientes cuyo ticket promedio o volumen diario en 7d es 3x+ mayor que su histórico de 90 días.",
        "category": "comportamiento_clientes",
        "category_label": "Comportamiento Clientes",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "swift_mismatch_detection",
        "display_name": "Mismatch SWIFT vs País Beneficiario (30d)",
        "description": "Transacciones donde el código de país del SWIFT del banco no coincide con el país beneficiario.",
        "category": "comportamiento_clientes",
        "category_label": "Comportamiento Clientes",
        "is_custom": False,
        "params": [],
    },
    # ─── KYC / Jumio ─────────────────────────────────────────────────────────
    {
        "report_name": "jumio_kyc_approval_rates",
        "display_name": "Tasas de Aprobación / Rechazo KYC por Flujo",
        "description": "Estadísticas agregadas de aprobación y rechazo de validaciones Jumio por business flow y país.",
        "category": "kyc_jumio",
        "category_label": "KYC / Jumio",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "jumio_duplicate_flows",
        "display_name": "Documentos Jumio Duplicados / Flujos Múltiples",
        "description": "DNIs con múltiples clientes, cuentas Jumio o business flows — posible duplicación de identidad.",
        "category": "kyc_jumio",
        "category_label": "KYC / Jumio",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "b2c_as_legal_rep",
        "display_name": "Clientes B2C que son Representantes Legales (B2B)",
        "description": "Personas físicas con cuenta B2C activa que también son representantes legales de empresas B2B.",
        "category": "kyc_jumio",
        "category_label": "KYC / Jumio",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "top_companies_by_legal_reps",
        "display_name": "Top 15 Empresas con Más Representantes Legales",
        "description": "Empresas activas con mayor cantidad de representantes legales distintos registrados.",
        "category": "kyc_jumio",
        "category_label": "KYC / Jumio",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "age_anomaly_customers",
        "display_name": "Clientes con Anomalía de Edad (<18 o >90 años)",
        "description": "Clientes activos con fecha de nacimiento que indica menor de 18 años o mayor de 90 años.",
        "category": "kyc_jumio",
        "category_label": "KYC / Jumio",
        "is_custom": False,
        "params": [],
    },
    # ─── Crypto / Bridge ─────────────────────────────────────────────────────
    {
        "report_name": "crypto_bridge_transactions",
        "display_name": "Transacciones Bridge/Crypto (30d)",
        "description": "Resumen de transacciones involucrando Bridge o métodos crypto, agrupadas por método, estado y corredor.",
        "category": "crypto_bridge",
        "category_label": "Crypto / Bridge",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "crypto_bridge_cash_calls",
        "display_name": "Cash Calls Bridge/Crypto (30d)",
        "description": "Cash calls con método Bridge o moneda USDC/USDT/BTC/ETH en los últimos 30 días.",
        "category": "crypto_bridge",
        "category_label": "Crypto / Bridge",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "crypto_high_risk_destinations",
        "display_name": "Crypto hacia Países de Riesgo (30d)",
        "description": "Cash calls crypto cuyo beneficiario está en países de la lista de alto riesgo.",
        "category": "crypto_bridge",
        "category_label": "Crypto / Bridge",
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "crypto_full_bridge_activity",
        "display_name": "Actividad Completa Bridge (30d)",
        "description": "Vista completa de clientes Bridge: wallets, balances, transacciones crypto, transferencias y cash calls.",
        "category": "crypto_bridge",
        "category_label": "Crypto / Bridge",
        "is_custom": False,
        "params": [],
    },
]


# ---------------------------------------------------------------------------
# Dashboard SQL queries (informational widgets, last 7 days of successful TRX)
# ---------------------------------------------------------------------------
_SQL_DAILY_EVOLUTION = """
SELECT CAST(t.start_date AS DATE) AS trx_date,
    COALESCE(t.payment_method, 'SIN_PAYMENT_METHOD') AS payment_method,
    COALESCE(t.outbound_bank_name, 'SIN_OUTBOUND_BANK') AS outbound_bank_name,
    t.origin_currency, t.destiny_currency,
    COUNT(*) AS total_transactions,
    COUNT(DISTINCT t.customer_id) AS unique_customers,
    SUM(t.destiny_amount_usd) AS total_amount_usd,
    AVG(t.destiny_amount_usd) AS avg_ticket_usd
FROM "db_prod"."transaction"."transaction" AS t
WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
  AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'
GROUP BY CAST(t.start_date AS DATE),
    COALESCE(t.payment_method, 'SIN_PAYMENT_METHOD'),
    COALESCE(t.outbound_bank_name, 'SIN_OUTBOUND_BANK'),
    t.origin_currency, t.destiny_currency
ORDER BY trx_date ASC, total_amount_usd DESC
"""

_SQL_OVER_300K = """
SELECT CAST(t.start_date AS DATE) AS trx_date,
    COALESCE(t.payment_method, 'SIN_PAYMENT_METHOD') AS payment_method,
    COALESCE(t.outbound_bank_name, 'SIN_OUTBOUND_BANK') AS outbound_bank_name,
    t.origin_currency, t.destiny_currency,
    COUNT(*) AS trx_over_300k,
    COUNT(DISTINCT t.customer_id) AS unique_customers_over_300k,
    SUM(t.destiny_amount_usd) AS total_amount_usd_over_300k,
    AVG(t.destiny_amount_usd) AS avg_ticket_usd_over_300k,
    MAX(t.destiny_amount_usd) AS max_ticket_usd
FROM "db_prod"."transaction"."transaction" AS t
WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
  AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'
  AND t.destiny_amount_usd >= 300000
GROUP BY CAST(t.start_date AS DATE),
    COALESCE(t.payment_method, 'SIN_PAYMENT_METHOD'),
    COALESCE(t.outbound_bank_name, 'SIN_OUTBOUND_BANK'),
    t.origin_currency, t.destiny_currency
ORDER BY trx_date ASC, total_amount_usd_over_300k DESC
"""

_SQL_BY_COUNTRY = """
SELECT t.beneficiary_country_code,
    MAX(t.beneficiary_country_name) AS beneficiary_country_name,
    COUNT(*) AS total_transactions,
    COUNT(DISTINCT t.customer_id) AS unique_customers,
    COUNT(DISTINCT t.beneficiary_id) AS unique_beneficiaries,
    SUM(t.destiny_amount_usd) AS total_amount_usd,
    AVG(t.destiny_amount_usd) AS avg_ticket_usd,
    MAX(t.destiny_amount_usd) AS max_ticket_usd
FROM "db_prod"."transaction"."transaction" AS t
WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
  AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'
GROUP BY t.beneficiary_country_code
ORDER BY total_amount_usd DESC
"""


# ---------------------------------------------------------------------------
# Redshift Data API helpers
# ---------------------------------------------------------------------------
def _esc(s) -> str:
    """Escape a value for safe inclusion in a Redshift SQL string literal."""
    return str(s).replace("'", "''")


def _rs_exec(sql: str) -> list[dict]:
    """Execute SQL via Redshift Data API; poll until done; return rows as list of dicts."""
    try:
        # Redshift Data API rejects trailing semicolons
        sql = sql.strip().rstrip(";").strip()
        resp_exec = redshift_data.execute_statement(
            ClusterIdentifier=CLUSTER_ID,
            Database=DATABASE_NAME,
            DbUser=DB_USER,
            Sql=sql,
        )
        statement_id = resp_exec["Id"]

        deadline = time.time() + 30
        while time.time() < deadline:
            desc = redshift_data.describe_statement(Id=statement_id)
            status = desc["Status"]
            if status == "FINISHED":
                if not desc.get("HasResultSet"):
                    return []
                rows: list[dict] = []
                columns: list[str] = []
                next_token = None
                while True:
                    kwargs = {"Id": statement_id}
                    if next_token:
                        kwargs["NextToken"] = next_token
                    result = redshift_data.get_statement_result(**kwargs)
                    if not columns:
                        columns = [c["name"] for c in result["ColumnMetadata"]]
                    for record in result["Records"]:
                        row = {}
                        for i, cell in enumerate(record):
                            if cell.get("isNull"):
                                row[columns[i]] = None
                            elif "stringValue" in cell:
                                row[columns[i]] = cell["stringValue"]
                            elif "longValue" in cell:
                                row[columns[i]] = cell["longValue"]
                            elif "doubleValue" in cell:
                                row[columns[i]] = cell["doubleValue"]
                            elif "booleanValue" in cell:
                                row[columns[i]] = cell["booleanValue"]
                            else:
                                row[columns[i]] = None
                        rows.append(row)
                    next_token = result.get("NextToken")
                    if not next_token:
                        break
                return rows
            if status in ("FAILED", "ABORTED"):
                raise RuntimeError(f"Redshift query {status}: {desc.get('Error', 'unknown error')}")
            time.sleep(0.5)

        raise RuntimeError("Redshift query timed out after 30s")

    except RuntimeError:
        raise
    except Exception as e:
        msg = str(e)
        if "paused" in msg.lower() or "unavailable" in msg.lower() or "not available" in msg.lower():
            raise RuntimeError(f"Redshift cluster is not available (may be paused): {msg}") from e
        raise


def _rs_get_rows(stmt_id: str) -> list[dict]:
    """Fetch all result rows from a FINISHED Redshift Data API statement (handles pagination)."""
    rows: list[dict] = []
    columns: list[str] = []
    next_token = None
    while True:
        kwargs: dict = {"Id": stmt_id}
        if next_token:
            kwargs["NextToken"] = next_token
        result = redshift_data.get_statement_result(**kwargs)
        if not columns:
            columns = [c["name"] for c in result["ColumnMetadata"]]
        for record in result["Records"]:
            row: dict = {}
            for i, cell in enumerate(record):
                if cell.get("isNull"):
                    row[columns[i]] = None
                elif "stringValue" in cell:
                    row[columns[i]] = cell["stringValue"]
                elif "longValue" in cell:
                    row[columns[i]] = cell["longValue"]
                elif "doubleValue" in cell:
                    row[columns[i]] = cell["doubleValue"]
                elif "booleanValue" in cell:
                    row[columns[i]] = cell["booleanValue"]
                else:
                    row[columns[i]] = None
            rows.append(row)
        next_token = result.get("NextToken")
        if not next_token:
            break
    return rows


def _rs_exec_multi(sqls: list, timeout_s: int = 90) -> list:
    """Submit multiple SQL statements in parallel via Redshift Data API and poll until all done.

    Exploits the async nature of the Data API: all statements are submitted first (no waiting),
    then polled together every second.  Individual failures return [] (non-blocking).
    Returns a list of row-lists in the same order as the input sqls.
    """
    if not sqls:
        return []

    # Submit all statements at once
    stmt_ids: list[str] = []
    for sql in sqls:
        r = redshift_data.execute_statement(
            ClusterIdentifier=CLUSTER_ID,
            Database=DATABASE_NAME,
            DbUser=DB_USER,
            Sql=sql.strip(),
        )
        stmt_ids.append(r["Id"])

    results: list = [[] for _ in sqls]
    pending: set = set(range(len(sqls)))
    deadline = time.time() + timeout_s

    while pending and time.time() < deadline:
        time.sleep(1.0)
        for i in list(pending):
            try:
                desc = redshift_data.describe_statement(Id=stmt_ids[i])
                status = desc["Status"]
                if status == "FINISHED":
                    pending.discard(i)
                    if desc.get("HasResultSet"):
                        results[i] = _rs_get_rows(stmt_ids[i])
                    # else results[i] stays []
                elif status in ("FAILED", "ABORTED"):
                    pending.discard(i)
                    # results[i] stays []
            except Exception:
                pending.discard(i)

    # Any still pending after timeout → left as []
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _Encoder(json.JSONEncoder):
    """Handle Decimal (DynamoDB numbers) and datetime."""
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o) if o % 1 else int(o)
        if isinstance(o, (dt.datetime, dt.date)):
            return o.isoformat()
        return super().default(o)


def resp(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body, cls=_Encoder),
    }


def get_user_email(event: dict) -> str:
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    return claims.get("email") or claims.get("cognito:username", "unknown")


def notify_alert(body: dict):
    """Send an SES email when an alert is assigned to an analyst."""
    to_email = str(body.get("to_email", "")).strip()
    to_name = str(body.get("to_name", "")).strip()
    assigned_by = str(body.get("assigned_by", "")).strip()
    entity_value = str(body.get("entity_value", "")).strip()
    entity_field = str(body.get("entity_field", "")).strip()
    report_name = str(body.get("report_name", "")).strip()
    note = str(body.get("note", "")).strip()

    if not to_email or "@" not in to_email:
        return resp(400, {"error": "to_email is required"})

    from_email = os.environ.get("SES_FROM_ADDRESS", "")
    if not from_email:
        return resp(500, {"error": "SES_FROM_ADDRESS not configured"})

    subject = f"[WatchTower AML] Nueva alerta asignada: {entity_value}"
    note_row = (
        f'<tr><td style="padding:8px;border:1px solid #ddd;background:#f8f8f8"><strong>Nota</strong></td>'
        f'<td style="padding:8px;border:1px solid #ddd">{note}</td></tr>'
        if note else ""
    )
    body_html = f"""<html><body style="font-family:Arial,sans-serif;color:#333">
<h2 style="color:#1B3A6B">&#128737;&#65039; WatchTower AML &#8212; Nueva Alerta Asignada</h2>
<p>Hola {to_name or to_email},</p>
<p><strong>{assigned_by}</strong> te asign&#243; una alerta para revisar:</p>
<table style="border-collapse:collapse;width:100%;max-width:500px">
  <tr><td style="padding:8px;border:1px solid #ddd;background:#f8f8f8"><strong>Campo</strong></td>
      <td style="padding:8px;border:1px solid #ddd">{entity_field}</td></tr>
  <tr><td style="padding:8px;border:1px solid #ddd;background:#f8f8f8"><strong>Valor</strong></td>
      <td style="padding:8px;border:1px solid #ddd"><strong>{entity_value}</strong></td></tr>
  <tr><td style="padding:8px;border:1px solid #ddd;background:#f8f8f8"><strong>Reporte</strong></td>
      <td style="padding:8px;border:1px solid #ddd">{report_name.replace("_", " ")}</td></tr>
  {note_row}
</table>
<p style="margin-top:20px">
  <a href="https://bmackenna-g66.github.io/compliance-redshift-reports"
     style="background:#f97316;color:white;padding:10px 20px;text-decoration:none;border-radius:6px;font-weight:bold">
    Ir a WatchTower AML &rarr;
  </a>
</p>
<p style="color:#999;font-size:12px;margin-top:20px">Mensaje autom&#225;tico de WatchTower AML.</p>
</body></html>"""

    try:
        ses = boto3.client("ses")
        ses.send_email(
            Source=from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body":    {"Html": {"Data": body_html, "Charset": "UTF-8"}},
            },
        )
        return resp(200, {"message": "Notification sent"})
    except Exception as e:
        return resp(500, {"error": f"Failed to send email: {e}"})


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def handler(event, context):  # noqa: ARG001
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/").rstrip("/") or "/"
    parts = [p for p in path.split("/") if p]

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    try:
        # CORS preflight — return proper CORS headers so browser accepts the request.
        # API Gateway $default route routes OPTIONS to Lambda, so we handle CORS here.
        if method == "OPTIONS":
            req_headers = event.get("headers", {}) or {}
            origin = req_headers.get("origin") or req_headers.get("Origin", "")
            _allowed_origins = {
                "https://bmackenna-g66.github.io",
                "https://di7f123v3u2y5.cloudfront.net",
            }
            cors_origin = origin if origin in _allowed_origins else "https://bmackenna-g66.github.io"
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": cors_origin,
                    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Access-Control-Max-Age": "300",
                },
                "body": "",
            }

        # GET /reports
        if method == "GET" and not parts:
            return resp(200, {"message": "Compliance Reports API"})

        if method == "GET" and parts == ["reports"]:
            return get_reports()

        # POST /execute
        if method == "POST" and parts == ["execute"]:
            return execute_report(body)

        # GET /runs
        if method == "GET" and parts == ["runs"]:
            qs = event.get("queryStringParameters") or {}
            return get_runs(qs.get("user_email", ""))

        # GET /runs/{run_id}
        if method == "GET" and len(parts) == 2 and parts[0] == "runs":
            return get_run(parts[1])

        # POST /queries
        if method == "POST" and parts == ["queries"]:
            return save_query(body, get_user_email(event))

        # DELETE /queries/{name}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "queries":
            return delete_query(parts[1])

        # GET /cluster/status
        if method == "GET" and parts == ["cluster", "status"]:
            return get_cluster_status()

        # POST /analyze/individual
        if method == "POST" and parts == ["analyze", "individual"]:
            return run_individual_analysis(body)

        # POST /search/transactions
        if method == "POST" and parts == ["search", "transactions"]:
            return run_transaction_search(body)

        # POST /cluster/wake
        if method == "POST" and parts == ["cluster", "wake"]:
            return wake_cluster()

        # POST /cluster/pause
        if method == "POST" and parts == ["cluster", "pause"]:
            return pause_cluster_api()

        # GET /whitelist
        if method == "GET" and parts == ["whitelist"]:
            return get_whitelist()
        # POST /whitelist
        if method == "POST" and parts == ["whitelist"]:
            return add_to_whitelist(body)
        # DELETE /whitelist/{id}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "whitelist":
            return remove_from_whitelist(parts[1])

        # GET /alerts/reviewed
        if method == "GET" and parts == ["alerts", "reviewed"]:
            return get_alerts(status="reviewed")
        # GET /alerts
        if method == "GET" and parts == ["alerts"]:
            return get_alerts(status="active")
        # POST /alerts
        if method == "POST" and parts == ["alerts"]:
            return add_alert(body)
        # PUT /alerts/{id}/review
        if method == "PUT" and len(parts) == 3 and parts[0] == "alerts" and parts[2] == "review":
            return review_alert(parts[1])
        # DELETE /alerts/{id}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "alerts":
            return delete_alert(parts[1])

        # POST /alerts/notify
        if method == "POST" and parts == ["alerts", "notify"]:
            return notify_alert(body)

        # GET /dashboard/stats (submit queries, returns stmt_ids)
        if method == "GET" and parts == ["dashboard", "stats"]:
            return get_dashboard_stats()
        # GET /dashboard/stats/result?q0=id&q1=id&q2=id (poll results)
        if method == "GET" and parts == ["dashboard", "stats", "result"]:
            qs = event.get("queryStringParameters") or {}
            return get_dashboard_stats_result(qs.get("q0", ""), qs.get("q1", ""), qs.get("q2", ""))

        return resp(404, {"error": "Not found", "path": path, "method": method})

    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return resp(500, {"error": str(e)})


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def get_reports():
    reports = list(BUILTIN_REPORTS)
    try:
        result = catalog_table.scan(
            FilterExpression=Attr("is_custom").eq(True)
        )
        for item in result.get("Items", []):
            item.setdefault("params", [])
            reports.append(item)
    except Exception:
        pass
    return resp(200, {"reports": reports})


def execute_report(body: dict):
    report_name = body.get("report_name", "").strip()
    if not report_name:
        return resp(400, {"error": "report_name is required"})

    run_id = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat()

    user_email = str(body.get("user_email", "")).strip()[:200]
    runs_table.put_item(Item={
        "run_id": run_id,
        "report_name": report_name,
        "status": "RUNNING",
        "params": json.dumps({k: v for k, v in body.items() if k not in ("report_name", "user_email")}),
        "started_at": now,
        "user_email": user_email,
        "ttl": int((dt.datetime.utcnow() + dt.timedelta(days=90)).timestamp()),
    })

    # Invoke report Lambda asynchronously (Event type = fire and forget)
    # Forward keep_session so the Lambda skips auto-pause when set
    payload = {**body, "run_id": run_id, "keep_session": bool(body.get("keep_session", False))}
    lambda_client.invoke(
        FunctionName=REPORT_LAMBDA_NAME,
        InvocationType="Event",
        Payload=json.dumps(payload),
    )

    return resp(202, {"run_id": run_id, "status": "RUNNING"})


def get_runs(user_email: str = ""):
    kwargs: dict = {
        "ProjectionExpression": (
            "run_id, report_name, #st, params, started_at, "
            "completed_at, s3_key, row_count, error_message, user_email"
        ),
        "ExpressionAttributeNames": {"#st": "status"},
    }
    if user_email:
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415
        kwargs["FilterExpression"] = Attr("user_email").eq(user_email)
    result = runs_table.scan(**kwargs)
    items = sorted(
        result.get("Items", []),
        key=lambda x: x.get("started_at", ""),
        reverse=True,
    )[:50]
    return resp(200, {"runs": items})


def get_run(run_id: str):
    result = runs_table.get_item(Key={"run_id": run_id})
    item = result.get("Item")
    if not item:
        return resp(404, {"error": "Run not found"})

    # Generate fresh presigned URL if s3_key exists
    if item.get("s3_key"):
        try:
            item["download_url"] = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": item["s3_key"]},
                ExpiresIn=3600,
            )
        except Exception:
            pass

    # Parse result_preview if stored as JSON string
    preview = item.get("result_preview")
    if isinstance(preview, str):
        try:
            item["result_preview"] = json.loads(preview)
        except Exception:
            item["result_preview"] = []

    return resp(200, item)


def save_query(body: dict, created_by: str):
    report_name = body.get("report_name", "").strip().lower().replace(" ", "_")
    if not report_name or not body.get("sql", "").strip():
        return resp(400, {"error": "report_name and sql are required"})

    builtin_names = {r["report_name"] for r in BUILTIN_REPORTS}
    if report_name in builtin_names:
        return resp(400, {"error": f"'{report_name}' is a built-in report and cannot be overwritten"})

    catalog_table.put_item(Item={
        "report_name": report_name,
        "display_name": body.get("display_name", report_name).strip() or report_name,
        "description": body.get("description", "").strip(),
        "sql": body["sql"].strip(),
        "is_custom": True,
        "params": [],
        "created_at": dt.datetime.utcnow().isoformat(),
        "created_by": created_by,
    })
    return resp(201, {"report_name": report_name, "message": "Query guardada correctamente"})


def get_cluster_status():
    try:
        r = redshift.describe_clusters(ClusterIdentifier=CLUSTER_ID)
        status = r["Clusters"][0]["ClusterStatus"]
    except Exception as e:
        return resp(200, {"status": "unknown", "error": str(e)})
    return resp(200, {"status": status})


def wake_cluster():
    try:
        r = redshift.describe_clusters(ClusterIdentifier=CLUSTER_ID)
        status = r["Clusters"][0]["ClusterStatus"]
        if status == "paused":
            redshift.resume_cluster(ClusterIdentifier=CLUSTER_ID)
            return resp(200, {"status": "resuming", "message": "Cluster despertando (3-5 min)"})
        return resp(200, {"status": status, "message": "Cluster ya está disponible"})
    except Exception as e:
        return resp(500, {"error": str(e)})


def pause_cluster_api():
    try:
        r = redshift.describe_clusters(ClusterIdentifier=CLUSTER_ID)
        status = r["Clusters"][0]["ClusterStatus"]
        if status == "available":
            redshift.pause_cluster(ClusterIdentifier=CLUSTER_ID)
            return resp(200, {"status": "pausing", "message": "Cluster pausándose..."})
        return resp(200, {"status": status, "message": f"Cluster en estado: {status}"})
    except Exception as e:
        return resp(500, {"error": str(e)})


def delete_query(report_name: str):
    builtin_names = {r["report_name"] for r in BUILTIN_REPORTS}
    if report_name in builtin_names:
        return resp(400, {"error": "No se pueden eliminar los reportes predefinidos"})
    catalog_table.delete_item(Key={"report_name": report_name})
    return resp(200, {"message": f"Query '{report_name}' eliminada"})


def get_whitelist():
    try:
        today = dt.datetime.utcnow().strftime("%Y-%m-%d")
        sql = (
            "SELECT whitelist_id, entity_field, entity_value, duration_days, reason, scope, "
            "report_name, created_at::VARCHAR AS created_at, expires_at::VARCHAR AS expires_at "
            "FROM compliance.whitelist "
            f"WHERE expires_at > '{today}' "
            "ORDER BY created_at DESC"
        )
        items = _rs_exec(sql)
        return resp(200, {"whitelist": items})
    except Exception as e:
        return resp(200, {"whitelist": [], "warning": str(e)})


def add_to_whitelist(body: dict):
    entity_field = body.get("entity_field", "").strip()
    entity_value = body.get("entity_value", "").strip()
    duration_days = int(body.get("duration_days", 30))
    reason = body.get("reason", "").strip()
    scope = body.get("scope", "global").strip()
    report_name = body.get("report_name", "").strip()

    if not entity_field or not entity_value:
        return resp(400, {"error": "entity_field and entity_value are required"})
    if duration_days not in (30, 60, 90):
        return resp(400, {"error": "duration_days must be 30, 60, or 90"})

    wid = str(uuid.uuid4())
    ef = _esc(entity_field)
    ev = _esc(entity_value)
    reason_esc = _esc(reason)
    scope_esc = _esc(scope)
    rn = _esc(report_name if scope == "report" else "")

    # Compute expiry in Python to avoid Redshift DATEADD timezone issues
    expires_at = (dt.datetime.utcnow() + dt.timedelta(days=duration_days)).strftime("%Y-%m-%d %H:%M:%S")

    sql = (
        f"INSERT INTO compliance.whitelist "
        f"(whitelist_id, entity_field, entity_value, duration_days, reason, scope, report_name, expires_at) "
        f"VALUES ('{wid}', '{ef}', '{ev}', {duration_days}, '{reason_esc}', '{scope_esc}', '{rn}', "
        f"'{expires_at}')"
    )
    _rs_exec(sql)
    return resp(201, {"whitelist_id": wid})


def remove_from_whitelist(whitelist_id: str):
    sql = f"DELETE FROM compliance.whitelist WHERE whitelist_id = '{_esc(whitelist_id)}'"
    _rs_exec(sql)
    return resp(200, {"message": f"Whitelist entry '{whitelist_id}' removed"})


# ---------------------------------------------------------------------------
# ALERTS (Alertados / Ya Revisados)
# ---------------------------------------------------------------------------

def get_alerts(status: str = "active"):
    try:
        sql = (
            "SELECT alert_id, entity_field, entity_value, reason, report_name, row_data, "
            "created_at::VARCHAR AS created_at, status, "
            "COALESCE(reviewed_at::VARCHAR, '') AS reviewed_at "
            "FROM compliance.alerts "
            f"WHERE status = '{_esc(status)}' "
            "ORDER BY created_at DESC"
        )
        items = _rs_exec(sql)
        return resp(200, {"alerts": items})
    except Exception as e:
        return resp(200, {"alerts": [], "warning": str(e)})


def add_alert(body: dict):
    entity_field = body.get("entity_field", "").strip()
    entity_value = body.get("entity_value", "").strip()
    reason = body.get("reason", "").strip()
    report_name = body.get("report_name", "").strip()
    row_data = body.get("row_data", {})

    if not entity_field or not entity_value:
        return resp(400, {"error": "entity_field and entity_value are required"})

    aid = str(uuid.uuid4())
    ef = _esc(entity_field)
    ev = _esc(entity_value)
    reason_esc = _esc(reason)
    rn = _esc(report_name)
    row_data_escaped = _esc(json.dumps(row_data, default=str))

    sql = (
        f"INSERT INTO compliance.alerts "
        f"(alert_id, entity_field, entity_value, reason, report_name, row_data, status) "
        f"VALUES ('{aid}', '{ef}', '{ev}', '{reason_esc}', '{rn}', '{row_data_escaped}', 'active')"
    )
    _rs_exec(sql)
    return resp(201, {"alert_id": aid})


def review_alert(alert_id: str):
    """Move an alert from 'active' to 'reviewed' (ya revisados)."""
    sql = (
        f"UPDATE compliance.alerts SET status = 'reviewed', reviewed_at = SYSDATE "
        f"WHERE alert_id = '{_esc(alert_id)}'"
    )
    _rs_exec(sql)
    return resp(200, {"message": f"Alert '{alert_id}' marked as reviewed"})


def delete_alert(alert_id: str):
    """Permanently remove an alert entry."""
    sql = f"DELETE FROM compliance.alerts WHERE alert_id = '{_esc(alert_id)}'"
    _rs_exec(sql)
    return resp(200, {"message": f"Alert '{alert_id}' permanently deleted"})


# ---------------------------------------------------------------------------
# DASHBOARD STATS
# ---------------------------------------------------------------------------

def get_dashboard_stats():
    """Submit 3 dashboard queries to Redshift Data API and return the statement IDs immediately.

    Uses a two-phase async pattern to avoid API Gateway's 30s timeout:
      1. This endpoint submits all 3 queries and returns stmt_ids in < 1s.
      2. The frontend polls /dashboard/stats/result?q0=id&q1=id&q2=id until all done.
    """
    try:
        stmt_ids: list[str] = []
        for sql in [_SQL_DAILY_EVOLUTION, _SQL_OVER_300K, _SQL_BY_COUNTRY]:
            r = redshift_data.execute_statement(
                ClusterIdentifier=CLUSTER_ID,
                Database=DATABASE_NAME,
                DbUser=DB_USER,
                Sql=sql.strip(),
            )
            stmt_ids.append(r["Id"])
        return resp(200, {"stmt_ids": stmt_ids})
    except Exception as e:
        msg = str(e)
        if "paused" in msg.lower() or "unavailable" in msg.lower() or "not available" in msg.lower():
            return resp(200, {
                "error": "cluster_paused",
                "message": "El cluster está pausado. Enciéndelo para cargar las estadísticas.",
            })
        return resp(200, {"error": str(e), "message": "Error enviando consultas al cluster."})


def run_transaction_search(body: dict):
    """Submit a transaction search by list of transaction_ids (remesas)."""
    transaction_ids = body.get("transaction_ids", [])
    if not transaction_ids:
        return resp(400, {"error": "transaction_ids is required"})
    if len(transaction_ids) > 5000:
        return resp(400, {"error": "Maximum 5000 transaction_ids per search"})

    clean_ids = []
    for tid in transaction_ids:
        try:
            clean_ids.append(int(str(tid).strip()))
        except (ValueError, TypeError):
            return resp(400, {"error": f"Invalid transaction_id: {tid!r}"})

    run_id = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat()
    user_email = str(body.get("user_email", "")).strip()[:200]
    runs_table.put_item(Item={
        "run_id": run_id,
        "report_name": "transaction_search",
        "status": "RUNNING",
        "params": json.dumps({"transaction_ids": clean_ids, "n_transactions": len(clean_ids)}),
        "started_at": now,
        "user_email": user_email,
        "ttl": int((dt.datetime.utcnow() + dt.timedelta(days=90)).timestamp()),
    })

    lambda_client.invoke(
        FunctionName=REPORT_LAMBDA_NAME,
        InvocationType="Event",
        Payload=json.dumps({
            "report_name": "transaction_search",
            "transaction_ids": clean_ids,
            "run_id": run_id,
            "keep_session": False,
        }),
    )
    return resp(202, {"run_id": run_id, "status": "RUNNING", "n_transactions": len(clean_ids)})


def run_individual_analysis(body: dict):
    """Submit an individual AML analysis for a list of customer_ids."""
    customer_ids = body.get("customer_ids", [])
    if not customer_ids:
        return resp(400, {"error": "customer_ids is required"})
    if len(customer_ids) > 1000:
        return resp(400, {"error": "Maximum 1000 customer_ids per analysis"})

    # Sanitize: accept integers or numeric strings
    clean_ids = []
    for cid in customer_ids:
        try:
            clean_ids.append(int(str(cid).strip()))
        except (ValueError, TypeError):
            return resp(400, {"error": f"Invalid customer_id: {cid!r}"})

    run_id = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat()
    user_email = str(body.get("user_email", "")).strip()[:200]
    runs_table.put_item(Item={
        "run_id": run_id,
        "report_name": "individual_aml_analysis",
        "status": "RUNNING",
        "params": json.dumps({"customer_ids": clean_ids, "n_customers": len(clean_ids)}),
        "started_at": now,
        "user_email": user_email,
        "ttl": int((dt.datetime.utcnow() + dt.timedelta(days=90)).timestamp()),
    })

    lambda_client.invoke(
        FunctionName=REPORT_LAMBDA_NAME,
        InvocationType="Event",
        Payload=json.dumps({
            "report_name": "individual_aml_analysis",
            "customer_ids": clean_ids,
            "run_id": run_id,
            "keep_session": False,
        }),
    )
    return resp(202, {"run_id": run_id, "status": "RUNNING", "n_customers": len(clean_ids)})


def get_dashboard_stats_result(q0: str, q1: str, q2: str):
    """Check status of 3 previously submitted statements; return results for done ones.

    Response keys:
      daily_evolution / over_300k / by_country → list[dict] if done, null if still running
      all_done → True when all 3 are finished (or failed)
    Each done/failed statement is fetched once and never polled again by the Lambda.
    """
    stmt_ids = [q0, q1, q2]
    keys = ["daily_evolution", "over_300k", "by_country"]
    result: dict = {}
    all_done = True

    for stmt_id, key in zip(stmt_ids, keys):
        if not stmt_id:
            result[key] = []
            continue
        try:
            desc = redshift_data.describe_statement(Id=stmt_id)
            status = desc["Status"]
            if status == "FINISHED":
                result[key] = _rs_get_rows(stmt_id) if desc.get("HasResultSet") else []
            elif status in ("FAILED", "ABORTED"):
                result[key] = []
            else:
                # SUBMITTED / PICKED / STARTED — still running
                all_done = False
                result[key] = None   # null signals "still pending" to the frontend
        except Exception:
            result[key] = []         # treat errors as done-empty

    result["all_done"] = all_done
    return resp(200, result)
