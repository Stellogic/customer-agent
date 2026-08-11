INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-DELAY-E2E-NORMAL', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-E2E-RECONCILIATION', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00);
