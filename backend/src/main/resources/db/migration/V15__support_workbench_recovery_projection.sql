CREATE TABLE support_workbench_event (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    epoch text NOT NULL CHECK (epoch = 'support-workbench-v1'),
    event_type text NOT NULL CHECK (event_type IN ('QUEUE_TICKET_UPSERTED', 'QUEUE_TICKET_REMOVED')),
    payload jsonb NOT NULL,
    occurred_at timestamptz NOT NULL
);

CREATE FUNCTION validate_support_workbench_event_payload() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF jsonb_typeof(NEW.payload) <> 'object'
       OR NOT (NEW.payload ? 'ticketId')
       OR jsonb_typeof(NEW.payload->'ticketId') <> 'string' THEN
        RAISE EXCEPTION 'support workbench payload must identify one ticket';
    END IF;
    IF NEW.event_type = 'QUEUE_TICKET_REMOVED' AND EXISTS (
        SELECT 1 FROM jsonb_object_keys(NEW.payload) key WHERE key <> 'ticketId'
    ) THEN
        RAISE EXCEPTION 'removed queue payload contains an unknown field';
    END IF;
    IF NEW.event_type = 'QUEUE_TICKET_UPSERTED' AND (
        NOT (NEW.payload ?& ARRAY[
            'ticketId', 'lifecycleState', 'handlingMode', 'sharedEnteredAt', 'escalationEnteredAt'
        ])
        OR EXISTS (
            SELECT 1 FROM jsonb_object_keys(NEW.payload) key
            WHERE key <> ALL (ARRAY[
                'ticketId', 'lifecycleState', 'handlingMode', 'sharedEnteredAt', 'escalationEnteredAt'
            ])
        )
        OR jsonb_typeof(NEW.payload->'lifecycleState') <> 'string'
        OR jsonb_typeof(NEW.payload->'handlingMode') <> 'string'
        OR jsonb_typeof(NEW.payload->'sharedEnteredAt') NOT IN ('string', 'null')
        OR jsonb_typeof(NEW.payload->'escalationEnteredAt') NOT IN ('string', 'null')
    ) THEN
        RAISE EXCEPTION 'invalid support queue summary payload';
    END IF;
    IF NEW.payload::text ~* '"(customerId|orderReference|description|reasonCode|investigation|message|note|audit|reasoning|checkpoint|token|thread|run|trace|approval|rawModel|rawTool)"[[:space:]]*:' THEN
        RAISE EXCEPTION 'support workbench payload contains a sensitive field';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER guard_support_workbench_event_payload
BEFORE INSERT OR UPDATE ON support_workbench_event
FOR EACH ROW EXECUTE FUNCTION validate_support_workbench_event_payload();

CREATE FUNCTION publish_support_workbench_ticket(changed_ticket_id uuid, changed_at timestamptz) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    ticket_row record;
    shared_entered timestamptz;
    escalation_entered timestamptz;
BEGIN
    SELECT lifecycle_state, handling_mode INTO ticket_row
    FROM support_ticket WHERE id = changed_ticket_id;
    SELECT min(entered_at), min(entered_at) FILTER (WHERE reason_code = 'SLA_BREACH')
    INTO shared_entered, escalation_entered
    FROM shared_support_queue_entry WHERE ticket_id = changed_ticket_id;

    IF shared_entered IS NULL THEN
        INSERT INTO support_workbench_event (epoch, event_type, payload, occurred_at)
        VALUES (
            'support-workbench-v1',
            'QUEUE_TICKET_REMOVED',
            jsonb_build_object('ticketId', changed_ticket_id::text),
            changed_at
        );
    ELSE
        INSERT INTO support_workbench_event (epoch, event_type, payload, occurred_at)
        VALUES (
            'support-workbench-v1',
            'QUEUE_TICKET_UPSERTED',
            jsonb_build_object(
                'ticketId', changed_ticket_id::text,
                'lifecycleState', ticket_row.lifecycle_state,
                'handlingMode', ticket_row.handling_mode,
                'sharedEnteredAt', shared_entered,
                'escalationEnteredAt', escalation_entered
            ),
            changed_at
        );
    END IF;
END;
$$;

CREATE FUNCTION publish_support_workbench_queue_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM publish_support_workbench_ticket(
        coalesce(NEW.ticket_id, OLD.ticket_id),
        coalesce(NEW.entered_at, OLD.entered_at, current_timestamp)
    );
    RETURN coalesce(NEW, OLD);
END;
$$;

CREATE TRIGGER publish_support_workbench_queue_change
AFTER INSERT OR UPDATE OR DELETE ON shared_support_queue_entry
FOR EACH ROW EXECUTE FUNCTION publish_support_workbench_queue_change();

CREATE FUNCTION publish_queued_ticket_summary_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM shared_support_queue_entry WHERE ticket_id = NEW.id) THEN
        PERFORM publish_support_workbench_ticket(NEW.id, current_timestamp);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER publish_queued_ticket_summary_change
AFTER UPDATE OF lifecycle_state, handling_mode ON support_ticket
FOR EACH ROW
WHEN (OLD.lifecycle_state IS DISTINCT FROM NEW.lifecycle_state OR OLD.handling_mode IS DISTINCT FROM NEW.handling_mode)
EXECUTE FUNCTION publish_queued_ticket_summary_change();

INSERT INTO support_workbench_event (epoch, event_type, payload, occurred_at)
SELECT
    'support-workbench-v1',
    'QUEUE_TICKET_UPSERTED',
    jsonb_build_object(
        'ticketId', q.ticket_id::text,
        'lifecycleState', t.lifecycle_state,
        'handlingMode', t.handling_mode,
        'sharedEnteredAt', min(q.entered_at),
        'escalationEnteredAt', min(q.entered_at) FILTER (WHERE q.reason_code = 'SLA_BREACH')
    ),
    min(q.entered_at)
FROM shared_support_queue_entry q
JOIN support_ticket t ON t.id = q.ticket_id
GROUP BY q.ticket_id, t.lifecycle_state, t.handling_mode
ORDER BY min(q.entered_at), q.ticket_id;

GRANT SELECT, INSERT ON support_workbench_event TO spring_app;
GRANT SELECT ON support_workbench_event TO spring_fixture;
GRANT USAGE, SELECT ON SEQUENCE support_workbench_event_sequence_seq TO spring_app;
GRANT DELETE ON shared_support_queue_entry TO spring_app;
