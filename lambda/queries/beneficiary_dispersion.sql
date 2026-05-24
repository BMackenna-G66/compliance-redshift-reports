SELECT
    t.customer_id,
    t.customer_email,
    t.remitter_account_type,

    COUNT(*) AS total_trx_7d,
    COUNT(DISTINCT t.beneficiary_id) AS beneficiarios_unicos_7d,

    ROUND(
        COUNT(DISTINCT t.beneficiary_id)::DECIMAL / NULLIF(COUNT(*), 0),
        2
    ) AS ratio_beneficiarios_sobre_trx,

    SUM(t.destiny_amount_usd) AS total_usd_7d,
    AVG(t.destiny_amount_usd) AS avg_ticket_usd_7d

FROM "db_prod"."transaction"."transaction" AS t
WHERE t.start_date >= DATEADD(day, -7, CURRENT_DATE)
  AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'  and t.remitter_account_type = 'Individual'
  AND t.beneficiary_id IS NOT NULL

GROUP BY
    t.customer_id,
    t.customer_email,
    t.remitter_account_type

HAVING COUNT(DISTINCT t.beneficiary_id) >= 5

ORDER BY
    beneficiarios_unicos_7d DESC,
    total_usd_7d DESC;
