#!/usr/bin/env python3
"""
load_bbdd_delitos.py
────────────────────────────────────────────────────────────────────────────────
Carga el Excel "Clientes con delitos bbdd_delitos.xlsx" en Redshift:

  compliance.bbdd_clientes   — 1 fila por cliente (info básica + total_delitos)
  compliance.bbdd_delitos    — 1 fila por delito  (normalizado desde Hoja1)

Estrategia de carga:
  1. Leer Excel (Hoja1)
  2. Generar dos archivos CSV comprimidos (gzip)
  3. Subir a S3  → s3://<bucket>/compliance-data/bbdd_delitos/
  4. CREATE TABLE IF NOT EXISTS en Redshift (via Data API)
  5. TRUNCATE + COPY desde S3

Requisitos:
  pip install openpyxl boto3

Uso:
  AWS_PROFILE=compliance-admin python3 load_bbdd_delitos.py
  AWS_PROFILE=compliance-admin python3 load_bbdd_delitos.py --excel /ruta/al/archivo.xlsx
────────────────────────────────────────────────────────────────────────────────
"""

import argparse
import csv
import gzip
import io
import os
import sys
import time
from datetime import datetime

import boto3
import openpyxl

# ── Config ────────────────────────────────────────────────────────────────────
CLUSTER_ID   = "compliance-redshift-cluster"
DATABASE     = "dev"
DB_USER      = "awsuser"
S3_BUCKET    = "compliance-redshift-reports-561521480266-us-east-1"
S3_PREFIX    = "compliance-data/bbdd-delitos"
REGION       = "us-east-1"
REDSHIFT_IAM = "arn:aws:iam::561521480266:role/service-role/AmazonRedshift-CommandsAccessRole-20260505T161312"

DEFAULT_EXCEL = os.path.expanduser(
    "~/Desktop/Clientes con delitos bbdd_delitos.xlsx"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_date(value):
    """Convert DD/MM/YYYY string → YYYY-MM-DD, or return None."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None  # unparseable → NULL in Redshift


def clean(value):
    """Stringify + strip; return empty string for None (CSV NULL placeholder)."""
    if value is None:
        return ""
    return str(value).strip().replace("\n", " ").replace("\r", "")


def rs_exec(client, sql, label=""):
    """Submit a SQL statement via Redshift Data API and wait for it to finish."""
    print(f"  ▶ {label or sql[:80]}")
    resp = client.execute_statement(
        ClusterIdentifier=CLUSTER_ID,
        Database=DATABASE,
        DbUser=DB_USER,
        Sql=sql,
    )
    stmt_id = resp["Id"]
    while True:
        desc = client.describe_statement(Id=stmt_id)
        status = desc["Status"]
        if status == "FINISHED":
            print(f"    ✓ OK")
            return
        if status in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Statement {label!r} {status}: {desc.get('Error')}")
        time.sleep(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", default=DEFAULT_EXCEL, help="Ruta al Excel")
    args = parser.parse_args()

    if not os.path.exists(args.excel):
        sys.exit(f"❌  No se encontró el archivo: {args.excel}")

    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "default"))
    s3      = session.client("s3", region_name=REGION)
    rd      = session.client("redshift-data", region_name=REGION)

    # ── 1. Leer Excel ──────────────────────────────────────────────────────────
    print(f"\n📂  Leyendo {args.excel} ...")
    wb = openpyxl.load_workbook(args.excel, read_only=True, data_only=True)
    ws = wb["Hoja1"]
    all_rows = list(ws.iter_rows(values_only=True))
    data_rows = all_rows[1:]
    print(f"    {len(data_rows):,} filas de clientes encontradas")

    # ── 2. Generar CSVs en memoria ─────────────────────────────────────────────
    print("\n🔄  Normalizando datos...")

    clientes_text = io.StringIO()
    delitos_text  = io.StringIO()

    cw = csv.writer(clientes_text, delimiter="|", quoting=csv.QUOTE_MINIMAL)
    dw = csv.writer(delitos_text,  delimiter="|", quoting=csv.QUOTE_MINIMAL)

    total_delitos  = 0
    total_clientes = 0

    for row in data_rows:
        grupo         = clean(row[0])
        rut           = clean(row[1])
        customer_id   = clean(row[2])
        compliance_st = clean(row[3])
        nombre        = clean(row[4])
        apellido      = clean(row[5])
        email         = clean(row[6])
        risk_level    = clean(row[7])
        con_info      = clean(row[8])

        # Count delitos for this client
        n_delitos = sum(
            1 for i in range(108)
            if (9 + i * 7) < len(row) and row[9 + i * 7] is not None
        )

        cw.writerow([
            grupo, rut, customer_id, compliance_st,
            nombre, apellido, email, risk_level, con_info, n_delitos,
        ])
        total_clientes += 1

        for i in range(108):
            base = 9 + (i * 7)
            if base >= len(row) or row[base] is None:
                continue
            crimen   = clean(row[base])
            estado   = clean(row[base + 1]) if base + 1 < len(row) else ""
            fecha    = parse_date(row[base + 2]) if base + 2 < len(row) else None
            riesgo   = clean(row[base + 3]) if base + 3 < len(row) else ""
            rit      = clean(row[base + 4]) if base + 4 < len(row) else ""
            ruc      = clean(row[base + 5]) if base + 5 < len(row) else ""
            tribunal = clean(row[base + 6]) if base + 6 < len(row) else ""

            dw.writerow([rut, customer_id, i, crimen, estado, fecha or "",
                         riesgo, rit, ruc, tribunal])
            total_delitos += 1

    print(f"    ✓ {total_clientes:,} clientes")
    print(f"    ✓ {total_delitos:,} delitos (normalizados)")

    # Compress to gzip bytes (simple and reliable)
    clientes_gz = gzip.compress(clientes_text.getvalue().encode("utf-8"))
    delitos_gz  = gzip.compress(delitos_text.getvalue().encode("utf-8"))
    clientes_text.close()
    delitos_text.close()

    # ── 3. Subir a S3 ──────────────────────────────────────────────────────────
    s3_clientes = f"{S3_PREFIX}/clientes.csv.gz"
    s3_delitos  = f"{S3_PREFIX}/delitos.csv.gz"

    print(f"\n☁️   Subiendo a s3://{S3_BUCKET}/{S3_PREFIX}/ ...")

    s3.upload_fileobj(
        io.BytesIO(clientes_gz), S3_BUCKET, s3_clientes,
        ExtraArgs={"ContentType": "application/gzip"},
    )
    print(f"    ✓ clientes.csv.gz  ({len(clientes_gz)/1024:.0f} KB)")

    s3.upload_fileobj(
        io.BytesIO(delitos_gz), S3_BUCKET, s3_delitos,
        ExtraArgs={"ContentType": "application/gzip"},
    )
    print(f"    ✓ delitos.csv.gz   ({len(delitos_gz)/1024:.0f} KB)")

    # ── 4. CREATE TABLES ───────────────────────────────────────────────────────
    print("\n🏗️   Creando tablas en compliance schema ...")

    # Drop + recreate to ensure schema is correct on re-runs
    rs_exec(rd, "DROP TABLE IF EXISTS compliance.bbdd_clientes", "DROP bbdd_clientes")
    rs_exec(rd, "DROP TABLE IF EXISTS compliance.bbdd_delitos",  "DROP bbdd_delitos")

    rs_exec(rd, """
CREATE TABLE compliance.bbdd_clientes (
    grupo             INTEGER,
    rut               VARCHAR(20),
    customer_id       BIGINT,
    compliance_status VARCHAR(50),
    nombre            VARCHAR(300),
    apellido          VARCHAR(300),
    email             VARCHAR(300),
    risk_level        VARCHAR(50),
    con_info          VARCHAR(10),
    total_delitos     SMALLINT,
    loaded_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
DISTKEY(customer_id)
SORTKEY(rut)
""", "CREATE TABLE bbdd_clientes")

    rs_exec(rd, """
CREATE TABLE compliance.bbdd_delitos (
    rut         VARCHAR(20),
    customer_id BIGINT,
    delito_num  SMALLINT,
    crimen      VARCHAR(1000),
    estado      VARCHAR(100),
    fecha       DATE,
    riesgo      VARCHAR(20),
    rit         VARCHAR(200),
    ruc         VARCHAR(200),
    tribunal    VARCHAR(500),
    loaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
DISTKEY(customer_id)
SORTKEY(rut, delito_num)
""", "CREATE TABLE bbdd_delitos")

    # ── 5. TRUNCATE + COPY ─────────────────────────────────────────────────────
    print("\n📥  Cargando datos (COPY desde S3) ...")

    rs_exec(rd, f"""
COPY compliance.bbdd_clientes (
    grupo, rut, customer_id, compliance_status,
    nombre, apellido, email, risk_level, con_info, total_delitos
)
FROM 's3://{S3_BUCKET}/{s3_clientes}'
IAM_ROLE '{REDSHIFT_IAM}'
FORMAT AS CSV
DELIMITER '|'
GZIP
NULL AS ''
TIMEFORMAT 'auto'
ACCEPTINVCHARS
COMPUPDATE OFF
STATUPDATE OFF
""", "COPY bbdd_clientes")

    rs_exec(rd, f"""
COPY compliance.bbdd_delitos (
    rut, customer_id, delito_num,
    crimen, estado, fecha, riesgo, rit, ruc, tribunal
)
FROM 's3://{S3_BUCKET}/{s3_delitos}'
IAM_ROLE '{REDSHIFT_IAM}'
FORMAT AS CSV
DELIMITER '|'
GZIP
NULL AS ''
DATEFORMAT 'YYYY-MM-DD'
ACCEPTINVCHARS
COMPUPDATE OFF
STATUPDATE OFF
""", "COPY bbdd_delitos")

    # ── 6. Verify ──────────────────────────────────────────────────────────────
    print("\n🔍  Verificando conteos ...")

    def count_rows(table):
        resp = rd.execute_statement(
            ClusterIdentifier=CLUSTER_ID, Database=DATABASE, DbUser=DB_USER,
            Sql=f"SELECT COUNT(*) FROM {table}",
        )
        sid = resp["Id"]
        while True:
            d = rd.describe_statement(Id=sid)
            if d["Status"] == "FINISHED":
                r = rd.get_statement_result(Id=sid)
                return r["Records"][0][0].get("longValue", 0)
            time.sleep(0.5)

    n_c = count_rows("compliance.bbdd_clientes")
    n_d = count_rows("compliance.bbdd_delitos")
    print(f"    compliance.bbdd_clientes : {n_c:,} filas")
    print(f"    compliance.bbdd_delitos  : {n_d:,} filas")

    print("\n✅  Carga completada exitosamente.\n")


if __name__ == "__main__":
    main()
