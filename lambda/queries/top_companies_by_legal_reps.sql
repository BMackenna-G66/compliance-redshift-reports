WITH active_companies AS (
    SELECT
        co.company_id,
        co.identification_number AS company_document_number,
        co.identification_type AS company_document_type,
        co.name AS company_name,
        co.compliance_status,
        co.risk_level
    FROM "db_prod"."company"."company" AS co
    WHERE co.compliance_status IN (
        'NORMAL',
        'UNDER_COMPLIANCE_REVIEW'
    )
),

legal_reps AS (
    SELECT DISTINCT
        lr.company_id,

        REGEXP_REPLACE(
            lr.identification_number,
            '[^0-9]',
            ''
        ) AS dni_normalizado,

        lr.identification_number,
        lr.identification_type,
        lr.name,
        lr.last_name,
        lr.email,
        lr.nationality,
        lr.status

    FROM "db_prod"."company"."legal_representative" AS lr

    WHERE lr.identification_number IS NOT NULL
      AND REGEXP_REPLACE(
            lr.identification_number,
            '[^0-9]',
            ''
          ) <> ''
      AND REGEXP_REPLACE(
            lr.identification_number,
            '[^0-9]',
            ''
          ) <> '0'
),

company_legal_rep_count AS (
    SELECT
        ac.company_id,
        ac.company_name,
        ac.company_document_number,
        ac.company_document_type,
        ac.compliance_status,
        ac.risk_level,

        COUNT(DISTINCT lr.dni_normalizado)
            AS total_legal_representatives

    FROM active_companies AS ac

    LEFT JOIN legal_reps AS lr
        ON ac.company_id = lr.company_id

    GROUP BY
        ac.company_id,
        ac.company_name,
        ac.company_document_number,
        ac.company_document_type,
        ac.compliance_status,
        ac.risk_level
),

legal_rep_list AS (
    SELECT
        company_id,

        LISTAGG(legal_rep_label, ' | ')
            WITHIN GROUP (
                ORDER BY legal_rep_label
            ) AS legal_representatives

    FROM (
        SELECT DISTINCT
            lr.company_id,

            COALESCE(
                lr.name || ' ' || lr.last_name,
                lr.identification_number
            ) AS legal_rep_label

        FROM legal_reps AS lr
    ) x

    GROUP BY
        company_id
)

SELECT
    clrc.company_id,
    clrc.company_name,
    clrc.company_document_number,
    clrc.company_document_type,
    clrc.compliance_status,
    clrc.risk_level,

    clrc.total_legal_representatives,

    lrl.legal_representatives

FROM company_legal_rep_count AS clrc

LEFT JOIN legal_rep_list AS lrl
    ON clrc.company_id = lrl.company_id

WHERE clrc.total_legal_representatives > 0

ORDER BY
    clrc.total_legal_representatives DESC,
    clrc.company_name

LIMIT 15;
