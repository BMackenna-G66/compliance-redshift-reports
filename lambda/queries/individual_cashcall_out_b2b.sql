-- Duplicado B2B de individual_cashcall_out.sql. Misma lógica, misma tabla
-- (treasury.cash_call) — identidad resuelta contra company.company en vez de
-- customer_v2, porque este customer_id también puede ser un company_id.
-- A diferencia de la versión CR (pay-in), esta SÍ entra al motor de scoring.
WITH target_companies AS (
    SELECT
        co.company_id,
        co.name AS company_name,
        co.identification_number AS company_document_number,
        co.identification_type AS company_document_type
    FROM "db_prod"."company"."company" AS co
    WHERE co.company_id IN ({customer_ids})
)

SELECT
    'OUT' AS movement_type,
    'CCA_CASHCALL_OUT' AS movement_source,
    cc.customer_id::BIGINT AS customer_id,
    NULL::VARCHAR AS customer_email,
    tc.company_name AS customer_name,
    NULL::VARCHAR AS customer_last_name,
    tc.company_document_number AS customer_identification,
    tc.company_document_type AS customer_identification_type,
    cc.cash_call_id,
    cc.external_reference_number,
    cc.creation_date AS start_date,
    cc.paid_date,
    cc.status AS tx_status,
    NULL::VARCHAR AS payment_status,
    'CCA_CASHCALL' AS payment_method,
    NULL::VARCHAR AS remitter_account_type,
    cc.currency_code AS origin_currency,
    cc.amount::DECIMAL(18,2) AS origin_amount,
    cc.origin_amount_usd::DECIMAL(18,2) AS origin_amount_usd,
    NULL::VARCHAR AS destiny_country,
    cc.currency_code AS destiny_currency,
    NULL::DECIMAL(18,2) AS destiny_amount,
    cc.destiny_amount_usd::DECIMAL(18,2) AS destiny_amount_usd,
    NULL::VARCHAR AS beneficiary_id,
    NULL::VARCHAR AS beneficiary_name,
    NULL::VARCHAR AS beneficiary_last_name,
    NULL::VARCHAR AS beneficiary_identification,
    NULL::VARCHAR AS beneficiary_identification_type,
    NULL::VARCHAR AS beneficiary_country_code,
    NULL::VARCHAR AS beneficiary_country_name,
    NULL::VARCHAR AS beneficiary_email,
    NULL::VARCHAR AS beneficiary_phone_number,
    NULL::VARCHAR AS beneficiary_type,
    NULL::VARCHAR AS beneficiary_account_bank_name,
    NULL::VARCHAR AS beneficiary_account_number,
    NULL::VARCHAR AS beneficiary_account_type,
    bb.bank_name AS outbound_bank_name,
    NULL::VARCHAR AS inbound_bank_name,
    -- Campos propios de cash_call: quién ordenó el pago
    cc.remitter_name,
    cc.remitter_lastname,
    cc.remitter_dni,
    cc.remitter_email,
    cc.business_bank_id,
    bb.bank_code
FROM "db_prod"."treasury"."cash_call" AS cc
INNER JOIN target_companies tc ON cc.customer_id::VARCHAR = tc.company_id::VARCHAR
LEFT JOIN "db_prod"."treasury"."business_bank" AS bb ON cc.business_bank_id = bb.business_bank_id
WHERE cc.type = 'DR'
  AND cc.status = 'PAID'
  {days_filter}
ORDER BY tc.company_name, cc.creation_date DESC
