WITH hist AS (
    SELECT DISTINCT
        customer_id,
        outbound_bank_name
    FROM "db_prod"."transaction"."transaction"
    WHERE start_date >= DATEADD(day, -30, CURRENT_DATE)
      AND start_date < DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(tx_status) = 'TRANSFERENCIA_EXITOSA'
      AND outbound_bank_name IS NOT NULL
),

last_7d AS (
    SELECT DISTINCT
        customer_id,
        customer_email,
        remitter_account_type,
        outbound_bank_name
    FROM "db_prod"."transaction"."transaction"
    WHERE start_date >= DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(tx_status) = 'TRANSFERENCIA_EXITOSA'
      AND outbound_bank_name IS NOT NULL
)

SELECT
    l.customer_id,
    l.customer_email,
    l.remitter_account_type,
    l.outbound_bank_name AS new_outbound_bank_name
FROM last_7d l
LEFT JOIN hist h
    ON l.customer_id = h.customer_id
   AND l.outbound_bank_name = h.outbound_bank_name
WHERE h.customer_id IS NULL
ORDER BY
    l.customer_id;
