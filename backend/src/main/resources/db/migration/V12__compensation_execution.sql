ALTER TABLE compensation_execution
    ADD COLUMN assigned_executor_id text NOT NULL DEFAULT 'compensation-executor',
    ADD COLUMN parameter_digest char(64),
    ADD COLUMN processing_attempt_id uuid,
    ADD COLUMN succeeded_at timestamptz;

ALTER TABLE compensation_execution ALTER COLUMN assigned_executor_id DROP DEFAULT;

UPDATE compensation_execution
SET parameter_digest = encode(sha256(
    int4send(octet_length(convert_to(id::text, 'UTF8'))) || convert_to(id::text, 'UTF8') ||
    int4send(octet_length(convert_to(idempotency_key, 'UTF8'))) || convert_to(idempotency_key, 'UTF8') ||
    int4send(octet_length(convert_to(order_reference, 'UTF8'))) || convert_to(order_reference, 'UTF8') ||
    int4send(octet_length(convert_to(reason_code, 'UTF8'))) || convert_to(reason_code, 'UTF8') ||
    int4send(octet_length(convert_to(compensation_method, 'UTF8'))) || convert_to(compensation_method, 'UTF8') ||
    int4send(octet_length(convert_to(amount::text, 'UTF8'))) || convert_to(amount::text, 'UTF8')
), 'hex');

ALTER TABLE compensation_execution ALTER COLUMN parameter_digest SET NOT NULL;

CREATE TABLE compensation_execution_attempt (
    id uuid PRIMARY KEY,
    execution_id uuid NOT NULL REFERENCES compensation_execution(id),
    executor_id text NOT NULL,
    delivery_request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    started_at timestamptz NOT NULL,
    UNIQUE (executor_id, delivery_request_id)
);

CREATE UNIQUE INDEX one_processing_attempt_per_execution
    ON compensation_execution_attempt (execution_id);

ALTER TABLE compensation_execution_attempt
    ADD CONSTRAINT execution_attempt_identity UNIQUE (id, execution_id);

ALTER TABLE compensation_execution
    ADD CONSTRAINT processing_attempt_belongs_to_execution
    FOREIGN KEY (processing_attempt_id, id) REFERENCES compensation_execution_attempt(id, execution_id);

CREATE TABLE compensation_claim_request (
    executor_id text NOT NULL,
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    execution_id uuid NOT NULL REFERENCES compensation_execution(id),
    attempt_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (executor_id, request_id),
    FOREIGN KEY (attempt_id, execution_id)
        REFERENCES compensation_execution_attempt(id, execution_id)
);

CREATE TABLE compensation_execution_result (
    execution_id uuid PRIMARY KEY REFERENCES compensation_execution(id),
    attempt_id uuid NOT NULL UNIQUE REFERENCES compensation_execution_attempt(id),
    result_reference text NOT NULL UNIQUE,
    compensation_method text NOT NULL CHECK (compensation_method IN ('COUPON', 'SIMULATED_PARTIAL_REFUND')),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    masked_destination text,
    customer_message text NOT NULL,
    confirmed_at timestamptz NOT NULL
);

CREATE TABLE compensation_success_request (
    executor_id text NOT NULL,
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    execution_id uuid NOT NULL REFERENCES compensation_execution(id),
    attempt_id uuid NOT NULL REFERENCES compensation_execution_attempt(id),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (executor_id, request_id)
);

CREATE TABLE simulated_coupon (
    execution_id uuid PRIMARY KEY REFERENCES compensation_execution(id),
    coupon_id text NOT NULL UNIQUE,
    amount numeric(12, 2) NOT NULL CHECK (amount IN (10.00, 20.00)),
    issued_at timestamptz NOT NULL
);

CREATE TABLE simulated_partial_refund (
    execution_id uuid PRIMARY KEY REFERENCES compensation_execution(id),
    refund_id text NOT NULL UNIQUE,
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    masked_destination text NOT NULL,
    completed_at timestamptz NOT NULL
);

CREATE FUNCTION reject_compensation_execution_authority_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.proposal_revision_id, NEW.decision_id, NEW.reservation_id, NEW.order_reference,
           NEW.reason_code, NEW.compensation_method, NEW.amount, NEW.idempotency_key,
           NEW.assigned_executor_id, NEW.parameter_digest, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.proposal_revision_id, OLD.decision_id, OLD.reservation_id, OLD.order_reference,
           OLD.reason_code, OLD.compensation_method, OLD.amount, OLD.idempotency_key,
           OLD.assigned_executor_id, OLD.parameter_digest, OLD.created_at) THEN
        RAISE EXCEPTION 'compensation execution authority fields are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER compensation_execution_authority_immutable
BEFORE UPDATE ON compensation_execution
FOR EACH ROW EXECUTE FUNCTION reject_compensation_execution_authority_mutation();

GRANT SELECT ON compensation_execution, compensation_execution_attempt,
    compensation_claim_request, compensation_execution_result, compensation_success_request,
    simulated_coupon, simulated_partial_refund TO spring_app;
GRANT INSERT ON compensation_execution_attempt, compensation_execution_result,
    compensation_claim_request, compensation_success_request, simulated_coupon,
    simulated_partial_refund TO spring_app;
GRANT UPDATE (status, processing_attempt_id, succeeded_at) ON compensation_execution TO spring_app;
GRANT UPDATE (status) ON compensation_reservation TO spring_app;
GRANT UPDATE (existing_compensation) ON synthetic_order TO spring_app;

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-DELAY-EXECUTION-10', 'customer-demo', 268.00, 'CNY', 24, 86400,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-EXECUTION-20', 'customer-demo', 268.00, 'CNY', 48, 172800,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-EXECUTOR-AUTO', 'customer-demo', 268.00, 'CNY', 24, 86400,
     true, false, false, false, 'delay-policy-v1', 268.00);
