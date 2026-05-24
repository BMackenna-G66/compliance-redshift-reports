SELECT
    c.status,
    c.payment_method,
    c.currency_code,
    *
FROM "db_prod"."treasury"."cash_call" AS c
left join "db_prod"."transaction"."transaction" as t on t.transaction_id = c.external_reference_number
WHERE c.creation_date >= DATEADD(day, -30, CURRENT_DATE)
  AND (
        LOWER(c.payment_method) LIKE '%bridge%'
        OR LOWER(c.currency_code) IN ('usdc', 'usdt', 'btc', 'eth')

      )

  AND UPPER(t.beneficiary_country_code) IN (
      'AF','AO','DZ','BY','BA','BG','BF','BI','CM','CG','KP','CI','HR','CU',
      'SI','ET','PH','GW','HT','IQ','IR','KZ','KE','LB','LR','LY','MK','ML',
      'MC','ME','MZ','MM','NA','NI','NG','PK','PS','CF','RU','EH','RS','SY',
      'SO','ZA','SD','SS','TZ','UA','VN','YE','ZW'
  )

ORDER BY
    c.destiny_amount_usd DESC,
    c.creation_date DESC;
