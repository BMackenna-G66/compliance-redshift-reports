WITH customer_7d AS (
    SELECT
        t.customer_id,
        t.customer_email,
        t.remitter_account_type,

        COUNT(*) AS total_trx_7d,
        SUM(t.destiny_amount_usd) AS total_usd_7d,
        AVG(t.destiny_amount_usd) AS avg_ticket_usd_7d,
        MAX(t.destiny_amount_usd) AS max_ticket_usd_7d,

        SUM(
            CASE
                WHEN t.destiny_amount_usd < 1000 THEN 1
                ELSE 0
            END
        ) AS trx_bajo_1000_usd,

        SUM(
            CASE
                WHEN t.destiny_amount_usd < 1000 THEN t.destiny_amount_usd
                ELSE 0
            END
        ) AS monto_bajo_1000_usd

    FROM "db_prod"."transaction"."transaction" AS t
    WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'

    GROUP BY
        t.customer_id,
        t.customer_email,
        t.remitter_account_type
)

SELECT
    customer_id,
    customer_email,
    remitter_account_type,

    total_trx_7d,
    total_usd_7d,
    avg_ticket_usd_7d,
    max_ticket_usd_7d,

    trx_bajo_1000_usd,
    monto_bajo_1000_usd,

    ROUND(
        trx_bajo_1000_usd::DECIMAL / NULLIF(total_trx_7d, 0),
        2
    ) AS ratio_trx_bajo_1000

FROM customer_7d

WHERE total_trx_7d >= 5
  AND trx_bajo_1000_usd >= 5
  AND total_usd_7d >= 3000

ORDER BY
    ratio_trx_bajo_1000 DESC,
    total_usd_7d DESC;
