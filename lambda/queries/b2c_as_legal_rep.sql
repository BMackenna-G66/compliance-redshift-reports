WITH latest_kyc_document AS (
    SELECT
        kd.customer_id,
        kd.document_number,
        kd.document_type,
        kd.country_code,
        kd.approval_status,
        kd.created_at,
        kd.updated_at,
        REGEXP_REPLACE(kd.document_number, '[^0-9]', '') AS dni_normalizado,
        ROW_NUMBER() OVER (
            PARTITION BY kd.customer_id
            ORDER BY COALESCE(kd.updated_at, kd.created_at) DESC
        ) AS rn
    FROM "db_prod"."customer"."kyc_document" AS kd
    WHERE kd.document_number IS NOT NULL
      AND REGEXP_REPLACE(kd.document_number, '[^0-9]', '') <> ''
      AND REGEXP_REPLACE(kd.document_number, '[^0-9]', '') <> '0'
),

latest_customer_kyc AS (
    SELECT
        ck.customer_id,
        ck.step_onboarding_id,
        ck.created_at,
        ROW_NUMBER() OVER (
            PARTITION BY ck.customer_id
            ORDER BY ck.created_at DESC
        ) AS rn
    FROM "db_prod"."customer"."customer_kyc" AS ck
),

latest_customer_compliance AS (
    SELECT
        c.customer_id,
        c.compliance_status,
        c.status_created_at,
        ROW_NUMBER() OVER (
            PARTITION BY c.customer_id
            ORDER BY c.status_created_at DESC
        ) AS rn
    FROM "db_prod"."customer"."compliance" AS c
),

b2c_customers AS (
    SELECT
        c.customer_id,
        c.email,
        c.name,
        c.last_name,
        kd.document_number AS b2c_document_number,
        kd.document_type AS b2c_document_type,
        kd.country_code AS b2c_document_country,
        kd.approval_status AS b2c_document_status,
        kd.dni_normalizado,
        sok.step,
        lc.compliance_status AS b2c_compliance_status
    FROM "db_prod"."customer"."customer_v2" AS c
    INNER JOIN latest_kyc_document AS kd
        ON c.customer_id = kd.customer_id
       AND kd.rn = 1
    LEFT JOIN latest_customer_kyc AS ck
        ON c.customer_id = ck.customer_id
       AND ck.rn = 1
    LEFT JOIN "db_prod"."customer"."step_onboarding_kyc" AS sok
        ON ck.step_onboarding_id = sok.id
    LEFT JOIN latest_customer_compliance AS lc
        ON c.customer_id = lc.customer_id
       AND lc.rn = 1
    WHERE sok.step = 'HOME'
      AND lc.compliance_status IN ('NORMAL', 'UNDER_COMPLIANCE_REVIEW')
),

legal_reps AS (
    SELECT DISTINCT
        lr.company_id,
        lr.identification_number AS legal_rep_document_number,
        lr.identification_type AS legal_rep_document_type,
        lr.name AS legal_rep_name,
        lr.last_name AS legal_rep_last_name,
        lr.email AS legal_rep_email,
        lr.nationality AS legal_rep_nationality,
        lr.status AS legal_rep_status,
        REGEXP_REPLACE(lr.identification_number, '[^0-9]', '') AS dni_normalizado
    FROM "db_prod"."company"."legal_representative" AS lr
    WHERE lr.identification_number IS NOT NULL
      AND REGEXP_REPLACE(lr.identification_number, '[^0-9]', '') <> ''
      AND REGEXP_REPLACE(lr.identification_number, '[^0-9]', '') <> '0'
),

companies AS (
    SELECT
        co.company_id,
        co.identification_number AS company_identification_number,
        co.identification_type AS company_identification_type,
        co.name AS company_name,
        co.compliance_status,
        co.risk_level
    FROM "db_prod"."company"."company" AS co
    WHERE co.compliance_status IN ('NORMAL', 'UNDER_COMPLIANCE_REVIEW')
),

b2c_legal_rep_base AS (
    SELECT
        bc.customer_id,
        bc.email AS b2c_email,
        bc.name AS b2c_name,
        bc.last_name AS b2c_last_name,
        bc.b2c_document_number,
        bc.b2c_document_type,
        bc.b2c_document_country,
        bc.b2c_document_status,
        bc.b2c_compliance_status,
        bc.step AS b2c_step,

        lr.company_id,
        lr.legal_rep_document_number,
        lr.legal_rep_document_type,
        lr.legal_rep_name,
        lr.legal_rep_last_name,
        lr.legal_rep_email,
        lr.legal_rep_nationality,
        lr.legal_rep_status,

        co.company_identification_number,
        co.company_identification_type,
        co.company_name,
        co.compliance_status AS company_compliance_status,
        co.risk_level AS company_risk_level

    FROM b2c_customers AS bc
    INNER JOIN legal_reps AS lr
        ON bc.dni_normalizado = lr.dni_normalizado
    INNER JOIN companies AS co
        ON lr.company_id = co.company_id
),

company_count AS (
    SELECT
        customer_id,
        COUNT(DISTINCT company_id) AS total_companies_as_legal_rep
    FROM b2c_legal_rep_base
    GROUP BY customer_id
),

company_list AS (
    SELECT
        customer_id,
        LISTAGG(company_label, ' | ')
            WITHIN GROUP (ORDER BY company_label) AS companies_where_is_legal_rep
    FROM (
        SELECT DISTINCT
            customer_id,
            COALESCE(company_name, company_id::VARCHAR) AS company_label
        FROM b2c_legal_rep_base
    ) x
    GROUP BY customer_id
)

SELECT
    b.customer_id,
    MAX(b.b2c_email) AS b2c_email,
    MAX(b.b2c_name) AS b2c_name,
    MAX(b.b2c_last_name) AS b2c_last_name,
    MAX(b.b2c_document_number) AS b2c_document_number,
    MAX(b.b2c_document_type) AS b2c_document_type,
    MAX(b.b2c_document_country) AS b2c_document_country,
    MAX(b.b2c_document_status) AS b2c_document_status,
    MAX(b.b2c_compliance_status) AS b2c_compliance_status,
    MAX(b.b2c_step) AS b2c_step,

    cc.total_companies_as_legal_rep,
    cl.companies_where_is_legal_rep

FROM b2c_legal_rep_base AS b
LEFT JOIN company_count AS cc
    ON b.customer_id = cc.customer_id
LEFT JOIN company_list AS cl
    ON b.customer_id = cl.customer_id

GROUP BY
    b.customer_id,
    cc.total_companies_as_legal_rep,
    cl.companies_where_is_legal_rep

ORDER BY
    cc.total_companies_as_legal_rep DESC;
