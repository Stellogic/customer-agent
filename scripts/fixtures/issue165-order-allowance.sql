\set ON_ERROR_STOP on
INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-ALLOW165-RACE', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 30.00),
    ('ORDER-ALLOW165-FAILURE', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 30.00),
    ('ORDER-ALLOW165-COMBINATION', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 60.00),
    ('ORDER-ALLOW165-STORAGE', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 30.00),
    ('ORDER-ALLOW165-EXPIRY', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 30.00),
    ('ORDER-ALLOW165-AUTO', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 30.00);
