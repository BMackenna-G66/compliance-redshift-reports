SELECT
    t.payment_method,
    t.payment_status,
    t.tx_status,
    t.origin_country,
    t.origin_currency,
    t.destiny_country,
    t.destiny_currency,
    t.outbound_bank_name,
    t.inbound_bank_name,
    COUNT(*) AS total_trx,
    COUNT(DISTINCT t.customer_id) AS clientes_unicos,
    SUM(t.destiny_amount_usd) AS total_usd,
    AVG(t.destiny_amount_usd) AS avg_ticket_usd
FROM "db_prod"."transaction"."transaction" AS t
WHERE t.start_date >= DATEADD(day, -30, CURRENT_DATE)
  AND (
        LOWER(t.outbound_bank_name) LIKE '%bridge%'
        OR LOWER(t.inbound_bank_name) LIKE '%bridge%'
        OR LOWER(t.payment_method) LIKE '%bridge%'
      )
GROUP BY
    t.payment_method,
    t.payment_status,
    t.tx_status,
    t.origin_country,
    t.origin_currency,
    t.destiny_country,
    t.destiny_currency,
    t.outbound_bank_name,
    t.inbound_bank_name
ORDER BY
    total_usd DESC;
