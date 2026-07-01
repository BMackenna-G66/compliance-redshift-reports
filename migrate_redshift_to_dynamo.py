#!/usr/bin/env python3
"""
migrate_redshift_to_dynamo.py
────────────────────────────────────────────────────────────────────────────────
Copia los datos operativos del CRM que hoy viven en Redshift hacia las tablas
DynamoDB, para que sigan visibles aunque el cluster esté pausado.

Se corre UNA SOLA VEZ por módulo, con el cluster Redshift ENCENDIDO.
Es idempotente: re-correrlo sobre-escribe (put_item) las mismas filas por su id,
no duplica.

Uso:
  AWS_PROFILE=compliance-admin python3 migrate_redshift_to_dynamo.py whitelist
  AWS_PROFILE=compliance-admin python3 migrate_redshift_to_dynamo.py --all

Módulos disponibles: whitelist  (alerts, cases, users, audit se agregan luego)
────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

import boto3

# ── Config (alinear con las env vars de las Lambdas / Terraform) ──────────────
CLUSTER_ID = "compliance-redshift-cluster"
DATABASE = "dev"
DB_USER = "awsuser"
REGION = "us-east-1"
PROJECT = "compliance-redshift-reports"

session = boto3.Session(region_name=REGION)
rs_data = session.client("redshift-data")
dynamodb = session.resource("dynamodb")


def _rs_query(sql: str, timeout_s: int = 60) -> list[dict]:
    """Ejecuta SQL en Redshift vía Data API y devuelve filas como dicts."""
    stmt = rs_data.execute_statement(
        ClusterIdentifier=CLUSTER_ID, Database=DATABASE, DbUser=DB_USER, Sql=sql,
    )
    sid = stmt["Id"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        desc = rs_data.describe_statement(Id=sid)
        status = desc["Status"]
        if status == "FINISHED":
            if not desc.get("HasResultSet"):
                return []
            result = rs_data.get_statement_result(Id=sid)
            cols = [c["name"] for c in result["ColumnMetadata"]]
            rows = []
            for rec in result["Records"]:
                row = {}
                for i, cell in enumerate(rec):
                    if cell.get("isNull"):
                        row[cols[i]] = None
                    else:
                        row[cols[i]] = (
                            cell.get("stringValue")
                            or cell.get("longValue")
                            or cell.get("doubleValue")
                            or cell.get("booleanValue")
                        )
                rows.append(row)
            return rows
        if status in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Redshift {status}: {desc.get('Error')}")
        time.sleep(1)
    raise TimeoutError(f"Query no terminó en {timeout_s}s")


def _to_epoch(ts: str | None) -> int:
    """Convierte 'YYYY-MM-DD HH:MM:SS' (o ISO) a epoch UTC. 0 si no parsea."""
    if not ts:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return int(dt.datetime.strptime(ts[:19], fmt).timestamp())
        except ValueError:
            continue
    return 0


# ── whitelist ─────────────────────────────────────────────────────────────────
def migrate_whitelist() -> int:
    rows = _rs_query(
        "SELECT whitelist_id, entity_field, entity_value, duration_days, reason, "
        "scope, report_name, created_at::VARCHAR AS created_at, "
        "expires_at::VARCHAR AS expires_at FROM compliance.whitelist"
    )
    table = dynamodb.Table(f"{PROJECT}-whitelist")
    n = 0
    with table.batch_writer() as bw:
        for r in rows:
            wid = r.get("whitelist_id")
            if not wid:
                continue
            bw.put_item(Item={
                "whitelist_id": str(wid),
                "entity_field": r.get("entity_field") or "",
                "entity_value": r.get("entity_value") or "",
                "duration_days": int(r.get("duration_days") or 0),
                "reason": r.get("reason") or "",
                "scope": r.get("scope") or "global",
                "report_name": r.get("report_name") or "",
                "created_at": (r.get("created_at") or "")[:19],
                "expires_at": _to_epoch(r.get("expires_at")),
            })
            n += 1
    return n


MIGRATIONS = {
    "whitelist": migrate_whitelist,
}


def main():
    ap = argparse.ArgumentParser(description="Migra datos del CRM de Redshift a DynamoDB")
    ap.add_argument("modules", nargs="*", help="Módulos a migrar: " + ", ".join(MIGRATIONS))
    ap.add_argument("--all", action="store_true", help="Migrar todos los módulos disponibles")
    args = ap.parse_args()

    targets = list(MIGRATIONS) if args.all else args.modules
    if not targets:
        ap.print_help()
        sys.exit(1)

    for name in targets:
        fn = MIGRATIONS.get(name)
        if not fn:
            print(f"  ⚠ módulo desconocido: {name} (disponibles: {', '.join(MIGRATIONS)})")
            continue
        print(f"→ Migrando {name} ...")
        count = fn()
        print(f"  ✓ {name}: {count} filas copiadas a DynamoDB")


if __name__ == "__main__":
    main()
