-- meta:
--   name: High-Risk Countries Transactions
--   description: Outbound transactions to FATF high-risk / sanctioned jurisdictions
--   schedule: "cron(0 8 ? * MON-FRI *)"
--   params:
--     - name: since_date
--       type: date
--       default: first_day_of_current_month
--       label: "Transactions since (YYYY-MM-DD)"
--     - name: only_successful
--       type: bool
--       default: false
--       label: "Only successful transfers"
--     - name: country_codes
--       type: list
--       source: config/high_risk_countries.yaml
--
-- NOTE on parameter passing:
--   - {country_codes} and {only_successful} are template-substituted in the
--     handler before submission (both come from trusted config / boolean flags,
--     not from external input).
--   - :since_date is a Redshift Data API parameter (parameterized query).
--     This is the right place for any value that might originate from
--     user input later (e.g. from the frontend).

SELECT
    t.transaction_id,
    t.payment_id,
    t.start_date,
    t.successfully_completed_date,
    t.payment_status,
    t.customer_id,
    t.remitter_name,
    t.remitter_country_code,
    t.beneficiary_name,
    t.beneficiary_country_code,
    t.beneficiary_country_name,
    t.beneficiary_city,
    t.beneficiary_state,
    t.beneficiary_address,
    t.beneficiary_email,
    t.beneficiary_phone_number,
    t.beneficiary_type,
    t.outbound_bank_id,
    t.outbound_bank_name,
    t.outbound_bank_type,
    t.beneficiary_account_bank_code,
    t.beneficiary_account_bank_name,
    t.beneficiary_account_number,
    t.beneficiary_account_type,
    t.beneficiary_routing_code_type1,
    t.beneficiary_routing_code_value1,
    t.beneficiary_routing_code_type2,
    t.beneficiary_routing_code_value2,
    t.beneficiary_routing_code_type3,
    t.beneficiary_routing_code_value3,
    UPPER(SUBSTRING(t.beneficiary_routing_code_value1, 5, 2)) AS bank_country_from_swift,
    CASE
        WHEN UPPER(SUBSTRING(t.beneficiary_routing_code_value1, 5, 2)) <> UPPER(t.beneficiary_country_code)
         AND LENGTH(t.beneficiary_routing_code_value1) >= 8
        THEN TRUE
        ELSE FALSE
    END AS swift_country_mismatch_flag,
    t.inbound_bank_id,
    t.inbound_bank_name,
    t.inbound_bank_type,
    t.origin_country,
    t.origin_currency,
    t.origin_amount,
    t.destiny_country,
    t.destiny_currency,
    t.destiny_amount,
    t.destiny_amount_usd
FROM "db_prod"."transaction"."transaction" AS t
WHERE UPPER(t.beneficiary_country_code) IN ({country_codes})
  AND t.successfully_completed_date::date >= :since_date
  AND (
        {only_successful} = FALSE
        OR LOWER(t.payment_status) = 'transferencia exitosa'
      )
ORDER BY t.successfully_completed_date DESC;
