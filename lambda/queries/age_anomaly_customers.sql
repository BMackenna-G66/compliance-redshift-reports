WITH latest_customer_compliance AS (
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
)

SELECT
    c.customer_id,
    c.email,
    c.name,
    c.last_name,

    c.country_code,
    c.nationality_code,

    c.birth,

    lc.compliance_status,

    sok.step,

    DATEDIFF(year, c.birth, CURRENT_DATE) AS edad,

    CASE
        WHEN DATEDIFF(year, c.birth, CURRENT_DATE) < 18
            THEN 'MENOR_DE_EDAD'

        WHEN DATEDIFF(year, c.birth, CURRENT_DATE) > 90
            THEN 'MAYOR_90'
    END AS tipo_alerta

FROM "db_prod"."customer"."customer_v2" AS c

INNER JOIN latest_customer_compliance AS lc
    ON c.customer_id = lc.customer_id
   AND lc.rn = 1

INNER JOIN latest_customer_kyc AS ck
    ON c.customer_id = ck.customer_id
   AND ck.rn = 1

LEFT JOIN "db_prod"."customer"."step_onboarding_kyc" AS sok
    ON ck.step_onboarding_id = sok.id

WHERE c.birth IS NOT NULL

  AND lc.compliance_status IN (
        'NORMAL',
        'UNDER_COMPLIANCE_REVIEW'
      )

  AND UPPER(sok.step) = 'HOME'

  AND (
        DATEDIFF(year, c.birth, CURRENT_DATE) < 18
        OR DATEDIFF(year, c.birth, CURRENT_DATE) > 90
      )

ORDER BY
    edad ASC,
    c.birth ASC;
