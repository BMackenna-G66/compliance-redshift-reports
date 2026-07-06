-- Duplicado B2B de individual_qrpayment.sql. Confirmado contra Redshift real
-- que hoy no hay empresas con actividad QR_PAYMENT (es un producto B2C), pero
-- se deja lista por consistencia con el resto de fuentes B2B.
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
    'QR_PAYMENT' AS movement_source,
    t.customer_id,
    NULL::VARCHAR AS customer_email,
    tc.company_name AS customer_name,
    NULL::VARCHAR AS customer_last_name,
    tc.company_document_number AS customer_identification,
    tc.company_document_type AS customer_identification_type,
    t.transaction_id,
    NULL::VARCHAR AS payment_id,
    (TIMESTAMP 'epoch' + (t.paid_date_millis::BIGINT / 1000) * INTERVAL '1 second') AS start_date,
    NULL::TIMESTAMP AS successfully_completed_date,
    t.status AS tx_status,
    NULL::VARCHAR AS payment_status,
    'QR_PAYMENT' AS payment_method,
    NULL::VARCHAR AS remitter_account_type,
    NULL::VARCHAR AS origin_country,
    t.currency AS origin_currency,
    t.amount::DECIMAL(18,2) AS origin_amount,
    NULL::DECIMAL(18,2) AS origin_amount_usd,
    CASE t.currency
        WHEN 'BRL' THEN 'Brasil' WHEN 'CLP' THEN 'Chile' WHEN 'ARS' THEN 'Argentina'
        WHEN 'COP' THEN 'Colombia' WHEN 'PEN' THEN 'Perú' WHEN 'MXN' THEN 'México'
        WHEN 'CRC' THEN 'Costa Rica' WHEN 'PYG' THEN 'Paraguay'
        ELSE NULL
    END AS destiny_country,
    t.currency AS destiny_currency,
    NULL::DECIMAL(18,2) AS destiny_amount,
    NULL::DECIMAL(18,2) AS destiny_amount_usd,
    t.description AS beneficiary_id,
    t.description AS beneficiary_name,
    NULL::VARCHAR AS beneficiary_last_name,
    NULL::VARCHAR AS beneficiary_identification,
    NULL::VARCHAR AS beneficiary_identification_type,
    NULL::VARCHAR AS beneficiary_country_code,
    NULL::VARCHAR AS beneficiary_country_name,
    NULL::VARCHAR AS beneficiary_email,
    NULL::VARCHAR AS beneficiary_phone_number,
    NULL::VARCHAR AS beneficiary_type,
    t.business_bank_name AS beneficiary_account_bank_name,
    NULL::VARCHAR AS beneficiary_account_number,
    NULL::VARCHAR AS beneficiary_account_type,
    t.business_bank_name AS outbound_bank_name,
    NULL::VARCHAR AS inbound_bank_name
FROM "db_prod"."product_gateway"."transaction" AS t
INNER JOIN target_companies tc ON t.customer_id = tc.company_id
WHERE t.product = 'QR_PAYMENT'
  AND t.status = 'PAID'
  {days_filter}
ORDER BY tc.company_name, t.paid_date_millis DESC
