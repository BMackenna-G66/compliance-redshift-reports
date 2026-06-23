"""
db_redshift.py — CRM Redshift Data API helper.

Provides synchronous CRUD wrappers over the Redshift Data API for CRM operations.
The Redshift cluster may be paused; every public function auto-resumes it on first
use and caches the "available" state for the lifetime of the Lambda warm instance.

Usage:
    from db_redshift import fetchone, fetchall, execute, write_audit

SQL style:
    Use :param_name placeholders in SQL; pass params as list of {"name": ..., "value": ...}.
    All values must be strings — Redshift casts to the column type automatically.
    For SUPER (JSON) columns, pass JSON-encoded strings and wrap with JSON_PARSE(:p).
"""

from __future__ import annotations

import json
import logging
import os
import time

import boto3

logger = logging.getLogger(__name__)

_redshift_data = None
_redshift_mgmt = None
_cluster_available = False  # module-level cache; reset on cold start

CLUSTER_ID = os.environ.get("CLUSTER_IDENTIFIER", "compliance-redshift-cluster")
DATABASE = os.environ.get("DATABASE_NAME", "dev")
DB_USER = os.environ.get("DB_USER", "awsuser")
_REGION = "us-east-1"

_RESUME_TIMEOUT_S = 300
_QUERY_TIMEOUT_S = 30


def _data_client():
    global _redshift_data
    if _redshift_data is None:
        _redshift_data = boto3.client("redshift-data", region_name=_REGION)
    return _redshift_data


def _mgmt_client():
    global _redshift_mgmt
    if _redshift_mgmt is None:
        _redshift_mgmt = boto3.client("redshift", region_name=_REGION)
    return _redshift_mgmt


# ---------------------------------------------------------------------------
# Cluster lifecycle
# ---------------------------------------------------------------------------

def ensure_available() -> None:
    """Resume the cluster if paused and wait until it's available.

    Idempotent — does nothing if the cluster is already running.
    Raises RuntimeError if the cluster doesn't become available within the timeout.
    """
    global _cluster_available
    if _cluster_available:
        return

    rs = _mgmt_client()
    cluster = rs.describe_clusters(ClusterIdentifier=CLUSTER_ID)["Clusters"][0]
    status = cluster["ClusterStatus"]

    if status == "available":
        _cluster_available = True
        return

    if status == "paused":
        logger.info("Redshift cluster is paused — resuming...")
        rs.resume_cluster(ClusterIdentifier=CLUSTER_ID)
    elif status not in ("resuming",):
        raise RuntimeError(f"Redshift cluster is in unexpected state: {status}")

    deadline = time.time() + _RESUME_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(10)
        status = rs.describe_clusters(ClusterIdentifier=CLUSTER_ID)["Clusters"][0]["ClusterStatus"]
        logger.info("Cluster status: %s", status)
        if status == "available":
            _cluster_available = True
            return

    raise RuntimeError(f"Cluster did not become available within {_RESUME_TIMEOUT_S}s")


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------

def _exec(sql: str, params: list[dict] | None = None, timeout_s: int = _QUERY_TIMEOUT_S) -> list[dict]:
    """Submit SQL to Redshift Data API, poll until done, return rows as list of dicts."""
    sql = sql.strip().rstrip(";").strip()
    kwargs: dict = {
        "ClusterIdentifier": CLUSTER_ID,
        "Database": DATABASE,
        "DbUser": DB_USER,
        "Sql": sql,
    }
    if params:
        kwargs["Parameters"] = params

    try:
        resp = _data_client().execute_statement(**kwargs)
    except Exception as e:
        msg = str(e)
        if any(x in msg.lower() for x in ("paused", "unavailable", "not available")):
            logger.warning("Cluster unavailable, attempting resume: %s", msg)
            _cluster_available_reset()
            ensure_available()
            resp = _data_client().execute_statement(**kwargs)
        else:
            raise

    stmt_id = resp["Id"]
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        desc = _data_client().describe_statement(Id=stmt_id)
        status = desc["Status"]

        if status == "FINISHED":
            if not desc.get("HasResultSet"):
                return []
            return _fetch_rows(stmt_id)

        if status in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Redshift statement {stmt_id} {status}: {desc.get('Error', 'unknown')}")

        time.sleep(0.4)

    raise RuntimeError(f"Redshift statement {stmt_id} did not finish within {timeout_s}s")


def _cluster_available_reset():
    global _cluster_available
    _cluster_available = False


def _fetch_rows(stmt_id: str) -> list[dict]:
    rows: list[dict] = []
    columns: list[str] = []
    next_token: str | None = None

    while True:
        kw: dict = {"Id": stmt_id}
        if next_token:
            kw["NextToken"] = next_token

        result = _data_client().get_statement_result(**kw)

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetchall(sql: str, params: list[dict] | None = None) -> list[dict]:
    """Run a SELECT and return all rows as a list of dicts."""
    return _exec(sql, params)


def fetchone(sql: str, params: list[dict] | None = None) -> dict | None:
    """Run a SELECT and return the first row, or None if no rows."""
    rows = _exec(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: list[dict] | None = None) -> None:
    """Run an INSERT / UPDATE / DELETE statement."""
    _exec(sql, params)


def write_audit(
    *,
    user_email: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value: object = None,
    new_value: object = None,
) -> None:
    """Append a row to crm.audit_log (fire-and-forget; errors are logged, not raised)."""
    try:
        execute(
            """
            INSERT INTO crm.audit_log
                (user_email, action, entity_type, entity_id, old_value, new_value)
            VALUES (
                :email,
                :action,
                :entity_type,
                :entity_id,
                JSON_PARSE(:old_value),
                JSON_PARSE(:new_value)
            )
            """,
            [
                {"name": "email",       "value": user_email},
                {"name": "action",      "value": action},
                {"name": "entity_type", "value": entity_type or ""},
                {"name": "entity_id",   "value": str(entity_id) if entity_id is not None else ""},
                {"name": "old_value",   "value": json.dumps(old_value) if old_value is not None else "null"},
                {"name": "new_value",   "value": json.dumps(new_value) if new_value is not None else "null"},
            ],
        )
    except Exception:
        logger.exception("write_audit failed (non-fatal)")
