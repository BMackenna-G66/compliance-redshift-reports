#!/usr/bin/env python3
"""
run_migration.py — Execute a Redshift CRM schema migration file.

Usage:
    cd compliance-redshift-reports-main
    AWS_PROFILE=compliance-admin python lambda/migrations/run_migration.py \
        lambda/migrations/001_redshift_crm_schema.sql

Each non-comment line ending in a blank line is treated as one SQL statement.
The script resumes the Redshift cluster if needed, then runs statements in order.
"""

import re
import sys
import time
import boto3

CLUSTER = "compliance-redshift-cluster"
DATABASE = "dev"
DB_USER = "awsuser"
REGION = "us-east-1"

rs = boto3.client("redshift", region_name=REGION)
rs_data = boto3.client("redshift-data", region_name=REGION)


def resume_cluster():
    clusters = rs.describe_clusters(ClusterIdentifier=CLUSTER)["Clusters"]
    status = clusters[0]["ClusterStatus"]
    print(f"Cluster status: {status}")

    if status == "available":
        return

    if status == "paused":
        print("Resuming cluster (this takes ~2-3 minutes)...")
        rs.resume_cluster(ClusterIdentifier=CLUSTER)

    for _ in range(30):
        time.sleep(10)
        status = rs.describe_clusters(ClusterIdentifier=CLUSTER)["Clusters"][0]["ClusterStatus"]
        print(f"  → {status}")
        if status == "available":
            return

    print("ERROR: Cluster did not become available within 5 minutes", file=sys.stderr)
    sys.exit(1)


def run_sql(sql: str, label: str) -> bool:
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        return True

    print(f"\n[{label}] {sql[:80]}{'...' if len(sql) > 80 else ''}")
    try:
        resp = rs_data.execute_statement(
            ClusterIdentifier=CLUSTER,
            Database=DATABASE,
            DbUser=DB_USER,
            Sql=sql,
        )
        stmt_id = resp["Id"]

        for _ in range(60):
            time.sleep(1)
            desc = rs_data.describe_statement(Id=stmt_id)
            status = desc["Status"]
            if status == "FINISHED":
                print("  ✓ OK")
                return True
            if status in ("FAILED", "ABORTED"):
                print(f"  ✗ {status}: {desc.get('Error', 'unknown')}", file=sys.stderr)
                return False

        print("  ✗ Timed out after 60s", file=sys.stderr)
        return False

    except Exception as e:
        print(f"  ✗ Exception: {e}", file=sys.stderr)
        return False


def parse_statements(sql_text: str) -> list[str]:
    """Split SQL file into individual statements by splitting on semicolons.

    Strips single-line comments (--) before splitting so they don't interfere.
    Empty statements and pure-comment lines are skipped.
    """
    # Remove single-line comments
    lines = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        # Inline comment: keep code, drop comment
        code = re.sub(r"\s*--.*$", "", line)
        lines.append(code)

    text = "\n".join(lines)
    raw_stmts = text.split(";")
    stmts = [s.strip() for s in raw_stmts if s.strip()]
    return stmts


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <migration.sql>", file=sys.stderr)
        sys.exit(1)

    sql_file = sys.argv[1]
    with open(sql_file) as f:
        sql_text = f.read()

    stmts = parse_statements(sql_text)
    print(f"Found {len(stmts)} statements in {sql_file}")

    resume_cluster()

    failed = 0
    for i, stmt in enumerate(stmts, 1):
        ok = run_sql(stmt, f"{i}/{len(stmts)}")
        if not ok:
            failed += 1

    print(f"\n{'='*60}")
    if failed == 0:
        print(f"Migration complete: {len(stmts)} statements executed successfully.")
    else:
        print(f"Migration finished with {failed} failure(s). Review errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
