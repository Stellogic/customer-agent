ALTER TABLE investigation_fact
    ADD COLUMN source_authority text NOT NULL DEFAULT 'SPRING_AUTHORIZED_CAPABILITY'
        CHECK (length(btrim(source_authority)) > 0),
    ADD COLUMN valid_until timestamptz,
    ADD COLUMN conflict_status text NOT NULL DEFAULT 'CLEAR'
        CHECK (conflict_status IN ('CLEAR', 'CONFLICT'));

UPDATE investigation_fact
SET valid_until = recorded_at + interval '1 hour'
WHERE valid_until IS NULL;

ALTER TABLE investigation_fact
    ALTER COLUMN valid_until SET NOT NULL,
    ADD CONSTRAINT investigation_fact_validity_window
        CHECK (valid_until > recorded_at);

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-EVIDENCE-PATH-A', 'customer-demo', 268.00, 'CNY', 23, 82800,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-EVIDENCE-PATH-B', 'customer-demo', 268.00, 'CNY', 23, 82800,
     true, false, false, false, 'delay-policy-v1', 268.00);
