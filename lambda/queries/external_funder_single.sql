WITH cr AS (
    SELECT
        customer_id,
        remitter_name,
        REGEXP_REPLACE(remitter_dni, '[^0-9]', '') AS remitter_dni,
        COUNT(*) AS total_cr,
        SUM(origin_amount_usd) AS total_cr_usd,
        AVG(origin_amount_usd) AS avg_cr_usd,
        MIN(creation_date) AS first_cr_date,
        MAX(creation_date) AS last_cr_date
    FROM "db_prod"."treasury"."cash_call"
    WHERE creation_date >= DATEADD(day, -7, CURRENT_DATE)
      AND LOWER(status) = 'paid'
      AND UPPER(type) = 'CR'
      AND remitter_dni IS NOT NULL
    GROUP BY
        customer_id,
        remitter_name,
        REGEXP_REPLACE(remitter_dni, '[^0-9]', '')
)

SELECT *
FROM cr
WHERE remitter_dni <> ''
  AND remitter_dni <> '0'
  AND total_cr >= 3
ORDER BY
    total_cr DESC,
    total_cr_usd DESC;
