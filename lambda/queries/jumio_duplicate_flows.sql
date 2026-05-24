WITH latest_kyc_document AS (
    SELECT
        kd.customer_id,
        kd.document_number,
        kd.document_type,
        kd.country_code,
        REGEXP_REPLACE(kd.document_number, '[^0-9]', '') AS dni_normalizado,
        kd.created_at,
        kd.updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY kd.customer_id
            ORDER BY COALESCE(kd.updated_at, kd.created_at) DESC
        ) AS rn
    FROM "db_prod"."customer"."kyc_document" AS kd
    WHERE kd.document_number IS NOT NULL
      AND REGEXP_REPLACE(kd.document_number, '[^0-9]', '') NOT IN ('', '0')
),

jumio_base AS (
    SELECT
        kd.dni_normalizado,
        kd.document_number,
        kd.document_type,
        kd.country_code,
        a.customer_id,
        a.user_type,
        a.jumio_account_id,
        wfe.work_flow_execution_id,
        wfe.status,
        wfe.created_at AS jumio_created_at,
        bf.business_flow_key,
        bf.country_code AS flow_country_code
    FROM latest_kyc_document kd
    INNER JOIN "db_prod"."jumio"."account" AS a
        ON kd.customer_id = a.customer_id
    LEFT JOIN "db_prod"."jumio"."work_flow_execution" AS wfe
        ON a.id = wfe.account_id
    LEFT JOIN "db_prod"."jumio"."business_flow" AS bf
        ON wfe.business_flow_id = bf.id
    WHERE kd.rn = 1
),

metrics AS (
    SELECT
        dni_normalizado,
        MAX(document_number) AS document_number_example,
        MAX(document_type) AS document_type,
        MAX(country_code) AS document_country_code,

        COUNT(DISTINCT customer_id) AS total_customers,
        COUNT(DISTINCT jumio_account_id) AS total_jumio_accounts,
        COUNT(DISTINCT work_flow_execution_id) AS total_jumio_executions,
        COUNT(DISTINCT business_flow_key) AS total_business_flows,
        COUNT(DISTINCT user_type) AS total_user_types,

        MAX(jumio_created_at) AS last_jumio_execution_at

    FROM jumio_base
    GROUP BY dni_normalizado
    HAVING COUNT(DISTINCT customer_id) > 1
        OR COUNT(DISTINCT business_flow_key) > 1
        OR COUNT(DISTINCT user_type) > 1
)

SELECT *
FROM metrics
ORDER BY
    total_customers DESC,
    total_business_flows DESC,
    total_jumio_executions DESC;
