-- QR Payment (pago con código QR a comercios) — product_gateway.transaction,
-- product='QR_PAYMENT'. Siempre es OUT (el cliente paga a un comercio) —
-- confirmado: no existen filas QR_PAYMENT tipo DEPOSIT.
-- Entra al motor de scoring (rows_out) — a diferencia de Cash Call Pay-In,
-- esto SÍ debe contarse como actividad normal del cliente.
--
-- Limitaciones conocidas de la fuente:
--  - amountUSD viene NULL en el 100% de las filas (sin conversión confiable
--    de moneda local a USD disponible) -> origin_amount_usd queda NULL, por
--    lo que los flags basados en monto USD (estructuración, monto alto) NO
--    van a activarse por actividad QR, aunque sí cuenta en volumen de
--    transacciones y en los KPIs generales.
--  - No hay un ID de comercio propio; se usa el texto de "description" como
--    identificador de comercio (para que Fan-Out/Concentración cuenten bien
--    comercios distintos en vez de contar cada transacción como "nuevo
--    beneficiario").
--  - No hay país estructurado; se infiere desde la moneda (best-effort).
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
    'OUT' AS movement_type,
    'QR_PAYMENT' AS movement_source,
    t.customer_id,
    tc.email AS customer_email,
    tc.name AS customer_name,
    tc.last_name AS customer_last_name,
    kd.document_number AS customer_identification,
    kd.document_type AS customer_identification_type,
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
INNER JOIN target_customers tc ON t.customer_id = tc.customer_id
LEFT JOIN latest_kyc_document kd ON t.customer_id = kd.customer_id AND kd.rn = 1
WHERE t.product = 'QR_PAYMENT'
  AND t.status = 'PAID'
  {days_filter}
ORDER BY tc.email, t.paid_date_millis DESC
