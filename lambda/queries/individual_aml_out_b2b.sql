-- Duplicado B2B de individual_aml_out.sql. Misma lógica, misma tabla
-- (transaction.transaction) — la identidad se resuelve contra company.company
-- en vez de customer_v2, porque el customer_id de esta tabla también puede
-- ser un company_id (empresas transan bajo el mismo campo).
WITH target_companies AS (
    SELECT
        co.company_id,
        co.name AS company_name,
        co.identification_number AS company_document_number,
        co.identification_type AS company_document_type
    FROM "db_prod"."company"."company" AS co
    WHERE co.company_id IN ({customer_ids})
),

beneficiary_base AS (
    SELECT
        b.beneficiary_id,
        b.name AS beneficiary_name_master,
        b.last_name AS beneficiary_last_name_master,
        b.dni AS beneficiary_identification,
        b.dni_type AS beneficiary_identification_type,
        b.country_code AS beneficiary_country_code_master,
        b.country_name AS beneficiary_country_name_master
    FROM "db_prod"."beneficiary"."beneficiary" AS b
)

SELECT
    'OUT' AS movement_type,
    t.customer_id,
    NULL::VARCHAR AS customer_email,
    tc.company_name AS customer_name,
    NULL::VARCHAR AS customer_last_name,
    tc.company_document_number AS customer_identification,
    tc.company_document_type AS customer_identification_type,
    t.transaction_id,
    t.payment_id,
    t.start_date,
    t.successfully_completed_date,
    t.tx_status,
    t.payment_status,
    t.payment_method,
    t.remitter_account_type,
    t.origin_country,
    t.origin_currency,
    REPLACE(t.origin_amount, '.', ',') AS origin_amount,
    REPLACE(t.origin_amount_usd, '.', ',') AS origin_amount_usd,
    t.destiny_country,
    t.destiny_currency,
    REPLACE(t.destiny_amount, '.', ',') AS destiny_amount,
    REPLACE(t.destiny_amount_usd, '.', ',') AS destiny_amount_usd,
    t.beneficiary_id,
    COALESCE(bb.beneficiary_name_master, t.beneficiary_name) AS beneficiary_name,
    bb.beneficiary_last_name_master AS beneficiary_last_name,
    bb.beneficiary_identification,
    bb.beneficiary_identification_type,
    COALESCE(bb.beneficiary_country_code_master, t.beneficiary_country_code) AS beneficiary_country_code,
    COALESCE(bb.beneficiary_country_name_master, t.beneficiary_country_name) AS beneficiary_country_name,
    t.beneficiary_email,
    t.beneficiary_phone_number,
    t.beneficiary_type,
    t.beneficiary_account_bank_name,
    t.beneficiary_account_number,
    t.beneficiary_account_type,
    t.outbound_bank_name,
    t.inbound_bank_name,
    'REMESA_TRANSACTION' AS movement_source
FROM "db_prod"."transaction"."transaction" AS t
INNER JOIN target_companies AS tc ON t.customer_id = tc.company_id
LEFT JOIN beneficiary_base AS bb ON t.beneficiary_id = bb.beneficiary_id
ORDER BY tc.company_name, t.start_date DESC
