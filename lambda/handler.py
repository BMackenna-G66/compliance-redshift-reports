"""
Compliance Redshift Reports — main Lambda handler.

Flow:
  1. Resume cluster if paused, wait until available.
  2. Execute the SQL for the requested report via Redshift Data API.
  3. Fetch results and build Excel + HTML summary.
  4. Upload Excel to S3 (encrypted).
  5. Send SES email with attachment + presigned link (best-effort).
  6. POST summary to Slack webhook.
  7. Pause cluster.

Supported reports (pass via event["report_name"] or REPORT_NAME env var):
  - high_risk_countries        : AML screening — outbound tx to FATF/OFAC countries
  - amount_ranges_by_country   : Volume distribution by USD range × destination country (7d)
  - top_customers_by_range_country : Top-15 customers per range × country (7d)

Environment variables expected (set by Terraform):
  CLUSTER_IDENTIFIER       — Redshift cluster identifier
  DATABASE_NAME            — DB name (e.g. dev)
  DB_USER                  — DB user — uses IAM auth via GetClusterCredentials
  S3_BUCKET                — output bucket
  SES_FROM_ADDRESS         — verified SES sender
  SES_TO_ADDRESSES         — comma-separated recipients
  SLACK_WEBHOOK_SECRET_ARN — Secrets Manager ARN holding the Slack webhook URL
  REPORT_NAME              — default report if not passed in event
  AUTO_PAUSE               — "true" to pause cluster after run
  RUNS_TABLE               — DynamoDB table name for run history (optional)
  CATALOG_TABLE            — DynamoDB table name for custom query catalog (optional)
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import logging
import os
import time
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import boto3
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# AWS clients (created once per Lambda container)
# ---------------------------------------------------------------------------
redshift = boto3.client("redshift")
redshift_data = boto3.client("redshift-data")
s3 = boto3.client("s3")
ses = boto3.client("ses")
secrets = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
CLUSTER_ID = os.environ["CLUSTER_IDENTIFIER"]
DATABASE = os.environ["DATABASE_NAME"]
DB_USER = os.environ["DB_USER"]
S3_BUCKET = os.environ["S3_BUCKET"]
SES_FROM = os.environ["SES_FROM_ADDRESS"]
SES_TO = [e.strip() for e in os.environ["SES_TO_ADDRESSES"].split(",") if e.strip()]
SLACK_SECRET_ARN = os.environ.get("SLACK_WEBHOOK_SECRET_ARN", "")
REPORT_NAME = os.environ.get("REPORT_NAME", "high_risk_countries")
AUTO_PAUSE = os.environ.get("AUTO_PAUSE", "true").lower() == "true"
RUNS_TABLE_NAME = os.environ.get("RUNS_TABLE", "")
CATALOG_TABLE_NAME = os.environ.get("CATALOG_TABLE", "")
WHITELIST_TABLE_NAME = os.environ.get("WHITELIST_TABLE", "")

BASE_DIR = Path(__file__).parent
QUERIES_DIR = BASE_DIR / "queries"
CONFIG_DIR = BASE_DIR / "config"
TEMPLATES_DIR = BASE_DIR

POLL_INTERVAL_SECONDS = 5
MAX_WAIT_RESUME_SECONDS = 780   # 13 min (Lambda timeout is 900s)
MAX_WAIT_QUERY_SECONDS = 540    # 9 min

# ---------------------------------------------------------------------------
# Report registry
# Add new reports here — no other changes needed for simple cases.
# ---------------------------------------------------------------------------
REPORT_CONFIGS: dict[str, dict] = {
    "high_risk_countries": {
        "display_name": "High-Risk Countries Transactions",
        "sql_file": "high_risk_countries_transactions.sql",
        "needs_country_filter": True,   # substitutes {country_codes} and {only_successful}
        "needs_since_date": True,        # passes :since_date as Data API parameter
    },
    "amount_ranges_by_country": {
        "display_name": "Amount Ranges by Country (7d)",
        "sql_file": "amount_ranges_by_country.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "top_customers_by_range_country": {
        "display_name": "Top Customers by Range & Country (7d)",
        "sql_file": "top_customers_by_range_country.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "tax_haven_transactions": {
        "display_name": "Transacciones a Régimen Fiscal Preferencial (90d)",
        "sql_file": "tax_haven_transactions.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "tax_haven_funding": {
        "display_name": "Fondeos desde Régimen Fiscal Preferencial (7d)",
        "sql_file": "tax_haven_funding.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "payin_payout_accumulation": {
        "display_name": "Acumulación Pay In → Pay Out (7d)",
        "sql_file": "payin_payout_accumulation.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "small_payin_structuring": {
        "display_name": "Pay In Pequeños → Pay Out (Smurfing, 7d)",
        "sql_file": "small_payin_structuring.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "velocity_payin_payout": {
        "display_name": "Velocity Pay In ↔ Pay Out < 24h (7d)",
        "sql_file": "velocity_payin_payout.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "external_funder_single": {
        "display_name": "Tercero que Fondea Una Sola Cuenta (7d)",
        "sql_file": "external_funder_single.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "external_funder_multiple": {
        "display_name": "Tercero que Fondea Múltiples Cuentas (7d)",
        "sql_file": "external_funder_multiple.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "circular_transactions": {
        "display_name": "Circularidad DNI Cliente ↔ Beneficiario (90d)",
        "sql_file": "circular_transactions.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "structuring_detection": {
        "display_name": "Estructuración / Fraccionamiento (7d)",
        "sql_file": "structuring_detection.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "shared_beneficiary": {
        "display_name": "Beneficiario Compartido por Múltiples Remitentes (7d)",
        "sql_file": "shared_beneficiary.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "customer_metrics_7d": {
        "display_name": "Métricas por Cliente B2C (7d)",
        "sql_file": "customer_metrics_7d.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "beneficiary_concentration": {
        "display_name": "Concentración de Beneficiarios (7d)",
        "sql_file": "beneficiary_concentration.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "beneficiary_dispersion": {
        "display_name": "Dispersión de Beneficiarios (7d)",
        "sql_file": "beneficiary_dispersion.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "outbound_bank_change": {
        "display_name": "Cambio de Banco Outbound (30d vs 7d)",
        "sql_file": "outbound_bank_change.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "new_corridor_detection": {
        "display_name": "Corredor Nuevo para el Cliente (7d vs 90d)",
        "sql_file": "new_corridor_detection.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "high_volume_vs_historical": {
        "display_name": "Alto Volumen vs Histórico (7d vs 90d)",
        "sql_file": "high_volume_vs_historical.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "swift_mismatch_detection": {
        "display_name": "Mismatch SWIFT vs País Beneficiario (30d)",
        "sql_file": "swift_mismatch_detection.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "jumio_kyc_approval_rates": {
        "display_name": "Tasas de Aprobación / Rechazo KYC por Flujo",
        "sql_file": "jumio_kyc_approval_rates.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "jumio_duplicate_flows": {
        "display_name": "Documentos Jumio Duplicados / Flujos Múltiples",
        "sql_file": "jumio_duplicate_flows.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "b2c_as_legal_rep": {
        "display_name": "Clientes B2C como Representantes Legales",
        "sql_file": "b2c_as_legal_rep.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "top_companies_by_legal_reps": {
        "display_name": "Top 15 Empresas con Más Representantes Legales",
        "sql_file": "top_companies_by_legal_reps.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "age_anomaly_customers": {
        "display_name": "Clientes con Anomalía de Edad (<18 o >90 años)",
        "sql_file": "age_anomaly_customers.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "crypto_bridge_transactions": {
        "display_name": "Transacciones Bridge/Crypto (30d)",
        "sql_file": "crypto_bridge_transactions.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "crypto_bridge_cash_calls": {
        "display_name": "Cash Calls Bridge/Crypto (30d)",
        "sql_file": "crypto_bridge_cash_calls.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "crypto_high_risk_destinations": {
        "display_name": "Crypto hacia Países de Riesgo (30d)",
        "sql_file": "crypto_high_risk_destinations.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
    "crypto_full_bridge_activity": {
        "display_name": "Actividad Completa Bridge (30d)",
        "sql_file": "crypto_full_bridge_activity.sql",
        "needs_country_filter": False,
        "needs_since_date": False,
    },
}


# ---------------------------------------------------------------------------
# Cluster control
# ---------------------------------------------------------------------------
def get_cluster_status() -> str:
    resp = redshift.describe_clusters(ClusterIdentifier=CLUSTER_ID)
    return resp["Clusters"][0]["ClusterStatus"]


def ensure_cluster_available() -> None:
    status = get_cluster_status()
    logger.info("Cluster %s status: %s", CLUSTER_ID, status)

    if status == "available":
        return

    if status == "paused":
        logger.info("Resuming cluster %s", CLUSTER_ID)
        redshift.resume_cluster(ClusterIdentifier=CLUSTER_ID)

    deadline = time.time() + MAX_WAIT_RESUME_SECONDS
    while time.time() < deadline:
        status = get_cluster_status()
        if status == "available":
            logger.info("Cluster is available")
            return
        logger.info("Waiting for cluster... (current: %s)", status)
        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"Cluster did not become available within {MAX_WAIT_RESUME_SECONDS}s")


def pause_cluster() -> None:
    """Pause the cluster, retrying if Redshift still has internal operations running."""
    MAX_PAUSE_ATTEMPTS = 6
    PAUSE_RETRY_WAIT = 20  # seconds between retries

    for attempt in range(1, MAX_PAUSE_ATTEMPTS + 1):
        try:
            status = get_cluster_status()
            if status != "available":
                logger.info("Cluster status is %s, skipping pause", status)
                return
            logger.info("Pausing cluster %s (attempt %d/%d)", CLUSTER_ID, attempt, MAX_PAUSE_ATTEMPTS)
            redshift.pause_cluster(ClusterIdentifier=CLUSTER_ID)
            logger.info("Cluster pause initiated successfully")
            return
        except redshift.exceptions.InvalidClusterStateFault:
            if attempt < MAX_PAUSE_ATTEMPTS:
                logger.info("Cluster busy, retrying pause in %ds...", PAUSE_RETRY_WAIT)
                time.sleep(PAUSE_RETRY_WAIT)
            else:
                logger.warning("Could not pause cluster after %d attempts — pause it manually", MAX_PAUSE_ATTEMPTS)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to pause cluster: %s", e)
            return


# ---------------------------------------------------------------------------
# Whitelist support
# ---------------------------------------------------------------------------
def fetch_active_whitelist(report_name: str = "") -> list[dict]:
    """Fetch non-expired whitelist entries. Returns global + report-specific."""
    if not WHITELIST_TABLE_NAME:
        return []
    try:
        from boto3.dynamodb.conditions import Attr
        table = dynamodb.Table(WHITELIST_TABLE_NAME)
        now_ts = int(time.time())
        result = table.scan(
            FilterExpression=Attr("expires_at").gt(now_ts)
        )
        entries = result.get("Items", [])
        # Filter: global entries OR entries matching this report
        return [
            e for e in entries
            if e.get("scope") == "global" or e.get("report_name") == report_name
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_active_whitelist failed (non-blocking): %s", e)
        return []


def inject_whitelist_exclusions(sql: str, whitelist_entries: list[dict]) -> str:
    """Wrap SQL in a subquery that excludes whitelisted entities."""
    if not whitelist_entries:
        return sql
    # Group exclusions by field
    by_field: dict[str, list[str]] = {}
    for entry in whitelist_entries:
        field = entry.get("entity_field", "").strip()
        value = str(entry.get("entity_value", "")).strip()
        if field and value:
            by_field.setdefault(field, []).append(value)
    if not by_field:
        return sql
    conditions = []
    for field, values in by_field.items():
        quoted = ", ".join(f"'{v.replace(chr(39), chr(39)+chr(39))}'" for v in values)
        conditions.append(f"CAST({field} AS VARCHAR) NOT IN ({quoted})")
    where_clause = " AND ".join(conditions)
    wrapped = f"SELECT * FROM (\n{sql}\n) _wt_base\nWHERE {where_clause}"
    logger.info("Whitelist injection: excluded %d entries across %d fields", len(whitelist_entries), len(by_field))
    return wrapped


# ---------------------------------------------------------------------------
# Query rendering + execution
# ---------------------------------------------------------------------------
def load_country_codes() -> list[dict]:
    with open(CONFIG_DIR / "high_risk_countries.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["countries"]


def render_query(
    report_name: str,
    since_date: str,
    only_successful: bool,
    country_codes: list[str],
) -> tuple[str, list[dict]]:
    """Return (sql_string, data_api_params_list) for the given report.

    For built-in reports, reads from the queries/ directory.
    For custom reports, reads SQL from the DynamoDB catalog.
    """
    api_params: list[dict] = []

    if report_name in REPORT_CONFIGS:
        config = REPORT_CONFIGS[report_name]
        sql = (QUERIES_DIR / config["sql_file"]).read_text(encoding="utf-8")

        if config["needs_country_filter"]:
            quoted = ",".join(f"'{c}'" for c in country_codes)
            sql = sql.replace("{country_codes}", quoted)
            sql = sql.replace("{only_successful}", "TRUE" if only_successful else "FALSE")

        if config["needs_since_date"]:
            api_params.append({"name": "since_date", "value": since_date})
    else:
        # Custom query from DynamoDB catalog
        sql = _load_custom_sql(report_name)
        if not sql:
            raise ValueError(f"Report '{report_name}' not found in built-in registry or catalog")

    # Inject whitelist exclusions
    whitelist_entries = fetch_active_whitelist(report_name)
    if whitelist_entries:
        sql = inject_whitelist_exclusions(sql, whitelist_entries)

    return sql, api_params


def execute_query(sql: str, api_params: list[dict] | None = None) -> list[dict]:
    logger.info("Submitting query to Redshift Data API")
    kwargs: dict = dict(
        ClusterIdentifier=CLUSTER_ID,
        Database=DATABASE,
        DbUser=DB_USER,
        Sql=sql,
        WithEvent=False,
    )
    if api_params:
        kwargs["Parameters"] = api_params

    resp = redshift_data.execute_statement(**kwargs)
    statement_id = resp["Id"]
    logger.info("Statement id: %s", statement_id)

    deadline = time.time() + MAX_WAIT_QUERY_SECONDS
    while time.time() < deadline:
        desc = redshift_data.describe_statement(Id=statement_id)
        status = desc["Status"]
        if status == "FINISHED":
            break
        if status in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Query {status}: {desc.get('Error', 'unknown error')}")
        time.sleep(POLL_INTERVAL_SECONDS)
    else:
        raise TimeoutError(f"Query did not finish within {MAX_WAIT_QUERY_SECONDS}s")

    return fetch_results(statement_id)


def fetch_results(statement_id: str) -> list[dict]:
    rows: list[dict] = []
    columns: list[str] = []
    next_token: str | None = None

    while True:
        kwargs = {"Id": statement_id}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = redshift_data.get_statement_result(**kwargs)

        if not columns:
            columns = [c["name"] for c in resp["ColumnMetadata"]]

        for record in resp["Records"]:
            rows.append({columns[i]: _unwrap_value(cell) for i, cell in enumerate(record)})

        next_token = resp.get("NextToken")
        if not next_token:
            break

    logger.info("Fetched %d rows", len(rows))
    return rows


def _unwrap_value(cell: dict):
    """Redshift Data API returns each cell as a single-key dict like {'stringValue': 'x'}."""
    if "isNull" in cell and cell["isNull"]:
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue", "blobValue"):
        if key in cell:
            return cell[key]
    return None


# ---------------------------------------------------------------------------
# DynamoDB run tracking  (no-ops when RUNS_TABLE_NAME is empty)
# ---------------------------------------------------------------------------
def _update_run(run_id: str | None, **attrs) -> None:
    """Best-effort DynamoDB update — failures are logged but never propagate."""
    if not run_id or not RUNS_TABLE_NAME:
        return
    try:
        table = dynamodb.Table(RUNS_TABLE_NAME)
        update_expr = "SET " + ", ".join(f"#{k} = :{k}" for k in attrs)
        expr_names = {f"#{k}": k for k in attrs}
        expr_values = {f":{k}": v for k, v in attrs.items()}
        table.update_item(
            Key={"run_id": run_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("DynamoDB update_run failed (non-blocking): %s", e)


def _load_custom_sql(report_name: str) -> str | None:
    """Fetch SQL from the DynamoDB catalog for custom queries. Returns None if not found."""
    if not CATALOG_TABLE_NAME:
        return None
    try:
        table = dynamodb.Table(CATALOG_TABLE_NAME)
        item = table.get_item(Key={"report_name": report_name}).get("Item")
        return item.get("sql") if item else None
    except Exception as e:  # noqa: BLE001
        logger.warning("DynamoDB catalog lookup failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------
def build_summary(rows: list[dict], report_name: str) -> dict:
    """Dispatch to report-specific summary builder."""
    if report_name == "high_risk_countries":
        return _summary_high_risk(rows)
    if report_name == "amount_ranges_by_country":
        return _summary_amount_ranges(rows)
    if report_name == "top_customers_by_range_country":
        return _summary_top_customers(rows)
    return _summary_generic(rows)


def _summary_high_risk(rows: list[dict]) -> dict:
    total = len(rows)
    by_country: dict[str, dict] = {}
    swift_mismatches = 0
    total_usd = 0.0

    for r in rows:
        country = r.get("beneficiary_country_code") or "UNK"
        usd = float(r.get("destiny_amount_usd") or 0)
        total_usd += usd
        if r.get("swift_country_mismatch_flag"):
            swift_mismatches += 1
        bucket = by_country.setdefault(country, {"count": 0, "usd": 0.0})
        bucket["count"] += 1
        bucket["usd"] += usd

    top_countries = sorted(
        ({"country": k, **v} for k, v in by_country.items()),
        key=lambda x: x["usd"],
        reverse=True,
    )[:10]

    return {
        "total_transactions": total,
        "total_usd": total_usd,
        "distinct_countries": len(by_country),
        "swift_country_mismatches": swift_mismatches,
        "top_countries": top_countries,
    }


def _summary_amount_ranges(rows: list[dict]) -> dict:
    total_rows = len(rows)
    total_txs = sum(int(r.get("total_transactions") or 0) for r in rows)
    total_usd = sum(float(r.get("total_amount_usd") or 0) for r in rows)
    distinct_countries = len({r.get("beneficiary_country_code") for r in rows})

    # Top 5 country+range combos by transaction count
    top_combos = sorted(rows, key=lambda r: int(r.get("total_transactions") or 0), reverse=True)[:5]

    return {
        "total_rows": total_rows,
        "total_transactions": total_txs,
        "total_usd": total_usd,
        "distinct_countries": distinct_countries,
        "top_combos": [
            {
                "country": r.get("beneficiary_country_code"),
                "range": r.get("amount_range_usd"),
                "count": r.get("total_transactions"),
                "usd": r.get("total_amount_usd"),
            }
            for r in top_combos
        ],
    }


def _summary_top_customers(rows: list[dict]) -> dict:
    total_rows = len(rows)
    distinct_customers = len({r.get("customer_id") for r in rows})
    distinct_countries = len({r.get("beneficiary_country_code") for r in rows})
    total_usd = sum(float(r.get("total_amount_usd") or 0) for r in rows)

    # Top 5 customers by total transactions
    top_customers = sorted(rows, key=lambda r: int(r.get("total_transactions") or 0), reverse=True)[:5]

    return {
        "total_rows": total_rows,
        "distinct_customers": distinct_customers,
        "distinct_countries": distinct_countries,
        "total_usd": total_usd,
        "top_customers": [
            {
                "customer_id": r.get("customer_id"),
                "email": r.get("customer_email"),
                "country": r.get("beneficiary_country_code"),
                "range": r.get("amount_range_usd"),
                "count": r.get("total_transactions"),
                "usd": r.get("total_amount_usd"),
            }
            for r in top_customers
        ],
    }


def _summary_generic(rows: list[dict]) -> dict:
    return {"total_rows": len(rows)}


def build_excel(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"

    if not rows:
        ws["A1"] = "No data found for the selected period."
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    columns = list(rows[0].keys())
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E78")

    for col_idx, col in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row_idx, row in enumerate(rows, start=2):
        for col_idx, col in enumerate(columns, start=1):
            ws.cell(row=row_idx, column=col_idx, value=row.get(col))

    for col_idx in range(1, len(columns) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 22

    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_to_s3(content: bytes, key: str, content_type: str) -> str:
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=content,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=24 * 60 * 60,  # 24h
    )
    return url


def render_email_html(summary: dict, params: dict, s3_url: str) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("email_template.html")
    return template.render(
        summary=summary,
        params=params,
        s3_url=s3_url,
        generated_at=dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
def send_email(html_body: str, xlsx_bytes: bytes, xlsx_filename: str, subject: str) -> None:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = SES_FROM
    msg["To"] = ", ".join(SES_TO)

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(body)

    att = MIMEApplication(xlsx_bytes)
    att.add_header("Content-Disposition", "attachment", filename=xlsx_filename)
    msg.attach(att)

    ses.send_raw_email(
        Source=SES_FROM,
        Destinations=SES_TO,
        RawMessage={"Data": msg.as_string()},
    )
    logger.info("Email sent to %s", SES_TO)


def post_slack(summary: dict, params: dict, s3_url: str, report_name: str) -> None:
    if not SLACK_SECRET_ARN:
        logger.info("No Slack secret configured, skipping Slack notification")
        return

    secret = secrets.get_secret_value(SecretId=SLACK_SECRET_ARN)
    webhook_url = secret["SecretString"].strip()
    display_name = REPORT_CONFIGS.get(report_name, {}).get("display_name", report_name)
    generated_at = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    text_lines = [f"*Compliance Report — {display_name}*", f"Generated: {generated_at}", ""]

    if report_name == "high_risk_countries":
        text_lines += [
            f"Period since: `{params['since_date']}`",
            f"• Total transactions: *{summary['total_transactions']:,}*",
            f"• Total USD: *${summary['total_usd']:,.2f}*",
            f"• Distinct countries: *{summary['distinct_countries']}*",
            f"• SWIFT/country mismatches: *{summary['swift_country_mismatches']}* :warning:",
            "",
            "*Top 5 countries by USD:*",
        ]
        for c in summary["top_countries"][:5]:
            text_lines.append(f"  • {c['country']}: {c['count']} tx — ${c['usd']:,.2f}")

    elif report_name == "amount_ranges_by_country":
        text_lines += [
            f"• Combinations country × range: *{summary['total_rows']:,}*",
            f"• Total transactions: *{summary['total_transactions']:,}*",
            f"• Total USD: *${summary['total_usd']:,.2f}*",
            f"• Distinct countries: *{summary['distinct_countries']}*",
            "",
            "*Top 5 combos by transaction count:*",
        ]
        for c in summary.get("top_combos", []):
            text_lines.append(f"  • {c['country']} / {c['range']}: {c['count']} tx — ${float(c['usd'] or 0):,.2f}")

    elif report_name == "top_customers_by_range_country":
        text_lines += [
            f"• Total rows: *{summary['total_rows']:,}*",
            f"• Distinct customers: *{summary['distinct_customers']:,}*",
            f"• Distinct countries: *{summary['distinct_countries']}*",
            f"• Total USD: *${summary['total_usd']:,.2f}*",
            "",
            "*Top 5 customers by transaction count:*",
        ]
        for c in summary.get("top_customers", []):
            text_lines.append(
                f"  • {c['customer_id']} ({c['country']} / {c['range']}): {c['count']} tx"
            )

    else:
        text_lines.append(f"• Total rows: *{summary.get('total_rows', '?'):,}*")

    text_lines += ["", f"<{s3_url}|Download full report (expires in 24h)>"]

    payload = json.dumps({"text": "\n".join(text_lines)}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Slack webhook returned {resp.status}")
    logger.info("Slack notification posted")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def handler(event, context):  # noqa: ARG001
    logger.info("Event: %s", json.dumps(event, default=str))

    # report_name: from event payload (EventBridge / API / manual invoke) → fallback to env var
    report_name = event.get("report_name") or REPORT_NAME
    # run_id is injected by api_handler when a user triggers via the frontend
    run_id: str | None = event.get("run_id")

    # Validate: built-in OR exists in DynamoDB catalog
    is_builtin = report_name in REPORT_CONFIGS
    if not is_builtin and not _load_custom_sql(report_name):
        err = f"Unknown report '{report_name}'. Valid built-ins: {list(REPORT_CONFIGS)}"
        _update_run(run_id, status="ERROR", error_message=err,
                    completed_at=dt.datetime.utcnow().isoformat())
        raise ValueError(err)

    config = REPORT_CONFIGS.get(report_name, {})
    display_name = config.get("display_name", report_name)
    logger.info("Running report: %s (run_id=%s)", display_name, run_id)

    # Resolve optional params (only used by high_risk_countries today)
    today = dt.date.today()
    default_since = today.replace(day=1).isoformat()
    since_date = event.get("since_date") or default_since
    only_successful = bool(event.get("only_successful", False))

    country_codes: list[str] = []
    if config.get("needs_country_filter"):
        countries = load_country_codes()
        country_codes = [c["code"] for c in countries]

    params = {
        "report_name": report_name,
        "since_date": since_date if config.get("needs_since_date") else "last_7_days",
        "only_successful": only_successful,
        "country_count": len(country_codes),
    }

    try:
        # Signal the frontend that we're waking the cluster
        _update_run(run_id, status="RESUMING")
        ensure_cluster_available()

        sql, api_params = render_query(report_name, since_date, only_successful, country_codes)
        rows = execute_query(sql, api_params)

        summary = build_summary(rows, report_name)
        xlsx_bytes = build_excel(rows)

        run_ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        # Key includes since_date for high_risk_countries; just timestamp for others
        if config.get("needs_since_date"):
            key = f"{report_name}/{run_ts}_since-{since_date}.xlsx"
        else:
            key = f"{report_name}/{run_ts}.xlsx"

        s3_url = upload_to_s3(
            xlsx_bytes, key,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        total_rows = summary.get("total_transactions") or summary.get("total_rows", 0)
        subject = f"[Compliance] {display_name} — {total_rows} rows"
        html = render_email_html(summary, params, s3_url)

        # Email is best-effort: SES identity may not be verified yet.
        try:
            send_email(html, xlsx_bytes, Path(key).name, subject)
        except Exception as e:  # noqa: BLE001
            logger.warning("Email delivery failed (non-blocking): %s", e)

        post_slack(summary, params, s3_url, report_name)

        # Update DynamoDB run record to DONE (best-effort)
        result_preview = rows[:10]  # first 10 rows for in-browser preview
        _update_run(
            run_id,
            status="DONE",
            completed_at=dt.datetime.utcnow().isoformat(),
            s3_key=key,
            row_count=total_rows,
            result_preview=json.dumps(result_preview, default=str),
        )

        return {
            "status": "ok",
            "report_name": report_name,
            "rows": total_rows,
            "s3_key": key,
            "params": params,
        }

    except Exception as e:  # noqa: BLE001
        logger.exception("Report run failed: %s", e)
        _update_run(
            run_id,
            status="ERROR",
            completed_at=dt.datetime.utcnow().isoformat(),
            error_message=str(e),
        )
        raise

    finally:
        if AUTO_PAUSE:
            pause_cluster()
