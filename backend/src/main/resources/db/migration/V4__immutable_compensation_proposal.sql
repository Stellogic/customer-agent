ALTER TABLE synthetic_order
    ADD COLUMN available_compensation_amount numeric(12, 2),
    ADD COLUMN delay_seconds bigint;

UPDATE synthetic_order
SET available_compensation_amount = paid_amount,
    delay_seconds = delay_hours * 60 * 60;

ALTER TABLE synthetic_order
    ALTER COLUMN available_compensation_amount SET NOT NULL,
    ALTER COLUMN delay_seconds SET NOT NULL,
    ADD CONSTRAINT synthetic_order_available_compensation_nonnegative
        CHECK (available_compensation_amount >= 0),
    ADD CONSTRAINT synthetic_order_delay_seconds_nonnegative
        CHECK (delay_seconds >= 0);

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-DELAY-CANCELLED', 'customer-demo', 268.00, 'CNY', 80, 288000, true, true, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-UNPAID', 'customer-demo', 268.00, 'CNY', 80, 288000, false, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-REFUNDED', 'customer-demo', 268.00, 'CNY', 80, 288000, true, false, true, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-COMPENSATED', 'customer-demo', 268.00, 'CNY', 80, 288000, true, false, false, true, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-LOW-ALLOWANCE', 'customer-demo', 268.00, 'CNY', 80, 288000, true, false, false, false, 'delay-policy-v1', 5.00),
    ('ORDER-DELAY-RESERVED', 'customer-demo', 268.00, 'CNY', 80, 288000, true, false, false, false, 'delay-policy-v1', 30.00),
    ('ORDER-DELAY-CONCURRENT-RESERVATION', 'customer-demo', 268.00, 'CNY', 80, 288000, true, false, false, false, 'delay-policy-v1', 30.00);

CREATE TABLE compensation_reservation (
    id uuid PRIMARY KEY,
    order_reference text NOT NULL REFERENCES synthetic_order(order_reference),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    status text NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED', 'CONSUMED')),
    created_at timestamptz NOT NULL
);

CREATE FUNCTION enforce_compensation_reservation_capacity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    allowance numeric(12, 2);
    already_reserved numeric(12, 2);
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.order_reference || E'\nCOMPENSATION_ALLOWANCE', 0));
    SELECT available_compensation_amount INTO STRICT allowance
    FROM synthetic_order
    WHERE order_reference = NEW.order_reference;

    IF NEW.status = 'ACTIVE' THEN
        SELECT coalesce(sum(amount), 0) INTO already_reserved
        FROM compensation_reservation
        WHERE order_reference = NEW.order_reference
          AND status = 'ACTIVE'
          AND id <> NEW.id;
        IF already_reserved + NEW.amount > allowance THEN
            RAISE EXCEPTION 'compensation reservation exceeds available allowance'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'compensation_reservation_capacity';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER compensation_reservation_capacity
    BEFORE INSERT OR UPDATE ON compensation_reservation
    FOR EACH ROW EXECUTE FUNCTION enforce_compensation_reservation_capacity();

INSERT INTO compensation_reservation (id, order_reference, amount, status, created_at)
VALUES ('15000000-0000-0000-0000-000000000001', 'ORDER-DELAY-RESERVED', 10.00, 'ACTIVE', '2026-08-09T00:00:00Z');

CREATE TABLE compensation_proposal_revision (
    id uuid PRIMARY KEY,
    proposal_id uuid NOT NULL,
    revision_number integer NOT NULL CHECK (revision_number > 0),
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    order_reference text NOT NULL REFERENCES synthetic_order(order_reference),
    generation_id uuid NOT NULL UNIQUE REFERENCES agent_processing_generation(id),
    delay_hours integer NOT NULL CHECK (delay_hours >= 24),
    delay_seconds bigint NOT NULL CHECK (delay_seconds >= 24 * 60 * 60),
    compensation_method text NOT NULL CHECK (compensation_method IN ('COUPON', 'SIMULATED_PARTIAL_REFUND')),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    reason_code text NOT NULL CHECK (reason_code = 'LOGISTICS_DELAY'),
    evidence_references jsonb NOT NULL,
    policy_version text NOT NULL,
    content_digest char(64) NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING_APPROVAL', 'SUPERSEDED', 'APPROVED', 'COMPLETED', 'REJECTED', 'EXPIRED')),
    created_at timestamptz NOT NULL,
    UNIQUE (proposal_id, revision_number)
);

CREATE UNIQUE INDEX one_active_logistics_compensation_intent
    ON compensation_proposal_revision (order_reference, reason_code)
    WHERE status IN ('PENDING_APPROVAL', 'APPROVED');

CREATE TABLE approval_evidence_snapshot (
    proposal_revision_id uuid PRIMARY KEY REFERENCES compensation_proposal_revision(id),
    order_reference text NOT NULL,
    delay_hours integer NOT NULL,
    delay_seconds bigint NOT NULL,
    paid_amount numeric(12, 2) NOT NULL,
    available_compensation_amount numeric(12, 2) NOT NULL,
    active_reservation_amount numeric(12, 2) NOT NULL,
    paid boolean NOT NULL,
    cancelled boolean NOT NULL,
    fully_refunded boolean NOT NULL,
    existing_compensation boolean NOT NULL,
    evidence_references jsonb NOT NULL,
    captured_at timestamptz NOT NULL
);

CREATE FUNCTION reject_proposal_content_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.proposal_id, NEW.revision_number, NEW.ticket_id, NEW.order_reference,
           NEW.generation_id, NEW.delay_hours, NEW.delay_seconds, NEW.compensation_method, NEW.amount,
           NEW.reason_code, NEW.evidence_references, NEW.policy_version,
           NEW.content_digest, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.proposal_id, OLD.revision_number, OLD.ticket_id, OLD.order_reference,
           OLD.generation_id, OLD.delay_hours, OLD.delay_seconds, OLD.compensation_method, OLD.amount,
           OLD.reason_code, OLD.evidence_references, OLD.policy_version,
           OLD.content_digest, OLD.created_at) THEN
        RAISE EXCEPTION 'compensation proposal revision content is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER compensation_proposal_revision_content_immutable
    BEFORE UPDATE ON compensation_proposal_revision
    FOR EACH ROW EXECUTE FUNCTION reject_proposal_content_mutation();

CREATE FUNCTION reject_approved_proposal_invalidation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'APPROVED' AND NEW.status NOT IN ('APPROVED', 'COMPLETED') THEN
        RAISE EXCEPTION 'approved compensation proposal cannot be invalidated';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER approved_compensation_proposal_not_invalidated
    BEFORE UPDATE ON compensation_proposal_revision
    FOR EACH ROW EXECUTE FUNCTION reject_approved_proposal_invalidation();

CREATE FUNCTION reject_approval_snapshot_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'approval evidence snapshot is immutable';
END;
$$;

CREATE TRIGGER approval_evidence_snapshot_immutable
    BEFORE UPDATE OR DELETE ON approval_evidence_snapshot
    FOR EACH ROW EXECUTE FUNCTION reject_approval_snapshot_mutation();

GRANT SELECT ON compensation_reservation TO spring_app;
GRANT SELECT, INSERT, UPDATE ON compensation_proposal_revision TO spring_app;
GRANT SELECT, INSERT ON approval_evidence_snapshot TO spring_app;

GRANT SELECT ON synthetic_order, compensation_reservation TO spring_fixture;
GRANT UPDATE (delay_hours, delay_seconds) ON synthetic_order TO spring_fixture;
GRANT INSERT ON compensation_reservation TO spring_fixture;
