WITH hist_routes AS (
    SELECT DISTINCT
        customer_id,
        origin_country,
        origin_currency,
        beneficiary_country_code,
        destiny_currency
    FROM "db_prod"."transaction"."transaction"
    WHERE start_date >= DATEADD(day, -90, CURRENT_DATE)
      AND start_date < DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(tx_status) = 'TRANSFERENCIA_EXITOSA'
),

last_7d_routes AS (
    SELECT
        customer_id,
        customer_email,
        remitter_account_type,
        origin_country,
        origin_currency,
        beneficiary_country_code,
        destiny_currency,
        COUNT(*) AS trx_count_7d,
        SUM(destiny_amount_usd) AS total_usd_7d
    FROM "db_prod"."transaction"."transaction"
    WHERE start_date >= DATEADD(day, -7, CURRENT_DATE)
      AND UPPER(tx_status) = 'TRANSFERENCIA_EXITOSA'
    GROUP BY
        customer_id,
        customer_email,
        remitter_account_type,
        origin_country,
        origin_currency,
        beneficiary_country_code,
        destiny_currency
)

SELECT
    l.customer_id,
    l.customer_email,
    l.remitter_account_type,
    l.origin_country || '/' || l.origin_currency || ' -> ' ||
    l.beneficiary_country_code || '/' || l.destiny_currency AS new_route,
    l.trx_count_7d,
    l.total_usd_7d
FROM last_7d_routes l
LEFT JOIN hist_routes h
    ON l.customer_id = h.customer_id
   AND l.origin_country = h.origin_country
   AND l.origin_currency = h.origin_currency
   AND l.beneficiary_country_code = h.beneficiary_country_code
   AND l.destiny_currency = h.destiny_currency
WHERE h.customer_id IS NULL
ORDER BY
    l.total_usd_7d DESC;
