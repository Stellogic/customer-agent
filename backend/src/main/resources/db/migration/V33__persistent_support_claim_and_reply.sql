CREATE TABLE support_public_message_request (
    support_id text NOT NULL,
    message_id text NOT NULL CHECK (char_length(btrim(message_id)) BETWEEN 1 AND 200),
    ticket_id uuid NOT NULL REFERENCES support_ticket(id),
    parameter_digest char(64) NOT NULL,
    public_message_id uuid NOT NULL REFERENCES public_message(id),
    outcome text NOT NULL CHECK (outcome = 'ACCEPTED'),
    received_at timestamptz NOT NULL,
    PRIMARY KEY (support_id, message_id),
    UNIQUE (public_message_id)
);

CREATE OR REPLACE FUNCTION revoke_support_assignment_after_ticket_authority_change()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    revoked_count integer;
    revocation_event text;
BEGIN
    IF (OLD.lifecycle_state IS DISTINCT FROM NEW.lifecycle_state
            OR OLD.handling_mode IS DISTINCT FROM NEW.handling_mode)
       AND (
            NEW.lifecycle_state IN ('RESOLVED', 'CLOSED')
            OR (NEW.handling_mode = 'AGENT' AND OLD.handling_mode IS DISTINCT FROM NEW.handling_mode)
       ) THEN
        UPDATE support_assignment
        SET status = 'REVOKED',
            revoked_at = coalesce(revoked_at, clock_timestamp())
        WHERE ticket_id = NEW.id AND status = 'ACTIVE';
        GET DIAGNOSTICS revoked_count = ROW_COUNT;
        IF revoked_count > 0 THEN
            revocation_event := CASE
                WHEN NEW.lifecycle_state IN ('RESOLVED', 'CLOSED')
                    THEN 'SUPPORT_ASSIGNMENT_REVOKED_TICKET_TERMINAL'
                ELSE 'SUPPORT_ASSIGNMENT_REVOKED_AGENT_HANDOFF'
            END;
            INSERT INTO audit_event (ticket_id, event_type, actor_id, occurred_at)
            VALUES (NEW.id, revocation_event, 'spring-system', clock_timestamp());
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER revoke_support_assignment_after_ticket_authority_change
AFTER UPDATE OF lifecycle_state, handling_mode ON support_ticket
FOR EACH ROW
EXECUTE FUNCTION revoke_support_assignment_after_ticket_authority_change();

WITH revoked AS (
    UPDATE support_assignment assignment
    SET status = 'REVOKED',
        revoked_at = coalesce(assignment.revoked_at, clock_timestamp())
    FROM support_ticket ticket
    WHERE assignment.ticket_id = ticket.id
      AND assignment.status = 'ACTIVE'
      AND (ticket.lifecycle_state IN ('RESOLVED', 'CLOSED') OR ticket.handling_mode = 'AGENT')
    RETURNING assignment.ticket_id
)
INSERT INTO audit_event (ticket_id, event_type, actor_id, occurred_at)
SELECT ticket_id, 'SUPPORT_ASSIGNMENT_REVOKED_DURING_MIGRATION', 'spring-system', clock_timestamp()
FROM revoked;

GRANT SELECT, INSERT ON support_public_message_request TO spring_app;
GRANT SELECT ON support_public_message_request TO spring_fixture;
