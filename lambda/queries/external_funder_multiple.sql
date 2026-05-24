WITH cr AS (
    SELECT
        customer_id,
        remitter_name,
        REGEXP_REPLACE(remitter_dni, '[^0-9]', '') AS remitter_dni,
        origin_amount_usd,
        creation_date
    FROM "db_prod"."treasury"."cash_call"
    WHERE creation_date >= DATEADD(day, -7, CURRENT_DATE)
      AND LOWER(status) = 'paid'
      AND UPPER(type) = 'CR'
      AND remitter_dni IS NOT NULL
),

agg AS (
    SELECT
        remitter_dni,
        MAX(remitter_name) AS remitter_name,
        COUNT(*) AS total_cr,
        COUNT(DISTINCT customer_id) AS clientes_fondeados,
        SUM(origin_amount_usd) AS total_cr_usd,
        AVG(origin_amount_usd) AS avg_cr_usd,
        MIN(creation_date) AS first_cr_date,
        MAX(creation_date) AS last_cr_date
    FROM cr
    WHERE remitter_dni <> ''
      AND remitter_dni <> '0'
    GROUP BY remitter_dni
)

SELECT *
FROM agg
WHERE clientes_fondeados >= 2
ORDER BY
    clientes_fondeados DESC,
    total_cr_usd DESC;
