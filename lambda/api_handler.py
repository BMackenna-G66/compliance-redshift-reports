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
  GET  /whitelist           → list active whitelist entries
  POST /whitelist           → add an entry to the whitelist
  DELETE /whitelist/{id}    → remove a whitelist entry
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
redshift = boto3.client("redshift")

CLUSTER_ID = os.environ.get("CLUSTER_IDENTIFIER", "compliance-redshift-cluster")

RUNS_TABLE_NAME = os.environ["RUNS_TABLE"]
CATALOG_TABLE_NAME = os.environ["CATALOG_TABLE"]
REPORT_LAMBDA_NAME = os.environ["REPORT_LAMBDA"]
S3_BUCKET = os.environ["S3_BUCKET"]
WHITELIST_TABLE_NAME = os.environ.get("WHITELIST_TABLE", "")

runs_table = dynamodb.Table(RUNS_TABLE_NAME)
catalog_table = dynamodb.Table(CATALOG_TABLE_NAME)
whitelist_table = dynamodb.Table(WHITELIST_TABLE_NAME) if WHITELIST_TABLE_NAME else None

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

        # GET /cluster/status
        if method == "GET" and parts == ["cluster", "status"]:
            return get_cluster_status()

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


def _whitelist_table_ready() -> bool:
    """Return True if the whitelist table resource is configured."""
    return whitelist_table is not None


def get_whitelist():
    if not _whitelist_table_ready():
        return resp(200, {"whitelist": [], "warning": "Whitelist table not configured"})
    now = int(dt.datetime.utcnow().timestamp())
    try:
        result = whitelist_table.scan(
            FilterExpression=Attr("expires_at").gt(now)
        )
        items = sorted(result.get("Items", []), key=lambda x: x.get("created_at", ""), reverse=True)
        return resp(200, {"whitelist": items})
    except Exception as e:
        err = str(e)
        if "ResourceNotFoundException" in err or "resource not found" in err.lower():
            return resp(200, {"whitelist": [], "warning": "Whitelist table does not exist yet"})
        raise


def add_to_whitelist(body: dict):
    if not _whitelist_table_ready():
        return resp(503, {"error": "Whitelist table not configured"})
    entity_field = body.get("entity_field", "").strip()
    entity_value = body.get("entity_value", "").strip()
    duration_days = int(body.get("duration_days", 30))
    reason = body.get("reason", "").strip()
    scope = body.get("scope", "global").strip()  # "global" or report_name
    report_name = body.get("report_name", "").strip()

    if not entity_field or not entity_value:
        return resp(400, {"error": "entity_field and entity_value are required"})
    if duration_days not in (30, 60, 90):
        return resp(400, {"error": "duration_days must be 30, 60, or 90"})

    whitelist_id = str(uuid.uuid4())
    now = dt.datetime.utcnow()
    expires_at = int((now + dt.timedelta(days=duration_days)).timestamp())
    expires_date = (now + dt.timedelta(days=duration_days)).strftime("%Y-%m-%d")

    try:
        whitelist_table.put_item(Item={
            "whitelist_id": whitelist_id,
            "entity_field": entity_field,
            "entity_value": entity_value,
            "duration_days": duration_days,
            "reason": reason,
            "scope": scope,
            "report_name": report_name if scope == "report" else "",
            "created_at": now.isoformat(),
            "expires_at": expires_at,
            "expires_date": expires_date,
        })
    except Exception as e:
        if "ResourceNotFoundException" in str(e):
            return resp(503, {"error": "Whitelist table does not exist yet. Ask your cloud admin to create it."})
        raise
    return resp(201, {"whitelist_id": whitelist_id, "expires_date": expires_date})


def remove_from_whitelist(whitelist_id: str):
    if not _whitelist_table_ready():
        return resp(503, {"error": "Whitelist table not configured"})
    try:
        whitelist_table.delete_item(Key={"whitelist_id": whitelist_id})
    except Exception as e:
        if "ResourceNotFoundException" in str(e):
            return resp(503, {"error": "Whitelist table does not exist yet."})
        raise
    return resp(200, {"message": f"Whitelist entry '{whitelist_id}' removed"})
