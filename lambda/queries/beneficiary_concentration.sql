SELECT
    t.customer_id,
    t.customer_email,
    t.remitter_account_type,

    COUNT(*) AS total_trx_7d,
    COUNT(DISTINCT t.beneficiary_id) AS beneficiarios_unicos_7d,

    ROUND(
        COUNT(*)::DECIMAL / NULLIF(COUNT(DISTINCT t.beneficiary_id), 0),
        2
    ) AS trx_por_beneficiario,

    SUM(t.destiny_amount_usd) AS total_usd_7d,
    AVG(t.destiny_amount_usd) AS avg_ticket_usd_7d

FROM "db_prod"."transaction"."transaction" AS t
WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
  AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'
  AND t.beneficiary_id IS NOT NULL

GROUP BY
    t.customer_id,
    t.customer_email,
    t.remitter_account_type

HAVING COUNT(*) >= 5
   AND COUNT(DISTINCT t.beneficiary_id) <= 2

ORDER BY
    trx_por_beneficiario DESC,
    total_usd_7d DESC;
