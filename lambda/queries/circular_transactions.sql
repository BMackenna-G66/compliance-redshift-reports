WITH latest_kyc_document AS (
    SELECT
        kd.customer_id,
        REGEXP_REPLACE(kd.document_number, '[^0-9]', '') AS customer_dni,
        kd.document_number,
        kd.document_type,
        ROW_NUMBER() OVER (
            PARTITION BY kd.customer_id
            ORDER BY COALESCE(kd.updated_at, kd.created_at) DESC
        ) AS rn
    FROM "db_prod"."customer"."kyc_document" AS kd
    WHERE kd.document_number IS NOT NULL
),

edges AS (
    SELECT
        t.customer_id,
        kd.customer_dni,
        t.beneficiary_id,
        REGEXP_REPLACE(b.dni, '[^0-9]', '') AS beneficiary_dni,
        MAX(t.customer_email) AS customer_email,
        MAX(t.beneficiary_name) AS beneficiary_name,
        COUNT(*) AS total_trx,
        SUM(t.destiny_amount_usd) AS total_usd,
        MIN(t.start_date) AS first_trx_date,
        MAX(t.start_date) AS last_trx_date
    FROM "db_prod"."transaction"."transaction" AS t
    INNER JOIN latest_kyc_document AS kd
        ON t.customer_id = kd.customer_id
       AND kd.rn = 1
    LEFT JOIN "db_prod"."beneficiary"."beneficiary" AS b
        ON t.beneficiary_id = b.beneficiary_id
    WHERE t.start_date >= DATEADD(day, -90, CURRENT_DATE)
      AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'
      AND b.dni IS NOT NULL
    GROUP BY
        t.customer_id,
        kd.customer_dni,
        t.beneficiary_id,
        REGEXP_REPLACE(b.dni, '[^0-9]', '')
)

SELECT
    e1.customer_id AS customer_a_id,
    e1.customer_email AS customer_a_email,
    e1.customer_dni AS customer_a_dni,
    e1.beneficiary_dni AS beneficiary_b_dni,
    e1.total_trx AS trx_a_to_b,
    e1.total_usd AS usd_a_to_b,

    e2.customer_id AS customer_b_id,
    e2.customer_email AS customer_b_email,
    e2.customer_dni AS customer_b_dni,
    e2.beneficiary_dni AS beneficiary_a_dni,
    e2.total_trx AS trx_b_to_a,
    e2.total_usd AS usd_b_to_a

FROM edges e1
INNER JOIN edges e2
    ON e1.customer_dni = e2.beneficiary_dni
   AND e1.beneficiary_dni = e2.customer_dni
   AND e1.customer_id <> e2.customer_id

WHERE e1.customer_dni <> ''
  AND e1.beneficiary_dni <> ''
  AND e1.customer_dni <> '0'
  AND e1.beneficiary_dni <> '0'

ORDER BY
    (e1.total_usd + e2.total_usd) DESC;
