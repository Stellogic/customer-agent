ALTER TABLE support_ticket
    ADD COLUMN resolution_elapsed_seconds bigint NOT NULL DEFAULT 0 CHECK (resolution_elapsed_seconds >= 0),
    ADD COLUMN resolution_running_since timestamptz,
    ADD COLUMN customer_human_preference boolean NOT NULL DEFAULT false;

UPDATE support_ticket
SET resolution_running_since = created_at
WHERE lifecycle_state IN ('NEW', 'INVESTIGATING', 'WAITING_FOR_EXTERNAL');

CREATE TABLE synthetic_order_alias (
    alias text NOT NULL,
    customer_id text NOT NULL,
    answer_code text NOT NULL,
    order_reference text NOT NULL REFERENCES synthetic_order(order_reference),
    PRIMARY KEY (alias, customer_id, answer_code),
    UNIQUE (alias, customer_id, order_reference)
);

INSERT INTO synthetic_order (
    order_reference, customer_id, paid_amount, currency, delay_hours, paid, cancelled,
    fully_refunded, existing_compensation, policy_version, available_compensation_amount, delay_seconds
) VALUES
    ('ORDER-DELAY-AMBIGUOUS-A', 'customer-demo', 268.00, 'CNY', 23, true, false, false, false,
     'delay-policy-v1', 268.00, 82800),
    ('ORDER-DELAY-AMBIGUOUS-B', 'customer-demo', 268.00, 'CNY', 80, true, false, false, false,
     'delay-policy-v1', 268.00, 288000);

INSERT INTO synthetic_order_alias (alias, customer_id, answer_code, order_reference) VALUES
    ('ORDER-DELAY-AMBIGUOUS', 'customer-demo', 'A', 'ORDER-DELAY-AMBIGUOUS-A'),
    ('ORDER-DELAY-AMBIGUOUS', 'customer-demo', 'B', 'ORDER-DELAY-AMBIGUOUS-B');

ALTER TABLE agent_processing_generation
    ADD CONSTRAINT agent_generation_id_ticket_unique UNIQUE (id, ticket_id);

CREATE TABLE customer_clarification_request (
    id uuid PRIMARY KEY,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    generation_id uuid NOT NULL REFERENCES agent_processing_generation(id),
    request_key text NOT NULL,
    reason_code text NOT NULL CHECK (reason_code = 'ORDER_AMBIGUOUS'),
    prompt_code text NOT NULL CHECK (prompt_code = 'ORDER_CONFIRMATION_CODE'),
    public_question text NOT NULL,
    status text NOT NULL CHECK (status IN ('OPEN', 'ANSWERED', 'INVALIDATED')),
    answer_digest char(64),
    answer_summary text,
    resolved_order_reference text REFERENCES synthetic_order(order_reference),
    created_at timestamptz NOT NULL,
    answered_at timestamptz,
    UNIQUE (generation_id, request_key),
    UNIQUE (id, generation_id),
    FOREIGN KEY (generation_id, ticket_id) REFERENCES agent_processing_generation(id, ticket_id)
);

CREATE UNIQUE INDEX one_open_customer_clarification_per_ticket
    ON customer_clarification_request (ticket_id) WHERE status = 'OPEN';

CREATE TABLE agent_resume_request (
    resume_request_id uuid PRIMARY KEY,
    customer_message_id text NOT NULL UNIQUE,
    clarification_request_id uuid NOT NULL UNIQUE REFERENCES customer_clarification_request(id),
    generation_id uuid NOT NULL REFERENCES agent_processing_generation(id),
    thread_id uuid NOT NULL,
    parameter_digest char(64) NOT NULL,
    answer_digest char(64) NOT NULL,
    answer_summary text NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING', 'SUBMITTING', 'SUBMITTED', 'RETRY', 'COMPLETED')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at timestamptz NOT NULL,
    last_error text,
    server_run_id text,
    created_at timestamptz NOT NULL,
    submitted_at timestamptz,
    FOREIGN KEY (generation_id, thread_id) REFERENCES agent_processing_generation(id, thread_id),
    FOREIGN KEY (clarification_request_id, generation_id)
        REFERENCES customer_clarification_request(id, generation_id)
);

CREATE FUNCTION invalidate_clarification_for_generation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'ACTIVE' AND NEW.status <> 'ACTIVE' THEN
        UPDATE customer_clarification_request
        SET status = 'INVALIDATED'
        WHERE generation_id = NEW.id AND status = 'OPEN';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER invalidate_clarification_when_generation_ends
AFTER UPDATE OF status ON agent_processing_generation
FOR EACH ROW EXECUTE FUNCTION invalidate_clarification_for_generation();

CREATE FUNCTION invalidate_clarification_for_human_handling() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.handling_mode = 'HUMAN' OR NEW.customer_human_preference THEN
        UPDATE customer_clarification_request
        SET status = 'INVALIDATED'
        WHERE ticket_id = NEW.id AND status = 'OPEN';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER invalidate_clarification_when_agent_authority_ends
AFTER UPDATE OF handling_mode, customer_human_preference ON support_ticket
FOR EACH ROW EXECUTE FUNCTION invalidate_clarification_for_human_handling();

ALTER TABLE customer_public_event DROP CONSTRAINT customer_public_event_event_type_check;
ALTER TABLE customer_public_event ADD CONSTRAINT customer_public_event_event_type_check
    CHECK (event_type IN (
        'TICKET_ACCEPTED', 'PUBLIC_MESSAGE_APPENDED', 'TICKET_RESOLVED',
        'CUSTOMER_CLARIFICATION_REQUESTED', 'TICKET_INVESTIGATION_RESUMED'
    ));

GRANT SELECT ON synthetic_order_alias TO spring_app;
GRANT SELECT, INSERT, UPDATE ON customer_clarification_request, agent_resume_request TO spring_app;
