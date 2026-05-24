WITH regimen_fiscal_preferencial AS (
    SELECT 'AF' AS country_code UNION ALL SELECT 'AO' UNION ALL SELECT 'AQ' UNION ALL SELECT 'DZ' UNION ALL
    SELECT 'BD' UNION ALL SELECT 'BY' UNION ALL SELECT 'BO' UNION ALL SELECT 'BQ' UNION ALL SELECT 'BI' UNION ALL
    SELECT 'BT' UNION ALL SELECT 'KH' UNION ALL SELECT 'TD' UNION ALL SELECT 'VA' UNION ALL SELECT 'KM' UNION ALL
    SELECT 'CG' UNION ALL SELECT 'KP' UNION ALL SELECT 'CI' UNION ALL SELECT 'CU' UNION ALL SELECT 'EG' UNION ALL
    SELECT 'ER' UNION ALL SELECT 'ET' UNION ALL SELECT 'FJ' UNION ALL SELECT 'GA' UNION ALL SELECT 'GM' UNION ALL
    SELECT 'GP' UNION ALL SELECT 'GU' UNION ALL SELECT 'GF' UNION ALL SELECT 'GN' UNION ALL SELECT 'GW' UNION ALL
    SELECT 'GQ' UNION ALL SELECT 'GY' UNION ALL SELECT 'HT' UNION ALL SELECT 'HN' UNION ALL SELECT 'IR' UNION ALL
    SELECT 'IQ' UNION ALL SELECT 'LY' UNION ALL SELECT 'ML' UNION ALL SELECT 'MZ' UNION ALL SELECT 'MM' UNION ALL
    SELECT 'NI' UNION ALL SELECT 'PS' UNION ALL SELECT 'CF' UNION ALL SELECT 'CD' UNION ALL SELECT 'SY' UNION ALL
    SELECT 'SO' UNION ALL SELECT 'SD' UNION ALL SELECT 'SS' UNION ALL SELECT 'SR' UNION ALL SELECT 'TW' UNION ALL
    SELECT 'TZ' UNION ALL SELECT 'VE' UNION ALL SELECT 'YE' UNION ALL SELECT 'ZM' UNION ALL SELECT 'ZW'
)

SELECT
    c.cash_call_id,
    c.customer_id,
    c.external_reference_number,
    c.creation_date,
    c.status,
    c.payment_method,
    c.currency_code,
    c.amount,
    c.destiny_amount_usd,
    c.origin_amount_usd,
    c.remitter_name,
    c.remitter_country_code,
    c.persona_name,
    c.persona_country_code,
    'REGIMEN_FISCAL_PREFERENCIAL' AS etiqueta_riesgo,
    c.*
FROM "db_prod"."treasury"."cash_call" AS c
INNER JOIN regimen_fiscal_preferencial AS rfp
    ON UPPER(c.remitter_country_code) = rfp.country_code
WHERE c.creation_date >= DATEADD(day, -7, CURRENT_DATE)
  AND LOWER(c.status) = 'paid'
ORDER BY
    c.destiny_amount_usd DESC,
    c.creation_date DESC;
