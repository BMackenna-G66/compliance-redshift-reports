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
    'CCA_PAYIN' AS movement_source,
    ti.customer_id,
    tc.email AS customer_email,
    tc.name AS customer_name,
    tc.last_name AS customer_last_name,
    kd.document_number AS customer_identification,
    kd.document_type AS customer_identification_type,
    w.id AS wallet_deposit_id,
    ti.transaction_id,
    os.id AS operation_status_id,
    os.last_update,
    w.transaction_code,
    w.deposit_date AS start_date,
    os.status_code,
    os.description,
    t.trace_number,
    ROUND(t.amount)::DECIMAL(18,2) AS amount_round,
    t.amount::DECIMAL(18,2) AS amount,
    w.amount_usd::DECIMAL(18,2) AS origin_amount_usd,
    od.receiver_account,
    od.originator_rut AS originator_identification,
    od.originator_name,
    od.receiver_rut AS receiver_identification,
    od.receiver_name,
    NULL::VARCHAR AS payment_id,
    NULL::TIMESTAMP AS successfully_completed_date,
    'PAID'::VARCHAR AS tx_status,
    NULL::VARCHAR AS payment_status,
    'CCA'::VARCHAR AS payment_method,
    NULL::VARCHAR AS remitter_account_type,
    'CL'::VARCHAR AS origin_country,
    'CLP'::VARCHAR AS origin_currency,
    NULL::VARCHAR AS destiny_country,
    'CLP'::VARCHAR AS destiny_currency,
    NULL::DECIMAL(18,2) AS destiny_amount,
    NULL::DECIMAL(18,2) AS destiny_amount_usd,
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
    NULL::VARCHAR AS outbound_bank_name,
    NULL::VARCHAR AS inbound_bank_name
FROM "db_prod"."cca"."wallet_deposit" w
INNER JOIN "db_prod"."cca"."transaction_info" ti ON w.transaction_id = ti.transaction_id
INNER JOIN "db_prod"."cca"."transaction" t ON t.id = w.transaction_id
INNER JOIN target_customers tc ON ti.customer_id = tc.customer_id
LEFT JOIN latest_kyc_document kd ON ti.customer_id = kd.customer_id AND kd.rn = 1
INNER JOIN "db_prod"."cca"."transaction_operation_status" os ON os.transaction_id = t.id
INNER JOIN "db_prod"."cca"."transaction_operation_detail" od ON os.transaction_operation_detail_id = od.id
WHERE ti.transaction_type = 'PAY_IN'
  AND os.status_code = '0210'
  {days_filter}
ORDER BY tc.email, w.deposit_date DESC
