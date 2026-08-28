ALTER TABLE shared_intake_record DROP CONSTRAINT shared_intake_record_intake_id_key;

CREATE TABLE customer_intake_pending_order (
    intake_id uuid NOT NULL REFERENCES customer_intake(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    order_reference text NOT NULL,
    order_version text NOT NULL,
    order_summary text NOT NULL,
    PRIMARY KEY (intake_id, ordinal),
    UNIQUE (intake_id, order_reference)
);

CREATE TABLE customer_intake_duplicate_match (
    intake_id uuid NOT NULL REFERENCES customer_intake(id) ON DELETE CASCADE,
    issue_kind text NOT NULL CHECK (issue_kind IN (
        'LOGISTICS_DELAY', 'PACKAGE_NOT_RECEIVED', 'DUPLICATE_CHARGE'
    )),
    existing_ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    issue_summary text NOT NULL CHECK (length(trim(issue_summary)) > 0),
    lifecycle_state text NOT NULL CHECK (lifecycle_state IN (
        'NEW', 'INVESTIGATING', 'WAITING_FOR_CUSTOMER', 'WAITING_FOR_EXTERNAL', 'RESOLVED'
    )),
    resolution text CHECK (resolution IS NULL OR resolution IN ('CONTINUE_EXISTING', 'CREATE_NEW')),
    resolved_at timestamptz,
    PRIMARY KEY (intake_id, issue_kind, existing_ticket_id),
    CHECK ((resolution IS NULL) = (resolved_at IS NULL))
);

CREATE TABLE customer_intake_routed_ticket (
    intake_id uuid NOT NULL REFERENCES customer_intake(id) ON DELETE CASCADE,
    order_reference text NOT NULL,
    issue_kind text NOT NULL,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    routed_at timestamptz NOT NULL,
    PRIMARY KEY (intake_id, order_reference, issue_kind),
    UNIQUE (intake_id, ticket_id)
);

CREATE TABLE customer_intake_duplicate_resolution_request (
    intake_id uuid NOT NULL REFERENCES customer_intake(id) ON DELETE CASCADE,
    request_key text NOT NULL,
    request_digest char(64) NOT NULL,
    existing_ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    action text NOT NULL CHECK (action IN ('CONTINUE_EXISTING', 'CREATE_NEW')),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (intake_id, request_key)
);

CREATE INDEX customer_intake_open_duplicate_lookup
    ON support_ticket (customer_id, order_reference, issue_kind, lifecycle_state)
    WHERE lifecycle_state <> 'CLOSED';

GRANT SELECT, INSERT, UPDATE, DELETE ON customer_intake_pending_order,
    customer_intake_duplicate_match TO spring_app;
GRANT SELECT, INSERT ON customer_intake_routed_ticket,
    customer_intake_duplicate_resolution_request TO spring_app;
