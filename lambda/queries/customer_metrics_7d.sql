WITH base AS (
    SELECT
        t.customer_id,
        c.email,
        t.remitter_account_type,
        t.transaction_id,
        t.beneficiary_id,
        t.destiny_amount_usd,
        COALESCE(t.outbound_bank_name, 'SIN_OUTBOUND_BANK') AS outbound_bank_name
    FROM "db_prod"."transaction"."transaction" AS t
    LEFT JOIN "db_prod"."customer"."customer_v2" AS c
        ON t.customer_id = c.customer_id
    WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA' and t.remitter_account_type = 'Individual'
),

customer_metrics AS (
    SELECT
        customer_id,
        email,
        remitter_account_type,
        COUNT(*) AS total_transactions_7d,
        COUNT(DISTINCT beneficiary_id) AS unique_beneficiaries_7d,
        SUM(destiny_amount_usd) AS total_amount_usd_7d,
        AVG(destiny_amount_usd) AS avg_ticket_usd_7d
    FROM base
    GROUP BY
        customer_id,
        email,
        remitter_account_type
),

customer_banks AS (
    SELECT
        customer_id,
        remitter_account_type,
        LISTAGG(outbound_bank_name, ' | ')
            WITHIN GROUP (ORDER BY outbound_bank_name) AS outbound_banks_used
    FROM (
        SELECT DISTINCT
            customer_id,
            remitter_account_type,
            outbound_bank_name
        FROM base
    ) b
    GROUP BY
        customer_id,
        remitter_account_type
)

SELECT
    cm.customer_id,
    cm.email,
    cm.remitter_account_type,
    cm.total_transactions_7d,
    cm.unique_beneficiaries_7d,
    cm.total_amount_usd_7d,
    cm.avg_ticket_usd_7d,
    cb.outbound_banks_used
FROM customer_metrics cm
LEFT JOIN customer_banks cb
    ON cm.customer_id = cb.customer_id
   AND cm.remitter_account_type = cb.remitter_account_type
ORDER BY
    cm.remitter_account_type,
    cm.total_transactions_7d DESC,
    cm.total_amount_usd_7d DESC;
