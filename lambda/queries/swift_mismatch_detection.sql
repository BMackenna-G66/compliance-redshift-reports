SELECT
    t.transaction_id,
    t.customer_id,
    t.customer_email,
    t.remitter_account_type,
    t.start_date,
    t.beneficiary_id,
    t.beneficiary_name,
    t.beneficiary_country_code,
    t.beneficiary_country_name,
    UPPER(SUBSTRING(t.beneficiary_routing_code_value1, 5, 2)) AS bank_country_from_swift,
    t.beneficiary_routing_code_value1,
    t.destiny_amount_usd,
    t.tx_status
FROM "db_prod"."transaction"."transaction" AS t
WHERE t.start_date >= DATEADD(day, -30, CURRENT_DATE)
  AND UPPER(t.tx_status) = 'TRANSFERENCIA_EXITOSA'
  AND t.beneficiary_routing_code_value1 IS NOT NULL
  AND UPPER(SUBSTRING(t.beneficiary_routing_code_value1, 5, 2)) <> UPPER(t.beneficiary_country_code)
ORDER BY
    t.destiny_amount_usd DESC;
