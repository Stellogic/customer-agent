DROP INDEX one_processing_attempt_per_execution;

ALTER TABLE compensation_execution_attempt
    ADD COLUMN attempt_type text NOT NULL DEFAULT 'EXECUTION'
        CHECK (attempt_type IN ('EXECUTION', 'RECONCILIATION')),
    ADD COLUMN outcome text CHECK (outcome IN ('UNKNOWN', 'FOUND', 'NOT_FOUND')),
    ADD COLUMN completed_at timestamptz;

ALTER TABLE compensation_execution
    ADD COLUMN unknown_at timestamptz,
    ADD COLUMN failed_at timestamptz,
    ADD COLUMN reconciliation_count integer NOT NULL DEFAULT 0 CHECK (reconciliation_count >= 0);

CREATE TABLE compensation_unknown_request (
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

CREATE TABLE compensation_reconciliation_request (
    executor_id text NOT NULL,
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    execution_id uuid NOT NULL REFERENCES compensation_execution(id),
    attempt_id uuid NOT NULL,
    query_id text NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('UNKNOWN', 'FOUND', 'NOT_FOUND')),
    result_reference text,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (executor_id, request_id),
    UNIQUE (executor_id, query_id)
);

CREATE TABLE compensation_failure_request (
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

CREATE TABLE domain_operation_alert (
    id uuid PRIMARY KEY,
    execution_id uuid NOT NULL REFERENCES compensation_execution(id),
    alert_type text NOT NULL CHECK (alert_type = 'COMPENSATION_RECONCILIATION_EXHAUSTED'),
    created_at timestamptz NOT NULL,
    UNIQUE (execution_id, alert_type)
);

CREATE TABLE simulated_compensation_provider_operation (
    execution_id uuid PRIMARY KEY REFERENCES compensation_execution(id),
    idempotency_key text NOT NULL UNIQUE,
    parameter_digest char(64) NOT NULL,
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    scenario text NOT NULL CHECK (scenario IN (
        'SUCCESS', 'BEFORE_EFFECT_FAILURE', 'AFTER_EFFECT_RESPONSE_LOST',
        'RECONCILIATION_NOT_FOUND', 'RECONCILIATION_UNKNOWN')),
    effect_status text NOT NULL CHECK (effect_status IN ('SUCCEEDED', 'NOT_OCCURRED', 'UNCERTAIN')),
    result_reference text UNIQUE,
    query_count integer NOT NULL DEFAULT 0 CHECK (query_count >= 0),
    created_at timestamptz NOT NULL
);

CREATE TABLE simulated_compensation_provider_query (
    query_id text PRIMARY KEY,
    execution_id uuid NOT NULL REFERENCES simulated_compensation_provider_operation(execution_id),
    outcome text NOT NULL CHECK (outcome IN ('FOUND', 'NOT_FOUND', 'UNKNOWN')),
    result_reference text,
    queried_at timestamptz NOT NULL
);

GRANT SELECT, INSERT ON compensation_unknown_request,
    compensation_failure_request, compensation_reconciliation_request, domain_operation_alert,
    simulated_compensation_provider_operation, simulated_compensation_provider_query TO spring_app;
GRANT UPDATE (status, processing_attempt_id, unknown_at, failed_at, reconciliation_count, succeeded_at)
    ON compensation_execution TO spring_app;
GRANT UPDATE (outcome, completed_at) ON compensation_execution_attempt TO spring_app;
GRANT UPDATE (query_count) ON simulated_compensation_provider_operation TO spring_app;


INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, delay_seconds,
    paid, cancelled, fully_refunded, existing_compensation, policy_version,
    available_compensation_amount
) VALUES
    ('ORDER-DELAY-EXECUTION-BEFORE-FAILURE', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-EXECUTION-NOT-FOUND', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00),
    ('ORDER-DELAY-EXECUTION-UNKNOWN', 'customer-demo', 268.00, 'CNY', 80, 288000,
     true, false, false, false, 'delay-policy-v1', 268.00);
