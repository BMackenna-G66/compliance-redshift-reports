"""
Compliance Redshift Reports — main Lambda handler.

Flow:
  1. Resume cluster if paused, wait until available.
  2. Execute parameterized SQL via Redshift Data API.
  3. Fetch results and build Excel + HTML summary.
  4. Upload Excel to S3 (encrypted).
  5. Send SES email with attachment + presigned link.
  6. POST summary to Slack webhook.
  7. Pause cluster.

Environment variables expected (set by Terraform):
  CLUSTER_IDENTIFIER       — Redshift cluster identifier
  DATABASE_NAME            — DB name (e.g. dev)
  DB_USER                  — DB user (e.g. awsuser) — uses IAM auth via GetClusterCredentials
  S3_BUCKET                — output bucket
  SES_FROM_ADDRESS         — verified SES sender
  SES_TO_ADDRESSES         — comma-separated recipients
  SLACK_WEBHOOK_SECRET_ARN — Secrets Manager ARN holding the Slack webhook URL
  REPORT_NAME              — short id for the report ("high_risk_countries")
  AUTO_PAUSE               — "true" to pause cluster after run, "false" to leave it on
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

# ---------------------------------------------------------------------------
# Config
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

BASE_DIR = Path(__file__).parent
QUERIES_DIR = BASE_DIR / "queries"
CONFIG_DIR = BASE_DIR / "config"
TEMPLATES_DIR = BASE_DIR

POLL_INTERVAL_SECONDS = 5
MAX_WAIT_RESUME_SECONDS = 600  # 10 min
MAX_WAIT_QUERY_SECONDS = 600   # 10 min


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
    try:
        status = get_cluster_status()
        if status == "available":
            logger.info("Pausing cluster %s", CLUSTER_ID)
            redshift.pause_cluster(ClusterIdentifier=CLUSTER_ID)
        else:
            logger.info("Cluster status is %s, skipping pause", status)
    except Exception as e:  # noqa: BLE001
        # Never fail the run on a pause error — the report is already delivered.
        logger.exception("Failed to pause cluster: %s", e)


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------
def load_country_codes() -> list[dict]:
    with open(CONFIG_DIR / "high_risk_countries.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["countries"]


def render_query(since_date: str, only_successful: bool, country_codes: list[str]) -> str:
    sql_template = (QUERIES_DIR / "high_risk_countries_transactions.sql").read_text(encoding="utf-8")
    # country list and boolean flag are template-substituted (trusted, not user input).
    # since_date stays as a Data API parameter (`:since_date`) — see SQL.
    quoted_countries = ",".join(f"'{c}'" for c in country_codes)
    return (
        sql_template
        .replace("{country_codes}", quoted_countries)
        .replace("{only_successful}", "TRUE" if only_successful else "FALSE")
    )


def execute_query(sql: str, since_date: str) -> list[dict]:
    logger.info("Submitting query to Redshift Data API")
    resp = redshift_data.execute_statement(
        ClusterIdentifier=CLUSTER_ID,
        Database=DATABASE,
        DbUser=DB_USER,
        Sql=sql,
        Parameters=[
            {"name": "since_date", "value": since_date},
        ],
        WithEvent=False,
    )
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
# Report building
# ---------------------------------------------------------------------------
def build_summary(rows: list[dict]) -> dict:
    """Aggregate stats for the email/slack summary."""
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


def build_excel(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"

    if not rows:
        ws["A1"] = "No transactions found for the selected period."
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


def post_slack(summary: dict, params: dict, s3_url: str) -> None:
    if not SLACK_SECRET_ARN:
        logger.info("No Slack secret configured, skipping Slack notification")
        return

    secret = secrets.get_secret_value(SecretId=SLACK_SECRET_ARN)
    webhook_url = secret["SecretString"].strip()

    text_lines = [
        f"*Compliance Report — High-Risk Countries Transactions*",
        f"Period since: `{params['since_date']}`  •  Generated: {dt.datetime.utcnow():%Y-%m-%d %H:%M UTC}",
        "",
        f"• Total transactions: *{summary['total_transactions']:,}*",
        f"• Total USD: *${summary['total_usd']:,.2f}*",
        f"• Distinct countries: *{summary['distinct_countries']}*",
        f"• SWIFT/country mismatches: *{summary['swift_country_mismatches']}* :warning:",
        "",
        "*Top 5 countries by USD:*",
    ]
    for c in summary["top_countries"][:5]:
        text_lines.append(f"  • {c['country']}: {c['count']} tx — ${c['usd']:,.2f}")
    text_lines.append("")
    text_lines.append(f"<{s3_url}|Download full report (expires in 24h)>")

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

    # --- resolve params (CLI/manual invoke override the defaults) ---
    today = dt.date.today()
    default_since = today.replace(day=1).isoformat()
    since_date = event.get("since_date") or default_since
    only_successful = bool(event.get("only_successful", False))

    countries = load_country_codes()
    country_codes = [c["code"] for c in countries]

    params = {
        "since_date": since_date,
        "only_successful": only_successful,
        "country_count": len(country_codes),
    }

    try:
        ensure_cluster_available()

        sql = render_query(since_date, only_successful, country_codes)
        rows = execute_query(sql, since_date)

        summary = build_summary(rows)
        xlsx_bytes = build_excel(rows)

        run_ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        key = f"{REPORT_NAME}/{run_ts}_since-{since_date}.xlsx"
        s3_url = upload_to_s3(xlsx_bytes, key, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        subject = f"[Compliance] High-Risk Countries Tx — since {since_date} — {summary['total_transactions']} tx"
        html = render_email_html(summary, params, s3_url)

        # Email is best-effort: SES identity may not be verified yet.
        # A failure here does NOT abort the run — report is already in S3 + Slack.
        try:
            send_email(html, xlsx_bytes, Path(key).name, subject)
        except Exception as e:  # noqa: BLE001
            logger.warning("Email delivery failed (non-blocking): %s", e)

        post_slack(summary, params, s3_url)

        return {
            "status": "ok",
            "rows": summary["total_transactions"],
            "s3_key": key,
            "params": params,
        }
    finally:
        if AUTO_PAUSE:
            pause_cluster()
