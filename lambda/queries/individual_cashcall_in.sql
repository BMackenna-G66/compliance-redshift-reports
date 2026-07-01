-- CCA Cash Call — PAY IN (type = 'CR')
-- Fuente: db_prod.treasury.cash_call. Complementa individual_aml_in.sql (CCA_PAYIN via
-- wallet_deposit) con la otra vía de fondeo — cash calls entrantes.
WITH target_customers AS (
    SELECT
        c.customer_id,
        c.email,
        c.name,
        c.last_name
    FROM "db_prod"."customer"."customer_v2" AS c
    WHERE c.customer_id IN ({customer_ids})
),

latest_kyc_document AS (
    SELECT
        kd.customer_id,
        kd.document_number,
        kd.document_type,
        ROW_NUMBER() OVER (
            PARTITION BY kd.customer_id
            ORDER BY COALESCE(kd.updated_at, kd.created_at) DESC
        ) AS rn
    FROM "db_prod"."customer"."kyc_document" kd
)

SELECT
    'IN' AS movement_type,
    'CCA_CASHCALL_IN' AS movement_source,
    cc.customer_id,
    tc.email AS customer_email,
    tc.name AS customer_name,
    tc.last_name AS customer_last_name,
    kd.document_number AS customer_identification,
    kd.document_type AS customer_identification_type,
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
    bb.bank_name AS beneficiary_account_bank_name,
    NULL::VARCHAR AS beneficiary_account_number,
    NULL::VARCHAR AS beneficiary_account_type,
    NULL::VARCHAR AS outbound_bank_name,
    bb.bank_name AS inbound_bank_name,
    -- Campos propios de cash_call (fondeo): quién envió el dinero hacia Global66
    cc.remitter_name,
    cc.remitter_lastname,
    cc.remitter_dni,
    cc.remitter_email,
    cc.business_bank_id,
    bb.bank_code
FROM "db_prod"."treasury"."cash_call" AS cc
INNER JOIN target_customers tc ON cc.customer_id::VARCHAR = tc.customer_id::VARCHAR
LEFT JOIN latest_kyc_document kd ON cc.customer_id::VARCHAR = kd.customer_id::VARCHAR AND kd.rn = 1
LEFT JOIN "db_prod"."treasury"."business_bank" AS bb ON cc.business_bank_id = bb.business_bank_id
WHERE cc.type = 'CR'
  AND cc.status = 'PAID'
  {days_filter}
ORDER BY tc.email, cc.creation_date DESC
