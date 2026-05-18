-- meta:
--   name: Top Customers by Range and Country
--   description: >
--     Top 15 customers (by transaction count) for each combination of
--     destination country × amount range, over the last 7 days.
--     Useful for identifying high-frequency senders that may indicate
--     structuring or smurfing.
--   schedule: "cron(0 8 ? * MON-FRI *)"
--   params: []
--
-- NOTE: No template substitution or Data API parameters needed.
--       The 7-day window is computed at query time via DATEADD + CURRENT_DATE.

WITH trx_base AS (
    SELECT
        t.transaction_id,
        t.customer_id,
        t.customer_email,
        t.remitter_account_type,
        t.beneficiary_country_code,
        t.beneficiary_country_name,
        t.destiny_amount_usd,

        CASE
            WHEN t.destiny_amount_usd < 100                                    THEN '01. < 100'
            WHEN t.destiny_amount_usd >= 100   AND t.destiny_amount_usd < 500  THEN '02. 100 - 499'
            WHEN t.destiny_amount_usd >= 500   AND t.destiny_amount_usd < 1000 THEN '03. 500 - 999'
            WHEN t.destiny_amount_usd >= 1000  AND t.destiny_amount_usd < 3000 THEN '04. 1.000 - 2.999'
            WHEN t.destiny_amount_usd >= 3000  AND t.destiny_amount_usd < 5000 THEN '05. 3.000 - 4.999'
            WHEN t.destiny_amount_usd >= 5000  AND t.destiny_amount_usd < 10000 THEN '06. 5.000 - 9.999'
            WHEN t.destiny_amount_usd >= 10000 AND t.destiny_amount_usd < 25000 THEN '07. 10.000 - 24.999'
            WHEN t.destiny_amount_usd >= 25000 AND t.destiny_amount_usd < 50000 THEN '08. 25.000 - 49.999'
            WHEN t.destiny_amount_usd >= 50000                                 THEN '09. >= 50.000'
            ELSE '00. SIN_MONTO'
        END AS amount_range_usd

    FROM "db_prod"."transaction"."transaction" AS t
    WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'
      AND t.destiny_amount_usd IS NOT NULL
),

customer_range_metrics AS (
    SELECT
        customer_id,
        customer_email,
        remitter_account_type,
        beneficiary_country_code,
        MAX(beneficiary_country_name) AS beneficiary_country_name,
        amount_range_usd,
        COUNT(*)                      AS total_transactions,
        SUM(destiny_amount_usd)       AS total_amount_usd,
        AVG(destiny_amount_usd)       AS avg_ticket_usd

    FROM trx_base

    GROUP BY
        customer_id,
        customer_email,
        remitter_account_type,
        beneficiary_country_code,
        amount_range_usd
),

ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY beneficiary_country_code, amount_range_usd
            ORDER BY total_transactions DESC, total_amount_usd DESC
        ) AS rn
    FROM customer_range_metrics
)

SELECT
    customer_id,
    customer_email,
    remitter_account_type,
    beneficiary_country_code,
    beneficiary_country_name,
    amount_range_usd,
    total_transactions,
    total_amount_usd,
    avg_ticket_usd

FROM ranked
WHERE rn <= 15

ORDER BY
    beneficiary_country_code,
    amount_range_usd,
    total_transactions DESC,
    total_amount_usd DESC;
