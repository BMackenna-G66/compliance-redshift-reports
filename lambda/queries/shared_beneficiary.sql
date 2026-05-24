WITH beneficiary_base AS (
    SELECT
        b.beneficiary_id,
        b.dni AS beneficiary_dni,
        REGEXP_REPLACE(b.dni, '[^0-9]', '') AS beneficiary_dni_normalizado,
        b.dni_type AS beneficiary_dni_type,
        b.name AS beneficiary_name,
        b.last_name AS beneficiary_last_name,
        b.country_code AS beneficiary_country_code,
        b.country_name AS beneficiary_country_name,
        b.email AS beneficiary_email,
        b.phone_number AS beneficiary_phone_number
    FROM "db_prod"."beneficiary"."beneficiary" AS b
    WHERE b.dni IS NOT NULL
      AND REGEXP_REPLACE(b.dni, '[^0-9]', '') NOT IN ('', '0')
),

trx_7d AS (
    SELECT
        t.transaction_id,
        t.customer_id,
        t.customer_email,
        t.remitter_account_type,
        t.beneficiary_id,
        t.start_date,
        t.destiny_amount_usd
    FROM "db_prod"."transaction"."transaction" AS t
    WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'
      AND t.beneficiary_id IS NOT NULL
)

SELECT
    bb.beneficiary_dni_normalizado,
    MAX(bb.beneficiary_dni) AS beneficiary_dni_example,
    MAX(bb.beneficiary_dni_type) AS beneficiary_dni_type,
    MAX(bb.beneficiary_name) AS beneficiary_name,
    MAX(bb.beneficiary_last_name) AS beneficiary_last_name,
    MAX(bb.beneficiary_country_code) AS beneficiary_country_code,
    MAX(bb.beneficiary_country_name) AS beneficiary_country_name,

    COUNT(*) AS total_trx_7d,
    COUNT(DISTINCT t.customer_id) AS remitentes_unicos_7d,
    COUNT(DISTINCT t.beneficiary_id) AS beneficiary_ids_distintos_7d,

    SUM(t.destiny_amount_usd) AS total_usd_7d,
    AVG(t.destiny_amount_usd) AS avg_ticket_usd_7d

FROM trx_7d AS t
INNER JOIN beneficiary_base AS bb
    ON t.beneficiary_id = bb.beneficiary_id

GROUP BY
    bb.beneficiary_dni_normalizado

HAVING COUNT(DISTINCT t.customer_id) >= 3

ORDER BY
    remitentes_unicos_7d DESC,
    total_usd_7d DESC;
