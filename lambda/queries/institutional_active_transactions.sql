SELECT
    -- Empresa / cliente institucional
    co.company_id,
    co.name AS company_name,
    co.identification_number,
    co.identification_type,
    co.compliance_status,
    co.risk_level,

    -- Actividad / industria
    act.name AS economic_activity,
    ind.name AS industry,

    -- Transacción
    t.transaction_id,
    t.payment_reference_number,
    t.start_date,
    t.successfully_completed_date,
    t.tx_status,

    -- Origen
    t.origin_country,
    t.origin_currency,
    CAST(ROUND(t.origin_amount, 2) AS DECIMAL(18,2)) AS origin_amount,

    -- Destino
    t.destiny_country,
    t.destiny_currency,
    CAST(ROUND(t.destiny_amount, 2) AS DECIMAL(18,2)) AS destiny_amount,
    CAST(ROUND(t.destiny_amount_usd, 2) AS DECIMAL(18,2)) AS destiny_amount_usd,

    -- Beneficiario
    t.beneficiary_id,
    t.beneficiary_name,
    t.beneficiary_first_name,
    t.beneficiary_last_name,
    t.beneficiary_dni,
    t.beneficiary_dni_type,
    t.beneficiary_country_code,
    t.beneficiary_country_name,

    -- Cuenta beneficiario
    t.beneficiary_account_number,
    t.beneficiary_account_type,
    t.beneficiary_account_bank_name,
    t.beneficiary_bank_alias,

    -- Ruta bancaria
    t.inbound_bank_name,
    t.outbound_bank_name

FROM "db_prod"."company"."company" AS co

INNER JOIN "db_prod"."transaction"."transaction" AS t
    ON co.company_id = t.customer_id

LEFT JOIN "db_prod"."company"."activity" AS act
    ON co.ind_activity = act.id

LEFT JOIN "db_prod"."company"."industry" AS ind
    ON act.industry_id = ind.id

WHERE co.institutional = 1
  -- Solo clientes activos: se excluyen los bloqueados (definición explícita
  -- del usuario — el resto de los estados sí cuenta como "activo").
  AND UPPER(co.compliance_status) NOT IN ('BLOCKED', 'FULLY_BLOCKED')

ORDER BY
    t.start_date DESC

LIMIT 1000
