WITH payins AS (
    SELECT
        cash_call_id AS payin_cash_call_id,
        customer_id,
        creation_date AS payin_date,
        origin_amount_usd AS payin_amount_usd
    FROM "db_prod"."treasury"."cash_call"
    WHERE creation_date >= DATEADD(day, -7, CURRENT_DATE)
      AND LOWER(status) = 'paid'
      AND UPPER(type) = 'CR'
),

payouts AS (
    SELECT
        cash_call_id AS payout_cash_call_id,
        customer_id,
        creation_date AS payout_date,
        destiny_amount_usd AS payout_amount_usd
    FROM "db_prod"."treasury"."cash_call"
    WHERE creation_date >= DATEADD(day, -7, CURRENT_DATE)
      AND LOWER(status) = 'paid'
      AND UPPER(type) = 'DR'
)

SELECT
    p.customer_id,
    p.payin_cash_call_id,
    p.payin_date,
    p.payin_amount_usd,
    o.payout_cash_call_id,
    o.payout_date,
    o.payout_amount_usd,
    DATEDIFF(hour, p.payin_date, o.payout_date) AS hours_between_payin_payout
FROM payins p
INNER JOIN payouts o
    ON p.customer_id = o.customer_id
   AND o.payout_date >= p.payin_date
   AND o.payout_date <= DATEADD(hour, 24, p.payin_date)
ORDER BY
    hours_between_payin_payout ASC,
    o.payout_amount_usd DESC;
