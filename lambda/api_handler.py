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
  GET  /analytics/summary      → submit 5 CRM analytics queries; returns stmt_ids immediately
  GET  /analytics/result       → poll analytics results (q0..q4); all_done flag
  GET  /analytics/sla          → submit 3 SLA queries; returns stmt_ids
  GET  /analytics/sla/result   → poll SLA results (q0..q2); all_done flag
  GET  /users                  → list all CRM users with role name
  POST /users                  → create user {email, full_name, role_id}
  PUT  /users/{id}             → update user {full_name, role_id, is_active}
  DELETE /users/{id}           → deactivate user (soft delete)
  GET  /roles                  → list all roles
  GET  /rules                  → list auto-case rules (S3 JSON)
  POST /rules                  → create auto-case rule
  PUT  /rules/{id}             → update auto-case rule
  DELETE /rules/{id}           → delete auto-case rule
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import re
import time
import uuid
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Attr

try:
    from db_redshift import write_audit as _write_audit
except Exception:
    def _write_audit(**kwargs):  # noqa: ANN001
        pass

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
s3 = boto3.client("s3")
redshift = boto3.client("redshift")
redshift_data = boto3.client("redshift-data")
secrets_client = boto3.client("secretsmanager")

SLACK_SECRET_ARN = os.environ.get("SLACK_WEBHOOK_SECRET_ARN", "")

def _get_slack_url() -> str:
    if not SLACK_SECRET_ARN:
        return ""
    try:
        val = secrets_client.get_secret_value(SecretId=SLACK_SECRET_ARN)
        raw = val.get("SecretString", "")
        try:
            return json.loads(raw).get("webhook_url", raw)
        except Exception:
            return raw.strip()
    except Exception:
        return ""

def _post_slack(text: str) -> None:
    url = _get_slack_url()
    if not url:
        return
    import urllib.request as _ur
    payload = json.dumps({"text": text}).encode()
    try:
        _ur.urlopen(_ur.Request(url, data=payload,
                                headers={"Content-Type": "application/json"},
                                method="POST"), timeout=5)
    except Exception:
        pass

CLUSTER_ID = os.environ.get("CLUSTER_IDENTIFIER", "compliance-redshift-cluster")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "dev")
DB_USER = os.environ.get("DB_USER", "awsuser")

RUNS_TABLE_NAME = os.environ["RUNS_TABLE"]
CATALOG_TABLE_NAME = os.environ["CATALOG_TABLE"]
REPORT_LAMBDA_NAME = os.environ["REPORT_LAMBDA"]
S3_BUCKET = os.environ["S3_BUCKET"]

# Phase 8 — Email notifications
GMAIL_USER = os.environ.get("GMAIL_USER", "benjamin.mackenna@global66.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Phase 10 — Auto-case rules S3 key
AUTO_RULES_KEY = "config/auto_case_rules.json"

# Priorización de alertas — mantenedor de documentos a solicitar por alerta
ALERT_DOCS_CONFIG_KEY = "config/alert_document_config.json"
PRIORITY_TEST_TABLE = "compliance.alert_priority_test_data"
_PRIORITY_TO_CASE_PRIORITY = {"P1": "high", "P2": "medium", "P3": "low"}
_ALL_DOC_CATEGORIES = [
    "Origen de fondo", "Comprobantes/Soporte", "Relación/Beneficiario",
    "Domicilio", "Identidad/Datos personales",
]
# Interruptor general del envío automático de solicitudes de documentos.
# Apagado por defecto — se prende explícitamente desde el Admin cuando el
# proceso esté listo para correr sobre alertas reales (hoy solo se usa en el
# botón de prueba, que respeta este mismo interruptor).
PRIORITY_QUEUE_SETTINGS_KEY = "config/priority_queue_settings.json"
# Remitente "enviar como" — alias configurado en la cuenta de GMAIL_USER, no
# necesita una app password propia (ver _send_email).
ALERT_DOCS_FROM_ADDR = "compliance@global66.com"
_DOCS_EMAIL_FRAGMENTS_PATH = Path(__file__).resolve().parent / "solicitud_documentos_fragments.json"

# Mapeo entre las 5 categorías del mantenedor y los 4 puntos numerados de la
# plantilla oficial (algunas categorías comparten punto, ej. "Comprobantes/
# Soporte" ya está cubierto por el punto de origen de fondos). Si se agregan
# categorías nuevas al mantenedor sin actualizar este mapeo, simplemente no
# agregan ningún punto extra al correo (no rompe nada).
_CATEGORY_TO_FRAGMENT = {
    "Domicilio": "domicilio",
    "Identidad/Datos personales": "formulario",
    "Origen de fondo": "origen",
    "Comprobantes/Soporte": "origen",
    "Relación/Beneficiario": "motivo",
}
_FRAGMENT_ORDER = ["domicilio", "formulario", "origen", "motivo"]


def _load_email_fragments() -> dict:
    try:
        return json.loads(_DOCS_EMAIL_FRAGMENTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _render_documentos_email(nombre_completo: str, documentos: list[str] | None = None) -> str:
    """Arma el correo solo con los puntos que corresponden a los documentos
    pedidos — antes mandaba siempre la plantilla completa sin importar qué
    se hubiera elegido."""
    frags = _load_email_fragments()
    if not frags:
        return f"<p>Hola {nombre_completo or 'cliente'}, necesitamos que nos envíes documentación adicional.</p>"

    documentos = documentos or []
    wanted_fragments = {_CATEGORY_TO_FRAGMENT[d] for d in documentos if d in _CATEGORY_TO_FRAGMENT}
    if not wanted_fragments:
        wanted_fragments = set(_FRAGMENT_ORDER)  # sin match conocido -> plantilla completa, por seguridad

    spacer = '<p style="margin: 0px;"><br></p>'
    body_parts = [frags[key] for key in _FRAGMENT_ORDER if key in wanted_fragments and key in frags]
    body = spacer.join(body_parts)

    html = frags.get("header", "") + body + frags.get("footer", "")
    return html.replace("{{nombre_completo}}", nombre_completo or "cliente")

runs_table = dynamodb.Table(RUNS_TABLE_NAME)
catalog_table = dynamodb.Table(CATALOG_TABLE_NAME)

# ---------------------------------------------------------------------------
# Built-in report definitions (mirrors REPORT_CONFIGS in handler.py)
# ---------------------------------------------------------------------------
BUILTIN_REPORTS = [
    # ─── Priorización de Alertas (datos de prueba) ──────────────────────────
    {
        "report_name": "priority_queue_test_alerts",
        "display_name": "Priorización de Alertas — Datos de Prueba",
        "description": "Priorización de alertas (datos de prueba): 5 filas ficticias con prioridad ya asignada, para probar el flujo manual completo (documentos, correo, caso) sin tocar datos reales.",
        "category": "priorizacion",
        "category_label": "Priorización (Pruebas)",
        "is_custom": False,
        "params": [],
    },
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
    """Send a notification email via Gmail SMTP when an alert is assigned."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    to_email = str(body.get("to_email", "")).strip()
    to_name = str(body.get("to_name", "")).strip()
    assigned_by = str(body.get("assigned_by", "")).strip()
    entity_value = str(body.get("entity_value", "")).strip()
    entity_field = str(body.get("entity_field", "")).strip()
    report_name = str(body.get("report_name", "")).strip()
    note = str(body.get("note", "")).strip()

    if not to_email or "@" not in to_email:
        return resp(400, {"error": "to_email is required"})

    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_app_password:
        return resp(500, {"error": "GMAIL_USER or GMAIL_APP_PASSWORD not configured"})

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
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Compliance Global66 <{gmail_user}>"
        msg["To"] = to_email
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, gmail_app_password)
            smtp.sendmail(gmail_user, [to_email], msg.as_bytes())

        return resp(200, {"message": "Notification sent"})
    except Exception as e:
        return resp(500, {"error": f"Failed to send email: {e}"})


_B2C_QUERY = """
WITH latest_kyc_document AS (
    SELECT kd.customer_id, kd.document_number, kd.document_type,
        kd.country_code AS document_country_code, kd.approval_status,
        ROW_NUMBER() OVER (PARTITION BY kd.customer_id ORDER BY COALESCE(kd.updated_at, kd.created_at) DESC) AS rn
    FROM "db_prod"."customer"."kyc_document" kd WHERE kd.document_number IS NOT NULL
),
latest_customer_compliance AS (
    SELECT cc.customer_id, cc.compliance_status, cc.status_created_at, cc.compliance_agent, cc.compliance_channel,
        ROW_NUMBER() OVER (PARTITION BY cc.customer_id ORDER BY cc.status_created_at DESC) AS rn
    FROM "db_prod"."customer"."compliance" cc
),
latest_customer_kyc AS (
    SELECT ck.customer_id, ck.kyc_status, ck.step_onboarding_id, ck.created_at AS kyc_created_at,
        ROW_NUMBER() OVER (PARTITION BY ck.customer_id ORDER BY ck.created_at DESC) AS rn
    FROM "db_prod"."customer"."customer_kyc" ck
),
latest_customer_work AS (
    SELECT cw.customer_id, cw.profession, cw.work_position, cw.workplace,
        ROW_NUMBER() OVER (PARTITION BY cw.customer_id ORDER BY COALESCE(cw.updated_at, cw.created_at) DESC) AS rn
    FROM "db_prod"."customer"."customer_work" cw
),
latest_customer_segmentation AS (
    SELECT s.customer_id, s.segmentation,
        ROW_NUMBER() OVER (PARTITION BY s.customer_id ORDER BY s.last_updated_date DESC) AS rn
    FROM "db_prod"."customer"."segmentation" s
),
latest_virtual_account AS (
    SELECT cva.customer_id, cva.id AS customer_virtual_account_id, cva.account_id,
        cva.virtual_account_number, cva.global_account_number,
        cva.country_code AS virtual_account_country_code, cva.virtual_account_type,
        cva.is_enabled, cva.created_at AS virtual_account_created_at,
        ROW_NUMBER() OVER (PARTITION BY cva.customer_id ORDER BY cva.created_at DESC) AS rn
    FROM "db_prod"."product_gateway"."customer_virtual_account" cva
)
SELECT c.customer_id, c.name AS nombre, c.last_name AS apellido, c.email, c.phone_number, c.calling_code,
    c.country_code AS pais_residencia, c.nationality_code AS nacionalidad, c.risk_level, c.created_date AS fecha_onboarding,
    kd.document_number AS dni, kd.document_type AS tipo_documento, kd.document_country_code AS pais_documento, kd.approval_status AS estado_documento,
    lc.compliance_status, lc.status_created_at AS compliance_status_created_at, lc.compliance_agent, lc.compliance_channel,
    ck.kyc_status, sok.step AS onboarding_step, ck.kyc_created_at,
    seg.segmentation, cw.profession, cw.work_position, cw.workplace,
    va.customer_virtual_account_id, va.account_id, va.virtual_account_number, va.global_account_number,
    va.virtual_account_country_code, va.virtual_account_type, va.is_enabled AS virtual_account_active, va.virtual_account_created_at,
    DATEDIFF(day, c.created_date, va.virtual_account_created_at) AS dias_desde_onboarding_hasta_cuenta_virtual,
    DATEDIFF(day, c.created_date, CURRENT_DATE) AS dias_desde_onboarding
FROM "db_prod"."customer"."customer_v2" c
LEFT JOIN latest_kyc_document kd ON c.customer_id = kd.customer_id AND kd.rn = 1
LEFT JOIN latest_customer_compliance lc ON c.customer_id = lc.customer_id AND lc.rn = 1
LEFT JOIN latest_customer_kyc ck ON c.customer_id = ck.customer_id AND ck.rn = 1
LEFT JOIN "db_prod"."customer"."step_onboarding_kyc" sok ON ck.step_onboarding_id = sok.id
LEFT JOIN latest_customer_work cw ON c.customer_id = cw.customer_id AND cw.rn = 1
LEFT JOIN latest_customer_segmentation seg ON c.customer_id = seg.customer_id AND seg.rn = 1
LEFT JOIN latest_virtual_account va ON c.customer_id = va.customer_id AND va.rn = 1
WHERE sok.step = 'HOME' AND ck.kyc_status = 'APPROVED'
__FILTER__
ORDER BY c.created_date DESC
LIMIT 5
"""

_B2B_QUERY = """
SELECT co.company_id, co.name AS company_name, co.identification_number AS company_document_number,
    co.identification_type AS company_document_type, co.username, co.phone_country_code, co.phone_number,
    co.compliance_status, co.compliance_status_comment,
    co.kyc_stage_1, co.kyc_stage_1_approved_date, co.kyc_stage_1_rejected_date, co.kyc_stage_1_requested_date, co.kyc_stage_1_comment,
    co.kyc_stage_2, co.kyc_stage_2_approved_date, co.kyc_stage_2_rejected_date, co.kyc_stage_2_requested_date, co.kyc_stage_2_comment,
    co.kyc_stage_3, co.kyc_stage_3_approved_date, co.kyc_stage_3_rejected_date, co.kyc_stage_3_requested_date, co.kyc_stage_3_comment,
    co.risk_level, co.risk_level_regcheq, co.dni_regcheq,
    co.activity AS company_activity_raw, act.name AS activity_name, act.risk_level AS activity_risk_level, ind.name AS industry_name,
    co.activity_start_date, co.company_financial_activity_id, co.ind_activity,
    co.monthly_income, co.monthly_expenses, co.estimated_annual_billings, co.total_assets, co.total_liabilities,
    co.shipment_amounts, co.shipment_frequency, co.purpose_use,
    co.has_board_directors, co.has_joint_administration, co.has_partners_ten_sharedholding,
    co.legal_representatives_count, co.institutional, co.multi_user_enabled, co.crs, co.fatca,
    ac.country AS company_address_country, ac.state AS company_address_state, ac.city AS company_address_city,
    ac.district AS company_address_district, ac.street AS company_address_street, ac.number AS company_address_number,
    ac.apt AS company_address_apt, ac.floor AS company_address_floor, ac.postal_code AS company_address_postal_code,
    co.create_at AS company_created_at, co.record_created_at,
    DATEDIFF(day, co.create_at, CURRENT_DATE) AS dias_desde_creacion_empresa
FROM "db_prod"."company"."company" AS co
LEFT JOIN "db_prod"."company"."activity" AS act ON co.ind_activity = act.id
LEFT JOIN "db_prod"."company"."industry" AS ind ON act.industry_id = ind.id
LEFT JOIN "db_prod"."company"."address_country" AS ac ON co.company_address_country = ac.address_id
__WHERE__
ORDER BY co.create_at DESC
LIMIT 5
"""


def search_customer_b2c(body: dict):
    identifier = str(body.get("identifier", "")).strip()
    if not identifier:
        return resp(400, {"error": "identifier is required"})
    if any(c in identifier for c in ("'", ";", "--", "\\")):
        return resp(400, {"error": "Invalid identifier"})
    safe = identifier.replace("'", "''")
    if identifier.isdigit():
        extra = f"AND c.customer_id = {int(identifier)}"
    elif "@" in identifier:
        extra = f"AND LOWER(c.email) = LOWER('{safe}')"
    else:
        extra = f"AND kd.document_number = '{safe}'"
    sql = _B2C_QUERY.replace("__FILTER__", extra)
    rows = _rs_exec_multi([sql], timeout_s=90)[0]
    return resp(200, {"rows": rows, "count": len(rows)})


def search_customer_b2b(body: dict):
    identifier = str(body.get("identifier", "")).strip()
    if not identifier:
        return resp(400, {"error": "identifier is required"})
    if any(c in identifier for c in ("'", ";", "--", "\\")):
        return resp(400, {"error": "Invalid identifier"})
    safe = identifier.replace("'", "''")
    if identifier.isdigit():
        where = f"WHERE co.company_id = {int(identifier)}"
    else:
        where = f"WHERE co.identification_number = '{safe}' OR co.username = '{safe}'"
    sql = _B2B_QUERY.replace("__WHERE__", where)
    rows = _rs_exec_multi([sql], timeout_s=90)[0]
    return resp(200, {"rows": rows, "count": len(rows)})


# ---------------------------------------------------------------------------
# AI generate proxy — calls Gemini using AI_API_KEY env var
# ---------------------------------------------------------------------------
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def ai_generate(body: dict):
    import urllib.request as _ur
    api_key = os.environ.get("AI_API_KEY", "")
    if not api_key:
        return resp(500, {"error": "AI_API_KEY not configured"})
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        return resp(400, {"error": "prompt is required"})
    temperature = float(body.get("temperature", 0.3))
    max_tokens = int(body.get("max_tokens", 2048))
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }).encode()
    url = f"{_GEMINI_URL}?key={api_key}"
    req = _ur.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _ur.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return resp(200, {"text": text})
    except _ur.HTTPError as e:
        err_body = e.read().decode(errors="ignore")
        try:
            err_msg = json.loads(err_body).get("error", {}).get("message", err_body)
        except Exception:
            err_msg = err_body
        return resp(502, {"error": err_msg})


# ---------------------------------------------------------------------------
# CUSTOMER CONTEXT — dossier para la IA (CRM siempre + transacciones si cluster on)
# ---------------------------------------------------------------------------
_ALLOWED_DAYS = (5, 15, 30, 60)


def _cluster_available() -> bool:
    try:
        r = redshift.describe_clusters(ClusterIdentifier=CLUSTER_ID)
        return r["Clusters"][0]["ClusterStatus"] == "available"
    except Exception:
        return False


def _customer_cashcall_sql(direction: str, customer_id: str, days: int) -> str:
    """Cash calls de un cliente. direction: 'DR' (pay out) | 'CR' (pay in).
    customer_id ya validado como dígitos; days dentro de _ALLOWED_DAYS."""
    return f"""
SELECT cc.cash_call_id, cc.external_reference_number,
    cc.customer_id, c.email, c.name, c.last_name,
    cc.creation_date, cc.paid_date, cc.type, cc.status, cc.currency_code,
    cc.amount, cc.origin_amount_usd, cc.destiny_amount_usd,
    cc.remitter_name, cc.remitter_lastname, cc.remitter_dni, cc.remitter_email,
    cc.business_bank_id, bb.bank_code, bb.bank_name
FROM "db_prod"."treasury"."cash_call" AS cc
LEFT JOIN "db_prod"."customer"."customer_v2" AS c
    ON cc.customer_id::VARCHAR = c.customer_id::VARCHAR
LEFT JOIN "db_prod"."treasury"."business_bank" AS bb
    ON cc.business_bank_id = bb.business_bank_id
WHERE cc.type = '{direction}'
  AND cc.customer_id::VARCHAR = '{customer_id}'
  AND cc.creation_date >= DATEADD(day, -{days}, CURRENT_DATE)
  AND cc.status = 'PAID'
ORDER BY cc.creation_date DESC
"""


def _tx_summary(rows: list, sample: int = 40) -> dict:
    """Resumen + muestra acotada (para no inflar el prompt de la IA)."""
    def _fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    total_origin = sum(_fnum(r.get("origin_amount_usd")) for r in rows)
    total_destiny = sum(_fnum(r.get("destiny_amount_usd")) for r in rows)
    return {
        "count": len(rows),
        "total_origin_usd": round(total_origin, 2),
        "total_destiny_usd": round(total_destiny, 2),
        "rows": rows[:sample],
        "truncated": len(rows) > sample,
    }


def _customer_crm_dossier(customer_id: str) -> dict:
    """Historial CRM del cliente desde S3 (siempre disponible)."""
    alerts = _crm_list("alerts")
    cust_alerts = [a for a in alerts
                   if str(a.get("entity_value", "")) == customer_id
                   and (a.get("entity_field") in ("customer_id", "", None) or True)]
    reports = sorted({a.get("report_name", "") for a in cust_alerts if a.get("report_name")})

    cases = _crm_list("cases")
    linked_ids = {a.get("case_id") for a in cust_alerts if a.get("case_id")}
    cust_cases = [c for c in cases
                  if str(c.get("entity_id", "")) == customer_id or c.get("case_id") in linked_ids]

    return {
        "alert_count": len(cust_alerts),
        "recurrent": len(cust_alerts) > 1,
        "combines_alerts": len(reports) > 1,
        "distinct_reports": reports,
        "alerts": [{
            "report_name": a.get("report_name", ""), "reason": a.get("reason", ""),
            "status": a.get("status", ""), "priority": a.get("priority", "medium"),
            "created_at": a.get("created_at", ""), "entity_field": a.get("entity_field", ""),
        } for a in sorted(cust_alerts, key=lambda x: x.get("created_at", ""), reverse=True)],
        "case_count": len(cust_cases),
        "cases": [{
            "case_id": c.get("case_id", ""), "title": c.get("title", ""),
            "status": c.get("status", ""), "priority": c.get("priority", ""),
            "created_at": c.get("created_at", ""),
        } for c in cust_cases],
    }


def customer_context(customer_id: str, days: int):
    customer_id = str(customer_id or "").strip()
    if not customer_id.isdigit():
        return resp(400, {"error": "customer_id debe ser numérico"})
    if days not in _ALLOWED_DAYS:
        days = 30

    crm = _customer_crm_dossier(customer_id)

    tx: dict = {"available": False, "reason": "cluster_paused"}
    if _cluster_available():
        try:
            payout = _rs_exec(_customer_cashcall_sql("DR", customer_id, days))
            payin = _rs_exec(_customer_cashcall_sql("CR", customer_id, days))
            tx = {"available": True, "days": days,
                  "payout": _tx_summary(payout), "payin": _tx_summary(payin)}
        except Exception as e:
            tx = {"available": False, "reason": "error", "error": str(e)}

    return resp(200, {"customer_id": customer_id, "days": days, "crm": crm, "transactions": tx})


# ---------------------------------------------------------------------------
# CASE EXCEL EXPORT
# ---------------------------------------------------------------------------

def export_case(case_id: str):
    """Generate an Excel workbook for a case and return a 1h presigned S3 URL."""
    import io
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return resp(500, {"error": "openpyxl not available"})

    case = _crm_get("cases", case_id)
    if case is None:
        return resp(404, {"error": "Case not found"})

    notes = sorted(case.get("notes", []), key=lambda n: n.get("created_at", ""))
    alerts = [a for a in _crm_list("alerts") if a.get("case_id") == case_id]

    wb = openpyxl.Workbook()
    HEADER_FILL = PatternFill("solid", fgColor="1E293B")
    HEADER_FONT = Font(bold=True, color="F97316", size=11)
    LABEL_FONT  = Font(bold=True, color="94A3B8")

    # ── Sheet 1: Resumen ──
    ws = wb.active
    ws.title = "Resumen"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60

    def add_row(label, value, row):
        c_a = ws.cell(row=row, column=1, value=label)
        c_a.font = LABEL_FONT
        c_b = ws.cell(row=row, column=2, value=str(value) if value else "—")
        c_b.alignment = Alignment(wrap_text=True)
        return row + 1

    r = 1
    ws.cell(r, 1, "REPORTE DE CASO — WatchTower AML").font = Font(bold=True, size=14, color="F97316")
    ws.merge_cells(f"A{r}:B{r}")
    r += 2
    for label, key in [
        ("ID del Caso", "case_id"), ("Título", "title"), ("Descripción", "description"),
        ("Estado", "status"), ("Prioridad", "priority"), ("Tipo entidad", "entity_type"),
        ("ID entidad", "entity_id"), ("Reporte origen", "report_name"),
        ("Asignado a", "assigned_to"), ("Creado por", "created_by"),
        ("Fecha creación", "created_at"), ("Última actualización", "updated_at"),
        ("Fecha cierre", "closed_at"),
    ]:
        r = add_row(label, case.get(key, ""), r)

    # ── Sheet 2: Notas ──
    ws2 = wb.create_sheet("Notas")
    ws2.sheet_view.showGridLines = False
    headers = ["#", "Autor", "Fecha", "Contenido"]
    widths   = [5, 30, 22, 80]
    for col, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws2.cell(1, col, h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        ws2.column_dimensions[cell.column_letter].width = w
    for i, n in enumerate(notes, 1):
        ws2.append([i, n.get("author_email",""), n.get("created_at",""), n.get("content","")])
        ws2.cell(i+1, 4).alignment = Alignment(wrap_text=True)

    # ── Sheet 3: Alertas vinculadas ──
    ws3 = wb.create_sheet("Alertas vinculadas")
    ws3.sheet_view.showGridLines = False
    a_headers = ["ID Alerta", "Campo", "Valor", "Razón", "Reporte", "Fecha", "Estado"]
    a_widths   = [36, 16, 24, 40, 24, 22, 12]
    for col, (h, w) in enumerate(zip(a_headers, a_widths), 1):
        cell = ws3.cell(1, col, h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        ws3.column_dimensions[cell.column_letter].width = w
    for a in alerts:
        ws3.append([a.get("alert_id",""), a.get("entity_field",""), a.get("entity_value",""),
                    a.get("reason",""), a.get("report_name",""), a.get("created_at",""), a.get("status","")])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    key = f"case-reports/{case_id}/caso_{case_id[:8]}_{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.xlsx"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=buf.getvalue(),
                  ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    url = s3.generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": key},
                                    ExpiresIn=3600)
    return resp(200, {"download_url": url, "filename": key.split("/")[-1]})


# ---------------------------------------------------------------------------
# ENTITY TIMELINE SEARCH
# ---------------------------------------------------------------------------

def search_entity_timeline(query: str, limit: int = 100):
    """Search alerts + cases for an entity value. Returns unified timeline sorted by date."""
    if not query or len(query) < 3:
        return resp(400, {"error": "query must be at least 3 characters"})
    q = query.strip().lower()
    try:
        alert_rows = []
        for a in _crm_list("alerts"):
            if q in (a.get("entity_value", "") or "").lower() or q in (a.get("reason", "") or "").lower():
                alert_rows.append({
                    "source_type": "alert", "source_id": a.get("alert_id", ""),
                    "entity_value": a.get("entity_value", ""), "detail": a.get("reason", ""),
                    "report_name": a.get("report_name", ""), "event_date": a.get("created_at", ""),
                    "status": a.get("status", ""),
                })
        case_rows = []
        for c in _crm_list("cases"):
            hay = (c.get("title", ""), c.get("entity_id", ""), c.get("description", ""))
            if any(q in (h or "").lower() for h in hay):
                case_rows.append({
                    "source_type": "case", "source_id": c.get("case_id", ""),
                    "entity_value": c.get("entity_id", ""), "detail": c.get("title", ""),
                    "report_name": c.get("report_name", ""), "event_date": c.get("created_at", ""),
                    "status": c.get("status", ""),
                })
        combined = sorted(alert_rows + case_rows,
                          key=lambda x: x.get("event_date", ""), reverse=True)
        return resp(200, {"results": combined[:int(limit)], "query": query,
                          "alert_count": len(alert_rows), "case_count": len(case_rows)})
    except Exception as e:
        return resp(200, {"results": [], "warning": str(e), "query": query})


# ---------------------------------------------------------------------------
# AUDIT LOG
# ---------------------------------------------------------------------------

def get_audit_log(limit: int = 200, entity_type: str | None = None,
                  user_email: str | None = None, action: str | None = None):
    """Read the audit log from S3 with optional filters. Most recent first."""
    try:
        rows = []
        for e in _crm_list("audit"):
            if entity_type and e.get("entity_type") != entity_type:
                continue
            if user_email and e.get("user_email") != user_email:
                continue
            if action and action.lower() not in (e.get("action", "") or "").lower():
                continue
            rows.append({
                "log_id": e.get("log_id", ""),
                "user_email": e.get("user_email", ""),
                "action": e.get("action", ""),
                "entity_type": e.get("entity_type", ""),
                "entity_id": e.get("entity_id", ""),
                "created_at": e.get("created_at", ""),
            })
        rows.sort(key=lambda x: x["created_at"], reverse=True)
        return resp(200, {"entries": rows[:int(limit)]})
    except Exception as e:
        return resp(200, {"entries": [], "warning": str(e)})


# ---------------------------------------------------------------------------
# SCHEDULER (EventBridge rules)
# ---------------------------------------------------------------------------

_events = boto3.client("events", region_name=os.environ.get("AWS_REGION", "us-east-1"))

def get_schedules():
    """List EventBridge rules tagged for this project."""
    try:
        result = _events.list_rules(NamePrefix="compliance-")
        rules = []
        for r in result.get("Rules", []):
            rules.append({
                "name":        r["Name"],
                "state":       r["State"],
                "description": r.get("Description", ""),
                "schedule":    r.get("ScheduleExpression", ""),
            })
        return resp(200, {"schedules": rules})
    except Exception as e:
        return resp(200, {"schedules": [], "warning": str(e)})


def toggle_schedule(name: str, body: dict):
    """Enable or disable an EventBridge rule."""
    action = body.get("action", "").lower()  # "enable" | "disable"
    if action not in ("enable", "disable"):
        return resp(400, {"error": "action must be 'enable' or 'disable'"})
    try:
        if action == "enable":
            _events.enable_rule(Name=name)
        else:
            _events.disable_rule(Name=name)
        return resp(200, {"message": f"Rule '{name}' {action}d"})
    except Exception as e:
        return resp(500, {"error": str(e)})


def update_schedule_expression(name: str, body: dict):
    """Update cron/rate expression of an EventBridge rule."""
    expression = body.get("schedule_expression", "").strip()
    if not expression:
        return resp(400, {"error": "schedule_expression is required"})
    try:
        existing = _events.describe_rule(Name=name)
        _events.put_rule(
            Name=name,
            ScheduleExpression=expression,
            State=existing.get("State", "ENABLED"),
            Description=existing.get("Description", ""),
        )
        return resp(200, {"message": f"Rule '{name}' expression updated to: {expression}"})
    except Exception as e:
        return resp(500, {"error": str(e)})


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
# Admin — verifica capacidad de escritura en S3 (diagnóstico de permisos)
# ---------------------------------------------------------------------------
def admin_s3check():
    key = "crm/_s3check.json"
    result = {"bucket": S3_BUCKET}
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=b'{"ok":true}',
                      ContentType="application/json")
        result["write"] = True
    except Exception as e:
        result["write"] = False
        result["error"] = str(e)
        return resp(200, result)
    try:
        s3.get_object(Bucket=S3_BUCKET, Key=key)
        result["read"] = True
    except Exception as e:
        result["read"] = False
        result["read_error"] = str(e)
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=key)
        result["delete"] = True
    except Exception as e:
        result["delete"] = False
        result["delete_error"] = str(e)
    return resp(200, result)


def _str_to_epoch(ts) -> int:
    if not ts:
        return 0
    s = str(ts)[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return int(dt.datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    return 0


def admin_migrate(body: dict):
    """One-time copy of CRM data from Redshift → S3. Runs inside the Lambda
    (has both redshift-data + S3 perms). Requires cluster ONLINE. Idempotent."""
    module = (body.get("module") or "").strip()
    migrators = {
        "whitelist": _migrate_whitelist_to_s3,
        "alerts": _migrate_alerts_to_s3,
        "cases": _migrate_cases_to_s3,
        "users": _migrate_users_to_s3,
    }
    if module == "all":
        out = {}
        for name, fn in migrators.items():
            try:
                out[name] = fn()
            except Exception as e:
                out[name] = f"error: {e}"
        return resp(200, {"migrated": out})
    fn = migrators.get(module)
    if not fn:
        return resp(400, {"error": f"unknown module '{module}'",
                          "available": list(migrators) + ["all"]})
    try:
        return resp(200, {"module": module, "migrated": fn()})
    except Exception as e:
        return resp(500, {"module": module, "error": str(e)})


def _migrate_whitelist_to_s3() -> int:
    rows = _rs_exec(
        "SELECT whitelist_id, entity_field, entity_value, duration_days, reason, scope, "
        "report_name, created_at::VARCHAR AS created_at, expires_at::VARCHAR AS expires_at "
        "FROM compliance.whitelist"
    )
    n = 0
    for r in rows:
        wid = r.get("whitelist_id")
        if not wid:
            continue
        exp_str = str(r.get("expires_at") or "")[:19]
        _crm_put("whitelist", str(wid), {
            "whitelist_id": str(wid),
            "entity_field": r.get("entity_field") or "",
            "entity_value": r.get("entity_value") or "",
            "duration_days": int(r.get("duration_days") or 0),
            "reason": r.get("reason") or "",
            "scope": r.get("scope") or "global",
            "report_name": r.get("report_name") or "",
            "created_at": str(r.get("created_at") or "")[:19],
            "expires_at": _str_to_epoch(exp_str),
            "expires_at_str": exp_str,
        })
        n += 1
    return n


def _migrate_alerts_to_s3() -> int:
    rows = _rs_exec(
        "SELECT alert_id, entity_field, entity_value, reason, report_name, row_data, "
        "created_at::VARCHAR AS created_at, status, "
        "COALESCE(reviewed_at::VARCHAR, '') AS reviewed_at, "
        "COALESCE(priority, 'medium') AS priority, "
        "COALESCE(assigned_to, '') AS assigned_to, "
        "COALESCE(reviewed_by, '') AS reviewed_by, "
        "COALESCE(notes, '') AS notes "
        "FROM compliance.alerts"
    )
    n = 0
    for r in rows:
        aid = r.get("alert_id")
        if not aid:
            continue
        _crm_put("alerts", str(aid), {
            "alert_id": str(aid),
            "entity_field": r.get("entity_field") or "",
            "entity_value": r.get("entity_value") or "",
            "reason": r.get("reason") or "",
            "report_name": r.get("report_name") or "",
            "row_data": r.get("row_data") or "",
            "created_at": str(r.get("created_at") or "")[:19],
            "status": r.get("status") or "active",
            "reviewed_at": str(r.get("reviewed_at") or "")[:19],
            "priority": r.get("priority") or "medium",
            "assigned_to": r.get("assigned_to") or "",
            "reviewed_by": r.get("reviewed_by") or "",
            "notes": r.get("notes") or "",
        })
        n += 1
    return n


def _migrate_cases_to_s3() -> int:
    cases = _rs_exec(
        "SELECT case_id, title, description, status, priority, entity_type, entity_id, "
        "report_name, COALESCE(assigned_to,'') AS assigned_to, created_by, "
        "created_at::VARCHAR AS created_at, updated_at::VARCHAR AS updated_at, "
        "COALESCE(closed_at::VARCHAR,'') AS closed_at FROM crm.cases"
    )
    notes = _rs_exec(
        "SELECT note_id, case_id, COALESCE(author_email,'') AS author_email, content, "
        "created_at::VARCHAR AS created_at FROM crm.case_notes"
    )
    notes_by_case: dict[str, list] = {}
    for nt in notes:
        notes_by_case.setdefault(str(nt.get("case_id")), []).append({
            "note_id": str(nt.get("note_id") or ""),
            "case_id": str(nt.get("case_id") or ""),
            "author_email": nt.get("author_email") or "",
            "content": nt.get("content") or "",
            "created_at": str(nt.get("created_at") or "")[:19],
        })
    n = 0
    for c in cases:
        cid = c.get("case_id")
        if not cid:
            continue
        cnotes = sorted(notes_by_case.get(str(cid), []), key=lambda x: x["created_at"])
        _crm_put("cases", str(cid), {
            "case_id": str(cid),
            "title": c.get("title") or "",
            "description": c.get("description") or "",
            "status": c.get("status") or "open",
            "priority": c.get("priority") or "medium",
            "entity_type": c.get("entity_type") or "",
            "entity_id": c.get("entity_id") or "",
            "report_name": c.get("report_name") or "",
            "assigned_to": c.get("assigned_to") or "",
            "created_by": c.get("created_by") or "",
            "created_at": str(c.get("created_at") or "")[:19],
            "updated_at": str(c.get("updated_at") or "")[:19],
            "closed_at": str(c.get("closed_at") or "")[:19],
            "notes": cnotes,
        })
        n += 1
    return n


def _migrate_users_to_s3() -> int:
    rows = _rs_exec(
        "SELECT u.email, COALESCE(u.full_name,'') AS full_name, u.is_active, "
        "COALESCE(r.name,'analyst') AS role_name, "
        "COALESCE(u.last_login_at::VARCHAR,'') AS last_login_at "
        "FROM crm.users u LEFT JOIN crm.roles r ON u.role_id = r.id"
    )
    n = 0
    for r in rows:
        email = (r.get("email") or "").strip()
        if not email:
            continue
        _crm_put("users", email, {
            "email": email,
            "full_name": r.get("full_name") or email,
            "is_active": bool(r.get("is_active", True)),
            "role_name": r.get("role_name") or "analyst",
            "last_login_at": str(r.get("last_login_at") or "")[:19],
        })
        n += 1
    return n


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
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
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
        # POST /analyze/customer/b2c
        if method == "POST" and parts == ["analyze", "customer", "b2c"]:
            return search_customer_b2c(body)
        # POST /analyze/customer/b2b
        if method == "POST" and parts == ["analyze", "customer", "b2b"]:
            return search_customer_b2b(body)

        # POST /search/transactions
        if method == "POST" and parts == ["search", "transactions"]:
            return run_transaction_search(body)
        # POST /search/wallet
        if method == "POST" and parts == ["search", "wallet"]:
            return run_wallet_search(body)

        # POST /cluster/wake
        if method == "POST" and parts == ["cluster", "wake"]:
            return wake_cluster()

        # POST /cluster/pause
        if method == "POST" and parts == ["cluster", "pause"]:
            return pause_cluster_api()

        # POST /admin/s3check — verifica si la Lambda puede escribir/leer/borrar en S3
        if method == "POST" and parts == ["admin", "s3check"]:
            return admin_s3check()

        # POST /admin/migrate — copia one-time de datos Redshift→S3 (cluster online)
        if method == "POST" and parts == ["admin", "migrate"]:
            return admin_migrate(body)

        # GET /whitelist
        if method == "GET" and parts == ["whitelist"]:
            return get_whitelist()
        # POST /whitelist
        if method == "POST" and parts == ["whitelist"]:
            return add_to_whitelist(body)
        # DELETE /whitelist/{id}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "whitelist":
            return remove_from_whitelist(parts[1])

        # ---------------------------------------------------------------------------
        # PRIORIZACIÓN DE ALERTAS — mantenedor de documentos + corrida de prueba
        # ---------------------------------------------------------------------------
        # GET /alert-document-config
        if method == "GET" and parts == ["alert-document-config"]:
            return get_alert_document_config()
        # POST /alert-document-config
        if method == "POST" and parts == ["alert-document-config"]:
            return create_alert_document_config(body)
        # PUT /alert-document-config/{id}
        if method in ("PUT", "POST") and len(parts) == 2 and parts[0] == "alert-document-config":
            return update_alert_document_config(parts[1], body)
        # DELETE /alert-document-config/{id}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "alert-document-config":
            return delete_alert_document_config(parts[1])
        # POST /alert-prioritization/test-run
        if method == "POST" and parts == ["alert-prioritization", "test-run"]:
            return run_alert_prioritization_test(body)
        # GET /alert-prioritization/settings
        if method == "GET" and parts == ["alert-prioritization", "settings"]:
            return get_priority_queue_settings()
        # POST /alert-prioritization/settings
        if method == "POST" and parts == ["alert-prioritization", "settings"]:
            return update_priority_queue_settings(body)
        # POST /alert-prioritization/run — flujo real (no datos de prueba)
        if method == "POST" and parts == ["alert-prioritization", "run"]:
            return run_alert_prioritization_real(body)
        # POST /alert-prioritization/send-manual — boton manual, documentos a eleccion
        if method == "POST" and parts == ["alert-prioritization", "send-manual"]:
            return send_manual_document_request(body)
        # POST /cases/{id}/documentos-checklist
        if method == "POST" and len(parts) == 3 and parts[0] == "cases" and parts[2] == "documentos-checklist":
            return update_case_document_checklist(parts[1], body)

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
        if method in ("PUT", "POST") and len(parts) == 3 and parts[0] == "alerts" and parts[2] == "review":
            return review_alert(parts[1], body)
        # PUT /alerts/{id}/assign
        if method in ("PUT", "POST") and len(parts) == 3 and parts[0] == "alerts" and parts[2] == "assign":
            return assign_alert(parts[1], body)
        # PUT /alerts/{id}/notes
        if method in ("PUT", "POST") and len(parts) == 3 and parts[0] == "alerts" and parts[2] == "notes":
            return update_alert_notes(parts[1], body)
        # DELETE /alerts/{id}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "alerts":
            return delete_alert(parts[1])

        # GET /crm/users
        if method == "GET" and parts == ["crm", "users"]:
            return get_crm_users()

        # ---------------------------------------------------------------------------
        # CASES CRM
        # ---------------------------------------------------------------------------
        # GET /cases
        if method == "GET" and parts == ["cases"]:
            qs = event.get("queryStringParameters") or {}
            return get_cases(qs.get("status"), qs.get("priority"), qs.get("assigned_to"))
        # POST /cases
        if method == "POST" and parts == ["cases"]:
            return create_case(body)
        # GET /cases/{id}
        if method == "GET" and len(parts) == 2 and parts[0] == "cases":
            return get_case_detail(parts[1])
        # PUT /cases/{id}  (update title / description / priority)
        if method in ("PUT", "POST") and len(parts) == 2 and parts[0] == "cases":
            return update_case(parts[1], body)
        # PUT /cases/{id}/status
        if method in ("PUT", "POST") and len(parts) == 3 and parts[0] == "cases" and parts[2] == "status":
            return update_case_status(parts[1], body)
        # PUT /cases/{id}/assign
        if method in ("PUT", "POST") and len(parts) == 3 and parts[0] == "cases" and parts[2] == "assign":
            return update_case_assign(parts[1], body)
        # POST /cases/{id}/notes
        if method == "POST" and len(parts) == 3 and parts[0] == "cases" and parts[2] == "notes":
            return add_case_note(parts[1], body)
        # POST /cases/{id}/attachments/upload-url
        if method == "POST" and len(parts) == 4 and parts[0] == "cases" and parts[2] == "attachments" and parts[3] == "upload-url":
            return get_attachment_upload_url(parts[1], body)
        # POST /cases/{id}/attachments
        if method == "POST" and len(parts) == 3 and parts[0] == "cases" and parts[2] == "attachments":
            return add_case_attachment(parts[1], body)
        # GET /cases/{id}/attachments/{attachment_id}/download-url
        if method == "GET" and len(parts) == 5 and parts[0] == "cases" and parts[2] == "attachments" and parts[4] == "download-url":
            return get_attachment_download_url(parts[1], parts[3])
        # DELETE /cases/{id}/attachments/{attachment_id}
        if method == "DELETE" and len(parts) == 4 and parts[0] == "cases" and parts[2] == "attachments":
            return delete_case_attachment(parts[1], parts[3])
        # POST /alerts/{id}/link-case
        if method == "POST" and len(parts) == 3 and parts[0] == "alerts" and parts[2] == "link-case":
            return link_alert_to_case(parts[1], body)

        # POST /alerts/notify
        if method == "POST" and parts == ["alerts", "notify"]:
            return notify_alert(body)

        if method == "POST" and parts == ["ai", "generate"]:
            return ai_generate(body)

        # GET /customer/context?customer_id=X&days=N  — dossier CRM + transacciones para la IA
        if method == "GET" and parts == ["customer", "context"]:
            qs = event.get("queryStringParameters") or {}
            try:
                days = int(qs.get("days", 30) or 30)
            except (ValueError, TypeError):
                days = 30
            return customer_context(qs.get("customer_id", ""), days)

        # GET /cases/{id}/export
        if method == "GET" and len(parts) == 3 and parts[0] == "cases" and parts[2] == "export":
            return export_case(parts[1])

        # GET /search/entity
        if method == "GET" and parts == ["search", "entity"]:
            qs = event.get("queryStringParameters") or {}
            return search_entity_timeline(qs.get("q", ""), int(qs.get("limit", 100)))

        # GET /audit
        if method == "GET" and parts == ["audit"]:
            qs = event.get("queryStringParameters") or {}
            return get_audit_log(
                limit=int(qs.get("limit", 200)),
                entity_type=qs.get("entity_type"),
                user_email=qs.get("user_email"),
                action=qs.get("action"),
            )

        # GET /schedules
        if method == "GET" and parts == ["schedules"]:
            return get_schedules()
        # PUT /schedules/{name}/toggle
        if method in ("PUT", "POST") and len(parts) == 3 and parts[0] == "schedules" and parts[2] == "toggle":
            return toggle_schedule(parts[1], body)
        # PUT /schedules/{name}/expression
        if method in ("PUT", "POST") and len(parts) == 3 and parts[0] == "schedules" and parts[2] == "expression":
            return update_schedule_expression(parts[1], body)

        # GET /dashboard/stats (submit queries, returns stmt_ids)
        if method == "GET" and parts == ["dashboard", "stats"]:
            return get_dashboard_stats()
        # GET /dashboard/stats/result?q0=id&q1=id&q2=id (poll results)
        if method == "GET" and parts == ["dashboard", "stats", "result"]:
            qs = event.get("queryStringParameters") or {}
            return get_dashboard_stats_result(qs.get("q0", ""), qs.get("q1", ""), qs.get("q2", ""))

        # GET /analytics/summary — submit 5 CRM analytics queries, return stmt_ids
        if method == "GET" and parts == ["analytics", "summary"]:
            return get_analytics_summary()
        # GET /analytics/result?q0=&q1=&q2=&q3=&q4= — poll analytics results
        if method == "GET" and parts == ["analytics", "result"]:
            qs = event.get("queryStringParameters") or {}
            return get_analytics_result(
                qs.get("q0", ""), qs.get("q1", ""), qs.get("q2", ""),
                qs.get("q3", ""), qs.get("q4", ""),
            )

        # GET /analytics/sla — submit 3 SLA queries
        if method == "GET" and parts == ["analytics", "sla"]:
            return get_analytics_sla()
        # GET /analytics/sla/result?q0=&q1=&q2=
        if method == "GET" and parts == ["analytics", "sla", "result"]:
            qs = event.get("queryStringParameters") or {}
            return get_analytics_sla_result(qs.get("q0", ""), qs.get("q1", ""), qs.get("q2", ""))

        # GET /users
        if method == "GET" and parts == ["users"]:
            return get_users()
        # POST /users
        if method == "POST" and parts == ["users"]:
            return create_user(body)
        # PUT /users/{id}
        if method in ("PUT", "POST") and len(parts) == 2 and parts[0] == "users":
            return update_user(parts[1], body)
        # DELETE /users/{id}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "users":
            return deactivate_user(parts[1])

        # GET /roles
        if method == "GET" and parts == ["roles"]:
            return get_roles()

        # GET /rules
        if method == "GET" and parts == ["rules"]:
            return get_rules()
        # POST /rules
        if method == "POST" and parts == ["rules"]:
            return create_rule(body)
        # PUT /rules/{id}
        if method in ("PUT", "POST") and len(parts) == 2 and parts[0] == "rules":
            return update_rule(parts[1], body)
        # DELETE /rules/{id}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "rules":
            return delete_rule(parts[1])

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

    # Parse result_preview / ai_summary if stored as JSON strings
    for fld, fallback in (("result_preview", []), ("ai_summary", None)):
        val = item.get(fld)
        if isinstance(val, str):
            try:
                item[fld] = json.loads(val)
            except Exception:
                item[fld] = fallback

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


def _do_pause_with_retry(max_attempts: int = 10, wait_sec: int = 15) -> None:
    """Attempt pause_cluster, retrying on transient InvalidClusterStateFault."""
    for attempt in range(max_attempts):
        try:
            redshift.pause_cluster(ClusterIdentifier=CLUSTER_ID)
            return
        except redshift.exceptions.InvalidClusterStateFault as e:
            if "operation running" in str(e).lower() and attempt < max_attempts - 1:
                time.sleep(wait_sec)
                continue
            raise


def pause_cluster_api():
    try:
        r = redshift.describe_clusters(ClusterIdentifier=CLUSTER_ID)
        status = r["Clusters"][0]["ClusterStatus"]
        if status != "available":
            return resp(200, {"status": status, "message": f"Cluster en estado: {status}"})
        try:
            _do_pause_with_retry()
            return resp(200, {"status": "pausing", "message": "Cluster pausándose..."})
        except redshift.exceptions.InvalidClusterStateFault as e:
            if "backup" not in str(e).lower() and "recently available" not in str(e).lower():
                raise
            # No recent snapshot — create one, wait, then pause
            snap_id = f"watchtower-autopause-{int(time.time())}"
            redshift.create_cluster_snapshot(
                SnapshotIdentifier=snap_id,
                ClusterIdentifier=CLUSTER_ID,
            )
            # Wait for snapshot to be available (up to 5 min)
            for _ in range(60):
                time.sleep(5)
                s = redshift.describe_cluster_snapshots(SnapshotIdentifier=snap_id)
                if s["Snapshots"][0]["Status"] == "available":
                    break
            # Extra buffer — Redshift needs time after snapshot before accepting pause
            time.sleep(30)
            _do_pause_with_retry(max_attempts=12, wait_sec=15)
            return resp(200, {"status": "pausing", "message": "Snapshot creado y cluster pausándose..."})
    except Exception as e:
        return resp(500, {"error": str(e)})


def delete_query(report_name: str):
    builtin_names = {r["report_name"] for r in BUILTIN_REPORTS}
    if report_name in builtin_names:
        return resp(400, {"error": "No se pueden eliminar los reportes predefinidos"})
    catalog_table.delete_item(Key={"report_name": report_name})
    return resp(200, {"message": f"Query '{report_name}' eliminada"})


# ---------------------------------------------------------------------------
# S3 JSON store — datos operativos del CRM (always-on, sin depender de Redshift)
# Un objeto por registro: s3://<bucket>/crm/<kind>/<id>.json
# Reutilizable por whitelist, alertados, casos, usuarios, audit.
# ---------------------------------------------------------------------------
CRM_PREFIX = "crm"


def _crm_key(kind: str, item_id: str) -> str:
    return f"{CRM_PREFIX}/{kind}/{item_id}.json"


def _crm_put(kind: str, item_id: str, item: dict) -> None:
    s3.put_object(
        Bucket=S3_BUCKET, Key=_crm_key(kind, item_id),
        Body=json.dumps(item, default=str).encode("utf-8"),
        ContentType="application/json",
    )


def _crm_get(kind: str, item_id: str) -> dict | None:
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=_crm_key(kind, item_id))
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None


def _crm_delete(kind: str, item_id: str) -> None:
    s3.delete_object(Bucket=S3_BUCKET, Key=_crm_key(kind, item_id))


def _crm_update(kind: str, item_id: str, changes: dict) -> dict | None:
    """Read-modify-write a single record. Returns the updated item, or None if
    it doesn't exist."""
    item = _crm_get(kind, item_id)
    if item is None:
        return None
    item.update(changes)
    _crm_put(kind, item_id, item)
    return item


def _safe_audit(*, user_email="unknown", action="", entity_type="",
                entity_id="", new_value=None, **_extra) -> None:
    """Best-effort audit write to the S3 store (always-on). Never breaks the
    calling operation if it fails."""
    try:
        aid = str(uuid.uuid4())
        _crm_put("audit", aid, {
            "log_id": aid,
            "user_email": user_email or "unknown",
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "new_value": new_value,
            "created_at": _now_str(),
        })
    except Exception:
        pass


def _crm_list(kind: str) -> list[dict]:
    """List all records of a kind. Lists keys then fetches each object in
    parallel (fine for the operational volumes here)."""
    prefix = f"{CRM_PREFIX}/{kind}/"
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".json"):
                keys.append(o["Key"])
    if not keys:
        return []

    def _fetch(k):
        try:
            return json.loads(s3.get_object(Bucket=S3_BUCKET, Key=k)["Body"].read())
        except Exception:
            return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=16) as ex:
        return [i for i in ex.map(_fetch, keys) if i is not None]


def get_whitelist():
    # S3-backed: works with the Redshift cluster paused.
    try:
        now = int(time.time())
        out = []
        for i in _crm_list("whitelist"):
            exp = int(i.get("expires_at", 0))
            if exp and exp <= now:
                continue  # vencida
            out.append({
                "whitelist_id": i.get("whitelist_id", ""),
                "entity_field": i.get("entity_field", ""),
                "entity_value": i.get("entity_value", ""),
                "duration_days": int(i.get("duration_days", 0)),
                "reason": i.get("reason", ""),
                "scope": i.get("scope", "global"),
                "report_name": i.get("report_name", ""),
                "created_at": i.get("created_at", ""),
                "expires_at": i.get("expires_at_str", ""),
            })
        out.sort(key=lambda x: x["created_at"], reverse=True)
        return resp(200, {"whitelist": out})
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
    now = dt.datetime.utcnow()
    expires = now + dt.timedelta(days=duration_days)
    _crm_put("whitelist", wid, {
        "whitelist_id": wid,
        "entity_field": entity_field,
        "entity_value": entity_value,
        "duration_days": duration_days,
        "reason": reason,
        "scope": scope,
        "report_name": report_name if scope == "report" else "",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "expires_at": int(expires.timestamp()),
        "expires_at_str": expires.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return resp(201, {"whitelist_id": wid})


def remove_from_whitelist(whitelist_id: str):
    _crm_delete("whitelist", whitelist_id)
    return resp(200, {"message": f"Whitelist entry '{whitelist_id}' removed"})


# ---------------------------------------------------------------------------
# Priorización de Alertas — mantenedor de documentos a solicitar por alerta
# (un solo JSON en S3, mismo patrón que auto_case_rules) + corrida de prueba
# end-to-end: evaluación → prioridad → email (Gmail SMTP) → caso sin asignar.
# ---------------------------------------------------------------------------
def _load_alert_document_config() -> list[dict]:
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=ALERT_DOCS_CONFIG_KEY)
        return json.loads(obj["Body"].read())
    except Exception:
        return []


def _save_alert_document_config(records: list[dict]) -> None:
    s3.put_object(
        Bucket=S3_BUCKET, Key=ALERT_DOCS_CONFIG_KEY,
        Body=json.dumps(records, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
    )


def get_alert_document_config():
    return resp(200, {"config": _load_alert_document_config()})


def create_alert_document_config(body: dict):
    alerta = str(body.get("alerta", "")).strip()
    if not alerta:
        return resp(400, {"error": "alerta is required"})
    records = _load_alert_document_config()
    entry = {
        "config_id": str(uuid.uuid4()),
        "tipo_alerta": str(body.get("tipo_alerta", "")).strip(),
        "alerta": alerta,
        "documentos_b2b": body.get("documentos_b2b") or [],
        "documentos_b2c": body.get("documentos_b2c") or [],
    }
    records.append(entry)
    _save_alert_document_config(records)
    return resp(201, {"config": entry})


def update_alert_document_config(config_id: str, body: dict):
    records = _load_alert_document_config()
    for r in records:
        if r.get("config_id") == config_id:
            for field in ("tipo_alerta", "alerta", "documentos_b2b", "documentos_b2c"):
                if field in body:
                    r[field] = body[field]
            _save_alert_document_config(records)
            return resp(200, {"config": r})
    return resp(404, {"error": "Config not found"})


def delete_alert_document_config(config_id: str):
    records = _load_alert_document_config()
    new_records = [r for r in records if r.get("config_id") != config_id]
    if len(new_records) == len(records):
        return resp(404, {"error": "Config not found"})
    _save_alert_document_config(new_records)
    return resp(200, {"message": "Config eliminada"})


def _load_priority_queue_settings() -> dict:
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=PRIORITY_QUEUE_SETTINGS_KEY)
        return json.loads(obj["Body"].read())
    except Exception:
        return {"enabled": False, "updated_at": "", "updated_by": ""}


def get_priority_queue_settings():
    return resp(200, _load_priority_queue_settings())


def update_priority_queue_settings(body: dict):
    enabled = bool(body.get("enabled", False))
    settings = {
        "enabled": enabled,
        "updated_at": _now_str(),
        "updated_by": body.get("updated_by", "").strip(),
    }
    s3.put_object(
        Bucket=S3_BUCKET, Key=PRIORITY_QUEUE_SETTINGS_KEY,
        Body=json.dumps(settings, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    _safe_audit(user_email=settings["updated_by"] or "unknown",
                action="priority_queue.toggle", entity_type="config",
                entity_id="priority_queue_settings", new_value={"enabled": enabled})
    return resp(200, settings)


def run_alert_prioritization_test(body: dict):
    """Prueba de concepto end-to-end: lee compliance.alert_priority_test_data
    (datos ficticios cargados a mano, con prioridad ya asignada) y por cada
    fila compone el correo de solicitud de documentos (modo prueba = TODAS las
    categorías, según lo pedido), lo manda vía _send_email (Gmail SMTP — hoy
    no-opea en silencio porque GMAIL_APP_PASSWORD no está configurado todavía,
    apenas se configure empieza a mandar de verdad sin tocar este código) y
    crea un caso automático sin asignar. Deja un registro de auditoría de cada
    solicitud de documentos en S3 (crm/document_requests/) independientemente
    de si el correo realmente salió o no.

    Respeta el interruptor general (config/priority_queue_settings.json) —
    si está apagado, no manda nada ni crea casos.
    """
    settings = _load_priority_queue_settings()
    if not settings.get("enabled"):
        return resp(409, {
            "error": "El proceso de priorización de alertas está apagado. "
                     "Prendelo desde Admin antes de correr la prueba.",
            "enabled": False,
        })
    try:
        rows = _rs_exec(
            "SELECT customer_id, total_payins_7d, total_payin_usd_7d, avg_payin_usd_7d, "
            "total_payouts_7d, total_payout_usd_7d, avg_payout_usd_7d, "
            "last_payin_date::VARCHAR AS last_payin_date, last_payout_date::VARCHAR AS last_payout_date, "
            "payout_vs_payin_ratio, nombre_completo, correo, prioridad, concepto "
            f"FROM {PRIORITY_TEST_TABLE} ORDER BY customer_id"
        )
    except Exception as e:
        return resp(500, {"error": f"No se pudo leer la tabla de prueba: {e}"})

    results = []
    for r in rows:
        customer_id = r.get("customer_id")
        nombre = r.get("nombre_completo") or ""
        correo = r.get("correo") or ""
        prioridad = str(r.get("prioridad") or "P3").strip().upper()
        concepto = r.get("concepto") or ""
        case_priority = _PRIORITY_TO_CASE_PRIORITY.get(prioridad, "low")

        # Modo prueba: se piden TODOS los documentos (los datos son ficticios,
        # "concepto" no es un nombre real de alerta del mantenedor). El cuerpo
        # del correo es la plantilla oficial de Global66 (solo se reemplaza el
        # nombre); la lista de documentos queda fija en la plantilla misma.
        documentos = _ALL_DOC_CATEGORIES

        subject = "Solicitud de información adicional — Global66"
        html_body = _render_documentos_email(nombre, documentos)
        _send_email(correo, subject, html_body, from_addr=ALERT_DOCS_FROM_ADDR)

        req_id = str(uuid.uuid4())
        _crm_put("document_requests", req_id, {
            "request_id": req_id,
            "customer_id": customer_id,
            "correo": correo,
            "nombre_completo": nombre,
            "prioridad": prioridad,
            "concepto": concepto,
            "documentos_solicitados": documentos,
            "subject": subject,
            "sent": bool(GMAIL_APP_PASSWORD),
            "created_at": _now_str(),
            "test_mode": True,
        })

        case_resp = create_case({
            "title": f"[{prioridad}] {concepto} — cliente {customer_id}",
            "description": (
                f"Caso generado automáticamente por priorización de alertas (PRUEBA).\n"
                f"Cliente: {nombre} ({customer_id})\n"
                f"Pay-ins 7d: {r.get('total_payins_7d')} (USD {r.get('total_payin_usd_7d')})\n"
                f"Pay-outs 7d: {r.get('total_payouts_7d')} (USD {r.get('total_payout_usd_7d')})\n"
                f"Ratio payout/payin: {r.get('payout_vs_payin_ratio')}\n"
                f"Último pay-in: {r.get('last_payin_date')} | Último pay-out: {r.get('last_payout_date')}\n"
                f"Documentos solicitados: {', '.join(documentos)}"
            ),
            "priority": case_priority,
            "entity_type": "customer_test",
            "entity_id": str(customer_id),
            "report_name": "alert_prioritization_test",
            "assigned_to": "",
            "created_by": "alert_prioritization_test",
        })
        case_body = json.loads(case_resp["body"])
        case_id = case_body.get("case_id", "")

        results.append({
            "customer_id": customer_id,
            "prioridad": prioridad,
            "concepto": concepto,
            "case_id": case_id,
            "email_sent": bool(GMAIL_APP_PASSWORD),
            "email_to": correo,
            "documentos_solicitados": documentos,
        })

    return resp(200, {"processed": len(results), "results": results})


_PRIORITY_QUEUE_VIEW = {"customer": "compliance.priority_queue_b2c", "company": "compliance.priority_queue_b2b"}


def _score_to_priority(score) -> str:
    """UMBRALES PLACEHOLDER — pendientes de confirmar con compliance, junto
    con los pesos reales de 'Riesgo Analizado'. Fáciles de ajustar acá."""
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "P3"
    if score >= 75:
        return "P1"
    if score >= 50:
        return "P2"
    return "P3"


def _lookup_alert_documents(alerta: str, entity_type: str) -> list[str]:
    """Busca en el mantenedor (config/alert_document_config.json) los
    documentos a pedir para esta alerta + tipo de cliente. Si la alerta no
    está configurada, cae de vuelta a pedir todas las categorías (mismo
    comportamiento que el modo prueba)."""
    records = _load_alert_document_config()
    alerta_norm = (alerta or "").strip().lower()
    field = "documentos_b2b" if entity_type == "company" else "documentos_b2c"
    for r in records:
        if (r.get("alerta") or "").strip().lower() == alerta_norm:
            docs = r.get(field) or []
            return docs if docs else _ALL_DOC_CATEGORIES
    return _ALL_DOC_CATEGORIES


def run_alert_prioritization_real(body: dict):
    """Flujo real: recibe alertas ya gatilladas (entity_type, entity_id,
    alerta, concepto) — típicamente el resultado de correr uno de los 29
    reportes — y por cada una:
      1. Calcula prioridad real desde compliance.priority_queue_b2c/b2b
         (score PLACEHOLDER: promedio simple de los 4 componentes, pendiente
         de los pesos reales de 'Riesgo Analizado' — ver Notas de la matriz).
      2. Busca en el mantenedor qué documentos pedir para esa alerta + tipo
         de cliente.
      3. Manda el correo (plantilla completa — el recorte dinámico del HTML
         por categoría queda pendiente de confirmar el mapeo) y crea un caso
         automático sin asignar.
    Respeta el interruptor general, igual que el modo prueba.

    body: {"alerts": [{"entity_type": "customer"|"company", "entity_id": 123,
                        "alerta": "Transacciones a Países Alto Riesgo",
                        "concepto": "texto libre opcional"}]}
    """
    settings = _load_priority_queue_settings()
    if not settings.get("enabled"):
        return resp(409, {
            "error": "El proceso de priorización de alertas está apagado. "
                     "Prendelo desde Admin antes de correrlo.",
            "enabled": False,
        })

    alerts_in = body.get("alerts") or []
    if not alerts_in:
        return resp(400, {"error": "alerts es requerido (lista de {entity_type, entity_id, alerta})"})

    results = []
    for item in alerts_in:
        entity_type = (item.get("entity_type") or "customer").strip().lower()
        if entity_type not in ("customer", "company"):
            entity_type = "customer"
        entity_id = item.get("entity_id")
        alerta = item.get("alerta", "")
        concepto = item.get("concepto") or alerta

        view = _PRIORITY_QUEUE_VIEW[entity_type]
        id_col = "customer_id" if entity_type == "customer" else "company_id"
        try:
            rows = _rs_exec(f"SELECT * FROM {view} WHERE {id_col} = {int(entity_id)}")
        except Exception as e:
            results.append({"entity_type": entity_type, "entity_id": entity_id, "error": f"No se pudo calcular prioridad: {e}"})
            continue
        if not rows:
            results.append({"entity_type": entity_type, "entity_id": entity_id, "error": "Cliente/empresa no encontrado en la vista de priorización"})
            continue
        row = rows[0]

        score = row.get("risk_score")
        prioridad = _score_to_priority(score)
        case_priority = _PRIORITY_TO_CASE_PRIORITY.get(prioridad, "low")

        if entity_type == "customer":
            nombre = f"{row.get('name','') or ''} {row.get('last_name','') or ''}".strip()
            correo = row.get("email") or ""
        else:
            nombre = row.get("rep_name") or row.get("company_name") or ""
            correo = row.get("rep_email") or ""

        documentos = _lookup_alert_documents(alerta, entity_type)

        subject = "Solicitud de información adicional — Global66"
        html_body = _render_documentos_email(nombre, documentos)
        _send_email(correo, subject, html_body, from_addr=ALERT_DOCS_FROM_ADDR)

        req_id = str(uuid.uuid4())
        _crm_put("document_requests", req_id, {
            "request_id": req_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "correo": correo,
            "nombre_completo": nombre,
            "prioridad": prioridad,
            "risk_score": score,
            "alerta": alerta,
            "concepto": concepto,
            "documentos_solicitados": documentos,
            "subject": subject,
            "sent": bool(GMAIL_APP_PASSWORD),
            "created_at": _now_str(),
            "test_mode": False,
        })

        case_resp = create_case({
            "title": f"[{prioridad}] {alerta} — {'cliente' if entity_type=='customer' else 'empresa'} {entity_id}",
            "description": (
                f"Caso generado automáticamente por priorización de alertas.\n"
                f"{'Cliente' if entity_type=='customer' else 'Empresa'}: {nombre} ({entity_id})\n"
                f"Alerta: {alerta}\n"
                f"Score de riesgo: {score} (PLACEHOLDER — pendiente pesos reales de 'Riesgo Analizado')\n"
                f"Documentos solicitados: {', '.join(documentos)}"
            ),
            "priority": case_priority,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "report_name": alerta,
            "assigned_to": "",
            "created_by": "alert_prioritization_real",
        })
        case_body = json.loads(case_resp["body"])
        case_id = case_body.get("case_id", "")
        if case_id:
            _crm_update("cases", case_id, {
                "documentos_checklist": [{"categoria": d, "entregado": False} for d in documentos],
            })

        results.append({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "alerta": alerta,
            "risk_score": score,
            "prioridad": prioridad,
            "case_id": case_id,
            "email_sent": bool(GMAIL_APP_PASSWORD),
            "email_to": correo,
            "documentos_solicitados": documentos,
        })

    return resp(200, {"processed": len(results), "results": results})


def send_manual_document_request(body: dict):
    """Botón manual — mismo correo/caso que el flujo automático, pero:
      - no depende del interruptor general (es una acción deliberada de un
        analista, uno a la vez, no el proceso masivo automático)
      - los documentos a pedir los elige el analista a mano (no el
        mantenedor), útil para casos puntuales fuera de lo estándar.

    body: {entity_type, entity_id, nombre, correo, prioridad, alerta,
           documentos: [...], case_id (opcional, para linkear a un caso
           existente en vez de crear uno nuevo)}
    """
    entity_type = (body.get("entity_type") or "customer").strip().lower()
    entity_id = body.get("entity_id", "")
    nombre = body.get("nombre", "").strip()
    correo = body.get("correo", "").strip()
    prioridad = (body.get("prioridad") or "P3").strip().upper()
    alerta = body.get("alerta", "").strip()
    documentos = body.get("documentos") or []
    existing_case_id = body.get("case_id", "").strip()

    if not correo:
        return resp(400, {"error": "correo is required"})
    if not documentos:
        return resp(400, {"error": "documentos (lista, al menos 1) is required"})

    subject = "Solicitud de información adicional — Global66"
    html_body = _render_documentos_email(nombre, documentos)
    _send_email(correo, subject, html_body, from_addr=ALERT_DOCS_FROM_ADDR)

    req_id = str(uuid.uuid4())
    _crm_put("document_requests", req_id, {
        "request_id": req_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "correo": correo,
        "nombre_completo": nombre,
        "prioridad": prioridad,
        "alerta": alerta,
        "documentos_solicitados": documentos,
        "subject": subject,
        "sent": bool(GMAIL_APP_PASSWORD),
        "created_at": _now_str(),
        "manual": True,
    })

    checklist = [{"categoria": d, "entregado": False} for d in documentos]

    if existing_case_id:
        updated = _crm_update("cases", existing_case_id, {"documentos_checklist": checklist})
        case_id = existing_case_id if updated else ""
    else:
        case_priority = _PRIORITY_TO_CASE_PRIORITY.get(prioridad, "low")
        case_resp = create_case({
            "title": f"[{prioridad}] {alerta or 'Solicitud manual'} — {'cliente' if entity_type=='customer' else 'empresa'} {entity_id}",
            "description": (
                f"Caso generado por solicitud manual de documentos.\n"
                f"{'Cliente' if entity_type=='customer' else 'Empresa'}: {nombre} ({entity_id})\n"
                f"Alerta: {alerta or '(sin alerta asociada)'}\n"
                f"Documentos solicitados: {', '.join(documentos)}"
            ),
            "priority": case_priority,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "report_name": alerta,
            "assigned_to": "",
            "created_by": "manual_document_request",
        })
        case_body = json.loads(case_resp["body"])
        case_id = case_body.get("case_id", "")
        if case_id:
            _crm_update("cases", case_id, {"documentos_checklist": checklist})

    return resp(200, {
        "case_id": case_id,
        "email_sent": bool(GMAIL_APP_PASSWORD),
        "email_to": correo,
        "documentos_solicitados": documentos,
    })


def update_case_document_checklist(case_id: str, body: dict):
    """Marca un documento del checklist como entregado o no. body: {categoria, entregado}."""
    categoria = body.get("categoria", "").strip()
    entregado = bool(body.get("entregado", False))
    if not categoria:
        return resp(400, {"error": "categoria is required"})

    case = _crm_get("cases", case_id)
    if case is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})

    checklist = case.get("documentos_checklist") or []
    found = False
    for item in checklist:
        if item.get("categoria") == categoria:
            item["entregado"] = entregado
            found = True
            break
    if not found:
        checklist.append({"categoria": categoria, "entregado": entregado})

    _crm_update("cases", case_id, {"documentos_checklist": checklist})
    return resp(200, {"documentos_checklist": checklist})


# ---------------------------------------------------------------------------
# ALERTS (Alertados / Ya Revisados)
# ---------------------------------------------------------------------------

_PRIORITY_RANK = {"high": 1, "medium": 2, "low": 3}


def get_alerts(status: str = "active"):
    # S3-backed: works with the Redshift cluster paused.
    try:
        out = []
        for i in _crm_list("alerts"):
            if i.get("status", "active") != status:
                continue
            out.append({
                "alert_id": i.get("alert_id", ""),
                "entity_field": i.get("entity_field", ""),
                "entity_value": i.get("entity_value", ""),
                "reason": i.get("reason", ""),
                "report_name": i.get("report_name", ""),
                "row_data": i.get("row_data", ""),
                "created_at": i.get("created_at", ""),
                "status": i.get("status", "active"),
                "reviewed_at": i.get("reviewed_at", ""),
                "priority": i.get("priority", "medium"),
                "assigned_to": i.get("assigned_to", ""),
                "reviewed_by": i.get("reviewed_by", ""),
                "notes": i.get("notes", ""),
            })
        # Stable sort: first by created_at DESC, then by priority → within a
        # priority, newest first (matches the old SQL ORDER BY).
        out.sort(key=lambda a: a["created_at"], reverse=True)
        out.sort(key=lambda a: _PRIORITY_RANK.get(a["priority"], 2))
        return resp(200, {"alerts": out})
    except Exception as e:
        return resp(200, {"alerts": [], "warning": str(e)})


def add_alert(body: dict):
    entity_field = body.get("entity_field", "").strip()
    entity_value = body.get("entity_value", "").strip()
    reason = body.get("reason", "").strip()
    report_name = body.get("report_name", "").strip()
    row_data = body.get("row_data", {})
    priority = body.get("priority", "medium").strip()
    if priority not in ("high", "medium", "low"):
        priority = "medium"

    if not entity_field or not entity_value:
        return resp(400, {"error": "entity_field and entity_value are required"})

    aid = str(uuid.uuid4())
    _crm_put("alerts", aid, {
        "alert_id": aid,
        "entity_field": entity_field,
        "entity_value": entity_value,
        "reason": reason,
        "report_name": report_name,
        "row_data": json.dumps(row_data, default=str) if not isinstance(row_data, str) else row_data,
        "status": "active",
        "priority": priority,
        "assigned_to": "",
        "reviewed_by": "",
        "reviewed_at": "",
        "notes": "",
        "created_at": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return resp(201, {"alert_id": aid})


def review_alert(alert_id: str, body: dict | None = None):
    """Move an alert from 'active' to 'reviewed' (ya revisados)."""
    body = body or {}
    changes = {
        "status": "reviewed",
        "reviewed_at": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if body.get("reviewed_by", "").strip():
        changes["reviewed_by"] = body["reviewed_by"].strip()
    if body.get("notes", "").strip():
        changes["notes"] = body["notes"].strip()
    if _crm_update("alerts", alert_id, changes) is None:
        return resp(404, {"error": f"Alert '{alert_id}' not found"})
    _safe_audit(user_email=changes.get("reviewed_by", "unknown"), action="alert.review",
                entity_type="alert", entity_id=alert_id)
    return resp(200, {"message": f"Alert '{alert_id}' marked as reviewed"})


def delete_alert(alert_id: str):
    """Permanently remove an alert entry."""
    _crm_delete("alerts", alert_id)
    return resp(200, {"message": f"Alert '{alert_id}' permanently deleted"})


def assign_alert(alert_id: str, body: dict):
    """Assign an alert to a CRM user (by email)."""
    assigned_to = body.get("assigned_to", "").strip()
    if not assigned_to:
        return resp(400, {"error": "assigned_to is required"})
    if _crm_update("alerts", alert_id, {"assigned_to": assigned_to}) is None:
        return resp(404, {"error": f"Alert '{alert_id}' not found"})
    _safe_audit(user_email=body.get("actor_email", "unknown"), action="alert.assign",
                entity_type="alert", entity_id=alert_id, new_value={"assigned_to": assigned_to})
    return resp(200, {"message": f"Alert '{alert_id}' assigned to {assigned_to}"})


def update_alert_notes(alert_id: str, body: dict):
    """Update the analyst notes on an alert."""
    if _crm_update("alerts", alert_id, {"notes": body.get("notes", "").strip()}) is None:
        return resp(404, {"error": f"Alert '{alert_id}' not found"})
    return resp(200, {"message": "Notes updated"})


def get_crm_users():
    """Return active CRM users for the assignee dropdown (S3-backed)."""
    try:
        users = [
            {"email": u.get("email", ""), "full_name": u.get("full_name") or u.get("email", "")}
            for u in _crm_list("users") if u.get("is_active", True)
        ]
        users.sort(key=lambda u: u["full_name"])
        return resp(200, {"users": users})
    except Exception as e:
        return resp(200, {"users": [], "warning": str(e)})


# ---------------------------------------------------------------------------
# CASES CRM
# ---------------------------------------------------------------------------

_CASE_STATUS_RANK = {"open": 1, "in_progress": 2, "under_review": 3, "closed": 4, "archived": 5}


def _now_str() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def get_cases(status_filter=None, priority_filter=None, assigned_filter=None):
    """List cases with optional filters (S3-backed). Ordered by status urgency,
    priority, then updated_at DESC."""
    try:
        out = []
        for c in _crm_list("cases"):
            if status_filter and status_filter != "all" and c.get("status") != status_filter:
                continue
            if priority_filter and c.get("priority") != priority_filter:
                continue
            if assigned_filter and c.get("assigned_to") != assigned_filter:
                continue
            out.append({
                "case_id": c.get("case_id", ""),
                "title": c.get("title", ""),
                "description": c.get("description", ""),
                "status": c.get("status", "open"),
                "priority": c.get("priority", "medium"),
                "entity_type": c.get("entity_type", ""),
                "entity_id": c.get("entity_id", ""),
                "report_name": c.get("report_name", ""),
                "assigned_to": c.get("assigned_to", ""),
                "created_by": c.get("created_by", ""),
                "created_at": c.get("created_at", ""),
                "updated_at": c.get("updated_at", ""),
                "closed_at": c.get("closed_at", ""),
                "note_count": len(c.get("notes", [])),
            })
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        out.sort(key=lambda x: (_CASE_STATUS_RANK.get(x["status"], 5),
                                _PRIORITY_RANK.get(x["priority"], 2)))
        return resp(200, {"cases": out})
    except Exception as e:
        return resp(200, {"cases": [], "warning": str(e)})


def create_case(body: dict):
    title = body.get("title", "").strip()
    if not title:
        return resp(400, {"error": "title is required"})

    priority = body.get("priority", "medium").strip()
    if priority not in ("high", "medium", "low"):
        priority = "medium"
    assigned_to = body.get("assigned_to", "").strip()
    created_by = body.get("created_by", "unknown").strip()

    cid = str(uuid.uuid4())
    now = _now_str()
    _crm_put("cases", cid, {
        "case_id": cid,
        "title": title,
        "description": body.get("description", "").strip(),
        "status": "open",
        "priority": priority,
        "entity_type": body.get("entity_type", "").strip(),
        "entity_id": body.get("entity_id", "").strip(),
        "report_name": body.get("report_name", "").strip(),
        "assigned_to": assigned_to,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
        "closed_at": "",
        "notes": [],
    })
    _safe_audit(user_email=created_by, action="case.create", entity_type="case",
                entity_id=cid, new_value={"title": title, "priority": priority})
    _post_slack(
        f"📁 *Nuevo caso creado* — {title}\n"
        f"Prioridad: {priority} | Asignado a: {assigned_to or 'Sin asignar'}\n"
        f"Creado por: {created_by}"
    )
    if assigned_to and "@" in assigned_to:
        _case_assignment_email(assigned_to, cid, title, priority, created_by)
    return resp(201, {"case_id": cid})


def get_case_detail(case_id: str):
    """Return full case data including notes and linked alerts (S3-backed)."""
    try:
        c = _crm_get("cases", case_id)
        if c is None:
            return resp(404, {"error": f"Case '{case_id}' not found"})
        notes = sorted(c.get("notes", []), key=lambda n: n.get("created_at", ""))
        # Linked alerts = alerts whose case_id points here
        alerts = []
        for a in _crm_list("alerts"):
            if a.get("case_id") == case_id:
                alerts.append({
                    "alert_id": a.get("alert_id", ""),
                    "entity_field": a.get("entity_field", ""),
                    "entity_value": a.get("entity_value", ""),
                    "reason": a.get("reason", ""),
                    "report_name": a.get("report_name", ""),
                    "created_at": a.get("created_at", ""),
                    "status": a.get("status", "active"),
                    "priority": a.get("priority", "medium"),
                })
        case_out = {k: v for k, v in c.items() if k != "notes"}
        return resp(200, {"case": case_out, "notes": notes, "alerts": alerts})
    except Exception as e:
        return resp(500, {"error": str(e)})


def update_case(case_id: str, body: dict):
    """Update title, description, or priority."""
    changes = {}
    if "title" in body:
        changes["title"] = str(body["title"]).strip()
    if "description" in body:
        changes["description"] = str(body["description"]).strip()
    if "priority" in body and body["priority"] in ("high", "medium", "low"):
        changes["priority"] = body["priority"]
    if not changes:
        return resp(400, {"error": "No valid fields to update"})
    changes["updated_at"] = _now_str()
    if _crm_update("cases", case_id, changes) is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})
    return resp(200, {"message": "Case updated"})


def update_case_status(case_id: str, body: dict):
    """Change case status. Sets closed_at when status = 'closed'."""
    status = body.get("status", "").strip()
    valid = ("open", "in_progress", "under_review", "closed", "archived")
    if status not in valid:
        return resp(400, {"error": f"status must be one of {valid}"})

    changes = {"status": status, "updated_at": _now_str()}
    if status == "closed":
        changes["closed_at"] = _now_str()
    elif status != "archived":
        changes["closed_at"] = ""

    if _crm_update("cases", case_id, changes) is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})
    actor = body.get("actor_email", "unknown")
    _safe_audit(user_email=actor, action="case.status_change", entity_type="case",
                entity_id=case_id, new_value={"status": status})
    _STATUS_LABEL = {"under_review": "⚠️ Bajo Revisión", "closed": "✅ Cerrado", "open": "🔵 Abierto", "in_progress": "🔄 En Investigación"}
    if status in ("under_review", "closed"):
        _post_slack(
            f"{_STATUS_LABEL.get(status, status)} *Caso actualizado*\n"
            f"ID: {case_id[:8]}… | Nuevo estado: {_STATUS_LABEL.get(status, status)}\n"
            f"Por: {actor}"
        )
    return resp(200, {"message": f"Case status updated to {status}"})


def update_case_assign(case_id: str, body: dict):
    assigned_to = body.get("assigned_to", "").strip()
    actor = body.get("actor_email", "unknown")
    updated = _crm_update("cases", case_id, {"assigned_to": assigned_to, "updated_at": _now_str()})
    if updated is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})
    _safe_audit(user_email=actor, action="case.assign", entity_type="case",
                entity_id=case_id, new_value={"assigned_to": assigned_to})
    if assigned_to and "@" in assigned_to:
        _case_assignment_email(assigned_to, case_id, updated.get("title", ""),
                               updated.get("priority", "medium"), actor)
    return resp(200, {"message": f"Case assigned to {assigned_to}"})


def add_case_note(case_id: str, body: dict):
    content = body.get("content", "").strip()
    if not content:
        return resp(400, {"error": "content is required"})
    author_email = body.get("author_email", "").strip()
    case = _crm_get("cases", case_id)
    if case is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})
    note = {
        "note_id": str(uuid.uuid4()),
        "case_id": case_id,
        "author_email": author_email,
        "content": content,
        "created_at": _now_str(),
    }
    case.setdefault("notes", []).append(note)
    case["updated_at"] = _now_str()
    _crm_put("cases", case_id, case)
    _safe_audit(user_email=author_email or "unknown", action="case.note_add",
                entity_type="case", entity_id=case_id)
    return resp(201, {"message": "Note added"})


def link_alert_to_case(alert_id: str, body: dict):
    """Link an alert to a case (sets case_id on the alert)."""
    case_id = body.get("case_id", "").strip()
    if not case_id:
        return resp(400, {"error": "case_id is required"})
    if _crm_update("alerts", alert_id, {"case_id": case_id}) is None:
        return resp(404, {"error": f"Alert '{alert_id}' not found"})
    _crm_update("cases", case_id, {"updated_at": _now_str()})
    return resp(200, {"message": f"Alert '{alert_id}' linked to case '{case_id}'"})


# ---------------------------------------------------------------------------
# CASE ATTACHMENTS — documentos adjuntos a un caso, organizados en S3 por
# cliente (customer_id o company_id), no solo por caso, para que todo lo que
# se le pidió/recibió de un cliente sea encontrable aunque abra varios casos
# a lo largo del tiempo:
#
#   client-documents/{entity_type}/{entity_id}/{case_id}/{ts}_{filename}
#
# Subida vía presigned PUT (el navegador sube directo a S3, sin pasar por el
# Lambda) — evita el límite de payload del Lambda/API Gateway para archivos
# grandes (PDFs escaneados, etc). Mismo patrón que ya usa el proyecto para
# descargas de reportes (presigned URL).
# ---------------------------------------------------------------------------
def _safe_filename(name: str) -> str:
    name = (name or "archivo").strip().replace("/", "_").replace("\\", "_")
    name = re.sub(r"[^A-Za-z0-9._\-]", "_", name)
    return name[:200] or "archivo"


def _attachment_s3_key(entity_type: str, entity_id: str, case_id: str, ts: str, filename: str) -> str:
    entity_type = (entity_type or "customer").strip().lower()
    if entity_type not in ("customer", "company"):
        entity_type = "customer"
    entity_id = re.sub(r"[^A-Za-z0-9_\-]", "_", str(entity_id or "sin_id"))
    return f"client-documents/{entity_type}/{entity_id}/{case_id}/{ts}_{_safe_filename(filename)}"


def get_attachment_upload_url(case_id: str, body: dict):
    """Paso 1 de la subida: devuelve una URL PUT firmada + la key donde va a
    quedar el archivo. El navegador sube directo a S3 con esa URL."""
    filename = body.get("filename", "").strip()
    if not filename:
        return resp(400, {"error": "filename is required"})
    content_type = body.get("content_type", "").strip() or "application/octet-stream"

    case = _crm_get("cases", case_id)
    if case is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})

    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    key = _attachment_s3_key(case.get("entity_type", ""), case.get("entity_id", ""), case_id, ts, filename)

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=300,
    )
    return resp(200, {"upload_url": upload_url, "s3_key": key, "content_type": content_type})


def add_case_attachment(case_id: str, body: dict):
    """Paso 2: el navegador ya subió el archivo a S3 con la URL del paso 1;
    esto registra la metadata en el caso (el archivo en sí no pasa por acá)."""
    s3_key = body.get("s3_key", "").strip()
    filename = body.get("filename", "").strip()
    if not s3_key or not filename:
        return resp(400, {"error": "s3_key and filename are required"})

    case = _crm_get("cases", case_id)
    if case is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})

    uploaded_by = body.get("uploaded_by", "").strip()
    attachment = {
        "attachment_id": str(uuid.uuid4()),
        "filename": filename,
        "s3_key": s3_key,
        "size": int(body.get("size") or 0),
        "content_type": body.get("content_type", "").strip(),
        "uploaded_by": uploaded_by,
        "uploaded_at": _now_str(),
    }
    case.setdefault("attachments", []).append(attachment)
    case["updated_at"] = _now_str()
    _crm_put("cases", case_id, case)
    _safe_audit(user_email=uploaded_by or "unknown", action="case.attachment_add",
                entity_type="case", entity_id=case_id, new_value={"filename": filename})
    return resp(201, {"attachment": attachment})


def get_attachment_download_url(case_id: str, attachment_id: str):
    case = _crm_get("cases", case_id)
    if case is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})
    for a in case.get("attachments", []):
        if a.get("attachment_id") == attachment_id:
            url = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": S3_BUCKET, "Key": a["s3_key"],
                    "ResponseContentDisposition": f'attachment; filename="{a.get("filename","archivo")}"',
                },
                ExpiresIn=300,
            )
            return resp(200, {"download_url": url, "filename": a.get("filename", "")})
    return resp(404, {"error": "Attachment not found"})


def delete_case_attachment(case_id: str, attachment_id: str):
    case = _crm_get("cases", case_id)
    if case is None:
        return resp(404, {"error": f"Case '{case_id}' not found"})
    attachments = case.get("attachments", [])
    target = next((a for a in attachments if a.get("attachment_id") == attachment_id), None)
    if target is None:
        return resp(404, {"error": "Attachment not found"})
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=target["s3_key"])
    except Exception:
        pass
    case["attachments"] = [a for a in attachments if a.get("attachment_id") != attachment_id]
    case["updated_at"] = _now_str()
    _crm_put("cases", case_id, case)
    _safe_audit(action="case.attachment_delete", entity_type="case", entity_id=case_id,
                new_value={"filename": target.get("filename", "")})
    return resp(200, {"message": "Attachment deleted"})


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


def run_wallet_search(body: dict):
    """Submit a wallet search by list of partner_account_ids (ej. 'CL-KNNW-8795')."""
    partner_account_ids = body.get("partner_account_ids", [])
    entity_type = body.get("entity_type", "b2c")
    if entity_type not in ("b2c", "b2b"):
        entity_type = "b2c"
    if not partner_account_ids:
        return resp(400, {"error": "partner_account_ids is required"})
    if len(partner_account_ids) > 5000:
        return resp(400, {"error": "Maximum 5000 partner_account_ids per search"})

    clean_ids = []
    for pid in partner_account_ids:
        pid = str(pid).strip()
        if pid:
            clean_ids.append(pid)
    if not clean_ids:
        return resp(400, {"error": "partner_account_ids is required"})

    run_id = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat()
    user_email = str(body.get("user_email", "")).strip()[:200]
    runs_table.put_item(Item={
        "run_id": run_id,
        "report_name": "wallet_search",
        "status": "RUNNING",
        "params": json.dumps({"partner_account_ids": clean_ids, "n_ids": len(clean_ids), "entity_type": entity_type}),
        "started_at": now,
        "user_email": user_email,
        "ttl": int((dt.datetime.utcnow() + dt.timedelta(days=90)).timestamp()),
    })

    lambda_client.invoke(
        FunctionName=REPORT_LAMBDA_NAME,
        InvocationType="Event",
        Payload=json.dumps({
            "report_name": "wallet_search",
            "partner_account_ids": clean_ids,
            "entity_type": entity_type,
            "run_id": run_id,
            "keep_session": False,
        }),
    )
    return resp(202, {"run_id": run_id, "status": "RUNNING", "n_ids": len(clean_ids)})


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

    # Período configurable: 5/15/30/60/90 días, o None/omitido = histórico (sin límite)
    days = body.get("days")
    try:
        days = int(days)
        if days not in (5, 15, 30, 60, 90):
            days = None
    except (TypeError, ValueError):
        days = None

    # Tipo de entidad: 'b2c' (default, customer_v2) o 'b2b' (company.company).
    entity_type = "b2b" if str(body.get("entity_type", "b2c")).lower() == "b2b" else "b2c"

    run_id = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat()
    user_email = str(body.get("user_email", "")).strip()[:200]
    runs_table.put_item(Item={
        "run_id": run_id,
        "report_name": "individual_aml_analysis",
        "status": "RUNNING",
        "params": json.dumps({"customer_ids": clean_ids, "n_customers": len(clean_ids), "days": days, "entity_type": entity_type}),
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
            "days": days,
            "entity_type": entity_type,
            "run_id": run_id,
            "keep_session": False,
        }),
    )
    return resp(202, {"run_id": run_id, "status": "RUNNING", "n_customers": len(clean_ids), "days": days, "entity_type": entity_type})


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


# ---------------------------------------------------------------------------
# Analytics CRM — Phase 6
# ---------------------------------------------------------------------------

_SQL_CASES_BY_STATUS = """
SELECT status, COUNT(*) AS n
FROM crm.cases
GROUP BY status
ORDER BY n DESC
"""

_SQL_CASES_BY_WEEK = """
SELECT DATE_TRUNC('week', created_at)::DATE AS week_start, COUNT(*) AS n
FROM crm.cases
WHERE created_at >= DATEADD(week, -8, GETDATE())
GROUP BY 1
ORDER BY 1
"""

_SQL_ALERTS_BY_REPORT = """
SELECT report_name, COUNT(*) AS n
FROM compliance.alerts
WHERE created_at >= DATEADD(day, -90, GETDATE())
GROUP BY report_name
ORDER BY n DESC
LIMIT 10
"""

_SQL_ALERTS_DAILY_30D = """
SELECT created_at::DATE AS day, COUNT(*) AS n
FROM compliance.alerts
WHERE created_at >= DATEADD(day, -30, GETDATE())
GROUP BY 1
ORDER BY 1
"""

_SQL_TOP_ENTITIES = """
SELECT entity_value, entity_type, COUNT(*) AS n
FROM compliance.alerts
WHERE entity_value IS NOT NULL AND TRIM(entity_value) <> ''
GROUP BY entity_value, entity_type
ORDER BY n DESC
LIMIT 5
"""


def _parse_dt(s):
    """Parse a stored 'YYYY-MM-DD HH:MM:SS' (or ISO) string to datetime, or None."""
    if not s:
        return None
    txt = str(s)[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def get_analytics_summary():
    """S3-backed analytics → no Redshift needed. Returns placeholder ids so the
    frontend's 2-phase flow keeps working; real data comes from /analytics/result."""
    return resp(200, {"stmt_ids": ["s3", "s3", "s3", "s3", "s3"]})


def get_analytics_result(q0: str = "", q1: str = "", q2: str = "", q3: str = "", q4: str = ""):
    """Compute the 5 CRM analytics datasets from the S3 store."""
    from collections import Counter
    try:
        now = dt.datetime.utcnow()
        cases = _crm_list("cases")
        alerts = _crm_list("alerts")

        # cases_by_status
        st = Counter(c.get("status", "open") for c in cases)
        cases_by_status = sorted([{"status": k, "n": v} for k, v in st.items()],
                                 key=lambda x: x["n"], reverse=True)

        # cases_by_week (last 8 weeks, Monday-anchored)
        wk = Counter()
        cutoff_8w = now - dt.timedelta(weeks=8)
        for c in cases:
            d = _parse_dt(c.get("created_at"))
            if d and d >= cutoff_8w:
                wstart = (d - dt.timedelta(days=d.weekday())).strftime("%Y-%m-%d")
                wk[wstart] += 1
        cases_by_week = [{"week_start": k, "n": wk[k]} for k in sorted(wk)]

        # alerts_by_report (last 90d, top 10)
        cutoff_90 = now - dt.timedelta(days=90)
        rep = Counter()
        for a in alerts:
            d = _parse_dt(a.get("created_at"))
            if d and d >= cutoff_90:
                rep[a.get("report_name", "") or "—"] += 1
        alerts_by_report = [{"report_name": k, "n": v} for k, v in rep.most_common(10)]

        # alerts_daily_30d
        cutoff_30 = now - dt.timedelta(days=30)
        day = Counter()
        for a in alerts:
            d = _parse_dt(a.get("created_at"))
            if d and d >= cutoff_30:
                day[d.strftime("%Y-%m-%d")] += 1
        alerts_daily_30d = [{"day": k, "n": day[k]} for k in sorted(day)]

        # top_entities (top 5)
        ent = Counter()
        for a in alerts:
            ev = (a.get("entity_value", "") or "").strip()
            if ev:
                ent[(ev, a.get("entity_type", "") or a.get("entity_field", ""))] += 1
        top_entities = [{"entity_value": k[0], "entity_type": k[1], "n": v}
                        for k, v in ent.most_common(5)]

        return resp(200, {
            "cases_by_status": cases_by_status,
            "cases_by_week": cases_by_week,
            "alerts_by_report": alerts_by_report,
            "alerts_daily_30d": alerts_daily_30d,
            "top_entities": top_entities,
            "all_done": True,
        })
    except Exception as e:
        return resp(200, {"cases_by_status": [], "cases_by_week": [], "alerts_by_report": [],
                          "alerts_daily_30d": [], "top_entities": [], "all_done": True,
                          "warning": str(e)})


# ---------------------------------------------------------------------------
# Phase 8 — Email notifications
# ---------------------------------------------------------------------------

def _send_email(to: str, subject: str, html_body: str, from_addr: str | None = None) -> None:
    """Send an email via Gmail SMTP (non-blocking — errors are swallowed).

    Always authenticates as GMAIL_USER (the account holding the app password),
    but `from_addr` lets the message go out as one of that account's "send
    mail as" aliases (e.g. compliance@global66.com) without needing a
    separate app password — Gmail allows this as long as the alias is
    configured under Settings → Accounts in that mailbox.
    """
    if not GMAIL_APP_PASSWORD or not to or not to.strip():
        return
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    sender = from_addr or GMAIL_USER
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(sender, [to], msg.as_string())
    except Exception:
        pass


def _case_assignment_email(to_email: str, case_id: str, title: str, priority: str, assigned_by: str) -> None:
    priority_color = {"critical": "#ef4444", "high": "#f97316", "medium": "#eab308", "low": "#22c55e"}.get(priority, "#94a3b8")
    html = f"""
<div style="font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px;border-radius:12px;max-width:560px">
  <div style="background:#1e293b;border-radius:8px;padding:16px 20px;margin-bottom:16px">
    <p style="margin:0;font-size:13px;color:#94a3b8">WatchTower AML &middot; Global66 Compliance</p>
    <h2 style="margin:8px 0 0;font-size:18px;color:#fff">Caso asignado a ti</h2>
  </div>
  <p style="font-size:14px;color:#cbd5e1">Se te ha asignado el siguiente caso de investigaci&#xf3;n:</p>
  <div style="background:#1e293b;border-left:4px solid {priority_color};border-radius:4px;padding:14px 18px;margin:12px 0">
    <p style="margin:0 0 4px;font-size:12px;color:#64748b;font-family:monospace">{case_id}</p>
    <p style="margin:0;font-size:15px;font-weight:600;color:#f1f5f9">{title}</p>
    <span style="display:inline-block;margin-top:8px;background:{priority_color}22;color:{priority_color};border-radius:999px;padding:2px 10px;font-size:11px;font-weight:600;text-transform:uppercase">{priority}</span>
  </div>
  <p style="font-size:12px;color:#475569;margin-top:16px">Asignado por: <strong style="color:#94a3b8">{assigned_by}</strong></p>
</div>
"""
    _send_email(to_email, f"[WatchTower] Caso asignado: {title}", html)


# ---------------------------------------------------------------------------
# Phase 9 — SLA Analytics
# ---------------------------------------------------------------------------

_SQL_SLA_AVG_RESOLUTION = """
SELECT priority,
       COUNT(*) AS total_closed,
       AVG(DATEDIFF(hour, created_at, closed_at)) AS avg_hours
FROM crm.cases
WHERE status = 'closed' AND closed_at IS NOT NULL
GROUP BY priority
ORDER BY priority
"""

_SQL_SLA_OVERDUE = """
SELECT
  SUM(CASE WHEN priority='critical' AND created_at < DATEADD(day,-1,GETDATE())  THEN 1 ELSE 0 END) AS critical_overdue,
  SUM(CASE WHEN priority='high'     AND created_at < DATEADD(day,-3,GETDATE())  THEN 1 ELSE 0 END) AS high_overdue,
  SUM(CASE WHEN priority='medium'   AND created_at < DATEADD(day,-7,GETDATE())  THEN 1 ELSE 0 END) AS medium_overdue,
  SUM(CASE WHEN priority='low'      AND created_at < DATEADD(day,-30,GETDATE()) THEN 1 ELSE 0 END) AS low_overdue,
  COUNT(*) AS total_open
FROM crm.cases
WHERE status NOT IN ('closed')
"""

_SQL_SLA_BY_PRIORITY = """
SELECT priority, status, COUNT(*) AS n
FROM crm.cases
GROUP BY priority, status
ORDER BY
  CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
  status
"""


def get_analytics_sla():
    """S3-backed → placeholder ids, real data from /analytics/sla/result."""
    return resp(200, {"stmt_ids": ["s3", "s3", "s3"]})


def get_analytics_sla_result(q0: str = "", q1: str = "", q2: str = ""):
    """Compute the 3 SLA datasets from the S3 cases store."""
    from collections import Counter
    try:
        now = dt.datetime.utcnow()
        cases = _crm_list("cases")

        # avg_resolution: por prioridad, horas promedio entre creación y cierre
        closed_by_pri: dict[str, list] = {}
        for c in cases:
            if c.get("status") == "closed" and c.get("closed_at"):
                cd, dd = _parse_dt(c.get("created_at")), _parse_dt(c.get("closed_at"))
                if cd and dd:
                    closed_by_pri.setdefault(c.get("priority", "medium"), []).append(
                        (dd - cd).total_seconds() / 3600.0)
        avg_resolution = []
        for pri in sorted(closed_by_pri):
            hrs = closed_by_pri[pri]
            avg_resolution.append({"priority": pri, "total_closed": len(hrs),
                                   "avg_hours": round(sum(hrs) / len(hrs), 1)})

        # overdue: casos abiertos que pasaron su SLA por prioridad
        sla_days = {"critical": 1, "high": 3, "medium": 7, "low": 30}
        overdue = {"critical_overdue": 0, "high_overdue": 0, "medium_overdue": 0,
                   "low_overdue": 0, "total_open": 0}
        for c in cases:
            if c.get("status") == "closed":
                continue
            overdue["total_open"] += 1
            pri = c.get("priority", "medium")
            d = _parse_dt(c.get("created_at"))
            if d and pri in sla_days and d < now - dt.timedelta(days=sla_days[pri]):
                overdue[f"{pri}_overdue"] += 1

        # by_priority: conteo por (prioridad, estado)
        bp = Counter((c.get("priority", "medium"), c.get("status", "open")) for c in cases)
        pri_rank = {"critical": 1, "high": 2, "medium": 3, "low": 4}
        by_priority = sorted(
            [{"priority": k[0], "status": k[1], "n": v} for k, v in bp.items()],
            key=lambda x: (pri_rank.get(x["priority"], 5), x["status"]))

        return resp(200, {"avg_resolution": avg_resolution, "overdue": [overdue],
                          "by_priority": by_priority, "all_done": True})
    except Exception as e:
        return resp(200, {"avg_resolution": [], "overdue": [], "by_priority": [],
                          "all_done": True, "warning": str(e)})


# ---------------------------------------------------------------------------
# Phase 7 — User Management
# ---------------------------------------------------------------------------

# Roles are a small fixed set (CRM has no role-editing UI).
ROLES = [
    {"id": 1, "name": "analyst", "description": "Analista AML"},
    {"id": 2, "name": "supervisor", "description": "Supervisor de Compliance"},
    {"id": 3, "name": "admin", "description": "Administrador"},
]
_ROLE_BY_ID = {r["id"]: r["name"] for r in ROLES}
_ROLE_BY_NAME = {r["name"]: r["id"] for r in ROLES}


def get_users():
    # S3-backed. Uses email as the stable id (route /users/{id}).
    try:
        users = []
        for u in _crm_list("users"):
            role_name = u.get("role_name", "analyst")
            users.append({
                "id": u.get("email", ""),
                "email": u.get("email", ""),
                "full_name": u.get("full_name") or u.get("email", ""),
                "is_active": bool(u.get("is_active", True)),
                "created_at": u.get("created_at", ""),
                "last_login_at": u.get("last_login_at", ""),
                "role_name": role_name,
                "role_id": _ROLE_BY_NAME.get(role_name, 1),
            })
        users.sort(key=lambda x: x["created_at"], reverse=True)
        return resp(200, {"users": users})
    except Exception as e:
        return resp(200, {"users": [], "warning": str(e)})


def get_roles():
    return resp(200, {"roles": ROLES})


def create_user(body: dict):
    email = str(body.get("email", "")).strip().lower()[:255]
    full_name = str(body.get("full_name", "")).strip()[:255]
    role_id = int(body.get("role_id", 1))
    if not email:
        return resp(400, {"error": "email is required"})
    _crm_put("users", email, {
        "email": email,
        "full_name": full_name or email,
        "is_active": True,
        "role_name": _ROLE_BY_ID.get(role_id, "analyst"),
        "created_at": _now_str(),
        "last_login_at": "",
    })
    _safe_audit(user_email="admin", action="create_user", entity_type="user", entity_id=email)
    return resp(201, {"message": "Usuario creado", "email": email})


def update_user(user_id: str, body: dict):
    # user_id is the email (what get_users returns as id).
    changes = {}
    if "full_name" in body:
        changes["full_name"] = str(body["full_name"]).strip()
    if "role_id" in body:
        changes["role_name"] = _ROLE_BY_ID.get(int(body["role_id"]), "analyst")
    if "is_active" in body:
        changes["is_active"] = bool(body["is_active"])
    if not changes:
        return resp(400, {"error": "nothing to update"})
    if _crm_update("users", user_id, changes) is None:
        return resp(404, {"error": f"User '{user_id}' not found"})
    _safe_audit(user_email="admin", action="update_user", entity_type="user", entity_id=user_id)
    return resp(200, {"message": "Usuario actualizado"})


def deactivate_user(user_id: str):
    if _crm_update("users", user_id, {"is_active": False}) is None:
        return resp(404, {"error": f"User '{user_id}' not found"})
    _safe_audit(user_email="admin", action="deactivate_user", entity_type="user", entity_id=user_id)
    return resp(200, {"message": "Usuario desactivado"})


# ---------------------------------------------------------------------------
# Phase 10 — Auto-case Rules (stored as JSON in S3)
# ---------------------------------------------------------------------------

def _load_rules() -> list[dict]:
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=AUTO_RULES_KEY)
        return json.loads(obj["Body"].read())
    except Exception:
        return []


def _save_rules(rules: list[dict]) -> None:
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=AUTO_RULES_KEY,
        Body=json.dumps(rules, default=str).encode(),
        ContentType="application/json",
    )


def get_rules():
    return resp(200, {"rules": _load_rules()})


def create_rule(body: dict):
    rules = _load_rules()
    rule = {
        "id": str(uuid.uuid4()),
        "name": str(body.get("name", "")).strip()[:100],
        "report_name": str(body.get("report_name", "")).strip()[:100],
        "row_threshold": int(body.get("row_threshold", 1)),
        "field_name": str(body.get("field_name", "")).strip()[:100],
        "field_value": float(body["field_value"]) if str(body.get("field_value", "")).strip() != "" else None,
        "case_title_template": str(body.get("case_title_template", "Alerta automática: {report_name}")).strip()[:255],
        "priority": str(body.get("priority", "medium")),
        "assigned_to": str(body.get("assigned_to", "")).strip()[:255],
        "enabled": bool(body.get("enabled", True)),
        "created_at": dt.datetime.utcnow().isoformat(),
    }
    rules.append(rule)
    _save_rules(rules)
    return resp(201, {"message": "Regla creada", "rule": rule})


def update_rule(rule_id: str, body: dict):
    rules = _load_rules()
    for rule in rules:
        if rule["id"] == rule_id:
            for field in ["name", "report_name", "row_threshold", "field_name", "case_title_template", "priority", "assigned_to", "enabled"]:
                if field in body:
                    rule[field] = body[field]
            if "field_value" in body:
                rule["field_value"] = float(body["field_value"]) if str(body["field_value"]).strip() != "" else None
            _save_rules(rules)
            return resp(200, {"message": "Regla actualizada", "rule": rule})
    return resp(404, {"error": "Rule not found"})


def delete_rule(rule_id: str):
    rules = _load_rules()
    new_rules = [r for r in rules if r["id"] != rule_id]
    if len(new_rules) == len(rules):
        return resp(404, {"error": "Rule not found"})
    _save_rules(new_rules)
    return resp(200, {"message": "Regla eliminada"})


def _create_auto_case(report_name: str, rule: dict, title: str, description: str,
                       entity_type: str = "report", entity_id: str = "") -> None:
    case_id = str(uuid.uuid4())
    now = _now_str()
    assigned = str(rule.get("assigned_to", "")).strip()
    priority = rule.get("priority", "medium")
    # Casos viven en S3 (always-on) → escribir ahí, no en Redshift.
    _crm_put("cases", case_id, {
        "case_id": case_id,
        "title": title,
        "description": description,
        "status": "open",
        "priority": priority,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "report_name": report_name,
        "assigned_to": assigned,
        "created_by": "sistema@auto",
        "created_at": now,
        "updated_at": now,
        "closed_at": "",
        "notes": [],
    })
    if assigned:
        _case_assignment_email(assigned, case_id, title, priority, "sistema automático")


class _SafeFormatDict(dict):
    """.format_map() dict that leaves unknown {placeholders} as literal text
    instead of raising KeyError (case_title_template is user-authored)."""
    def __missing__(self, key):
        return "{" + key + "}"


def apply_auto_case_rules(report_name: str, rows: list[dict], run_id: str) -> None:
    """Called after a report completes — creates cases for matching enabled rules.

    Two modes, chosen per rule:
    - field_name/field_value set  → condición por fila: crea UN caso por cada
      fila donde float(row[field_name]) > field_value (ej. smurfing con
      small_payins_7d > 1000). No envía solicitud de documentos, solo abre
      el caso y notifica al analista asignado.
    - field_name vacío (legado)   → condición por reporte completo: crea UN
      solo caso si el total de filas del reporte >= row_threshold.
    """
    row_count = len(rows)
    try:
        rules = _load_rules()
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            if rule.get("report_name") and rule["report_name"] != report_name:
                continue
            rule_name = str(rule.get("name", ""))
            field_name = str(rule.get("field_name", "")).strip()
            field_value = rule.get("field_value")

            if field_name and field_value is not None:
                for row in rows:
                    raw = row.get(field_name)
                    if raw is None:
                        continue
                    try:
                        val = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if val <= float(field_value):
                        continue
                    entity_type = "customer" if "customer_id" in row else "company" if "company_id" in row else "report"
                    entity_id = str(row.get("customer_id") or row.get("company_id") or "")
                    ctx = _SafeFormatDict(row)
                    ctx.update(report_name=report_name, row_count=row_count, run_id=run_id)
                    title = rule.get("case_title_template", "Alerta automática: {report_name}").format_map(ctx)
                    description = (f'Creado automáticamente por regla "{rule_name}" — '
                                    f"{report_name}: {field_name}={raw} (run {run_id}).")
                    _create_auto_case(report_name, rule, title, description, entity_type, entity_id)
            else:
                ctx = _SafeFormatDict(report_name=report_name, row_count=row_count, run_id=run_id)
                if row_count < int(rule.get("row_threshold", 1)):
                    continue
                title = rule.get("case_title_template", "Alerta automática: {report_name}").format_map(ctx)
                description = (f'Creado automáticamente por regla "{rule_name}" — '
                                f"{report_name} con {row_count} filas (run {run_id}).")
                _create_auto_case(report_name, rule, title, description, "report", "")
    except Exception:
        pass
