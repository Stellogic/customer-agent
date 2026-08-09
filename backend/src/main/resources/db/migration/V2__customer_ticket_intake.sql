CREATE TABLE support_ticket (
    id uuid PRIMARY KEY,
    customer_id text NOT NULL,
    order_reference text NOT NULL,
    description text NOT NULL,
    lifecycle_state text NOT NULL CHECK (lifecycle_state IN ('NEW', 'INVESTIGATING', 'WAITING_FOR_CUSTOMER', 'WAITING_FOR_EXTERNAL', 'RESOLVED', 'CLOSED')),
    handling_mode text NOT NULL CHECK (handling_mode IN ('AGENT', 'HUMAN')),
    created_at timestamptz NOT NULL,
    first_responded_at timestamptz NOT NULL CHECK (first_responded_at >= created_at)
);

CREATE TABLE customer_ticket_request (
    customer_id text NOT NULL,
    request_id text NOT NULL,
    parameter_digest char(64) NOT NULL,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    PRIMARY KEY (customer_id, request_id)
);

CREATE TABLE public_message (
    id uuid PRIMARY KEY,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    message_sequence bigint NOT NULL CHECK (message_sequence > 0),
    author text NOT NULL CHECK (author IN ('CUSTOMER', 'SUPPORT')),
    body text NOT NULL,
    sent_at timestamptz NOT NULL,
    UNIQUE (ticket_id, message_sequence)
);

CREATE TABLE audit_event (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    event_type text NOT NULL,
    actor_id text NOT NULL,
    occurred_at timestamptz NOT NULL
);

CREATE TABLE customer_public_event (
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    epoch text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    event_type text NOT NULL CHECK (event_type IN ('TICKET_ACCEPTED', 'PUBLIC_MESSAGE_APPENDED')),
    payload jsonb NOT NULL,
    occurred_at timestamptz NOT NULL,
    PRIMARY KEY (ticket_id, epoch, sequence)
);

CREATE INDEX public_message_ticket_order ON public_message (ticket_id, message_sequence);

GRANT SELECT, INSERT, UPDATE ON support_ticket, customer_ticket_request, public_message, audit_event, customer_public_event TO spring_app;
GRANT USAGE, SELECT ON SEQUENCE audit_event_id_seq TO spring_app;
