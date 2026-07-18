-- Datos ficticios para probar el flujo manual de priorización de alertas
-- de punta a punta (prioridad → documentos → correo → caso) sin tocar
-- clientes reales. La prioridad ya viene asignada a mano en la tabla.
SELECT
    customer_id,
    nombre_completo,
    correo,
    concepto,
    prioridad,
    total_payins_7d,
    total_payin_usd_7d,
    total_payouts_7d,
    total_payout_usd_7d,
    payout_vs_payin_ratio,
    last_payin_date::VARCHAR AS last_payin_date,
    last_payout_date::VARCHAR AS last_payout_date
FROM compliance.alert_priority_test_data
ORDER BY customer_id
