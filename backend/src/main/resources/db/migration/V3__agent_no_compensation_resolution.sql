CREATE TABLE synthetic_order (
    order_reference text PRIMARY KEY,
    customer_id text NOT NULL,
    paid_amount numeric(12, 2) NOT NULL CHECK (paid_amount >= 0),
    currency char(3) NOT NULL,
    delay_hours integer NOT NULL CHECK (delay_hours >= 0),
    paid boolean NOT NULL,
    cancelled boolean NOT NULL,
    fully_refunded boolean NOT NULL,
    existing_compensation boolean NOT NULL,
    policy_version text NOT NULL
);

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours,
    paid, cancelled, fully_refunded, existing_compensation, policy_version
) VALUES
    ('ORDER-DELAY-001', 'customer-demo', 268.00, 'CNY', 80, true, false, false, false, 'delay-policy-v1'),
    ('ORDER-DELAY-UNDER-24', 'customer-demo', 268.00, 'CNY', 23, true, false, false, false, 'delay-policy-v1');

CREATE TABLE synthetic_pending_action (
    id uuid PRIMARY KEY,
    order_reference text NOT NULL REFERENCES synthetic_order(order_reference),
    action_type text NOT NULL,
    action_state text NOT NULL CHECK (action_state IN ('READY', 'PROCESSING', 'UNKNOWN'))
);

CREATE TABLE agent_processing_generation (
    id uuid PRIMARY KEY,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    generation_number integer NOT NULL CHECK (generation_number > 0),
    thread_id uuid NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('ACTIVE', 'COMPLETED', 'SUPERSEDED', 'HANDED_OFF')),
    created_at timestamptz NOT NULL,
    completed_at timestamptz,
    UNIQUE (ticket_id, generation_number)
);

CREATE UNIQUE INDEX one_active_agent_generation_per_ticket
    ON agent_processing_generation (ticket_id) WHERE status = 'ACTIVE';

ALTER TABLE agent_processing_generation
    ADD CONSTRAINT agent_processing_generation_id_thread_unique UNIQUE (id, thread_id);

CREATE TABLE agent_submission (
    submission_request_id uuid PRIMARY KEY,
    generation_id uuid NOT NULL UNIQUE REFERENCES agent_processing_generation(id),
    thread_id uuid NOT NULL,
    parameter_digest char(64) NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING', 'SUBMITTING', 'SUBMITTED', 'RETRY', 'COMPLETED')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at timestamptz NOT NULL,
    last_error text,
    created_at timestamptz NOT NULL,
    submitted_at timestamptz,
    FOREIGN KEY (generation_id, thread_id) REFERENCES agent_processing_generation(id, thread_id)
);

CREATE TABLE investigation_fact (
    generation_id uuid NOT NULL REFERENCES agent_processing_generation(id),
    fact_type text NOT NULL,
    fact_value text NOT NULL,
    evidence_reference text NOT NULL,
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (generation_id, fact_type)
);

CREATE TABLE agent_command_request (
    generation_id uuid NOT NULL REFERENCES agent_processing_generation(id),
    request_id text NOT NULL,
    operation text NOT NULL,
    parameter_digest char(64) NOT NULL,
    response_payload jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (generation_id, request_id)
);

ALTER TABLE customer_public_event DROP CONSTRAINT customer_public_event_event_type_check;
ALTER TABLE customer_public_event ADD CONSTRAINT customer_public_event_event_type_check
    CHECK (event_type IN ('TICKET_ACCEPTED', 'PUBLIC_MESSAGE_APPENDED', 'TICKET_RESOLVED'));

ALTER TABLE public_message DROP CONSTRAINT public_message_author_check;
ALTER TABLE public_message ADD CONSTRAINT public_message_author_check
    CHECK (author IN ('CUSTOMER', 'SUPPORT', 'AGENT'));

GRANT SELECT ON synthetic_order, synthetic_pending_action TO spring_app;
GRANT SELECT, INSERT, UPDATE ON agent_processing_generation, agent_submission,
    investigation_fact, agent_command_request TO spring_app;
