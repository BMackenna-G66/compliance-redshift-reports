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
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import uuid

import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
s3 = boto3.client("s3")

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
    {
        "report_name": "high_risk_countries",
        "display_name": "High-Risk Countries Transactions",
        "description": "Transacciones outbound a jurisdicciones FATF/OFAC de alto riesgo. Incluye flag de mismatch SWIFT.",
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
        "is_custom": False,
        "params": [],
    },
    {
        "report_name": "top_customers_by_range_country",
        "display_name": "Top Clientes por Rango y País (7d)",
        "description": "Top 15 clientes por cantidad de transacciones para cada combinación país × rango USD, últimos 7 días.",
        "is_custom": False,
        "params": [],
    },
]


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
        # CORS preflight — return 200 so the browser accepts the request
        if method == "OPTIONS":
            return resp(200, {})

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
            return get_runs()

        # GET /runs/{run_id}
        if method == "GET" and len(parts) == 2 and parts[0] == "runs":
            return get_run(parts[1])

        # POST /queries
        if method == "POST" and parts == ["queries"]:
            return save_query(body, get_user_email(event))

        # DELETE /queries/{name}
        if method == "DELETE" and len(parts) == 2 and parts[0] == "queries":
            return delete_query(parts[1])

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

    runs_table.put_item(Item={
        "run_id": run_id,
        "report_name": report_name,
        "status": "RUNNING",
        "params": json.dumps({k: v for k, v in body.items() if k != "report_name"}),
        "started_at": now,
        "ttl": int((dt.datetime.utcnow() + dt.timedelta(days=90)).timestamp()),
    })

    # Invoke report Lambda asynchronously (Event type = fire and forget)
    payload = {**body, "run_id": run_id}
    lambda_client.invoke(
        FunctionName=REPORT_LAMBDA_NAME,
        InvocationType="Event",
        Payload=json.dumps(payload),
    )

    return resp(202, {"run_id": run_id, "status": "RUNNING"})


def get_runs():
    result = runs_table.scan(
        ProjectionExpression=(
            "run_id, report_name, #st, params, started_at, "
            "completed_at, s3_key, row_count, error_message"
        ),
        ExpressionAttributeNames={"#st": "status"},
    )
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


def delete_query(report_name: str):
    builtin_names = {r["report_name"] for r in BUILTIN_REPORTS}
    if report_name in builtin_names:
        return resp(400, {"error": "No se pueden eliminar los reportes predefinidos"})
    catalog_table.delete_item(Key={"report_name": report_name})
    return resp(200, {"message": f"Query '{report_name}' eliminada"})
