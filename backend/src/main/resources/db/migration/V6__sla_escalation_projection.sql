ALTER TABLE support_ticket ALTER COLUMN first_responded_at DROP NOT NULL;

CREATE FUNCTION enforce_resolution_elapsed_monotonic() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.resolution_elapsed_seconds < OLD.resolution_elapsed_seconds THEN
        RAISE EXCEPTION 'resolution elapsed time cannot decrease'
            USING ERRCODE = '23514', CONSTRAINT = 'resolution_elapsed_seconds_monotonic';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER resolution_elapsed_seconds_monotonic
BEFORE UPDATE OF resolution_elapsed_seconds ON support_ticket
FOR EACH ROW EXECUTE FUNCTION enforce_resolution_elapsed_monotonic();

CREATE TABLE support_assignment (
    id uuid PRIMARY KEY,
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    support_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
    assigned_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK ((status = 'ACTIVE' AND revoked_at IS NULL) OR (status = 'REVOKED' AND revoked_at IS NOT NULL))
);

CREATE UNIQUE INDEX one_active_support_assignment_per_ticket
    ON support_assignment (ticket_id) WHERE status = 'ACTIVE';

CREATE TABLE ticket_sla_fact (
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    objective text NOT NULL CHECK (objective IN ('FIRST_RESPONSE', 'RESOLUTION')),
    fact_type text NOT NULL CHECK (fact_type IN ('WARNING', 'BREACH')),
    elapsed_seconds bigint NOT NULL CHECK (elapsed_seconds >= 0),
    occurred_at timestamptz NOT NULL,
    PRIMARY KEY (ticket_id, objective, fact_type)
);

CREATE TABLE support_sla_notification (
    ticket_id uuid NOT NULL,
    objective text NOT NULL,
    fact_type text NOT NULL CHECK (fact_type = 'WARNING'),
    support_id text NOT NULL,
    notified_at timestamptz NOT NULL,
    PRIMARY KEY (ticket_id, objective, fact_type, support_id),
    FOREIGN KEY (ticket_id, objective, fact_type)
        REFERENCES ticket_sla_fact(ticket_id, objective, fact_type)
);

CREATE TABLE shared_support_queue_entry (
    ticket_id uuid PRIMARY KEY REFERENCES support_ticket(id),
    reason_code text NOT NULL CHECK (reason_code = 'SLA_BREACH'),
    entered_at timestamptz NOT NULL
);

GRANT SELECT, INSERT, UPDATE ON support_assignment TO spring_app;
GRANT SELECT, INSERT ON ticket_sla_fact, support_sla_notification, shared_support_queue_entry TO spring_app;
GRANT SELECT, INSERT, UPDATE ON support_assignment TO spring_fixture;
GRANT SELECT ON ticket_sla_fact, support_sla_notification, shared_support_queue_entry TO spring_fixture;
