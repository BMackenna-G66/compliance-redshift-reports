WITH payins_small AS (
    SELECT
        customer_id,
        COUNT(*) AS small_payins_7d,
        SUM(origin_amount_usd) AS small_payin_total_usd_7d,
        AVG(origin_amount_usd) AS small_payin_avg_usd_7d,
        MAX(creation_date) AS last_small_payin_date
    FROM "db_prod"."treasury"."cash_call"
    WHERE creation_date >= DATEADD(day, -7, CURRENT_DATE)
      AND LOWER(status) = 'paid'
      AND UPPER(type) = 'CR'
      AND origin_amount_usd < 1000
    GROUP BY customer_id
),

payouts AS (
    SELECT
        customer_id,
        COUNT(*) AS total_payouts_7d,
        SUM(destiny_amount_usd) AS total_payout_usd_7d,
        MAX(creation_date) AS last_payout_date
    FROM "db_prod"."treasury"."cash_call"
    WHERE creation_date >= DATEADD(day, -7, CURRENT_DATE)
      AND LOWER(status) = 'paid'
      AND UPPER(type) = 'DR'
    GROUP BY customer_id
)

SELECT
    s.customer_id,
    s.small_payins_7d,
    s.small_payin_total_usd_7d,
    s.small_payin_avg_usd_7d,
    p.total_payouts_7d,
    p.total_payout_usd_7d,
    s.last_small_payin_date,
    p.last_payout_date,
    ROUND(p.total_payout_usd_7d / NULLIF(s.small_payin_total_usd_7d, 0), 2) AS payout_vs_small_payin_ratio
FROM payins_small s
INNER JOIN payouts p
    ON s.customer_id = p.customer_id
WHERE s.small_payins_7d >= 5
  AND p.total_payouts_7d >= 1
ORDER BY
    s.small_payins_7d DESC,
    p.total_payout_usd_7d DESC;
