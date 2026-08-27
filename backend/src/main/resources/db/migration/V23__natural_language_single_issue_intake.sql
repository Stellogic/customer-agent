CREATE TABLE customer_intake (
    id uuid PRIMARY KEY,
    customer_id text NOT NULL,
    start_request_key text NOT NULL,
    start_digest text NOT NULL,
    original_message text NOT NULL,
    status text NOT NULL CHECK (status IN ('READY_TO_CONFIRM', 'NEEDS_CLARIFICATION', 'CONFIRMED')),
    candidate_order_reference text,
    candidate_order_version text,
    candidate_order_summary text,
    issue_kind text CHECK (issue_kind IS NULL OR issue_kind = 'LOGISTICS_DELAY'),
    issue_summary text,
    assistant_message text NOT NULL,
    ticket_id uuid UNIQUE REFERENCES support_ticket(id),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    confirmed_at timestamptz,
    UNIQUE (customer_id, start_request_key),
    CHECK ((status = 'CONFIRMED') = (ticket_id IS NOT NULL)),
    CHECK (status <> 'READY_TO_CONFIRM' OR
           (candidate_order_reference IS NOT NULL AND candidate_order_version IS NOT NULL
            AND candidate_order_summary IS NOT NULL AND issue_kind IS NOT NULL AND issue_summary IS NOT NULL))
);

CREATE TABLE customer_intake_message (
    intake_id uuid NOT NULL REFERENCES customer_intake(id),
    request_key text NOT NULL,
    request_digest text NOT NULL,
    customer_message text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (intake_id, request_key)
);

GRANT SELECT, INSERT, UPDATE ON customer_intake, customer_intake_message TO spring_app;
