"""
MySQL connection module for WatchTower CRM V2.

Reads credentials from Secrets Manager (DB_SECRET_ARN env var).
Keeps one connection alive across warm Lambda invocations.
"""
from __future__ import annotations

import json
import os
import logging

import boto3
import pymysql
import pymysql.cursors

logger = logging.getLogger(__name__)

_conn: pymysql.connections.Connection | None = None
_creds: dict | None = None


def _load_creds() -> dict:
    global _creds
    if _creds is not None:
        return _creds
    secret_arn = os.environ.get("DB_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError("DB_SECRET_ARN env var not set")
    sm = boto3.client("secretsmanager")
    raw = sm.get_secret_value(SecretId=secret_arn)["SecretString"]
    _creds = json.loads(raw)
    return _creds


def get_connection() -> pymysql.connections.Connection:
    """Return a live MySQL connection, reconnecting if needed."""
    global _conn
    if _conn is not None:
        try:
            _conn.ping(reconnect=True)
            return _conn
        except Exception:
            _conn = None

    creds = _load_creds()
    _conn = pymysql.connect(
        host=creds["host"],
        user=creds["username"],
        password=creds["password"],
        database=creds.get("dbname", "watchtower"),
        port=int(creds.get("port", 3306)),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=30,
        write_timeout=30,
        charset="utf8mb4",
    )
    logger.info("MySQL connection established")
    return _conn


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def fetchone(sql: str, params: tuple | None = None) -> dict | None:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def fetchall(sql: str, params: tuple | None = None) -> list[dict]:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def execute(sql: str, params: tuple | None = None) -> int:
    """Run INSERT/UPDATE/DELETE. Returns rowcount."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        conn.commit()
        return cur.rowcount


def insert(sql: str, params: tuple | None = None) -> int:
    """Run INSERT. Returns lastrowid."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        conn.commit()
        return cur.lastrowid


def execute_many(sql: str, rows: list[tuple]) -> int:
    """Bulk insert/update. Returns rowcount."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# Audit log helper
# ---------------------------------------------------------------------------

def write_audit(
    *,
    user_email: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> None:
    """Write a structured audit log entry. Failures are logged, not raised."""
    try:
        insert(
            """
            INSERT INTO audit_log
              (user_email, action, entity_type, entity_id, old_value, new_value)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_email,
                action,
                entity_type,
                entity_id,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None,
            ),
        )
    except Exception as exc:
        logger.error("audit_log write failed: %s", exc)
