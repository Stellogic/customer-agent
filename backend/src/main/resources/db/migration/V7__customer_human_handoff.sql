ALTER TABLE support_ticket
    ADD COLUMN human_handoff_reason_code text,
    ADD CONSTRAINT support_ticket_handoff_reason_check
        CHECK (human_handoff_reason_code IS NULL OR human_handoff_reason_code = 'CUSTOMER_REQUESTED');

CREATE TABLE customer_human_handoff_request (
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    reason_code text NOT NULL CHECK (reason_code = 'CUSTOMER_REQUESTED'),
    investigation_summary jsonb NOT NULL,
    completed_at timestamptz NOT NULL,
    PRIMARY KEY (ticket_id, request_id)
);

ALTER TABLE shared_support_queue_entry
    DROP CONSTRAINT shared_support_queue_entry_pkey,
    DROP CONSTRAINT shared_support_queue_entry_reason_code_check;

ALTER TABLE shared_support_queue_entry
    ADD CONSTRAINT shared_support_queue_entry_reason_code_check
        CHECK (reason_code IN ('SLA_BREACH', 'CUSTOMER_REQUESTED_HANDOFF')),
    ADD PRIMARY KEY (ticket_id, reason_code);

ALTER TABLE customer_public_event DROP CONSTRAINT customer_public_event_event_type_check;
ALTER TABLE customer_public_event ADD CONSTRAINT customer_public_event_event_type_check
    CHECK (event_type IN (
        'TICKET_ACCEPTED', 'PUBLIC_MESSAGE_APPENDED', 'TICKET_RESOLVED',
        'CUSTOMER_CLARIFICATION_REQUESTED', 'TICKET_INVESTIGATION_RESUMED',
        'TICKET_HANDED_OFF'
    ));

GRANT SELECT, INSERT ON customer_human_handoff_request TO spring_app;
