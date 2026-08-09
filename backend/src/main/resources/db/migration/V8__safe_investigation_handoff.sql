ALTER TABLE support_ticket DROP CONSTRAINT support_ticket_handoff_reason_check;
ALTER TABLE support_ticket ADD CONSTRAINT support_ticket_handoff_reason_check
    CHECK (human_handoff_reason_code IS NULL OR human_handoff_reason_code IN (
        'CUSTOMER_REQUESTED', 'TOOL_RETRY_EXHAUSTED', 'FACT_CONFLICT',
        'INVALID_TOOL_RESPONSE', 'REQUIRED_FACT_MISSING', 'UNSUPPORTED_SCENARIO'
    ));

CREATE TABLE agent_safety_handoff_request (
    generation_id uuid NOT NULL REFERENCES agent_processing_generation(id),
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    reason_code text NOT NULL CHECK (reason_code IN (
        'TOOL_RETRY_EXHAUSTED', 'FACT_CONFLICT', 'INVALID_TOOL_RESPONSE',
        'REQUIRED_FACT_MISSING', 'UNSUPPORTED_SCENARIO'
    )),
    investigation_summary jsonb NOT NULL,
    completed_at timestamptz NOT NULL,
    PRIMARY KEY (generation_id, request_id)
);

ALTER TABLE shared_support_queue_entry DROP CONSTRAINT shared_support_queue_entry_reason_code_check;
ALTER TABLE shared_support_queue_entry ADD CONSTRAINT shared_support_queue_entry_reason_code_check
    CHECK (reason_code IN ('SLA_BREACH', 'CUSTOMER_REQUESTED_HANDOFF', 'SAFE_INVESTIGATION_HANDOFF'));

GRANT SELECT, INSERT ON agent_safety_handoff_request TO spring_app;
