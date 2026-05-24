WITH hist AS (
    SELECT
        customer_id,
        AVG(destiny_amount_usd) AS hist_avg_ticket_usd,
        SUM(destiny_amount_usd) / NULLIF(COUNT(DISTINCT CAST(start_date AS DATE)), 0) AS hist_avg_daily_usd
    FROM "db_prod"."transaction"."transaction"
    WHERE start_date >= DATEADD(day, -90, CURRENT_DATE)
      AND start_date < DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(tx_status) = 'TRANSFERENCIA_EXITOSA'
    GROUP BY customer_id
),

last_7d AS (
    SELECT
        customer_id,
        MAX(customer_email) AS customer_email,
        MAX(remitter_account_type) AS remitter_account_type,
        COUNT(*) AS trx_count_7d,
        SUM(destiny_amount_usd) AS total_usd_7d,
        AVG(destiny_amount_usd) AS avg_ticket_usd_7d
    FROM "db_prod"."transaction"."transaction"
    WHERE start_date >= DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(tx_status) = 'TRANSFERENCIA_EXITOSA'
    GROUP BY customer_id
)

SELECT
    l.customer_id,
    l.customer_email,
    l.remitter_account_type,
    l.trx_count_7d,
    l.total_usd_7d,
    l.avg_ticket_usd_7d,
    h.hist_avg_ticket_usd,
    h.hist_avg_daily_usd,
    ROUND(l.avg_ticket_usd_7d / NULLIF(h.hist_avg_ticket_usd, 0), 2) AS ticket_multiplier,
    ROUND((l.total_usd_7d / 7) / NULLIF(h.hist_avg_daily_usd, 0), 2) AS daily_volume_multiplier
FROM last_7d l
INNER JOIN hist h
    ON l.customer_id = h.customer_id
WHERE l.avg_ticket_usd_7d >= h.hist_avg_ticket_usd * 3
   OR (l.total_usd_7d / 7) >= h.hist_avg_daily_usd * 3
ORDER BY
    daily_volume_multiplier DESC,
    ticket_multiplier DESC;
