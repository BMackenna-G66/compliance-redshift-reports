WITH latest_wallet_balance AS (
    SELECT
        wb.wallet_id,
        wb.balance,
        wb.retrieved_at,
        ROW_NUMBER() OVER (
            PARTITION BY wb.wallet_id
            ORDER BY wb.retrieved_at DESC
        ) AS rn
    FROM "db_prod"."bridge"."wallet_balance" AS wb
),

bridge_base AS (
    SELECT
        bc.customer_id,
        bc.id AS bridge_customer_id,
        bc.created_at AS bridge_customer_created_at,
        bc.kyc_status AS bridge_kyc_status,
        bc.endorsement_reliance_status,
        bc.endorsement_kyc_reliance_data_received_status,
        bc.is_company,

        w.id AS wallet_id,
        w.address AS wallet_address,
        w.created_at AS wallet_created_at,
        lwb.balance AS latest_wallet_balance,
        lwb.retrieved_at AS wallet_balance_retrieved_at,

        la.id AS liquidation_address_id,
        la.address AS liquidation_address,
        la.currency AS liquidation_currency,
        la.payment_rail AS liquidation_payment_rail,
        la.created_at AS liquidation_address_created_at

    FROM "db_prod"."bridge"."customer" AS bc

    LEFT JOIN "db_prod"."bridge"."wallet" AS w
        ON bc.id = w.bridge_customer_id

    LEFT JOIN latest_wallet_balance AS lwb
        ON w.id = lwb.wallet_id
       AND lwb.rn = 1

    LEFT JOIN "db_prod"."bridge"."liquidation_address" AS la
        ON bc.id = la.bridge_customer_id
),

crypto_transactions AS (
    SELECT
        ct.id AS crypto_transaction_id,
        ct.amount AS crypto_amount,
        ct.created_at AS crypto_transaction_created_at,
        ct.currency AS crypto_currency,
        ct.exchange_rate AS crypto_exchange_rate,
        ct.outgoing_amount AS crypto_outgoing_amount,
        ct.status AS crypto_transaction_status,
        ct.liquidation_address_id
    FROM "db_prod"."bridge"."crypto_transaction" AS ct
),

bridge_transfers AS (
    SELECT
        tr.id AS transfer_id,
        tr.amount AS transfer_amount,
        tr.created_at AS transfer_created_at,
        tr.destination_address,
        tr.tx_hash,
        tr.cash_call_id,
        tr.destination_currency,
        tr.destination_payment_rail,
        tr.exchange_rate AS transfer_exchange_rate,
        tr.source_bridge_wallet_id,
        tr.source_currency,
        tr.source_payment_rail,
        tr.status AS transfer_status,
        tr.subtotal_amount
    FROM "db_prod"."bridge"."transfer" AS tr
),

bridge_fiat_transactions AS (
    SELECT
        bt.id AS bridge_transaction_id,
        bt.amount AS bridge_transaction_amount,
        bt.created_at AS bridge_transaction_created_at,
        bt.type AS bridge_transaction_type,
        bt.currency AS bridge_transaction_currency,
        bt.deposit_id,
        bt.sender_bank_routing_number,
        bt.sender_name,
        bt.source_description,
        bt.source_payment_rail,
        bt.trace_number,
        bt.virtual_account_id,
        bt.transfer_id,
        bt.transfer_status AS bridge_transaction_transfer_status,
        bt.fraud_status AS bridge_transaction_fraud_status
    FROM "db_prod"."bridge"."transaction" AS bt
),

virtual_accounts AS (
    SELECT
        va.id AS virtual_account_id,
        va.created_at AS virtual_account_created_at,
        va.deposit_account_holder_name,
        va.deposit_bank_address,
        va.deposit_bank_name,
        va.deposit_currency,
        va.deposit_payment_rails,
        va.destination_currency AS virtual_account_destination_currency,
        va.status AS virtual_account_status,
        va.deposit_account_number,
        va.deposit_routing_code,
        va.wallet_id
    FROM "db_prod"."bridge"."virtual_account" AS va
)

SELECT
    bb.customer_id,
    c.email AS customer_email,
    c.name AS customer_name,
    c.last_name AS customer_last_name,
    c.country_code AS customer_country_code,
    c.nationality_code AS customer_nationality_code,

    bb.bridge_customer_id,
    bb.bridge_customer_created_at,
    bb.bridge_kyc_status,
    bb.endorsement_reliance_status,
    bb.endorsement_kyc_reliance_data_received_status,
    bb.is_company,

    bb.wallet_id,
    bb.wallet_address,
    bb.wallet_created_at,
    bb.latest_wallet_balance,
    bb.wallet_balance_retrieved_at,

    bb.liquidation_address_id,
    bb.liquidation_address,
    bb.liquidation_currency,
    bb.liquidation_payment_rail,
    bb.liquidation_address_created_at,

    ct.crypto_transaction_id,
    ct.crypto_transaction_created_at,
    ct.crypto_transaction_status,
    ct.crypto_currency,
    ct.crypto_amount,
    ct.crypto_exchange_rate,
    ct.crypto_outgoing_amount,

    va.virtual_account_id,
    va.virtual_account_status,
    va.deposit_account_holder_name,
    va.deposit_bank_name,
    va.deposit_bank_address,
    va.deposit_currency,
    va.deposit_payment_rails,
    va.virtual_account_destination_currency,
    va.deposit_account_number,
    va.deposit_routing_code,

    bft.bridge_transaction_id,
    bft.bridge_transaction_created_at,
    bft.bridge_transaction_type,
    bft.bridge_transaction_currency,
    bft.bridge_transaction_amount,
    bft.sender_name,
    bft.sender_bank_routing_number,
    bft.source_description,
    bft.source_payment_rail,
    bft.trace_number,
    bft.bridge_transaction_transfer_status,
    bft.bridge_transaction_fraud_status,

    tr.transfer_id,
    tr.transfer_created_at,
    tr.transfer_status,
    tr.transfer_amount,
    tr.subtotal_amount,
    tr.source_currency,
    tr.source_payment_rail,
    tr.destination_currency,
    tr.destination_payment_rail,
    tr.destination_address,
    tr.source_bridge_wallet_id,
    tr.tx_hash,
    tr.cash_call_id,

    cc.creation_date AS cash_call_creation_date,
    cc.status AS cash_call_status,
    cc.type AS cash_call_type,
    cc.payment_method AS cash_call_payment_method,
    cc.currency_code AS cash_call_currency_code,
    cc.amount AS cash_call_amount,
    cc.origin_amount_usd,
    cc.destiny_amount_usd,
    cc.external_reference_number

FROM bridge_base AS bb

LEFT JOIN "db_prod"."customer"."customer_v2" AS c
    ON bb.customer_id = c.customer_id

LEFT JOIN crypto_transactions AS ct
    ON bb.liquidation_address_id = ct.liquidation_address_id

LEFT JOIN virtual_accounts AS va
    ON bb.wallet_id = va.wallet_id

LEFT JOIN bridge_fiat_transactions AS bft
    ON va.virtual_account_id = bft.virtual_account_id

LEFT JOIN bridge_transfers AS tr
    ON bft.transfer_id = tr.transfer_id

LEFT JOIN "db_prod"."treasury"."cash_call" AS cc
    ON tr.cash_call_id = cc.cash_call_id

WHERE COALESCE(
        ct.crypto_transaction_created_at,
        bft.bridge_transaction_created_at,
        tr.transfer_created_at,
        cc.creation_date
      ) >= DATEADD(day, -30, CURRENT_DATE)

ORDER BY
    bb.customer_id,
    COALESCE(
        ct.crypto_transaction_created_at,
        bft.bridge_transaction_created_at,
        tr.transfer_created_at,
        cc.creation_date
    ) DESC;
