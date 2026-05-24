WITH payins AS (
    SELECT
        customer_id,
        COUNT(*) AS total_payins_7d,
        SUM(origin_amount_usd) AS total_payin_usd_7d,
        AVG(origin_amount_usd) AS avg_payin_usd_7d,
        MAX(creation_date) AS last_payin_date
    FROM "db_prod"."treasury"."cash_call"
    WHERE creation_date >= DATEADD(day, -7, CURRENT_DATE)
      AND LOWER(status) = 'paid'
      AND UPPER(type) = 'CR'
    GROUP BY customer_id
),

payouts AS (
    SELECT
        customer_id,
        COUNT(*) AS total_payouts_7d,
        SUM(destiny_amount_usd) AS total_payout_usd_7d,
        AVG(destiny_amount_usd) AS avg_payout_usd_7d,
        MAX(creation_date) AS last_payout_date
    FROM "db_prod"."treasury"."cash_call"
    WHERE creation_date >= DATEADD(day, -7, CURRENT_DATE)
      AND LOWER(status) = 'paid'
      AND UPPER(type) = 'DR'
    GROUP BY customer_id
)

SELECT
    p.customer_id,
    p.total_payins_7d,
    p.total_payin_usd_7d,
    p.avg_payin_usd_7d,
    o.total_payouts_7d,
    o.total_payout_usd_7d,
    o.avg_payout_usd_7d,
    p.last_payin_date,
    o.last_payout_date,
    ROUND(o.total_payout_usd_7d / NULLIF(p.total_payin_usd_7d, 0), 2) AS payout_vs_payin_ratio
FROM payins p
INNER JOIN payouts o
    ON p.customer_id = o.customer_id
WHERE p.total_payins_7d >= 5
  AND o.total_payouts_7d >= 1
ORDER BY
    payout_vs_payin_ratio DESC,
    p.total_payin_usd_7d DESC;
