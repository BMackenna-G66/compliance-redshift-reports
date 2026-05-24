SELECT
    bf.business_flow_key,
    bf.country_code,
    wf.work_flow_key,
    wfe.status,

    COUNT(*) AS total_executions,
    COUNT(DISTINCT a.customer_id) AS unique_customers,

    ROUND(
        COUNT(*)::DECIMAL
        / NULLIF(SUM(COUNT(*)) OVER (
            PARTITION BY bf.business_flow_key, bf.country_code, wf.work_flow_key
        ), 0),
        4
    ) AS status_share

FROM "db_prod"."jumio"."work_flow_execution" AS wfe
LEFT JOIN "db_prod"."jumio"."account" AS a
    ON wfe.account_id = a.id
LEFT JOIN "db_prod"."jumio"."business_flow" AS bf
    ON wfe.business_flow_id = bf.id
LEFT JOIN "db_prod"."jumio"."work_flow" AS wf
    ON wfe.work_flow_id = wf.id

GROUP BY
    bf.business_flow_key,
    bf.country_code,
    wf.work_flow_key,
    wfe.status

ORDER BY
    bf.business_flow_key,
    bf.country_code,
    total_executions DESC;
