ALTER TABLE compensation_reservation
    ADD COLUMN proposal_revision_id uuid REFERENCES compensation_proposal_revision(id);

CREATE UNIQUE INDEX one_reservation_per_proposal_revision
    ON compensation_reservation (proposal_revision_id)
    WHERE proposal_revision_id IS NOT NULL;

CREATE FUNCTION lock_authoritative_order(p_order_reference text)
RETURNS TABLE (
    paid_amount numeric(12, 2),
    available_compensation_amount numeric(12, 2),
    delay_hours integer,
    delay_seconds bigint,
    paid boolean,
    cancelled boolean,
    fully_refunded boolean,
    existing_compensation boolean,
    policy_version text
) LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT o.paid_amount, o.available_compensation_amount, o.delay_hours, o.delay_seconds,
           o.paid, o.cancelled, o.fully_refunded, o.existing_compensation, o.policy_version
    FROM public.synthetic_order o
    WHERE o.order_reference = p_order_reference
    FOR UPDATE
$$;

REVOKE ALL ON FUNCTION lock_authoritative_order(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lock_authoritative_order(text) TO spring_app;

CREATE TABLE compensation_execution (
    id uuid PRIMARY KEY,
    proposal_revision_id uuid NOT NULL UNIQUE REFERENCES compensation_proposal_revision(id),
    decision_id uuid NOT NULL UNIQUE REFERENCES proposal_decision(id),
    reservation_id uuid NOT NULL UNIQUE REFERENCES compensation_reservation(id),
    order_reference text NOT NULL REFERENCES synthetic_order(order_reference),
    reason_code text NOT NULL CHECK (reason_code = 'LOGISTICS_DELAY'),
    compensation_method text NOT NULL CHECK (compensation_method IN ('COUPON', 'SIMULATED_PARTIAL_REFUND')),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    status text NOT NULL CHECK (status IN ('READY', 'PROCESSING', 'UNKNOWN', 'SUCCEEDED', 'FAILED')),
    idempotency_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL,
    UNIQUE (order_reference, reason_code)
);

GRANT SELECT, INSERT ON compensation_execution TO spring_app;
GRANT INSERT ON compensation_reservation TO spring_app;

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-DELAY-APPROVAL', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-APPROVAL-DRIFT', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-APPROVAL-RACE', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-PROPOSAL-RACE', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00);
