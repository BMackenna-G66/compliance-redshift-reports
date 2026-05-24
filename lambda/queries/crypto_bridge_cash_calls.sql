SELECT
    c.status,
    c.payment_method,
    c.currency_code,
    COUNT(*) AS total_cash_calls,
    COUNT(DISTINCT c.customer_id) AS clientes_unicos,
    SUM(c.destiny_amount_usd) AS total_usd,
    AVG(c.destiny_amount_usd) AS avg_ticket_usd
FROM "db_prod"."treasury"."cash_call" AS c
WHERE c.creation_date >= DATEADD(day, -30, CURRENT_DATE)
  AND (
        LOWER(c.payment_method) LIKE '%bridge%'
        OR LOWER(c.currency_code) IN ('usdc', 'usdt', 'btc', 'eth')
      )
GROUP BY
    c.status,
    c.payment_method,
    c.currency_code
ORDER BY
    total_usd DESC;
